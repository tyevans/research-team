"""`known_names`: every name an entity may appear under in the corpus.

Seeded directly through `InMemoryGraphStore.upsert_entities` / `upsert_alias`
-- no LLM, no extraction, no merge fold. What is under test is the read-side
walk over aliases, not how a merge produces them.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from redstring import (
    Alias,
    Entity,
    ExtractionMethod,
    InMemoryGraphStore,
    Provenance,
)

from research_team.infrastructure.knowledge.aliases import known_names

TENANT_ID = uuid4()


def _entity(entity_id, name: str) -> Entity:
    return Entity(
        id=entity_id,
        tenant_id=TENANT_ID,
        name=name,
        normalized_name=name.lower(),
        entity_type="organization",
        # Fixed rather than `datetime.now`: nothing under test reads
        # `observed_at`, and a moving value in a fixture is a difference that
        # shows up in a failure diff without meaning anything.
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


@pytest.fixture
async def graph():
    async with InMemoryGraphStore() as store:
        yield store


async def test_an_entity_with_no_merges_is_known_by_its_own_name(graph):
    acme_id = uuid4()
    await graph.upsert_entity(_entity(acme_id, "Acme Corporation"))

    assert await known_names(graph, acme_id, TENANT_ID) == ["Acme Corporation"]


async def test_a_merge_chain_is_walked_to_the_end(graph):
    """`find_aliases` returns direct absorptions only. An entity that absorbed
    an entity that had itself absorbed another loses the deepest name unless
    this recurses -- and that name is exactly the obsolete spelling an old
    document is most likely to use."""
    acme_id, corp_id, short_id = uuid4(), uuid4(), uuid4()
    await graph.upsert_entity(_entity(acme_id, "Acme Corporation"))
    # `corp_id` and `short_id` are absorbed entities, never upserted as
    # entities themselves -- an alias is a statement about ids and does not
    # require its endpoints to exist (`AliasStore.upsert_alias` docstring).
    await graph.upsert_alias(_alias(acme_id, corp_id, "Acme Corp"))
    await graph.upsert_alias(_alias(corp_id, short_id, "ACME"))

    names = await known_names(graph, acme_id, TENANT_ID)
    assert set(names) == {"Acme Corporation", "Acme Corp", "ACME"}


async def test_an_alias_with_no_recorded_name_is_skipped(graph):
    """`Alias.alias_name` is `str | None` because the projection folds
    `EntitiesMerged`, which carries ids and no names. A `None` here must not
    become a blank query -- `retrieve`/`rank` treat a blank as an error."""
    acme_id, nameless_id = uuid4(), uuid4()
    await graph.upsert_entity(_entity(acme_id, "Acme Corporation"))
    await graph.upsert_alias(_alias(acme_id, nameless_id, None))

    names = await known_names(graph, acme_id, TENANT_ID)
    assert None not in names
    assert names == ["Acme Corporation"]


async def test_a_cycle_in_the_alias_graph_terminates(graph):
    """Nothing in the port's contract promises acyclicity, and a cycle here
    hangs a request rather than returning a wrong answer. Passes with the
    seen-set removed only if the fixture graph is acyclic -- this one is not.

    `InMemoryGraphStore` (the reference adapter) does not itself refuse this
    shape at `upsert_alias` time -- only `resolve_entity_ids` raises
    `AliasCycleError`, and only when walking a *resolution* chain, not
    `find_aliases`. So the fixture below round-trips through the store
    exactly as written: A's aliases include B, and B's aliases include A.
    """
    a_id, b_id = uuid4(), uuid4()
    await graph.upsert_entity(_entity(a_id, "A"))
    await graph.upsert_entity(_entity(b_id, "B"))
    await graph.upsert_alias(_alias(a_id, b_id, "B-as-alias-of-A"))
    await graph.upsert_alias(_alias(b_id, a_id, "A-as-alias-of-B"))

    names = await known_names(graph, a_id, TENANT_ID)
    assert "A" in names
