"""Which entities each passage of a project named.

A read model of three fields, and the reason it is not a `ChunkStore` is that
three fields is all anything reads. `CoMentionPort`'s only consumer asks for
frozensets of entity ids keyed by passage; it never touches a passage's text,
offsets, metadata or vector.

**This was designed as a second `ChunkStore` first, and that was wrong.** The
argument for it was that redstring's extraction path is the only thing that
knows which entities came out of which passage, and that reaching it meant
passing `chunks=` to `build_graph` -- which, with the retrieval corpus already
under that source id, meant a second store to keep the two chunkings apart.
`build_graph`'s own docstring says otherwise, at the `event_store` argument:

    **Chunking is recorded whenever this is given, whether or not `chunks`
    is** -- `record_chunking` runs unconditionally on the aggregate, and only
    the write into `chunks` is gated on it being given.

Verified in `redstring/composition/build_graph.py`: `aggregate.record_chunking(
..., chunks=result.chunks)` runs unconditionally, `_persist` writes it whenever
there is a repository, and `ChunkProjection(chunks).handle(chunk_event)` is the
only line gated on `chunks`. So the entity-linked `DocumentChunked` reaches the
log with `event_store=` alone, and a `ChunkStore` was never the price of
getting at it.

What that mistake would have cost, had it shipped: every passage's **text**
held a third time in memory -- retrieval corpus, entity cards, and this --
to record what is a set of ids per passage. `AGENT_CHUNK_STORE=memory` is the
default and the only wired backend, so the whole corpus is resident.

## What it is not

Not durable, and not meant to be. It is folded from `DocumentChunked` at
project open exactly as the graph, the corpus and the card vectors are, so
losing it with the process costs a replay rather than data. That is the same
argument `build_chunk_store` makes for the corpus and `build_card_vector_store`
makes for the card vectors.

Not tenant-scoped internally, either: one instance holds one project, the way
`_chunk_stores` and `_card_vectors` do, and `ProjectGraphs` is what keys them
by project. A shared instance would need a tenant on every call and would make
"which passages does this project have" a question with a wrong answer
available.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from uuid import UUID


class CoMentionIndex:
    """Passages of one project, each as the set of entity ids it named.

    Keyed by `(source_id, chunk_index)`. Content-addressed chunk ids were
    rejected as the key for the reason `StoredChunk`'s own docstring gives for
    choosing them -- they are a property of the *text*, so a document that
    repeats a passage verbatim has one id for two positions, and this model
    would silently hold one passage where the corpus holds one too. Position is
    the right key here precisely because this model stores no text to be wrong
    about: a re-chunking replaces the whole source in one call, so a position
    never outlives the split that produced it.
    """

    def __init__(self) -> None:
        self._by_source: dict[str, dict[int, frozenset[UUID]]] = {}
        # A reverse index rather than a scan per lookup. `by_entity` is called
        # once per entity in the graph read -- up to `MAX_CLUSTERED_ENTITIES`
        # of them -- and a scan of every passage per call is that many passes
        # over the corpus. Rebuilt wholesale in `replace_source`, which is the
        # only writer, so the two cannot drift.
        self._by_entity: dict[UUID, set[tuple[str, int]]] = {}

    def replace_source(self, source_id: str, passages: Mapping[int, Iterable[UUID]]) -> None:
        """Make `passages` the whole of what this source contributed.

        Replacement rather than accumulation, matching `ChunkProjection`'s use
        of `replace_source` and for the same reason: a `DocumentChunked`
        carries a document's *whole* chunking, so a re-chunk under new settings
        must delete the positions the old split had and not merge with them.
        Applying it as one call is also what makes redelivery idempotent -- the
        incoming set is the same set.
        """
        for index in self._by_source.get(source_id, {}):
            key = (source_id, index)
            for entity_id in list(self._by_entity):
                self._by_entity[entity_id].discard(key)
                if not self._by_entity[entity_id]:
                    del self._by_entity[entity_id]

        held = {index: frozenset(ids) for index, ids in passages.items()}
        self._by_source[source_id] = held
        for index, ids in held.items():
            for entity_id in ids:
                self._by_entity.setdefault(entity_id, set()).add((source_id, index))

    def by_entity(self, entity_id: UUID) -> list[tuple[tuple[str, int], frozenset[UUID]]]:
        """Every passage naming `entity_id`, as `((source_id, index), ids)`.

        The key comes back with the ids because the caller deduplicates on it:
        one passage is reached once per entity it names, and counting it once
        per arrival would weight it by its own length. Returning the key rather
        than making the caller re-derive it keeps that correction possible
        without a second lookup.
        """
        keys = self._by_entity.get(entity_id, set())
        return [(key, self._by_source[key[0]][key[1]]) for key in sorted(keys)]

    def __len__(self) -> int:
        """How many passages this project has recorded links for.

        For diagnostics and for tests that need to tell "folded nothing" from
        "folded passages that named nothing" -- two states that look identical
        from `by_entity` and are a wiring fault and an extraction outcome
        respectively.
        """
        return sum(len(indexed) for indexed in self._by_source.values())
