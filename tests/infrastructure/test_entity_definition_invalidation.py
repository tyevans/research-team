"""Keeping cached definitions honest when the entity they describe changes.

`EntityDefinitionProjection` never writes definition text -- that is
the definition service's `put`, elsewhere -- it only marks a cached row
untrustworthy (or deletes it outright) in reaction to graph events. The two
tests that matter most are paired on purpose: the first proves the touched
row gets marked, the second proves an untouched sibling does not. The obvious
wrong implementation -- mark the whole project stale on any activity --
passes the first test perfectly and is invisible without the second.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eventsource.adapters.memory.readmodels import InMemoryReadModelRepository
from redstring import DocumentExtracted, EntitiesMerged
from redstring.domain.entity import Entity
from redstring.domain.provenance import ExtractionMethod, Provenance

from research_team.infrastructure.persistence.read_models import (
    EntityDefinitionProjection,
    EntityDefinitionRow,
    EntityDefinitionStore,
)


def _entity(project_id, entity_id, source_id="s1") -> Entity:
    """A minimally-valid extracted entity, built by hand for the reason
    `test_corpus_read_model.py`'s `_extracted` gives: nothing here folds
    anything, so standing up a real extraction to get one `Entity` would put
    a model provider between this test and the column it is about.
    """
    return Entity(
        id=entity_id,
        tenant_id=project_id,
        name="Acme",
        normalized_name="acme",
        entity_type="organization",
        provenance=Provenance(
            observed_at=datetime(2026, 8, 14, tzinfo=UTC),
            extraction_method=ExtractionMethod.LLM,
            confidence=0.9,
            source_id=source_id,
        ),
    )


def _extracted(project_id, *entity_ids) -> DocumentExtracted:
    return DocumentExtracted(
        aggregate_id=uuid4(),
        tenant_id=project_id,
        source_id="s1",
        entities=[_entity(project_id, entity_id) for entity_id in entity_ids],
        relationships=[],
        model_version="test",
    )


def _merged(project_id, canonical_id, *merged_ids) -> EntitiesMerged:
    return EntitiesMerged(
        aggregate_id=uuid4(),
        tenant_id=project_id,
        canonical_entity_id=canonical_id,
        merged_entity_ids=list(merged_ids),
    )


def _row(project_id, entity_id) -> EntityDefinitionRow:
    return EntityDefinitionRow(
        id=EntityDefinitionRow.row_id(project_id, entity_id),
        project_id=project_id,
        entity_id=entity_id,
        text="A protein that folds RNA.",
        citations="[]",
        model="test-model",
        generated_at="2026-08-14T00:00:00+00:00",
        stale=False,
    )


@pytest.fixture
def store() -> EntityDefinitionStore:
    connection = None  # never opened -- see the note on `rows` below.
    rows = InMemoryReadModelRepository(EntityDefinitionRow)
    return EntityDefinitionStore(connection, rows)


@pytest.fixture
def projection(store) -> EntityDefinitionProjection:
    return EntityDefinitionProjection(store)


async def test_extraction_marks_the_touched_entities_stale(projection, store):
    project_id, acme_id = uuid4(), uuid4()
    await store.put(_row(project_id, acme_id))

    await projection.handle(_extracted(project_id, acme_id))

    assert (await store.get(project_id, acme_id)).stale is True


async def test_extraction_leaves_untouched_entities_alone(projection, store):
    """Fails if the handler marks the whole project stale -- the obvious
    wrong implementation, and invisible without this sibling test."""
    project_id, acme_id, other_id = uuid4(), uuid4(), uuid4()
    await store.put(_row(project_id, acme_id))

    await projection.handle(_extracted(project_id, other_id))

    assert (await store.get(project_id, acme_id)).stale is False


async def test_a_merge_marks_the_survivor_stale_and_deletes_the_absorbed(projection, store):
    """An absorbed id is no longer clickable, so its cached definition is
    unreachable text -- and leaving it would make a `/rebuild` produce a
    different row count than steady-state operation, for no reason anyone
    could explain later."""
    project_id, acme_id, acme_corp_id = uuid4(), uuid4(), uuid4()
    await store.put(_row(project_id, acme_id))
    await store.put(_row(project_id, acme_corp_id))

    await projection.handle(_merged(project_id, acme_id, acme_corp_id))

    assert (await store.get(project_id, acme_id)).stale is True
    assert await store.get(project_id, acme_corp_id) is None


async def test_a_definition_for_an_entity_with_no_cached_row_is_not_an_error(projection):
    """Matches `CorpusProjection._on_extracted`: a projection that raises on a
    row it has never seen cannot replay a log that predates it."""
    project_id, never_defined_id = uuid4(), uuid4()
    await projection.handle(_extracted(project_id, never_defined_id))  # does not raise
