from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eventsource import StreamId, collect
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.snapshots import SQLiteSnapshotStore
from redstring import (
    FakeLlmProvider,
    InMemoryGraphStore,
    LlmProviderError,
    document_stream,
)

from research_team.application.knowledge import KnowledgeError, SourceRef
from research_team.infrastructure.knowledge import redstring_adapter
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from research_team.infrastructure.persistence.event_store import build_corpus_repository
from tests.conftest import TWO_PEOPLE, fake_provider

#: A second document's worth of people, sharing nothing with `TWO_PEOPLE` --
#: not the names, and (since redstring 0.5.0 compares neighbours by name) not
#: the neighbourhood either.
_HOPPER = {
    "entities": [
        {"name": "Grace Hopper", "entity_type": "Person"},
        {"name": "Harvard Mark I", "entity_type": "Machine"},
    ],
    "relationships": [
        {
            "source_name": "Grace Hopper",
            "target_name": "Harvard Mark I",
            "relationship_type": "WORKED_ON",
        }
    ],
}


@pytest.fixture
async def build_adapter():
    """Factory fixture for a `RedstringKnowledge` over a real `SQLiteEventStore`.

    Both stores hold a long-lived `aiosqlite` connection with a non-daemon
    worker thread, and both must be closed or that thread lingers past the
    test and surfaces later as an unrelated test's "Event loop is closed".
    Some tests call this factory only once, but it is shaped to support more --
    everything it opens is tracked and closed in teardown, so nothing here can
    be forgotten by a future test that calls it twice.

    `SQLiteSnapshotStore` used to open a connection per operation and need no
    closing. That stopped being true in eventsource 0.12, which gave it one
    connection for its lifetime and a `close()` to match.
    """
    opened_event_stores = []
    opened_snapshot_stores = []

    def _build(tmp_path, project_id, *, provider=None, adjudicate=False):
        db_path = str(tmp_path / "sessions.db")
        store = SQLiteEventStore(db_path)
        snapshot_store = SQLiteSnapshotStore(db_path)
        opened_event_stores.append(store)
        opened_snapshot_stores.append(snapshot_store)
        return (
            RedstringKnowledge(
                project_id,
                store=InMemoryGraphStore(),
                event_store=store,
                snapshot_store=snapshot_store,
                provider=provider if provider is not None else fake_provider(),
                corpus=build_corpus_repository(store, snapshot_store=snapshot_store),
                domain="encyclopedia_wiki",
                # Off by default: most tests here are about the adapter's own
                # bookkeeping and an adjudicator would put a second, unrelated
                # schema in every fake provider's way. Tests about *whether two
                # things merge* must turn it on -- with it off the ambiguous
                # band is rejected, which is redstring's stated behaviour and
                # not something this adapter can work around.
                adjudicate=adjudicate,
            ),
            store,
            snapshot_store,
        )

    yield _build

    for snapshot_store in opened_snapshot_stores:
        await snapshot_store.close()
    for store in opened_event_stores:
        await store.close()


@pytest.mark.asyncio
async def test_ingest_reports_what_it_extracted(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    report = await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    assert report.source_id == "notes"
    assert report.entity_count >= 1
    assert report.domain == "encyclopedia_wiki"


@pytest.mark.asyncio
async def test_ingest_appends_the_extraction_to_the_document_stream(tmp_path, build_adapter):
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
async def test_a_blank_source_id_is_rejected(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="   ", text="anything"))


