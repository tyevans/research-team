from uuid import uuid4

import pytest
from eventsource.adapters.sqlite import SQLiteEventStore
from redstring import FakeLlmProvider, LlmProviderError

from research_team.application.knowledge import KnowledgeError, SourceRef
from research_team.domain.judgements import EntityKey, HoldSame
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from research_team.infrastructure.persistence.event_store import (
    build_corpus_repository,
    build_judgements_repository,
)
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

    async def always_fails(subjects_or_entity, **kwargs):
        raise LlmProviderError("the adjudicator is rate limited", model="test-model")

    # Both, and the pair is the point. `_consolidate` batches through
    # `resolve_many` now, and a batch fails as a batch -- which can say only
    # "some of these did not consolidate". The failed batch is retried entity
    # by entity through `resolve`, and that retry is the only thing that can
    # name one. Patching just `resolve_many` would leave the retry succeeding
    # and report no failure at all.
    adapter._consolidator.resolve_many = always_fails
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


#: Two documents naming one person two ways, with no shared neighbour.
#:
#: `JFK` against `John F. Kennedy` scores 0.609 on name similarity and the two
#: share no blocking prefix, so redstring's own finder never builds the pair as
#: a candidate at all -- which is the case entity judgements exist for, and the
#: reason these fixtures are not the `Nova Scotia` pair the rest of this module
#: uses. An identical-name pair would merge on its own evidence and prove
#: nothing about judgements.
_KENNEDY_SHORT = {
    "entities": [
        {"name": "JFK", "entity_type": "concept"},
        {"name": "PT-109", "entity_type": "concept"},
    ],
    "relationships": [
        {
            "source_name": "JFK",
            "target_name": "PT-109",
            "relationship_type": "COMMANDED",
        }
    ],
}

_KENNEDY_LONG = {
    "entities": [
        {"name": "John F. Kennedy", "entity_type": "concept"},
        {"name": "Inauguration", "entity_type": "concept"},
    ],
    "relationships": [
        {
            "source_name": "John F. Kennedy",
            "target_name": "Inauguration",
            "relationship_type": "SPOKE_AT",
        }
    ],
}


@pytest.fixture
def kennedy_provider():
    """One person, two documents, two spellings, two distinct neighbours."""
    return FakeLlmProvider(
        by_substring={"inauguration": _KENNEDY_LONG},
        default=_KENNEDY_SHORT,
    )


async def _record_same(store, snapshot_store, project_id, left, right, reason):
    """Record one held-same judgement over the adapter's own log."""
    repository = build_judgements_repository(store, snapshot_store=snapshot_store)
    judgements = await repository.load_or_create(project_id)
    judgements.execute(
        HoldSame(
            judgements_id=project_id,
            keys=[EntityKey.of(left, "concept"), EntityKey.of(right, "concept")],
            reason=reason,
        )
    )
    await repository.save(judgements)


@pytest.mark.asyncio
async def test_a_held_same_judgement_merges_what_scoring_never_pairs(
    tmp_path, build_adapter, kennedy_provider
):
    """The whole point of the feature, end to end.

    `JFK` and `John F. Kennedy` score 0.609 on name and share no blocking
    prefix, so no threshold or weight change reaches them -- redstring never
    builds the pair as a candidate at all. The judgement is what puts the
    counterpart in front of consolidation, injected at 1.0 so it merges
    without a model call.

    **Proved red before it was trusted green**: with `judgements=False` passed
    to `build_adapter` and everything else identical, this finds two nodes.
    The test below makes that permanent rather than leaving it as a claim.
    """
    project_id = uuid4()
    adapter, store, snapshot_store = build_adapter(
        tmp_path, project_id, provider=kennedy_provider, judgements=True
    )
    await _record_same(
        store, snapshot_store, project_id, "JFK", "John F. Kennedy", "one president"
    )

    await adapter.ingest(SourceRef(source_id="a", text="JFK commanded PT-109."))
    await adapter.ingest(SourceRef(source_id="b", text="The inauguration was cold."))

    assert len((await adapter.search("JFK")).matches) == 0, "the short spelling was absorbed"
    assert len((await adapter.search("Kennedy")).matches) == 1, "one person, one node"


@pytest.mark.asyncio
async def test_without_a_judgements_repository_the_same_pair_stays_two_nodes(
    tmp_path, build_adapter, kennedy_provider
):
    """The other half, and what makes the test above evidence rather than hope.

    Identical but for the repository. It is also the passthrough guarantee that
    every existing construction site relies on: with no repository the adapter
    builds no finder, `resolve` falls back to its own, and consolidation is
    exactly what it was before judgements existed.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id, provider=kennedy_provider)

    await adapter.ingest(SourceRef(source_id="a", text="JFK commanded PT-109."))
    await adapter.ingest(SourceRef(source_id="b", text="The inauguration was cold."))

    assert len((await adapter.search("JFK")).matches) == 1, "still its own node"
    assert len((await adapter.search("Kennedy")).matches) == 1, "and so is the long spelling"
