"""Tests for entity definition invalidation: projection handlers and runner methods."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from redstring import DocumentExtracted, EntitiesMerged, Entity, ExtractionMethod, Provenance

from research_team.infrastructure.persistence.definition_cache import ProjectDefinitionCache
from research_team.infrastructure.persistence.read_models import (
    EntityDefinitionProjection,
    EntityDefinitionRow,
    EntityDefinitionRunner,
    EntityDefinitionStore,
)
from research_team.knowledge.application.entity_definitions import Citation, Definition
from research_team.research.domain.corpus import CorpusDocumentDropped


def _row(project_id, entity_id, **overrides) -> EntityDefinitionRow:
    fields = {
        "id": EntityDefinitionRow.row_id(project_id, entity_id),
        "project_id": project_id,
        "entity_id": entity_id,
        "text": "A protein that folds RNA.",
        "citations": json.dumps([{"source_id": "doc-1", "start": 0, "end": 26}]),
        "model": "test-model",
        "generated_at": "2026-08-14T00:00:00+00:00",
        "stale": False,
    }
    fields.update(overrides)
    return EntityDefinitionRow(**fields)


@pytest.fixture
async def def_store(db_path):
    store = await EntityDefinitionStore.open(db_path)
    yield store
    await store.close()


@pytest.fixture
async def def_runner(db_path, store, publisher):
    runner = EntityDefinitionRunner(store, db_path, publisher)
    await runner.start()
    yield runner
    await runner.stop()


async def test_projection_handles_corpus_document_dropped(def_store):
    project_id = uuid4()
    e1, e2 = uuid4(), uuid4()

    # e1 cites doc-dropped, e2 cites doc-kept
    await def_store.put(
        _row(
            project_id,
            e1,
            citations=json.dumps([{"source_id": "doc-dropped", "start": 0, "end": 10}]),
        )
    )
    await def_store.put(
        _row(
            project_id,
            e2,
            citations=json.dumps([{"source_id": "doc-kept", "start": 0, "end": 10}]),
        )
    )

    projection = EntityDefinitionProjection(def_store)
    event = CorpusDocumentDropped(
        aggregate_id=project_id, source_id="doc-dropped", reason="test"
    )
    await projection.handle(event)

    row1 = await def_store.get(project_id, e1)
    row2 = await def_store.get(project_id, e2)

    assert row1 is not None and row1.stale is True
    assert row2 is not None and row2.stale is False


async def test_projection_handles_document_extracted(def_store):
    project_id = uuid4()
    e1, e2, e3 = uuid4(), uuid4(), uuid4()

    await def_store.put(_row(project_id, e1))
    await def_store.put(_row(project_id, e2))
    await def_store.put(_row(project_id, e3))

    projection = EntityDefinitionProjection(def_store)
    entities = [
        Entity(
            id=e1,
            tenant_id=project_id,
            name="E1",
            normalized_name="e1",
            entity_type="type",
            provenance=Provenance(
                source_id="doc-x",
                observed_at=datetime.now(UTC),
                extraction_method=ExtractionMethod.MANUAL,
                confidence=1.0,
            ),
        ),
        Entity(
            id=e2,
            tenant_id=project_id,
            name="E2",
            normalized_name="e2",
            entity_type="type",
            provenance=Provenance(
                source_id="doc-x",
                observed_at=datetime.now(UTC),
                extraction_method=ExtractionMethod.MANUAL,
                confidence=1.0,
            ),
        ),
    ]
    event = DocumentExtracted(
        aggregate_id=project_id,
        tenant_id=project_id,
        source_id="doc-x",
        model_version="test-model",
        entities=entities,
        relationships=[],
    )
    await projection.handle(event)

    assert (await def_store.get(project_id, e1)).stale is True
    assert (await def_store.get(project_id, e2)).stale is True
    assert (await def_store.get(project_id, e3)).stale is False


async def test_projection_handles_entities_merged(def_store):
    project_id = uuid4()
    canonical = uuid4()
    absorbed1 = uuid4()
    absorbed2 = uuid4()

    await def_store.put(_row(project_id, canonical, stale=False))
    await def_store.put(_row(project_id, absorbed1, stale=False))
    await def_store.put(_row(project_id, absorbed2, stale=False))

    projection = EntityDefinitionProjection(def_store)
    event = EntitiesMerged(
        aggregate_id=project_id,
        tenant_id=project_id,
        canonical_entity_id=canonical,
        merged_entity_ids=[absorbed1, absorbed2],
    )
    await projection.handle(event)

    # Canonical is marked stale
    assert (await def_store.get(project_id, canonical)).stale is True
    # Absorbed entities are deleted
    assert await def_store.get(project_id, absorbed1) is None
    assert await def_store.get(project_id, absorbed2) is None


async def test_runner_and_project_definition_cache(def_runner):
    project_id = uuid4()
    e1, e2 = uuid4(), uuid4()

    cache = ProjectDefinitionCache(def_runner, project_id)

    # Put definitions
    d1 = Definition(
        text="Def 1",
        citations=[Citation(source_id="doc-alpha", start=0, end=5)],
        model="test",
        generated_at="2026-01-01T00:00:00Z",
        stale=False,
    )
    d2 = Definition(
        text="Def 2",
        citations=[Citation(source_id="doc-beta", start=0, end=5)],
        model="test",
        generated_at="2026-01-01T00:00:00Z",
        stale=False,
    )
    await cache.put(e1, d1)
    await cache.put(e2, d2)

    assert (await cache.get(e1)).stale is False
    assert (await cache.get(e2)).stale is False

    # Invalidate by source
    count = await cache.mark_stale_for_source("doc-alpha")
    assert count == 1
    assert (await cache.get(e1)).stale is True
    assert (await cache.get(e2)).stale is False

    # Invalidate by entity_id
    await cache.mark_stale(e2)
    assert (await cache.get(e2)).stale is True

    # Delete entity
    await cache.delete(e1)
    assert await cache.get(e1) is None
    assert await cache.get(e2) is not None

    # Runner delegation: mark_all_stale and delete_many
    await def_runner.mark_all_stale(project_id)
    assert (await cache.get(e2)).stale is True

    await def_runner.delete_many(project_id, [e2])
    assert await cache.get(e2) is None