@pytest.mark.asyncio
async def test_an_oversized_document_is_refused_before_extraction(tmp_path, build_adapter):
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
async def test_reconsolidate_is_scoped_to_one_documents_entities(tmp_path, build_adapter):
    """`reconsolidate(source_id)` acts on exactly that document's entities.

    Asserted directly, by capturing what `_consolidate` is actually handed:
    `reconsolidate("a")` must pass the entity ids `entities_for("a")` reports
    and none of `entities_for("b")`'s. A `reconsolidate` that ignored
    `source_id` and always re-resolved the same set -- or read the wrong
    stream -- would fail the disjointness check below even though its return
    value (empty merges, zero failures) would look identical either way. That
    return value is otherwise uninformative here: re-resolving after an
    explicit merge is a genuine no-op, because `CandidateFinder._block` runs
    `resolve_entity_ids` over the whole block and drops every entity that is
    already an alias -- an absorbed entity cannot be merged again, so it is
    never proposed. That is redstring's own idempotence rather than anything
    this adapter adds, and it is why the no-op alone cannot prove `source_id`
    did any work.

    This docstring previously attributed the no-op to the merged entity's
    graph-similarity signal dropping to `0.0` and holding its score under
    redstring's threshold. That mechanism is real -- it is the bug
    `test_one_entity_named_the_same_in_two_documents_becomes_one_node` pins --
    but it is not what makes *this* case a no-op, and alias exclusion happens
    first regardless of any score.

    The provider is explicit rather than `fake_provider()` because of
    redstring 0.5.0. `fake_provider()` answers `TWO_PEOPLE` whatever it is
    asked, so both documents used to extract Ada and Babbage, and the test
    read as two documents about different things only in the prose it fed the
    fake. Under 0.4.0 that was harmless -- the cross-document pair scored
    0.7143 and was rejected -- but 0.5.0 compares neighbours by name, so the
    two Adas share the neighbour "charles babbage", score 1.0, and *auto-merge
    during the second ingest*. The fixture's own `merge_entities` then failed
    on an entity that was already an alias. The two documents now genuinely
    extract different people, which is what the assertions below have always
    claimed and what the prose already said.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(
        tmp_path,
        project_id,
        provider=FakeLlmProvider(by_substring={"Grace Hopper": _HOPPER}, default=TWO_PEOPLE),
    )
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


#: One entity, named identically in two documents, each with a *different*
#: neighbour. That difference is the whole point: entity ids are namespaced per
#: document by `redstring.extraction.mapping.entity_id_for`, so the two
#: neighbours are two ids no matter what they are called, and the neighbour sets
#: of the duplicate pair are disjoint by construction.
_BREED_IN_CANADA = {
    "entities": [
        {"name": "Nova Scotia Duck Tolling Retriever", "entity_type": "concept"},
        {"name": "Canada", "entity_type": "concept"},
    ],
    "relationships": [
        {
            "source_name": "Nova Scotia Duck Tolling Retriever",
            "target_name": "Canada",
            "relationship_type": "ORIGINATES_IN",
        }
    ],
}

_BREED_AND_HUNTING = {
    "entities": [
        {"name": "Nova Scotia Duck Tolling Retriever", "entity_type": "concept"},
        {"name": "Duck hunting", "entity_type": "concept"},
    ],
    "relationships": [
        {
            "source_name": "Nova Scotia Duck Tolling Retriever",
            "target_name": "Duck hunting",
            "relationship_type": "USED_FOR",
        }
    ],
}


#: What the adjudicator says when it is asked. One verdict, because the
#: identical-name pair is the only thing that should ever reach the band --
#: `zip(strict=True)` upstream turns a count mismatch into "no answer", so a
#: second candidate arriving here would show up as a failed merge rather than
#: as a silently mis-paired verdict.
_SAYS_THEY_ARE_THE_SAME = {
    "verdicts": [
        {"same": True, "confidence": 0.99, "reason": "the same dog breed, named identically"}
    ]
}


@pytest.mark.asyncio
async def test_one_entity_named_the_same_in_two_documents_becomes_one_node(
    tmp_path, build_adapter
):
    """The reported duplicate, reduced: same name, same type, two documents.

    This is the bug the repo owner saw -- "Nova Scotia Duck Tolling Retriever"
    twice in one graph. It is not a blocking miss: an identical name and an
    identical type share all three of redstring's default blocking keys, so the
    pair is found and scored. It is scored **0.7143**, below redstring's
    `LOW_SIMILARITY` of 0.75, and `resolve` is called with `minimum_score=low`
    so the candidate is dropped before the adjudicator is ever offered it. No
    exception, no verdict, no counted failure -- two nodes and silence.

    The arithmetic, for a deployment with no `VectorStore` (which is ours):
    name 1.0 at weight 0.5, graph 0.0 at weight 0.2, embedding absent, so
    `0.5 / 0.7 = 0.7143`.

    **Why the graph feature is 0.0 changed under redstring 0.5.0, and the
    number did not.** When this was written, neighbours were compared by id and
    `entity_id_for` namespaces ids per document, so a cross-document duplicate
    was disjoint *by construction* -- "Canada" from one document and "Canada"
    from another were two ids however identical they were. 0.5.0 compares
    normalized neighbour names, which removes that artefact. This fixture is
    still 0.0 because its two documents genuinely describe different
    neighbourhoods: Canada in one, duck hunting in the other. So the test now
    pins the case the upstream fix deliberately leaves alone rather than the
    case it fixes, and `EXACT_NAME_SCORE` is what still carries it.

    Re-run with `EXACT_NAME_SCORE` raised to redstring's own `LOW_SIMILARITY`
    of 0.75 and this fails on 0.5.0 exactly as it did on 0.4.0: two canonical
    nodes with the same name. The floor removal was tried, not assumed.
    `test_two_documents_describing_the_same_pair_merge_without_a_floor` is the
    other half -- the case 0.5.0 does fix, which needs no floor.
    """
    project_id = uuid4()
    provider = FakeLlmProvider(
        by_substring={
            "duck hunting": _BREED_AND_HUNTING,
            # `policy._render` numbers the pairs it asks about, so "Pair 1" is
            # the one substring that identifies an adjudication prompt and
            # cannot appear in a document being extracted.
            "Pair 1": _SAYS_THEY_ARE_THE_SAME,
        },
        default=_BREED_IN_CANADA,
    )
    adapter, _, _ = build_adapter(tmp_path, project_id, provider=provider, adjudicate=True)

    await adapter.ingest(SourceRef(source_id="a", text="The breed originates in Canada."))
    await adapter.ingest(SourceRef(source_id="b", text="The breed is used for duck hunting."))

    matches = await adapter.search("Nova Scotia Duck Tolling Retriever")
    assert len(matches) == 1, f"one breed, one node; got {[match.name for match in matches]}"


#: The same pair of people from two documents, related in two different ways.
#: The *relationship type* differs and the neighbour name does not, which is
#: the whole point: this is what redstring 0.5.0 fixed and what 0.4.0 could not
#: see, because the neighbour ids were namespaced per document.
_PAIR_WORKED_WITH = {
    "entities": [
        {"name": "Ada Lovelace", "entity_type": "Person"},
        {"name": "Charles Babbage", "entity_type": "Person"},
    ],
    "relationships": [
        {
            "source_name": "Ada Lovelace",
            "target_name": "Charles Babbage",
            "relationship_type": "WORKED_WITH",
        }
    ],
}

_PAIR_CORRESPONDED_WITH = {
    "entities": [
        {"name": "Ada Lovelace", "entity_type": "Person"},
        {"name": "Charles Babbage", "entity_type": "Person"},
    ],
    "relationships": [
        {
            "source_name": "Ada Lovelace",
            "target_name": "Charles Babbage",
            "relationship_type": "CORRESPONDED_WITH",
        }
    ],
}


@pytest.mark.asyncio
async def test_two_documents_describing_the_same_pair_merge_without_a_floor(
    tmp_path, build_adapter, monkeypatch
):
    """The case redstring 0.5.0 fixes, pinned with our floor taken away.

    Two documents, the same two people, the same neighbourhood. Under 0.4.0
    this scored `graph = 0.0` -- an artefact, because neighbour ids are
    namespaced per document -- and landed on 0.7143 like everything else.
    0.5.0 compares normalized neighbour *names*, so the two Adas share
    "charles babbage", `graph = 1.0`, and the combined score is a flat 1.0:
    above `HIGH_SIMILARITY` (0.92), so it merges with **no adjudicator at
    all**, which is why this fixture leaves `adjudicate` off. Before 0.5.0 no
    cross-document pair could reach that band whatever the evidence.

    `EXACT_NAME_SCORE` is monkeypatched away to redstring's own
    `LOW_SIMILARITY` so that the floor cannot be what makes this pass. It is
    not: the floor moves `low`, and this pair clears `high`. Reverting the
    version bump is what makes this fail -- with the floor in place and
    redstring 0.4.0 the pair scores 0.7143, is admitted to adjudication, and is
    rejected because there is no adjudicator to ask.
    """
    monkeypatch.setattr(redstring_adapter, "EXACT_NAME_SCORE", 0.75)
    project_id = uuid4()
    provider = FakeLlmProvider(
        by_substring={"corresponded": _PAIR_CORRESPONDED_WITH},
        default=_PAIR_WORKED_WITH,
    )
    adapter, _, _ = build_adapter(tmp_path, project_id, provider=provider)

    await adapter.ingest(SourceRef(source_id="a", text="Ada Lovelace worked with Babbage."))
    await adapter.ingest(
        SourceRef(source_id="b", text="Ada Lovelace corresponded with Babbage.")
    )

    matches = await adapter.search("Ada Lovelace")
    assert len(matches) == 1, f"one person, one node; got {[match.name for match in matches]}"


@pytest.mark.asyncio
async def test_a_consolidation_failure_says_which_entity_and_why(tmp_path, build_adapter):
    """A swallowed `RedstringError` used to be indistinguishable from routine.

    `_consolidate` caught every `RedstringError`, incremented a counter and
    continued, on the stated assumption that the cause is "typically the entity
    was absorbed by a merge earlier in this same loop". That is only true of
    `ConsolidationInvariantError`. `RedstringError` is redstring's *base* class,
    so `CircuitOpen`, `RateLimitExceeded`, `LlmProviderError`,
    `MissingEntityError` and `AliasCycleError` all landed in the same arm --
    a rate-limited adjudicator would consolidate nothing across a whole ingest
    and report only a number.

    The count itself was always reported (`format_ingest_report` prints it), so
    what was missing is *which entity and why*. This asserts the note carries
    the entity's name and the error's own text.

    Reverting the change makes this fail: without it the only note for a failed
    entity is the "consolidating" one made before `resolve` was called, which
    names the entity but not the failure.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    async def always_fails(entity, **kwargs):
        raise LlmProviderError("the adjudicator is rate limited", model="test-model")

    adapter._consolidator.resolve = always_fails

    notes = []
    report = await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage."),
        report=notes.append,
    )

    assert report.consolidation_failures == report.entity_count
    details = [note.detail for note in notes if note.detail]
    assert any(
        "could not be consolidated" in detail and "rate limited" in detail
        for detail in details
    ), details


