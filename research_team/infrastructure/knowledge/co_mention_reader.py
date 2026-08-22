"""`CoMentionPort` over a project's chunk store.

The chunk store is the right source for this and the vector store is not, for
the reason `docs/design/learning-areas-and-paths.md` §1 sets out at length: a
chunk is folded from a `DocumentChunked` event, so it survives a restart and
replays identically, and it records *which entities a passage names* — which
is the co-occurrence signal itself rather than a proxy for it.

**One call per entity, not one scan of the corpus.** `ChunkStore` has
`get_by_entity` and no enumeration, so the shape is fixed by the port
upstream. It is cheaper than it looks: the store is in memory on every
supported configuration, the results are deduplicated by passage key as they
arrive, and the cap above this (`MAX_CLUSTERED_ENTITIES`) bounds the loop
before it is entered.
"""

from collections.abc import Sequence
from uuid import UUID

from redstring.ports.chunk_store import ChunkStore


class ChunkCoMentions:
    """Which of this project's entities its passages name together.

    `tenant_id` is fixed at construction, the same way `UsageReader` fixes
    it and for the same reason: nothing above can pass a different tenant and
    read another project's passages.
    """

    def __init__(self, chunks: ChunkStore, tenant_id: UUID) -> None:
        self._chunks = chunks
        self._tenant_id = tenant_id

    async def passages(self, entity_ids: Sequence[str]) -> Sequence[frozenset[str]]:
        """One frozenset per passage naming two or more of `entity_ids`.

        Passages are keyed by `(source_id, chunk_index)` rather than by
        identity, because the same passage comes back once per entity it
        contains — a paragraph naming six entities is fetched six times, and
        counting it six times would weight it by its own entity count, which
        is precisely the bias `CO_MENTION_BUDGET`'s normalisation exists to
        remove. Deduplicating here rather than in the projection keeps that
        correction in one place instead of two.

        **Entities outside `entity_ids` are dropped from each passage**, not
        merely ignored downstream. A passage may name an entity the graph read
        truncated away, and a pair with one end missing from the graph is an
        edge the clusterer cannot use; leaving them in would inflate the pair
        count that the passage's weight is divided by, quietly weakening every
        real pair in proportion to how much of the graph was cut.
        """
        wanted = frozenset(entity_ids)
        seen: dict[tuple[str, int], frozenset[str]] = {}
        for entity_id in entity_ids:
            for chunk in await self._chunks.get_by_entity(UUID(entity_id), self._tenant_id):
                key = (str(chunk.source_id), chunk.chunk_index)
                if key in seen:
                    continue
                named = frozenset(str(e) for e in chunk.entity_ids) & wanted
                if len(named) >= 2:
                    seen[key] = named
        # Sorted so the projection's input is a function of the corpus rather
        # than of dict iteration. The projection is order-independent by
        # construction, but a caller that can hand it two different orders is
        # a caller whose reproducibility rests on someone remembering that.
        return [seen[key] for key in sorted(seen)]
