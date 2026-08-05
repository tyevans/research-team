from uuid import uuid4

import pytest
from eventsource import collect
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.snapshots import SQLiteSnapshotStore
from redstring import InMemoryGraphStore, document_stream

from research_team.application.knowledge import KnowledgeError, SourceRef
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from tests.conftest import fake_provider


def build_adapter(tmp_path, project_id, *, provider=None):
    db_path = str(tmp_path / "sessions.db")
    store = SQLiteEventStore(db_path)
    snapshot_store = SQLiteSnapshotStore(db_path)
    return (
        RedstringKnowledge(
            project_id,
            store=InMemoryGraphStore(),
            event_store=store,
            snapshot_store=snapshot_store,
            provider=provider if provider is not None else fake_provider(),
            domain="encyclopedia_wiki",
            adjudicate=False,
        ),
        store,
        snapshot_store,
    )


@pytest.mark.asyncio
async def test_ingest_reports_what_it_extracted(tmp_path):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    report = await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    assert report.source_id == "notes"
    assert report.entity_count >= 1
    assert report.domain == "encyclopedia_wiki"


@pytest.mark.asyncio
async def test_ingest_appends_the_extraction_to_the_document_stream(tmp_path):
    """The event is the record; the graph is derived from it."""
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    stream = document_stream(tenant_id=project_id, source_id="notes")
    envelopes = await collect(store.read_stream(stream))
    assert len(envelopes) == 1
    assert type(envelopes[0].event).__name__ == "DocumentExtracted"


@pytest.mark.asyncio
async def test_a_blank_source_id_is_rejected(tmp_path):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="   ", text="anything"))


@pytest.mark.asyncio
async def test_an_oversized_document_is_refused_before_extraction(tmp_path):
    from research_team.infrastructure.knowledge.redstring_adapter import (
        MAX_DOCUMENT_CHARS,
    )

    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError, match="limit"):
        await adapter.ingest(SourceRef(source_id="huge", text="x" * (MAX_DOCUMENT_CHARS + 1)))

    stream = document_stream(tenant_id=project_id, source_id="huge")
    assert await collect(store.read_stream(stream)) == []


@pytest.mark.asyncio
async def test_reconsolidate_is_scoped_to_one_documents_entities(tmp_path):
    """`reconsolidate(source_id)` acts on exactly that document's entities.

    Asserted directly, by capturing what `_consolidate` is actually handed:
    `reconsolidate("a")` must pass the entity ids `entities_for("a")` reports
    and none of `entities_for("b")`'s. A `reconsolidate` that ignored
    `source_id` and always re-resolved the same set -- or read the wrong
    stream -- would fail the disjointness check below even though its return
    value (empty merges, zero failures) would look identical either way. That
    return value is otherwise uninformative here: a merged entity's
    relationships are fully redirected onto its canonical, which drops its
    own graph-similarity signal to `0.0` and keeps its score under
    redstring's candidate threshold, so re-resolving it after an explicit
    merge is a genuine no-op (redstring's own idempotence, not something this
    adapter adds) -- which is exactly why the no-op alone cannot prove
    `source_id` did any work.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="a", text="Ada Lovelace worked with Charles Babbage.")
    )
    await adapter.ingest(
        SourceRef(source_id="b", text="Grace Hopper worked on the Harvard Mark I.")
    )

    a_entities = await adapter.entities_for("a")
    b_entities = await adapter.entities_for("b")
    assert len(a_entities) >= 2, "fixture needs two entities in document a"
    await adapter.merge_entities(
        canonical=a_entities[0].id, absorbed=[a_entities[1].id], reason="test fixture"
    )

    seen: list[set] = []
    original_consolidate = adapter._consolidate

    async def recording_consolidate(entities):
        seen.append({entity.id for entity in entities})
        return await original_consolidate(entities)

    adapter._consolidate = recording_consolidate

    a_merges, a_failures = await adapter.reconsolidate("a")
    b_merges, b_failures = await adapter.reconsolidate("b")

    assert len(seen) == 2, "one _consolidate call per reconsolidate"
    a_ids_seen, b_ids_seen = seen
    a_ids = {entity.id for entity in a_entities}
    b_ids = {entity.id for entity in b_entities}
    assert a_ids_seen == a_ids, "reconsolidate('a') must act on exactly a's entities"
    assert b_ids_seen == b_ids, "reconsolidate('b') must act on exactly b's entities"
    assert a_ids_seen.isdisjoint(b_ids), "a's and b's entities are never the same ids"
    assert b_ids_seen.isdisjoint(a_ids), "the property must hold in both directions"

    assert a_failures == 0, "nothing further for a to resolve; not a fault"
    assert a_merges == (), "the merge already happened; resolve has nothing to redo"
    assert b_failures == 0, "document b's entities were never touched"
    assert b_merges == (), "b's entities were never candidates for each other"


@pytest.mark.asyncio
async def test_merge_entities_rejects_absorbing_an_already_merged_entity(tmp_path):
    """`merge_entities` is the explicit path -- it still enforces redstring's

    own invariant that an absorbed entity cannot be merged again, and that
    invariant surfaces as `KnowledgeError`, not a raw redstring exception.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="a", text="Ada Lovelace worked with Charles Babbage.")
    )

    a_entities = await adapter.entities_for("a")
    await adapter.merge_entities(
        canonical=a_entities[0].id, absorbed=[a_entities[1].id], reason="first merge"
    )

    with pytest.raises(KnowledgeError):
        await adapter.merge_entities(
            canonical=a_entities[1].id,
            absorbed=[a_entities[0].id],
            reason="already absorbed",
        )