@pytest.mark.asyncio
async def test_merge_entities_rejects_absorbing_an_already_merged_entity(
    tmp_path, build_adapter
):
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
async def test_reconsolidating_an_unknown_source_is_an_error(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError, match="never-ingested"):
        await adapter.reconsolidate("never-ingested")


@pytest.mark.asyncio
async def test_a_provider_failure_records_no_extraction(tmp_path, build_adapter):
    """No extraction is appended, and the caller gets an error it can render.

    The corpus write is a separate guarantee and deliberately does survive
    this -- see `test_the_document_survives_a_failed_extraction`.
    """

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
async def test_search_finds_an_ingested_entity_by_substring(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    matches = await adapter.search("lovelace")

    assert matches, "an ingested entity should be findable"
    assert any("lovelace" in match.name.lower() for match in matches)


@pytest.mark.asyncio
async def test_search_caps_at_the_limit(tmp_path, build_adapter):
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
async def test_search_rejects_a_limit_below_one(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError):
        await adapter.search("anything", limit=0)


@pytest.mark.asyncio
async def test_search_of_a_blank_query_returns_nothing(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    assert await adapter.search("   ") == []


@pytest.mark.asyncio
async def test_undo_merge_rejects_an_unknown_id(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError):
        await adapter.undo_merge(uuid4())


@pytest.mark.asyncio
async def test_undo_merge_reverses_an_explicit_merge(tmp_path, build_adapter):
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
async def test_merges_are_remembered_across_restarts(tmp_path, build_adapter):
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
            corpus=build_corpus_repository(
                restarted_event_store, snapshot_store=snapshot_store
            ),
            domain="encyclopedia_wiki",
            adjudicate=False,
        )

        record = await restarted.undo_merge(merge.merge_id)
        assert record.merge_id == merge.merge_id
    finally:
        await restarted_event_store.close()


@pytest.fixture
def captured_documents(monkeypatch):
    """Records every `SourceDocument` the adapter hands to `build_graph`.

    The citation fields are asserted against the document rather than the
    `IngestReport`, which carries none of them and so would pass whether or
    not they were ever set -- the exact bug these tests exist to catch.
    """
    from research_team.infrastructure.knowledge import redstring_adapter

    documents = []
    real_build_graph = redstring_adapter.build_graph

    async def recording_build_graph(document, **kwargs):
        documents.append(document)
        return await real_build_graph(document, **kwargs)

    monkeypatch.setattr(redstring_adapter, "build_graph", recording_build_graph)
    return documents


@pytest.mark.asyncio
async def test_citation_fields_reach_the_source_document(
    tmp_path, build_adapter, captured_documents
):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(
        SourceRef(
            source_id="notes",
            text="Ada Lovelace worked with Charles Babbage.",
            uri="https://example.test/ada",
            title="Ada Lovelace",
            published_at="1843-07-10",
        )
    )

    document = captured_documents[0]
    assert document.uri == "https://example.test/ada"
    assert document.title == "Ada Lovelace"
    assert document.published_at == datetime(1843, 7, 10, tzinfo=UTC)


@pytest.mark.asyncio
async def test_a_source_without_citation_fields_leaves_them_unset(
    tmp_path, build_adapter, captured_documents
):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    document = captured_documents[0]
    assert document.uri is None
    assert document.title is None
    assert document.published_at is None
    assert "published_at" not in document.metadata


@pytest.mark.asyncio
async def test_an_unparseable_date_is_kept_verbatim_rather_than_dropped(
    tmp_path, build_adapter, captured_documents
):
    """An unreadable date must not cost us the document, nor the string itself."""
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    report = await adapter.ingest(
        SourceRef(
            source_id="notes",
            text="Ada Lovelace worked with Charles Babbage.",
            published_at="sometime last spring",
        )
    )

    assert report.entity_count >= 1
    document = captured_documents[0]
    assert document.published_at is None
    assert document.metadata["published_at"] == "sometime last spring"


@pytest.mark.asyncio
async def test_a_timestamp_with_a_zone_is_accepted(
    tmp_path, build_adapter, captured_documents
):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(
        SourceRef(
            source_id="notes",
            text="Ada Lovelace worked with Charles Babbage.",
            published_at="2026-08-05T12:30:00Z",
        )
    )

    assert captured_documents[0].published_at == datetime(2026, 8, 5, 12, 30, tzinfo=UTC)


def _corpus_events(store, project_id):
    """The corpus stream's events, read directly rather than via a projection.

    The read model for the corpus is built in a separate workstream; reading
    the log keeps these assertions independent of it, and the log is the
    thing B12 is actually about -- a projection could be rebuilt, a missing
    event could not.
    """
    return collect(store.read_stream(StreamId(project_id, "Corpus")))


@pytest.mark.asyncio
async def test_ingest_keeps_the_source_text(tmp_path, build_adapter):
    """After `remember` the system holds the document, not just a graph about it.

    The guarantee the corpus layer exists to provide: extraction used to be
    handed the text and drop it, leaving a graph whose every claim named a
    source nothing could produce.
    """
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(
        SourceRef(
            source_id="notes",
            text="Ada Lovelace worked with Charles Babbage.",
            uri="https://example.test/ada",
            title="Ada Lovelace",
            published_at="sometime last spring",
            note="for the timeline",
        )
    )

    envelopes = await _corpus_events(store, project_id)
    assert len(envelopes) == 1
    stored = envelopes[0].event
    assert type(stored).__name__ == "SourceDocumentStored"
    assert stored.source_id == "notes"
    assert stored.text == "Ada Lovelace worked with Charles Babbage."
    assert stored.uri == "https://example.test/ada"
    assert stored.title == "Ada Lovelace"
    # Verbatim, unlike redstring's `published_at`: the corpus event is the
    # archival copy, so it keeps what the source said even when it is prose.
    assert stored.published_at == "sometime last spring"
    assert stored.note == "for the timeline"


@pytest.mark.asyncio
async def test_the_document_survives_a_failed_extraction(tmp_path, build_adapter):
    """Store first, extract second -- and a failed extraction keeps the text."""

    class Failing:
        async def complete(self, *args, **kwargs):
            raise RuntimeError("endpoint down")

    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id, provider=Failing())

    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="notes", text="Ada Lovelace."))

    envelopes = await _corpus_events(store, project_id)
    assert [e.event.text for e in envelopes] == ["Ada Lovelace."]
    extraction = document_stream(tenant_id=project_id, source_id="notes")
    assert await collect(store.read_stream(extraction)) == []


