"""One project's curriculum: its areas, and the paths through them.

The join between `area_projection` (what belongs together), `learning_paths`
(what comes first) and the two ports that supply them. Both of those modules
are pure; this is the only thing here that reads anything, which is why it is
the only thing here that can be wrong about the corpus rather than about
arithmetic.

**Recomputed on every call, never stored.** `domain/learning_area.py` records
the reasoning: a projection is a pure function of a graph that is itself
folded from the log, so storing it would store a derivation beside its own
inputs, and a stored copy that disagrees with a re-derived one is a question
nothing can answer. The cost is real -- a clustering pass per request -- and
`CurriculumService` caches per `(project, entity_count)` to pay it once per
graph rather than once per view.
"""

from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from research_team.curriculum.application.area_projection import (
    CoMentionPort,
    SemanticPort,
    project_areas,
)
from research_team.curriculum.application.learning_paths import full_path, path_to
from research_team.curriculum.domain.learning_area import (
    AreaProjection,
    LearningArea,
    LearningPath,
)
from research_team.knowledge.application.graph_read import (
    MAX_GRAPH_NODES,
    Graph,
    GraphReadPort,
)


def graph_fingerprint(graph: Graph) -> str:
    """A deterministic fingerprint of the entities and relationships in `graph`.

    Detects changes to entity membership, names, or relationships even when
    counts remain identical (B127).
    """
    entity_tokens = sorted(f"{e.entity_id}:{e.name}:{e.entity_type}" for e in graph.entities)
    rel_tokens = sorted(
        f"{r.source_id}->{r.target_id}:{r.relationship_type}" for r in graph.relationships
    )
    payload = "\n".join(entity_tokens) + "\n---\n" + "\n".join(rel_tokens)
    return sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Curriculum:
    """A projection and the complete path through it, together.

    One object rather than two calls because the two are always wanted
    together and are derived from one read of the graph: an area map with no
    order is a bag, and an order with no areas is a list of slugs. Splitting
    them would mean two graph reads that could disagree, since a project can
    be extracting while somebody browses.
    """

    projection: AreaProjection
    path: LearningPath

    def area(self, slug: str) -> LearningArea | None:
        return next((a for a in self.projection.areas if a.slug == slug), None)

    @property
    def by_slug(self) -> dict[str, LearningArea]:
        return {a.slug: a for a in self.projection.areas}


class CurriculumService:
    """Builds a project's curriculum, and remembers the last one it built.

    The cache is keyed on `(entity_count, relationship_count, fingerprint)`
    (B127) rather than counts alone: a graph whose membership or structure
    changes without shifting either count is detected and reprojected, while
    an unchanged graph uses the cached result.
    """

    def __init__(self) -> None:
        self._cache: dict[
            UUID, tuple[tuple[int, int, str], Curriculum, Graph, list[frozenset[str]]]
        ] = {}

    async def build(
        self,
        project_id: UUID,
        graph_reader: GraphReadPort,
        co_mentions: CoMentionPort,
        semantic: SemanticPort | None = None,
        *,
        limit: int = MAX_GRAPH_NODES,
        force_refresh: bool = False,
    ) -> Curriculum:
        """This project's areas and the path through them.

        `semantic` is optional and its absence is not a degraded mode to warn
        about: embeddings are off on plenty of installs and absent on every
        project ingested before they were durable. What it must not do is
        change silently in the *other* direction -- a run that had the channel
        and drew nothing from it is recorded as `used_embeddings=False` on the
        projection, so "configured" and "used" stay distinguishable.

        `force_refresh` forces a fresh reprojection even when the cached key matches.
        """
        graph = await graph_reader.whole(limit=limit)
        key = (len(graph.entities), len(graph.relationships), graph_fingerprint(graph))
        cached = self._cache.get(project_id)
        if not force_refresh and cached is not None and cached[0] == key:
            return cached[1]

        ids = sorted(e.entity_id for e in graph.entities)
        passages = list(await co_mentions.passages(ids))
        pairs = list(await semantic.neighbours(ids)) if semantic is not None else []
        projection = project_areas(graph, passages, pairs)
        curriculum = Curriculum(
            projection=projection,
            path=full_path(projection.areas, graph.relationships, passages),
        )
        self._cache[project_id] = (key, curriculum, graph, passages)
        return curriculum

    async def path_toward(
        self,
        project_id: UUID,
        destination: str,
        graph_reader: GraphReadPort,
        co_mentions: CoMentionPort,
        semantic: SemanticPort | None = None,
    ) -> LearningPath | None:
        """The prerequisite closure of one area.

        Built from the *same* graph and passages the complete path was, by
        going through `build` first: two cuts taken from two reads could
        order the same pair differently, and a learner switching views would
        be told two incompatible things with no way to choose.
        """
        await self.build(project_id, graph_reader, co_mentions, semantic)
        _, curriculum, graph, passages = self._cache[project_id]
        return path_to(destination, curriculum.projection.areas, graph.relationships, passages)

    def forget(self, project_id: UUID) -> None:
        """Drop a project's cached curriculum.

        For the delete route, which must not leave a deleted project's
        curriculum answerable, and for a caller that wants a forced
        reprojection after an edit the count-based key cannot see.
        """
        self._cache.pop(project_id, None)
