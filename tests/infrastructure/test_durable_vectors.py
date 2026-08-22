"""Vectors survive the process that computed them.

The defect these were written against, measured on 2026-08-22 against a copy
of the real database: **zero `EntitiesEmbedded` rows in a log holding 8
`DocumentExtracted` and 772 `EntitiesMerged`.** Embeddings had been on by
default the whole time. redstring computed one per entity on every ingest,
folded it into an in-memory store, returned a count, and the ingest path let
the event go -- so every vector the system ever paid for died with the
process, and nothing on the log could bring it back.

Two of the tests here fail against that build. The rest pin the parts of the
fix whose absence would be silent.
"""

from uuid import uuid4

import pytest
from redstring import InMemoryGraphStore, InMemoryVectorStore
from redstring.llm.adapters.fake_embedding import FakeEmbeddingProvider

from research_team.application.knowledge import SourceRef
from research_team.infrastructure.knowledge.entity_embeddings import (
    PROJECT_EMBEDDING_SOURCE,
)
from research_team.infrastructure.knowledge.rebuild import rebuild_graph

DIMENSION = 64
TEXT = "Ada Lovelace worked with Charles Babbage on the Analytical Engine."


def _provider(model: str = "fake-embed") -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider(dimension=DIMENSION, model=model)


async def _ingest(build_adapter, tmp_path, project_id, **kwargs):
    """One ingest with both embedding channels wired, and its stores."""
    vectors = InMemoryVectorStore(dimension=DIMENSION)
    cards = InMemoryVectorStore(dimension=DIMENSION)
    adapter, event_store, _ = build_adapter(
        tmp_path,
        project_id,
        embeddings=_provider(**kwargs),
        vector_store=vectors,
        card_vector_store=cards,
    )
    await adapter.ingest(SourceRef(source_id="notes", text=TEXT))
    return adapter, event_store, vectors, cards


@pytest.mark.asyncio
async def test_an_ingest_puts_its_embeddings_on_the_log(build_adapter, tmp_path):
    """The whole defect, in one assertion.

    **Fails against the build this was written for**, which appended only
    `DocumentExtracted` and left the vectors in memory. Asserting on the log
    rather than on the store is the entire point: a store holding vectors is
    exactly what that build also had, right up until it exited.
    """
    project_id = uuid4()
    _, event_store, _, _ = await _ingest(build_adapter, tmp_path, project_id)

    recorded = [
        envelope.event
        async for envelope in event_store.read_all()
        if type(envelope.event).__name__ == "EntitiesEmbedded"
    ]

    assert recorded, "an ingest with embeddings on must leave EntitiesEmbedded behind"
    assert any(e.embeddings for e in recorded), (
        "an event carrying no vectors is not durability"
    )


@pytest.mark.asyncio
async def test_a_fresh_store_gets_its_vectors_back_from_the_log(build_adapter, tmp_path):
    """A restart loses the store and not the vectors.

    The store is built empty and folded from the log alone -- no adapter, no
    provider, nothing that could recompute an embedding. What ends up in it
    came from `EntitiesEmbedded` or it did not come from anywhere.
    """
    project_id = uuid4()
    adapter, event_store, _, _ = await _ingest(build_adapter, tmp_path, project_id)

    embedded = [entity.id for entity in await adapter._store.find_entities(project_id)]
    assert embedded, "the fixture should have produced entities"

    restarted = InMemoryVectorStore(dimension=DIMENSION)
    await rebuild_graph(
        InMemoryGraphStore(),
        feed=event_store,
        project_id=project_id,
        card_vectors=restarted,
        embedding_model="fake-embed",
    )

    recovered = [
        entity_id
        for entity_id in embedded
        if await restarted.get(entity_id, project_id) is not None
    ]
    assert recovered, "folding the log must repopulate a vector store built empty"