@pytest.mark.asyncio
async def test_nothing_is_stored_when_the_document_is_refused(tmp_path, build_adapter):
    """The size and id guards run before the corpus write, not after."""
    from research_team.infrastructure.knowledge.redstring_adapter import (
        MAX_DOCUMENT_CHARS,
    )

    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="huge", text="x" * (MAX_DOCUMENT_CHARS + 1)))
    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="  ", text="Ada Lovelace."))

    assert await _corpus_events(store, project_id) == []


@pytest.mark.asyncio
async def test_re_ingesting_identical_bytes_stores_one_document(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)
    source = SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")

    await adapter.ingest(source)
    await adapter.ingest(source)

    envelopes = await _corpus_events(store, project_id)
    assert len(envelopes) == 1


@pytest.mark.asyncio
async def test_re_ingesting_changed_bytes_records_the_revision(tmp_path, build_adapter):
    """Same id, new text is a revision -- both versions stay in the log."""
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(SourceRef(source_id="notes", text="Ada Lovelace."))
    await adapter.ingest(SourceRef(source_id="notes", text="Ada Lovelace and Babbage."))

    envelopes = await _corpus_events(store, project_id)
    assert [e.event.text for e in envelopes] == [
        "Ada Lovelace.",
        "Ada Lovelace and Babbage.",
    ]


