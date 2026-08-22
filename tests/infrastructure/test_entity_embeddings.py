"""What gets embedded, and what happens when the provider misbehaves."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from redstring import (
    Entity,
    ExtractionMethod,
    InMemoryGraphStore,
    Provenance,
    Relationship,
)
from redstring.llm.adapters.fake_embedding import FakeEmbeddingProvider

from research_team.infrastructure.knowledge.entity_cards import assemble_cards
from research_team.infrastructure.knowledge.entity_embeddings import (
    embed_entities,
)

DIMENSION = 32


async def graph_with_two_related_entities(tenant_id):
    """Two entities and an edge, so the cards differ from the names."""

    def make(name: str, entity_type: str) -> Entity:
        return Entity(
            id=uuid4(),
            tenant_id=tenant_id,
            name=name,
            normalized_name=name.lower(),
            entity_type=entity_type,
            # Fixed rather than `datetime.now`, matching the other graph
            # fixtures here: nothing under test reads it, and a moving value
            # shows up in a failure diff without meaning anything.
            provenance=Provenance(
                observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                extraction_method=ExtractionMethod.MANUAL,
                confidence=1.0,
            ),
        )

    store = InMemoryGraphStore()
    left = make("Ada Lovelace", "person")
    right = make("Analytical Engine", "machine")
    await store.upsert_entities([left, right])
    await store.upsert_relationship(
        Relationship(
            id=uuid4(),
            source_entity_id=left.id,
            target_entity_id=right.id,
            relationship_type="worked_on",
            tenant_id=tenant_id,
            confidence=1.0,
        )
    )
    return store, left, right


@pytest.mark.asyncio
async def test_the_card_is_embedded_and_not_the_name():
    """The enrichment, asserted on the vector rather than on the intent.

    **The test that separates this from what redstring does.** `build_graph`
    embeds `[entity.name for entity in entities]`; this embeds the entity's
    card, which carries its type, its properties and its named relations.
    Both produce a vector of the right width for the right entity, and every
    structural assertion anyone would think to write passes either way.

    `FakeEmbeddingProvider` hashes its input, so the two are distinguishable
    only because the texts are. That is also the limit of what this proves: it
    shows *which text was sent*, not that a richer text embeds better, which is
    a claim about a real model and not something a test can settle.
    """
    tenant_id = uuid4()
    store, left, _ = await graph_with_two_related_entities(tenant_id)
    provider = FakeEmbeddingProvider(dimension=DIMENSION, model="fake")

    event = await embed_entities(graph=store, provider=provider, tenant_id=tenant_id)
    assert event is not None

    cards = {
        card.entity_id: card.text
        for card in await assemble_cards(graph=store, tenant_id=tenant_id)
    }
    stored = {record.entity_id: record.vector for record in event.embeddings}

    from_card = (await provider.embed([cards[left.id]]))[0]
    from_name = (await provider.embed([left.name]))[0]

    assert stored[left.id] == from_card
    assert stored[left.id] != from_name, (
        "embedding the bare name is what this module exists not to do"
    )
    assert "worked_on" in cards[left.id], "the card should carry the relation"


@pytest.mark.asyncio
async def test_only_narrows_the_pass_to_the_entities_asked_for():
    """The ingest path embeds one document's entities, not the whole graph.

    Without it the tenth document costs more than the first nine together,
    because every ingest would re-embed everything already extracted.
    """
    tenant_id = uuid4()
    store, left, _ = await graph_with_two_related_entities(tenant_id)
    provider = FakeEmbeddingProvider(dimension=DIMENSION, model="fake")

    event = await embed_entities(
        graph=store, provider=provider, tenant_id=tenant_id, only={left.id}
    )

    assert event is not None
    assert [record.entity_id for record in event.embeddings] == [left.id]


@pytest.mark.asyncio
async def test_an_empty_graph_yields_no_event_rather_than_an_empty_one():
    """`None`, not an `EntitiesEmbedded` carrying nothing.

    An empty event is indistinguishable on the log from a pass that ran and
    found nothing to say, and it marks the model as recorded on the aggregate,
    which is how a later real pass comes to be refused as a repeat.
    """
    tenant_id = uuid4()
    event = await embed_entities(
        graph=InMemoryGraphStore(),
        provider=FakeEmbeddingProvider(dimension=DIMENSION, model="fake"),
        tenant_id=tenant_id,
    )

    assert event is None


@pytest.mark.asyncio
async def test_a_short_reply_drops_its_batch_rather_than_misaligning_it():
    """Positional results, so a short list cannot be matched to its inputs.

    The dangerous alternative is not raising -- it is `zip` truncating, which
    silently gives entity two the vector of entity one. Every downstream
    lookup then succeeds and returns a confidently wrong neighbour.
    """

    class Short(FakeEmbeddingProvider):
        async def embed(self, texts):
            full = await super().embed(list(texts))
            return full[:-1]

    tenant_id = uuid4()
    store, _, _ = await graph_with_two_related_entities(tenant_id)

    event = await embed_entities(
        graph=store,
        provider=Short(dimension=DIMENSION, model="fake"),
        tenant_id=tenant_id,
    )

    assert event is None, "a batch that cannot be aligned must contribute nothing"