@pytest.mark.asyncio
async def test_the_two_channels_do_not_cross(build_adapter, tmp_path):
    """A card store folded from the log holds card vectors, not name vectors.

    Both channels are `EntitiesEmbedded` over the same entity ids, so a fold
    that ignored `source_id` would fill both stores with whichever event came
    last and every lookup would still succeed. The failure has no symptom
    except wrong neighbours, which is why it is asserted on the *value*.

    `FakeEmbeddingProvider` hashes its input, so the two channels' vectors
    differ exactly because the texts differ -- a card carries the entity's type
    and relations, a name carries a name.
    """
    project_id = uuid4()
    adapter, event_store, _, _ = await _ingest(build_adapter, tmp_path, project_id)
    entities = await adapter._store.find_entities(project_id)
    assert entities

    document_side = InMemoryVectorStore(dimension=DIMENSION)
    card_side = InMemoryVectorStore(dimension=DIMENSION)
    await rebuild_graph(
        InMemoryGraphStore(),
        feed=event_store,
        project_id=project_id,
        vectors=document_side,
        card_vectors=card_side,
        embedding_model="fake-embed",
    )

    differing = 0
    for entity in entities:
        left = await document_side.get(entity.id, project_id)
        right = await card_side.get(entity.id, project_id)
        if left is not None and right is not None and left.vector != right.vector:
            differing += 1

    assert differing, (
        "the two channels embed different text, so a correct fold gives at "
        "least one entity two different vectors; identical vectors everywhere "
        "means one channel overwrote the other"
    )


@pytest.mark.asyncio
async def test_another_models_vectors_are_skipped_rather_than_refused(build_adapter, tmp_path):
    """Changing the embedding model must not make a project unopenable.

    A vector store's width is fixed at construction and the log is permanent,
    so without the model filter the first foreign-width event raises
    `DimensionMismatchError`, `strict=True` turns that into a refusal, and
    every project that had ever been embedded stops opening.

    The store is built at a *different* width from the one the events carry,
    which is the case the filter has to survive: if the events were applied at
    all, this raises rather than merely filling the store.
    """
    project_id = uuid4()
    _, event_store, _, _ = await _ingest(build_adapter, tmp_path, project_id)

    narrower = InMemoryVectorStore(dimension=DIMENSION // 2)
    applied = await rebuild_graph(
        InMemoryGraphStore(),
        feed=event_store,
        project_id=project_id,
        card_vectors=narrower,
        embedding_model="some-other-model",
    )

    assert applied > 0, "the graph must still fold"


@pytest.mark.asyncio
async def test_vectors_without_a_model_is_refused_rather_than_guessed(tmp_path):
    """Passing a store and no model name is a programming error, loudly.

    The tempting default is "apply everything", and it is the setting that
    makes a project stop opening the first time somebody changes models. A
    raise here is cheaper than that discovery.
    """
    with pytest.raises(ValueError, match="embedding_model"):
        await rebuild_graph(
            InMemoryGraphStore(),
            feed=object(),
            project_id=uuid4(),
            card_vectors=InMemoryVectorStore(dimension=DIMENSION),
        )


@pytest.mark.asyncio
async def test_the_card_channel_records_against_its_own_source(build_adapter, tmp_path):
    """Card embeddings land on the synthetic stream, not the document's.

    That is what the fold tells the channels apart by, so it is the one detail
    of the event that another part of the system depends on.
    """
    project_id = uuid4()
    _, event_store, _, _ = await _ingest(build_adapter, tmp_path, project_id)

    sources = {
        envelope.event.source_id
        async for envelope in event_store.read_all()
        if type(envelope.event).__name__ == "EntitiesEmbedded"
    }

    assert PROJECT_EMBEDDING_SOURCE in sources
    assert sources - {PROJECT_EMBEDDING_SOURCE}, "the document channel should also record"


@pytest.mark.asyncio
async def test_an_ingest_survives_an_embedding_endpoint_that_dies(build_adapter, tmp_path):
    """An embedding failure must not lose an extraction that already landed.

    The extraction is folded into the graph store and appended to the log
    before anything is embedded, so a provider raising afterwards has to leave
    that alone. Without the guard the ingest raises, the caller sees a failed
    document, and the graph quietly contains it anyway.
    """

    class Dying(FakeEmbeddingProvider):
        async def embed(self, texts):
            raise RuntimeError("endpoint is down")

    project_id = uuid4()
    adapter, _, _ = build_adapter(
        tmp_path,
        project_id,
        embeddings=Dying(dimension=DIMENSION, model="fake-embed"),
        vector_store=InMemoryVectorStore(dimension=DIMENSION),
        card_vector_store=InMemoryVectorStore(dimension=DIMENSION),
    )

    report = await adapter.ingest(SourceRef(source_id="notes", text=TEXT))

    assert report.entity_count > 0
    assert await adapter._store.find_entities(project_id)
