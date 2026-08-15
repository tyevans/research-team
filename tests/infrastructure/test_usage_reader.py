"""`UsageReader`: `UsageReadPort` over a live `GraphStore` + `ChunkStore`.

Chunks are seeded straight through `InMemoryChunkStore.upsert_many` -- no
`index_documents`, no chunker -- because what is under test is the fan-out
over `known_names` and the fusion of per-name lexical results, not chunking.
Entities/aliases are seeded the same way `test_aliases.py` seeds them, since
`known_names` (Task 4) is a real collaborator here, not a fake.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from redstring import (
    Alias,
    Entity,
    ExtractionMethod,
    InMemoryChunkStore,
    InMemoryGraphStore,
    Provenance,
    StoredChunk,
)

from research_team.infrastructure.knowledge.usage_reader import UsageReader

TENANT_ID = uuid4()

DOC_1_TEXT = "Acme Corp builds rockets in Texas."


def _entity(entity_id, name: str) -> Entity:
    return Entity(
        id=entity_id,
        tenant_id=TENANT_ID,
        name=name,
        normalized_name=name.lower(),
        entity_type="organization",
        provenance=Provenance(
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            extraction_method=ExtractionMethod.MANUAL,
            confidence=1.0,
        ),
    )


def _alias(canonical_id, alias_id, alias_name: str | None) -> Alias:
    return Alias(
        id=uuid4(),
        tenant_id=TENANT_ID,
        canonical_entity_id=canonical_id,
        alias_entity_id=alias_id,
        alias_name=alias_name,
        alias_normalized_name=alias_name.lower() if alias_name else None,
        merged_at=datetime(2026, 1, 2, tzinfo=UTC),
    )


def _chunk(*, chunk_id: str, source_id: str, text: str, start: int, end: int) -> StoredChunk:
    return StoredChunk(
        id=chunk_id,
        tenant_id=TENANT_ID,
        source_id=source_id,
        text=text,
        chunk_index=0,
        start_char=start,
        end_char=end,
    )


@pytest.fixture
async def graph():
    async with InMemoryGraphStore() as store:
        yield store


@pytest.fixture
def chunks():
    return InMemoryChunkStore(dimension=8)


@pytest.fixture
def reader(graph, chunks):
    return UsageReader(graph, chunks, TENANT_ID)


async def test_a_passage_naming_the_entity_is_returned_with_its_offsets(graph, chunks, reader):
    acme_id = uuid4()
    await graph.upsert_entity(_entity(acme_id, "Acme"))
    await chunks.upsert_many(
        [
            _chunk(
                chunk_id="c1", source_id="doc-1", text=DOC_1_TEXT, start=0, end=len(DOC_1_TEXT)
            )
        ]
    )

    usages = await reader.usages(acme_id)

    assert len(usages) == 1
    assert usages[0].source_id == "doc-1"
    assert DOC_1_TEXT[usages[0].start : usages[0].end] == usages[0].text


async def test_a_passage_matching_two_aliases_appears_once(graph, chunks, reader):
    """ "Acme" and "Acme Corporation" both match the same sentence via two
    separate queries -- one per name. A usages list that shows the same
    passage twice reads as a bug to anyone looking at it. Fails with the
    dedup-by-(source_id, start, end) removed."""
    acme_id, alias_id = uuid4(), uuid4()
    await graph.upsert_entity(_entity(acme_id, "Acme Corporation"))
    await graph.upsert_alias(_alias(acme_id, alias_id, "Acme"))
    await chunks.upsert_many(
        [
            _chunk(
                chunk_id="c1", source_id="doc-1", text=DOC_1_TEXT, start=0, end=len(DOC_1_TEXT)
            )
        ]
    )

    usages = await reader.usages(acme_id)

    keys = [(u.source_id, u.start, u.end) for u in usages]
    assert len(keys) == len(set(keys))


async def test_an_entity_with_no_mentions_returns_nothing_rather_than_raising(
    graph, chunks, reader
):
    unmentioned_id = uuid4()
    # No term overlap with DOC_1_TEXT at all -- "Unrelated Corp" would still
    # score under BM25 on "Corp" alone, which is not the case this test means
    # to cover.
    await graph.upsert_entity(_entity(unmentioned_id, "Zzyzx Quombat"))
    await chunks.upsert_many(
        [
            _chunk(
                chunk_id="c1", source_id="doc-1", text=DOC_1_TEXT, start=0, end=len(DOC_1_TEXT)
            )
        ]
    )

    assert await reader.usages(unmentioned_id) == []


async def test_a_blank_name_never_reaches_the_ranker(graph, chunks, reader):
    """`tokenize`/`rank_chunks` treat a blank query as an error, and an
    entity whose only name is blank would otherwise raise out of a read
    endpoint instead of answering. Fails if the blank filter is removed."""
    blank_named_id = uuid4()
    # Punctuation-only rather than whitespace-only: `Entity` itself rejects a
    # blank `name` at construction, so this fixture needs a name that is
    # non-blank to redstring's validator but tokenizes to nothing --
    # `tokenize` strips punctuation and keeps no terms from "!!!".
    await graph.upsert_entity(_entity(blank_named_id, "!!!"))
    await chunks.upsert_many(
        [
            _chunk(
                chunk_id="c1", source_id="doc-1", text=DOC_1_TEXT, start=0, end=len(DOC_1_TEXT)
            )
        ]
    )

    assert await reader.usages(blank_named_id) == []
