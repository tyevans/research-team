"""The check-telemetry read model: a review, and the decision that answered it.

The interesting property here is a fold across two events that arrive at
different times. `StageChecksEvaluated` writes one row per bound check with the
decision columns empty; the `ToolCallDecided` that answers it lands later and
fills every one of them. Most of these tests exist to pin one of the ways that
fold could quietly go wrong -- a decision that matches nothing, a replay that
doubles rows, an unimplemented binding stored as a check that passed.

The database-level cases at the bottom are separate on purpose: a read-model
change verified only against a fresh database is unverified, and the last one
opens a database that predates the table.
"""

from uuid import uuid4

import aiosqlite
import pytest
from eventsource.adapters.memory.readmodels import InMemoryReadModelRepository

from research_team.domain import (
    RecordStageReview,
    RecordToolDecision,
    Session,
    SessionPurpose,
    StartSession,
)
from research_team.infrastructure.persistence.check_telemetry import (
    CheckOutcomeRow,
    CheckTelemetryProjection,
    CheckTelemetryRunner,
    CheckTelemetryStore,
)
from tests.conftest import MODEL_NAME, SYSTEM_PROMPT

NINE_CHECKS = [
    {"check": f"shared.check_{index}", "severity": "advisory", "findings": 0}
    for index in range(9)
]


@pytest.fixture
def rows() -> InMemoryReadModelRepository:
    return InMemoryReadModelRepository(CheckOutcomeRow)


@pytest.fixture
def projection(rows) -> CheckTelemetryProjection:
    return CheckTelemetryProjection(rows)


def _session(project_id=None) -> Session:
    """A started session, because `decide` stamps the aggregate id from state.

    Driving the real aggregate rather than hand-building events keeps these
    tests honest about the payload shape: `evaluated` is a list of dicts because
    that is what `RecordStageReview` puts on the event, not because a fixture
    said so.
    """
    session = Session(uuid4())
    session.execute(
        StartSession(
            session_id=session.aggregate_id,
            system_prompt=SYSTEM_PROMPT,
            model_name=MODEL_NAME,
            project_id=project_id or uuid4(),
            purpose=SessionPurpose.CHAT,
        )
    )
    return session


def _review(session, project_id, review_id, *, evaluated, unimplemented=(), posed_by="runner"):
    session.execute(
        RecordStageReview(
            review_id=review_id,
            project_id=project_id,
            stage="analysis",
            preset="hybrid.default",
            preset_version="1",
            evaluated=list(evaluated),
            unimplemented=list(unimplemented),
            posed_by=posed_by,
        )
    )


def _decision(session, *, review_id, decision="approve", decided_by="human"):
    session.execute(
        RecordToolDecision(
            tool_name="advance_stage",
            args={"rationale": "looks right"},
            decision=decision,
            decided_by=decided_by,
            review_id=review_id,
        )
    )


async def _project(projection, session) -> None:
    """Feed everything the session has produced, in stream order."""
    for event in session.uncommitted_events:
        await projection.handle(event)


async def test_a_review_writes_one_row_per_bound_check(projection, rows):
    """Nine bound checks, nine rows, decision columns empty until it is made."""
    project_id, review_id = uuid4(), uuid4()
    session = _session(project_id)
    _review(session, project_id, review_id, evaluated=NINE_CHECKS)

    await _project(projection, session)

    stored = await rows.find(None)
    assert len(stored) == 9
    assert {row.check_name for row in stored} == {entry["check"] for entry in NINE_CHECKS}
    assert all(row.review_id == review_id for row in stored)
    assert all(row.project_id == project_id for row in stored)
    assert all(row.session_id == session.aggregate_id for row in stored)
    assert all(row.stage == "analysis" and row.posed_by == "runner" for row in stored)
    assert all(row.decision is None for row in stored)
    assert all(row.decided_by is None for row in stored)
    assert all(row.decided_at is None for row in stored)


async def test_a_check_that_passed_is_stored_with_no_findings(projection, rows):
    """`findings == 0` and `status == "ran"` -- the denominator, in a row."""
    project_id, review_id = uuid4(), uuid4()
    session = _session(project_id)
    _review(
        session,
        project_id,
        review_id,
        evaluated=[
            {"check": "shared.orphan", "severity": "blocking", "findings": 0},
            {"check": "shared.coverage", "severity": "blocking", "findings": 2},
        ],
    )

    await _project(projection, session)

    by_name = {row.check_name: row for row in await rows.find(None)}
    assert by_name["shared.orphan"].findings == 0
    assert by_name["shared.orphan"].status == "ran"
    assert by_name["shared.coverage"].findings == 2
    assert by_name["shared.coverage"].status == "ran"


