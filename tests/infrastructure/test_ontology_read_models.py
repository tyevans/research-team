"""The ontology tables: what they store and what they refuse to lose."""

import json
from uuid import uuid4

import aiosqlite
import pytest
from eventsource import ExpectedVersion, StreamId
from redstring import DocumentExtracted

from research_team.domain.ontology import (
    ONTOLOGY_AGGREGATE_TYPE,
    DiscoveredClass,
    DiscoveredMember,
    EvidenceSpan,
    OntologyDiscovered,
    RejectedMember,
)
from research_team.infrastructure.persistence.read_models import (
    OntologyClassRow,
    OntologyMembershipRow,
    OntologyRunner,
    OntologyStore,
)


def _difficulty() -> DiscoveredClass:
    return DiscoveredClass(
        name="Difficulty",
        kind="ordered_scale",
        declared_count=6,
        evidence=EvidenceSpan(source_id="songs", start=10, end=90),
        members=[
            DiscoveredMember(name="EASY", ordinal=0),
            DiscoveredMember(name="NORMAL", ordinal=1),
        ],
        rejected_members=[RejectedMember(name="LEGEND", reason="not in the document")],
    )


@pytest.fixture
async def ontology(db_path):
    """The tables alone, with no projection following the log.

    Named `ontology` rather than `store` because conftest's `store` is the
    event store, and the projection tests below need both at once.
    """
    opened = await OntologyStore.open(db_path)
    yield opened
    await opened.close()


@pytest.fixture
def other_project_id():
    return uuid4()


async def test_a_stored_class_keeps_its_checksum_its_evidence_and_its_rejections(
    ontology, project_id
):
    await ontology.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="2026-08-15T00:00:00Z"
    )

    (row,) = await ontology.classes_for(project_id)

    assert row.name == "Difficulty"
    assert row.kind == "ordered_scale"
    # The checksum and what was actually found, both stored. Storing only the
    # difference would make "5 of 6" indistinguishable from "5 of 5".
    assert (row.declared_count, row.member_count) == (6, 2)
    assert (row.evidence_start, row.evidence_end) == (10, 90)
    assert json.loads(row.rejected_members) == [
        {"name": "LEGEND", "reason": "not in the document"}
    ]


async def test_members_keep_the_order_the_text_gave_them(ontology, project_id):
    await ontology.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="t"
    )
    (row,) = await ontology.classes_for(project_id)

    members = await ontology.members_for(row.id)

    assert [(m.member_name, m.ordinal) for m in members] == [("EASY", 0), ("NORMAL", 1)]


async def test_re_running_replaces_a_source_rather_than_appending_to_it(ontology, project_id):
    """The pass is re-run whenever its prompt changes. Without replacement
    every re-run would double the classes and the graph would grow a duplicate
    hub per attempt. Would pass with `replace_for_source` implemented as an
    append only if this asserted a count of one, which is why it does."""
    await ontology.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="t"
    )
    await ontology.replace_for_source(
        project_id, "songs", [_difficulty()], model="m2", generated_at="t2"
    )

    rows = await ontology.classes_for(project_id)

    assert len(rows) == 1
    assert rows[0].model == "m2"


async def test_a_re_run_that_no_longer_finds_a_class_removes_it(ontology, project_id):
    """The half of replacement that an upsert would miss. A prompt that stops
    producing a class must not leave the old one on the canvas forever."""
    await ontology.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="t"
    )

    await ontology.replace_for_source(project_id, "songs", [], model="m2", generated_at="t2")

    assert await ontology.classes_for(project_id) == []


async def test_replacing_one_source_leaves_another_sources_classes_alone(ontology, project_id):
    """A pass over one document must not clear a class discovered in another.
    Nothing else here would catch a DELETE missing its `source_id` predicate,
    because every other test in this file uses one source."""
    await ontology.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="t"
    )
    other = _difficulty().model_copy(update={"name": "Rank"})
    await ontology.replace_for_source(
        project_id, "ranks", [other], model="m", generated_at="t"
    )

    names = {row.name for row in await ontology.classes_for(project_id)}

    assert names == {"Difficulty", "Rank"}