@pytest.mark.asyncio
async def test_identical_bytes_under_a_new_id_are_stored_separately(tmp_path, build_adapter):
    """Two URIs can legitimately serve one document, and each needs its own record."""
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)
    text = "Ada Lovelace worked with Charles Babbage."

    await adapter.ingest(SourceRef(source_id="mirror-a", text=text))
    await adapter.ingest(SourceRef(source_id="mirror-b", text=text))

    envelopes = await _corpus_events(store, project_id)
    assert [e.event.source_id for e in envelopes] == ["mirror-a", "mirror-b"]


# --- concurrent ingest ------------------------------------------------------
#
# The model puts several tool calls in one assistant message and the executor
# runs them concurrently, so two `remember` calls land in the same moment. Both
# reach `_store_document`, both load the corpus at the same version, and the
# second save loses the compare-and-swap.
#
# What made this worth a fix rather than a shrug is where the error surfaced.
# `remember` catches `KnowledgeError` and nothing else, so an
# `OptimisticLockError` escaped the tool, escaped the executor, and was
# recorded as a `TurnFailed` -- the whole turn discarded because two of its
# tool calls were merely simultaneous. And because a corpus shares its
# project's UUID, the message named the *project*, which is why this reads as
# a project-level fault in the UI when nothing about the project was wrong.