async def test_an_unimplemented_binding_is_stored_as_unimplemented(projection, rows):
    """`status == "unimplemented"`, so `findings == 0` cannot be misread.

    Fails if the projection stores unimplemented bindings with status "ran",
    which would make every unimplemented check look like a check that passed.
    """
    project_id, review_id = uuid4(), uuid4()
    session = _session(project_id)
    _review(
        session,
        project_id,
        review_id,
        evaluated=[{"check": "shared.orphan", "severity": "blocking", "findings": 0}],
        unimplemented=[{"check": "shared.no_such_check", "severity": "advisory"}],
    )

    await _project(projection, session)

    by_name = {row.check_name: row for row in await rows.find(None)}
    assert by_name["shared.no_such_check"].status == "unimplemented"
    assert by_name["shared.no_such_check"].findings == 0
    assert by_name["shared.no_such_check"].severity == "advisory"
    assert by_name["shared.orphan"].status == "ran"


async def test_a_decision_fills_every_row_of_its_review(projection, rows):
    """The fold: a decision arriving later completes records written earlier.

    This is the whole feature. A review of nine checks followed by one approval
    leaves nine rows all carrying that approval, which is what makes "how often
    was this check overridden" a query rather than a join across two streams.
    """
    project_id, review_id = uuid4(), uuid4()
    session = _session(project_id)
    _review(session, project_id, review_id, evaluated=NINE_CHECKS)
    _decision(session, review_id=review_id, decision="approve", decided_by="human")

    await _project(projection, session)

    stored = await rows.find(None)
    assert len(stored) == 9
    assert {row.decision for row in stored} == {"approve"}
    assert {row.decided_by for row in stored} == {"human"}
    assert all(row.decided_at is not None for row in stored)
    assert all(row.decided_at >= row.evaluated_at for row in stored)


async def test_a_decision_only_fills_the_review_it_names(projection, rows):
    """Two reviews in one session must not be completed by one decision.

    Fails against a projection that filtered on the session rather than on the
    review -- which is the shape a first implementation reaches for, and which
    would attribute every later decision to every earlier gate.
    """
    project_id = uuid4()
    first, second = uuid4(), uuid4()
    session = _session(project_id)
    _review(
        session,
        project_id,
        first,
        evaluated=[{"check": "shared.coverage", "severity": "blocking", "findings": 1}],
    )
    _review(
        session,
        project_id,
        second,
        evaluated=[{"check": "shared.coverage", "severity": "blocking", "findings": 1}],
    )
    _decision(session, review_id=second, decision="reject")

    await _project(projection, session)

    by_review = {row.review_id: row for row in await rows.find(None)}
    assert by_review[first].decision is None
    assert by_review[second].decision == "reject"


async def test_a_decision_naming_no_review_is_ignored(projection, rows):
    """Not a poison event.

    A `ToolCallDecided` with `review_id=None` is every ordinary gated tool
    call. One with a `review_id` matching no row is a decision whose review a
    truncated rebuild has not replayed yet. Neither may raise -- a projection
    that dies on either stops updating every other row too.
    """
    session = _session()
    session.execute(
        RecordToolDecision(
            tool_name="web_search",
            args={"query": "backward design"},
            decision="approve",
            decided_by="human",
        )
    )
    _decision(session, review_id=uuid4())

    await _project(projection, session)

    assert await rows.find(None) == []


async def test_replaying_a_review_twice_leaves_one_row_per_check(projection, rows):
    """Idempotent under replay from a stale checkpoint.

    Weaker than it looks on its own, and the docstring says so rather than
    leaving it as reassurance: both repository implementations treat `save` as
    an upsert on the row id, so a blind insert passes this too. It is here for
    the derived row id -- a random one would double the rows -- and the test
    below is the one that constrains the handler.
    """
    project_id, review_id = uuid4(), uuid4()
    session = _session(project_id)
    _review(session, project_id, review_id, evaluated=NINE_CHECKS)
    events = list(session.uncommitted_events)

    for event in events:
        await projection.handle(event)
    for event in events:
        await projection.handle(event)

    assert len(await rows.find(None)) == 9


async def test_redelivering_a_review_alone_does_not_erase_its_decision(projection, rows):
    """Load-then-mutate, not blind insert -- and this is what that buys.

    At-least-once delivery means a single event can arrive twice without its
    neighbours: a handler retried after a transient failure, or a subscription
    resuming from a checkpoint written mid-review. A handler that constructed a
    fresh row would write the review's facts back with `decision` at its
    default and silently drop an answer that had already been recorded, leaving
    a gate that was decided looking like one nobody ever answered.

    A full-stream replay hides this, because the decision is re-applied
    afterwards -- which is why the case is redelivery of the review *alone*.
    """
    project_id, review_id = uuid4(), uuid4()
    session = _session(project_id)
    _review(session, project_id, review_id, evaluated=NINE_CHECKS)
    _decision(session, review_id=review_id, decision="reject", decided_by="human")
    review_event, decision_event = session.uncommitted_events[-2:]

    await projection.handle(review_event)
    await projection.handle(decision_event)
    await projection.handle(review_event)

    stored = await rows.find(None)
    assert len(stored) == 9
    assert {row.decision for row in stored} == {"reject"}
    assert {row.decided_by for row in stored} == {"human"}