@pytest.mark.asyncio
async def test_reconsolidating_an_unknown_source_is_an_error(tmp_path):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError, match="never-ingested"):
        await adapter.reconsolidate("never-ingested")


@pytest.mark.asyncio
async def test_a_provider_failure_records_nothing(tmp_path):
    """Nothing is appended, and the caller gets an error it can render."""

    class Failing:
        async def complete(self, *args, **kwargs):
            raise RuntimeError("endpoint down")

    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id, provider=Failing())

    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="notes", text="Ada Lovelace."))

    stream = document_stream(tenant_id=project_id, source_id="notes")
    assert await collect(store.read_stream(stream)) == []


@pytest.mark.asyncio
async def test_search_finds_an_ingested_entity_by_substring(tmp_path):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    matches = await adapter.search("lovelace")

    assert matches, "an ingested entity should be findable"
    assert any("lovelace" in match.name.lower() for match in matches)


@pytest.mark.asyncio
async def test_search_caps_at_the_limit(tmp_path):
    """Distinguish "capped correctly" from "returned nothing": both entities
    match "a" (Ada Lovelace, Charles Babbage), so an uncapped search returns
    two -- only a working cap brings it down to exactly one."""
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    uncapped = await adapter.search("a")
    assert len(uncapped) >= 2, "fixture needs at least two entities matching 'a'"

    assert len(await adapter.search("a", limit=1)) == 1


@pytest.mark.asyncio
async def test_search_rejects_a_limit_below_one(tmp_path):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError):
        await adapter.search("anything", limit=0)


@pytest.mark.asyncio
async def test_search_of_a_blank_query_returns_nothing(tmp_path):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    assert await adapter.search("   ") == []


@pytest.mark.asyncio
async def test_undo_merge_rejects_an_unknown_id(tmp_path):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError):
        await adapter.undo_merge(uuid4())


@pytest.mark.asyncio
async def test_undo_merge_reverses_an_explicit_merge(tmp_path):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="a", text="Ada Lovelace worked with Charles Babbage.")
    )
    a_entities = await adapter.entities_for("a")
    merge = await adapter.merge_entities(
        canonical=a_entities[0].id, absorbed=[a_entities[1].id], reason="test fixture"
    )

    record = await adapter.undo_merge(merge.merge_id)

    assert record.merge_id == merge.merge_id
    # Undoing the same merge again must fail -- it is no longer in effect.
    with pytest.raises(KnowledgeError):
        await adapter.undo_merge(merge.merge_id)


@pytest.mark.asyncio
async def test_merges_are_remembered_across_restarts(tmp_path):
    """Undo is durable only when both stores are passed; assert it, don't assume.

    The boolean alone is a claim about durability, not proof of it, so this
    also performs a merge through one adapter and undoes it through a SECOND
    adapter built with a FRESH `SQLiteEventStore` over the same db_path -- the
    strongest cheap evidence that the merge log actually survived a restart
    rather than living in memory.

    The snapshot store is deliberately reused rather than reopened: it is an
    optimisation over the event log, not the record, and `SQLiteSnapshotStore`
    has no `close()` -- a second instance over the same path would leak its
    worker thread and hang interpreter shutdown. Durability is a property of
    the event log, which is exactly what the fresh `SQLiteEventStore` proves.

    The graph store is also reused rather than reopened, for an unrelated
    reason: `InMemoryGraphStore` is this test's stand-in for what would be a
    persistent backend (e.g. Neo4j) in production, and its persistence is not
    what this test is about -- undoing a merge replays restored relationships
    onto entities the merge touched, and a fresh, empty `InMemoryGraphStore`
    would not have them. What is under test is that the *merge log* survives
    a restart of the event store, not that this stand-in graph backend does.
    """
    project_id = uuid4()
    adapter, _, snapshot_store = build_adapter(tmp_path, project_id)

    assert adapter.remembers_merges_across_restarts

    await adapter.ingest(
        SourceRef(source_id="a", text="Ada Lovelace worked with Charles Babbage.")
    )
    a_entities = await adapter.entities_for("a")
    merge = await adapter.merge_entities(
        canonical=a_entities[0].id, absorbed=[a_entities[1].id], reason="test fixture"
    )

    db_path = str(tmp_path / "sessions.db")
    restarted_event_store = SQLiteEventStore(db_path)
    try:
        restarted = RedstringKnowledge(
            project_id,
            store=adapter._store,
            event_store=restarted_event_store,
            snapshot_store=snapshot_store,
            provider=fake_provider(),
            domain="encyclopedia_wiki",
            adjudicate=False,
        )

        record = await restarted.undo_merge(merge.merge_id)
        assert record.merge_id == merge.merge_id
    finally:
        await restarted_event_store.close()