@pytest.mark.asyncio
async def test_two_ingests_at_once_do_not_lose_one_to_a_lock_error(tmp_path, build_adapter):
    """Two `remember` calls in one assistant message must both land."""
    import asyncio

    project_id = uuid4()
    adapter, store, snapshot_store = build_adapter(tmp_path, project_id)

    reports = await asyncio.gather(
        adapter.ingest(SourceRef(source_id="a", text="Ada Lovelace wrote a program.")),
        adapter.ingest(SourceRef(source_id="b", text="Grace Hopper built a compiler.")),
    )

    assert len(reports) == 2
    # Both documents are in the corpus. A lost write here means a source the
    # user paid to fetch is silently absent, which is the failure the corpus
    # layer exists to prevent.
    corpus = build_corpus_repository(store, snapshot_store=snapshot_store)
    state = (await corpus.load(project_id)).state
    assert sorted(state.documents) == ["a", "b"]


@pytest.mark.asyncio
async def test_ingest_reports_its_stages_in_order(tmp_path, build_adapter):
    """The stage sequence, pinned.

    This is what stops a refactor from quietly silencing the pane: the
    sequence is the contract, not the individual calls.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    notes = []

    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage."),
        report=notes.append,
    )

    stages = [note.stage for note in notes]
    assert stages[0] == "storing"
    assert stages[1] == "extracting"
    assert "extracted" in stages
    assert stages[-1] == "consolidated"
    # Consolidation is per entity, and the fake extracts two.
    consolidating = [note for note in notes if note.stage == "consolidating"]
    assert [note.index for note in consolidating] == [1, 2]
    assert all(note.total == 2 for note in consolidating)
    assert all(note.source_id == "notes" for note in notes)


@pytest.mark.asyncio
async def test_the_extracted_note_carries_the_counts_and_the_schema(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    notes = []

    report = await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage."),
        report=notes.append,
    )

    extracted = next(note for note in notes if note.stage == "extracted")
    assert extracted.entities == report.entity_count
    assert extracted.relationships == report.relationship_count
    assert extracted.domain == report.domain


@pytest.mark.asyncio
async def test_model_calls_are_counted_from_inside_extraction(tmp_path, build_adapter):
    """`build_graph` takes no callbacks, so the provider is the way in.

    Without this the pane has nothing to show during the longest part of an
    ingest, and a slow model looks identical to a hung one.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    notes = []

    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage."),
        report=notes.append,
    )

    counted = [note.model_calls for note in notes if note.model_calls]
    assert counted, "no note reported a model call"
    assert max(counted) >= 1


