"""`CoMentionPort` over a project's co-mention index.

The event log is the right source for this and the vector store is not, for
the reason `docs/design/learning-areas-and-paths.md` §1 sets out at length: a
passage's entity links are folded from a `DocumentChunked`, so they survive a
restart and replay identically, and they record *which entities a passage
named* — which is the co-occurrence signal itself rather than a proxy for it.

**This used to read a `ChunkStore` and returned nothing for the life of the
feature.** The store it was handed was the retrieval corpus, filled by
`index_documents`, which runs before extraction and has no entity knowledge —
so every chunk in it carries `entity_ids: []`. Measured 2026-08-22 over a real
ingest: 36 chunks stored for one document, 0 with any links, 0 passages
returned, and an area projection byte-identical with and without them. See
`docs/design/co-mention-channel-findings.md`.

It now reads `CoMentionIndex`, which is folded from the *extraction* chunking
— the one path that knows which entities came out of which passage.
"""

from collections.abc import Sequence
from uuid import UUID

from redstring.ports.graph_store import GraphStore

from research_team.infrastructure.knowledge.aliases import absorbed_ids
from research_team.infrastructure.knowledge.co_mentions import CoMentionIndex


class RecordedCoMentions:
    """Which of this project's entities its passages named together.

    `tenant_id` is fixed at construction, the same way `UsageReader` fixes it
    and for the same reason: nothing above can pass a different tenant and read
    another project's passages. It is not passed to the index -- that holds one
    project by construction -- but it scopes the alias lookups, which go to a
    shared `GraphStore`.

    `graph` is **required, not optional**, and that is the decision rather than
    an oversight. Recorded links are pre-consolidation ids (see `absorbed_ids`),
    so without the alias graph this class silently under-reports in exact
    proportion to how much consolidation the project has done -- and a project
    with no merges makes the two behave identically, which is how the defect
    would be reviewed as absent. An optional collaborator here would be a
    guarantee that holds only until somebody forgets it.
    """

    def __init__(self, index: CoMentionIndex, tenant_id: UUID, graph: GraphStore) -> None:
        self._index = index
        self._tenant_id = tenant_id
        self._graph = graph

    async def passages(self, entity_ids: Sequence[str]) -> Sequence[frozenset[str]]:
        """One frozenset per passage naming two or more of `entity_ids`.

        Passages are keyed by `(source_id, chunk_index)` rather than by
        identity, because the same passage comes back once per entity it
        contains — a paragraph naming six entities is reached six times, and
        counting it six times would weight it by its own entity count, which
        is precisely the bias `CO_MENTION_BUDGET`'s normalisation exists to
        remove. Deduplicating here rather than in the projection keeps that
        correction in one place instead of two.

        **Absorbed ids are resolved to their survivor**, in both directions:
        the index is asked under every id a canonical entity has absorbed, and
        each passage's own ids are mapped back through the same table before
        the pair is formed. A raw intersection against the canonical set drops
        both halves of that — the passage is never reached, and if some other
        entity reaches it, the absorbed id is not counted as naming the
        survivor. On the corpus `docs/design/co-mention-channel-findings.md`
        measured, that is 633 extracted ids against 545 canonical.

        **Entities outside `entity_ids` are dropped from each passage**, not
        merely ignored downstream. A passage may name an entity the graph read
        truncated away, and a pair with one end missing from the graph is an
        edge the clusterer cannot use; leaving them in would inflate the pair
        count that the passage's weight is divided by, quietly weakening every
        real pair in proportion to how much of the graph was cut.
        """
        # Every id the index might hold for one of the wanted entities, mapped
        # to the wanted id it now stands for. Built once for the whole call
        # rather than per passage: the same table answers both the lookup below
        # and the narrowing inside the loop, and two walks of the alias graph
        # is two chances for them to disagree.
        canonical: dict[UUID, str] = {}
        for entity_id in entity_ids:
            wanted_id = UUID(entity_id)
            for stored_id in await absorbed_ids(self._graph, wanted_id, self._tenant_id):
                canonical[stored_id] = entity_id

        seen: dict[tuple[str, int], frozenset[str]] = {}
        for stored_id in canonical:
            for key, ids in self._index.by_entity(stored_id):
                if key in seen:
                    continue
                named = frozenset(canonical[e] for e in ids if e in canonical)
                if len(named) >= 2:
                    seen[key] = named
        # Sorted so the projection's input is a function of the corpus rather
        # than of dict iteration. The projection is order-independent by
        # construction, but a caller that can hand it two different orders is
        # a caller whose reproducibility rests on someone remembering that.
        return [seen[key] for key in sorted(seen)]