async def test_one_projects_classes_are_invisible_to_another(
    ontology, project_id, other_project_id
):
    await ontology.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="t"
    )

    assert await ontology.classes_for(other_project_id) == []


async def test_a_source_that_stated_no_classes_is_still_recorded_as_examined(
    ontology, project_id
):
    """`replace_for_source` with an empty list is how "grouped, found nothing"
    is distinguished from "never grouped". The `ungrouped` sweep is built
    entirely on that distinction, so losing it would make the sweep re-run
    every barren document forever, at model cost."""
    await ontology.replace_for_source(project_id, "songs", [], model="m", generated_at="t")

    assert await ontology.classes_for(project_id) == []
    assert await ontology.sources_with_classes(project_id) == {"songs"}


async def test_staling_a_source_leaves_its_classes_readable(ontology, project_id):
    """Stale text is still shown, labelled, rather than disappearing out from
    under a reader -- the same contract `EntityDefinitionStore.mark_stale`
    keeps, and for the same reason."""
    await ontology.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="t"
    )

    await ontology.mark_stale_for_source(project_id, "songs")

    (row,) = await ontology.classes_for(project_id)
    assert row.stale is True
    assert row.name == "Difficulty"


async def test_staling_one_source_leaves_another_source_alone(ontology, project_id):
    """B74 replaced the load-mutate-save loop with one `UPDATE`, and the loop
    filtered by source in Python where the statement filters in SQL. That moves
    the scoping into a `WHERE` clause, so this is the assertion that clause has
    to earn: a re-extraction of one document must not stale every class in the
    project.

    Red against an `UPDATE` scoped to `project_id` alone, which is the mistake
    the rewrite makes if the source is dropped from the clause -- and nothing
    else in this file would notice, because every other staling test has one
    source in the project.
    """
    await ontology.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="t"
    )
    await ontology.replace_for_source(
        project_id, "poems", [_difficulty()], model="m", generated_at="t"
    )

    await ontology.mark_stale_for_source(project_id, "songs")

    rows = await ontology.classes_for(project_id)
    stale_by_source = {row.source_id: row.stale for row in rows}
    assert stale_by_source == {"songs": True, "poems": False}


async def test_staling_a_source_nobody_has_grouped_is_not_an_error(ontology, project_id):
    """Called from a projection reacting to every extraction in the log, and
    most documents have no classes. Raising here would put routine extraction
    in the DLQ."""
    await ontology.mark_stale_for_source(project_id, "never-grouped")


# --- the projection and the runner ------------------------------------------
#
# Every assertion below is on a *row*, never on "replay completed" or a status.
# An event no projection handles counts as APPLIED, not rejected -- `strict`
# raises only when a handler itself raises, and has no opinion about an event
# nothing subscribed to. So a build with `OntologyProjection` never registered
# replays perfectly cleanly and serves an empty table, and any assertion
# weaker than "this row holds this value" passes against exactly the bug this
# feature is most likely to ship with.


async def _discover(store, publisher, project_id, source_id, classes):
    """Append an `OntologyDiscovered` the way the recorder will.

    Straight to the store, with no aggregate: `Ontology` deliberately has none
    (see `domain/ontology.py`), so there is no `execute`/`save` pair to drive
    the way the corpus tests drive `Corpus`.
    """
    event = OntologyDiscovered(
        aggregate_id=project_id,
        project_id=project_id,
        source_id=source_id,
        model_version="test-model",
        classes=classes,
    )
    # `any_()`: the ontology stream protects no invariant, and two documents'
    # passes append to one project's stream concurrently -- an exact version
    # would make a second pass fail on a race it has no reason to care about.
    await store.append(
        StreamId(project_id, ONTOLOGY_AGGREGATE_TYPE), [event], ExpectedVersion.any_()
    )
    if publisher is not None:
        await publisher.publish([event])