@pytest.mark.asyncio
async def test_a_reporter_that_raises_does_not_fail_the_ingest(tmp_path, build_adapter):
    """A listener must not cost a document already fetched and paid for."""
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    def explode(note):
        raise RuntimeError("the listener is broken")

    report = await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage."),
        report=explode,
    )

    assert report.entity_count > 0


@pytest.mark.asyncio
async def test_a_failed_extraction_reports_a_failed_stage(tmp_path, build_adapter):
    """The pane must be able to say "it broke", not just stop updating."""
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    notes = []

    with pytest.raises(KnowledgeError):
        await adapter.ingest(
            SourceRef(source_id="notes", text="x" * 200_001), report=notes.append
        )

    assert notes[-1].stage == "failed"
    assert notes[-1].detail


@pytest.mark.asyncio
async def test_a_no_op_re_ingest_still_closes_its_pane(tmp_path, build_adapter):
    """Same content, same model version: nothing new to record, but the pane

    still needs its closing note. A watcher cannot tell "already known" from
    "hung" if the second ingest goes quiet after `extracting`.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    source = SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")

    await adapter.ingest(source)
    notes = []
    await adapter.ingest(source, report=notes.append)

    stages = [note.stage for note in notes]
    assert "extracted" in stages
    assert stages[-1] == "consolidated"


@pytest.mark.asyncio
async def test_a_blank_source_id_announces_nothing(tmp_path, build_adapter):
    """There is no id to attribute a note to, so no note is made."""
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    notes = []

    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="   ", text="anything"), report=notes.append)

    assert notes == []
