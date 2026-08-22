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
from uuid import UUID

from research_team.application.area_projection import (
    CoMentionPort,
    project_areas,
)
from research_team.application.graph_read import MAX_GRAPH_NODES, Graph, GraphReadPort
from research_team.application.learning_paths import full_path, path_to
from research_team.domain.learning_area import AreaProjection, LearningArea, LearningPath


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

    The cache is keyed on `(project_id, entity_count, relationship_count)`
    rather than on the project alone, and that pair is the whole of the
    invalidation strategy. It is deliberately crude and deliberately
    *conservative in the right direction*: a graph that has grown produces a
    different key and is reprojected, while a graph that has changed without
    changing either count -- a consolidation that merged two entities and
    dropped an edge, say -- serves a stale projection until the next
    extraction moves a count.

    A subscription to the log would be exact. It is not written because the
    failure it prevents is bounded and visible: the projection carries
    `entity_count`, every surface shows it, and a reader looking at a stale
    map can see the number it was built from disagree with the graph page.
    An exact invalidation that was subtly wrong would be neither bounded nor
    visible, and this is a cache in front of a pure function rather than a
    read model anything writes to.
    """

    def __init__(self) -> None:
        self._cache: dict[
            UUID, tuple[tuple[int, int], Curriculum, Graph, list[frozenset[str]]]
        ] = {}

    async def build(
        self,
        project_id: UUID,
        graph_reader: GraphReadPort,
        co_mentions: CoMentionPort,
        *,
        limit: int = MAX_GRAPH_NODES,
    ) -> Curriculum:
        graph = await graph_reader.whole(limit=limit)
        key = (len(graph.entities), len(graph.relationships))
        cached = self._cache.get(project_id)
        if cached is not None and cached[0] == key:
            return cached[1]

        passages = list(
            await co_mentions.passages(sorted(e.entity_id for e in graph.entities))
        )
        projection = project_areas(graph, passages)
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
    ) -> LearningPath | None:
        """The prerequisite closure of one area.

        Built from the *same* graph and passages the complete path was, by
        going through `build` first: two cuts taken from two reads could
        order the same pair differently, and a learner switching views would
        be told two incompatible things with no way to choose.
        """
        await self.build(project_id, graph_reader, co_mentions)
        _, curriculum, graph, passages = self._cache[project_id]
        return path_to(destination, curriculum.projection.areas, graph.relationships, passages)

    def forget(self, project_id: UUID) -> None:
        """Drop a project's cached curriculum.

        For the delete route, which must not leave a deleted project's
        curriculum answerable, and for a caller that wants a forced
        reprojection after an edit the count-based key cannot see.
        """
        self._cache.pop(project_id, None)