async def test_a_decision_replayed_after_its_review_is_rewritten_is_still_applied(
    projection, rows
):
    """Order within a rebuild is stream order, so the review always precedes.

    Pinned because the opposite ordering is what a naive test fixture produces,
    and a projection that only worked in fixture order would pass the suite and
    fail on a real rebuild. The replay rewrites the review rows *after* the
    decision has already filled them once, so the decision has to be re-applied
    rather than merely not lost.
    """
    project_id, review_id = uuid4(), uuid4()
    session = _session(project_id)
    _review(session, project_id, review_id, evaluated=NINE_CHECKS)
    _decision(session, review_id=review_id, decision="edit", decided_by="human")
    events = list(session.uncommitted_events)

    for event in events:
        await projection.handle(event)
    for event in events:
        await projection.handle(event)

    stored = await rows.find(None)
    assert len(stored) == 9
    assert {row.decision for row in stored} == {"edit"}


async def test_a_rebuild_from_an_empty_table_reproduces_the_same_rows(rows):
    """The log is truth and this table is derived -- demonstrated, not assumed.

    A rebuild is the repair for drift, and it is only safe if a replay from
    nothing lands in the same place. `version` is excluded because it counts
    writes rather than describing the row.
    """
    project_id, review_id = uuid4(), uuid4()
    session = _session(project_id)
    _review(
        session,
        project_id,
        review_id,
        evaluated=NINE_CHECKS,
        unimplemented=[{"check": "ubd.uncoverage", "severity": "blocking"}],
    )
    _decision(session, review_id=review_id)
    events = list(session.uncommitted_events)

    first_projection = CheckTelemetryProjection(rows)
    for event in events:
        await first_projection.handle(event)
    first = {
        row.id: row.model_dump(exclude={"created_at", "updated_at", "version"})
        for row in await rows.find(None)
    }

    rebuilt = InMemoryReadModelRepository(CheckOutcomeRow)
    second_projection = CheckTelemetryProjection(rebuilt)
    for event in events:
        await second_projection.handle(event)
    second = {
        row.id: row.model_dump(exclude={"created_at", "updated_at", "version"})
        for row in await rebuilt.find(None)
    }

    assert first == second


# ---------------- against a database ----------------


async def test_the_table_is_created_on_open(db_path):
    """No migration step to forget: opening the store is enough."""
    store = await CheckTelemetryStore.open(db_path)
    try:
        assert await store.outcomes(uuid4()) == []
    finally:
        await store.close()


async def test_rows_outlive_the_process(db_path):
    project_id, review_id = uuid4(), uuid4()
    session = _session(project_id)
    _review(
        session,
        project_id,
        review_id,
        evaluated=[{"check": "shared.coverage", "severity": "blocking", "findings": 3}],
    )
    _decision(session, review_id=review_id)
    events = list(session.uncommitted_events)

    store = await CheckTelemetryStore.open(db_path)
    for event in events:
        await store.projection.handle(event)
    await store.close()

    reopened = await CheckTelemetryStore.open(db_path)
    try:
        stored = await reopened.outcomes(project_id)
        assert [row.check_name for row in stored] == ["shared.coverage"]
        assert stored[0].findings == 3
        assert stored[0].decision == "approve"
    finally:
        await reopened.close()


async def test_one_project_cannot_read_anothers_outcomes(db_path):
    project_id, other = uuid4(), uuid4()
    session = _session(project_id)
    _review(
        session,
        project_id,
        uuid4(),
        evaluated=[{"check": "shared.coverage", "severity": "blocking", "findings": 1}],
    )

    store = await CheckTelemetryStore.open(db_path)
    try:
        for event in session.uncommitted_events:
            await store.projection.handle(event)
        assert await store.outcomes(other) == []
        assert len(await store.outcomes(project_id)) == 1
    finally:
        await store.close()