@pytest.fixture
async def runner(db_path, store, publisher):
    started = OntologyRunner(store, db_path, publisher)
    await started.start()
    yield started
    await started.stop()


async def test_the_projection_stores_the_classes_an_event_carried(
    runner, store, publisher, project_id
):
    await _discover(store, publisher, project_id, "songs", [_difficulty()])
    await runner.caught_up()

    (row,) = await runner.classes_for(project_id)

    assert (row.name, row.kind, row.declared_count) == ("Difficulty", "ordered_scale", 6)
    assert row.model == "test-model"
    assert [m.member_name for m in await runner.members_for(row.id)] == ["EASY", "NORMAL"]


async def test_a_document_examined_with_no_classes_is_recorded_as_examined(
    runner, store, publisher, project_id
):
    """The row that is *not* a class. Nothing else here would catch a
    projection that skipped `replace_for_source` entirely on an empty list."""
    await _discover(store, publisher, project_id, "barren", [])
    await runner.caught_up()

    assert await runner.classes_for(project_id) == []
    assert await runner.sources_with_classes(project_id) == {"barren"}


async def test_re_extracting_a_grouped_source_stales_its_classes(
    runner, store, publisher, project_id
):
    """Mark, never regenerate. A bulk re-extraction touching every document
    would otherwise fire one paid model call per document for classes nobody
    asked to see. This projection is handed no model, so it cannot call one
    even by mistake -- this pins that the staling still happens without one.
    """
    await _discover(store, publisher, project_id, "songs", [_difficulty()])
    await runner.caught_up()

    extracted = DocumentExtracted(
        aggregate_id=uuid4(),
        tenant_id=project_id,
        source_id="songs",
        model_version="m",
        entities=[],
        relationships=[],
    )
    await store.append(
        StreamId(extracted.aggregate_id, extracted.aggregate_type),
        [extracted],
        ExpectedVersion.any_(),
    )
    await publisher.publish([extracted])
    await runner.caught_up()

    (row,) = await runner.classes_for(project_id)
    assert row.stale is True
    # Staled, not deleted: the text still describes something a reader may
    # want, labelled, until a discovery run replaces it.
    assert row.name == "Difficulty"


async def test_a_rebuild_reproduces_the_tables_from_the_log(
    runner, store, publisher, project_id, db_path
):
    """Truncates and replays, unlike `EntityDefinitionRunner.rebuild`, and the
    difference is which columns come from the log: every column here is written
    by `_on_discovered` from an event payload, so a replay reproduces the table
    exactly.

    Proved by emptying the tables first -- a rebuild that quietly left the
    checkpoint in place would resume over an empty table and look like success
    until somebody read from it.
    """
    await _discover(store, publisher, project_id, "songs", [_difficulty()])
    await runner.caught_up()
    async with aiosqlite.connect(db_path) as connection:
        await connection.execute(f"DELETE FROM {OntologyClassRow.table_name()}")
        await connection.execute(f"DELETE FROM {OntologyMembershipRow.table_name()}")
        await connection.commit()
    assert await runner.classes_for(project_id) == []

    await runner.rebuild()

    (row,) = await runner.classes_for(project_id)
    assert row.name == "Difficulty"
    assert len(await runner.members_for(row.id)) == 2


async def test_a_rebuild_drops_a_class_a_later_pass_stopped_finding(
    runner, store, publisher, project_id
):
    """The truncate earning its place. A replay alone would re-apply both
    events and leave the first pass's class behind, because the second event
    does not mention it -- and a superseded class on the canvas is exactly
    what replacement exists to prevent."""
    await _discover(store, publisher, project_id, "songs", [_difficulty()])
    await runner.caught_up()
    await _discover(store, publisher, project_id, "songs", [])
    await runner.caught_up()

    await runner.rebuild()

    assert await runner.classes_for(project_id) == []