async def test_a_database_written_before_check_outcomes_existed_gains_the_table(tmp_path):
    """A read-model change verified only against a fresh database is unverified.

    `CREATE TABLE IF NOT EXISTS` does nothing to a table that is already there
    -- and does the right thing when it is not. This opens a database that
    predates the table, applies the schema, and writes a row. Everything in
    this file above it builds its database from nothing, which is exactly the
    condition under which the `SessionSummaryRow` incident passed every test.
    """
    db_path = str(tmp_path / "old.db")
    connection = await aiosqlite.connect(db_path)
    await connection.execute("CREATE TABLE something_else (id TEXT PRIMARY KEY)")
    await connection.commit()
    await connection.close()

    project_id, review_id = uuid4(), uuid4()
    session = _session(project_id)
    _review(
        session,
        project_id,
        review_id,
        evaluated=[{"check": "shared.coverage", "severity": "blocking", "findings": 1}],
    )

    store = await CheckTelemetryStore.open(db_path)
    try:
        for event in session.uncommitted_events:
            await store.projection.handle(event)
        stored = await store.outcomes(project_id)
        assert [row.check_name for row in stored] == ["shared.coverage"]
    finally:
        await store.close()


async def test_the_runner_follows_the_log(db_path, store, publisher, repository):
    project_id, review_id = uuid4(), uuid4()
    runner = CheckTelemetryRunner(store, db_path, publisher)
    await runner.start()
    try:
        session = _session(project_id)
        _review(
            session,
            project_id,
            review_id,
            evaluated=[{"check": "shared.coverage", "severity": "blocking", "findings": 1}],
        )
        _decision(session, review_id=review_id, decision="reject")
        await repository.save(session)

        await runner.caught_up()
        outcomes = await runner.outcomes(project_id)
        assert [row.check_name for row in outcomes] == ["shared.coverage"]
        assert outcomes[0].decision == "reject"
    finally:
        await runner.stop()


async def test_caught_up_returns_with_other_aggregate_types_in_the_store(
    db_path, store, publisher, repository
):
    """The divergence from `CorpusRunner`, pinned.

    This projection is scoped to `Session` in a store holding many types,
    so a `caught_up` comparing against the store's *global* position would wait
    for an event it must never process and time out. The `Project` append below
    is what any real session produces on the way past.

    Fails as a 10s `TimeoutError` naming nothing about the cause, which is
    exactly why it is written down here.
    """
    project_id = uuid4()
    runner = CheckTelemetryRunner(store, db_path, publisher)
    await runner.start()
    try:
        session = _session(project_id)
        _review(
            session,
            project_id,
            uuid4(),
            evaluated=[{"check": "shared.coverage", "severity": "blocking", "findings": 1}],
        )
        await repository.save(session)
        await _append_a_non_session_event(store, publisher, project_id)

        await runner.caught_up(timeout=2.0)
        assert len(await runner.outcomes(project_id)) == 1
    finally:
        await runner.stop()


async def test_a_rebuild_reproduces_the_table_from_the_log(
    db_path, store, publisher, repository
):
    """The repair for drift, over a real store rather than a repository double.

    A rebuild that quietly left the checkpoint in place would resume over an
    empty table and look like success until someone read from it.
    """
    project_id, review_id = uuid4(), uuid4()
    runner = CheckTelemetryRunner(store, db_path, publisher)
    await runner.start()
    try:
        session = _session(project_id)
        _review(
            session,
            project_id,
            review_id,
            evaluated=NINE_CHECKS,
            unimplemented=[{"check": "ubd.uncoverage", "severity": "blocking"}],
        )
        _decision(session, review_id=review_id)
        await repository.save(session)
        await runner.caught_up()
        before = sorted(
            (row.check_name, row.status, row.decision)
            for row in await runner.outcomes(project_id)
        )

        await runner.rebuild()

        after = sorted(
            (row.check_name, row.status, row.decision)
            for row in await runner.outcomes(project_id)
        )
        assert after == before
        assert len(after) == 10
    finally:
        await runner.stop()


async def _append_a_non_session_event(store, publisher, project_id) -> None:
    """Move the store's global position with something this projection ignores.

    A `Project` append is the realistic case -- `start_in_project` ends with
    one -- and any aggregate type other than `Session` would do.
    """
    from research_team.domain.project import CreateProject, Project
    from research_team.infrastructure.persistence.event_store import build_project_repository

    project = Project(project_id)
    project.execute(CreateProject(project_id=project_id, name="somewhere else"))
    await build_project_repository(store, publisher).save(project)


def test_the_row_id_is_derived_from_the_review_and_the_check():
    """Derived rather than random, so a replay can find the row it wrote.

    Keyed on both because one review writes a row per check and one check
    appears in many reviews; either half alone collides.
    """
    review, other = uuid4(), uuid4()
    assert CheckOutcomeRow.row_id(review, "a") != CheckOutcomeRow.row_id(review, "b")
    assert CheckOutcomeRow.row_id(review, "a") != CheckOutcomeRow.row_id(other, "a")
    assert CheckOutcomeRow.row_id(review, "a") == CheckOutcomeRow.row_id(review, "a")
