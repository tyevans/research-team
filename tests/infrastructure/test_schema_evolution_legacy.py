"""Legacy workflow and retired event schema migration tests.

Reading retired events and legacy snapshots from older versions of the schema.
Covers legacy workflow events dropped when presets, stages, and check library
were removed, as well as pre-rename aggregates and snapshots.
"""

import json
from datetime import UTC, datetime
from uuid import uuid4

import aiosqlite
import pytest
from eventsource import (
    AggregateNotFoundError,
    EventTypeNotFoundError,
)
from eventsource.adapters.sqlite.snapshots import SQLiteSnapshotStore
from pydantic import ValidationError

from research_team.domain import (
    Project,
    SessionPurpose,
    StartSession,
)
from research_team.infrastructure.persistence.event_store import (
    build_project_repository,
)
from tests.conftest import MODEL_NAME, SYSTEM_PROMPT


async def _write_old_event(
    db_path: str,
    session_id,
    version: int,
    event_type: str,
    payload: dict,
    aggregate_type: str = "Session",
) -> None:
    """Insert an event exactly as an older build would have left it.

    Deliberately bypasses the library: constructing the event through today's
    model would add today's fields, which is the very thing under test.
    """
    async with aiosqlite.connect(db_path) as connection:
        await connection.execute(
            "INSERT INTO events (event_id, aggregate_id, aggregate_type, event_type,"
            " version, timestamp, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid4()),
                str(session_id),
                aggregate_type,
                event_type,
                version,
                datetime.now(UTC).isoformat(),
                json.dumps(payload),
            ),
        )
        await connection.commit()


@pytest.fixture
async def started(repository, session_id, db_path):
    """A session with only its creation event, written normally."""
    session = repository.create(session_id)
    session.execute(
        StartSession(
            session_id=session.aggregate_id,
            system_prompt=SYSTEM_PROMPT,
            model_name=MODEL_NAME,
            project_id=uuid4(),
            purpose=SessionPurpose.CHAT,
        )
    )
    await repository.save(session)
    return session_id


async def test_a_project_snapshot_written_while_the_workflow_fields_existed_still_loads(
    store, repository, started, db_path
):
    """The riskier half: projects are snapshotted, and a snapshot *is* the state.

    A stored snapshot is a serialized `ProjectState` from whenever it was
    taken, and unlike an event it is not reconstructed field by field from a
    stream -- it is handed to the model whole. So a snapshot written while
    `ProjectState` still carried `preset_id`, `preset_version`, `current_stage`
    and `stage_history` is the payload most likely to stop validating now that
    those four are gone, and it is loaded in preference to replaying, which
    means the failure would be silent until some specific old project was
    opened.

    It loads because `ProjectState` is an ordinary `BaseModel` and pydantic
    ignores unknown keys by default -- the four are read and dropped. That is
    the opposite of the event refusals below, where `DomainEvent` sets
    `extra="forbid"`, and the asymmetry is worth knowing: a *state* may quietly
    shed a field, a stored *fact* may not.

    Written at the schema version the library currently reads, deliberately:
    at a *mismatched* version it would be ignored and the aggregate replayed
    from events, which would pass this test while proving nothing. The
    snapshot's `name` differs from the creation event's for the same reason --
    it is the only thing here that distinguishes "the snapshot was loaded"
    from "the snapshot was skipped and the stream replayed cleanly". Without
    it this test passed against a repository that never read the snapshot.

    Builds its own project repository because the shared `repository` fixture
    is assembled without a snapshot store, and `build_project_repository` has
    no fallback that invents one. `SQLiteSnapshotStore` opens per-operation
    connections and needs no closing.
    """
    project_id = uuid4()
    await _write_old_event(
        db_path,
        project_id,
        version=1,
        event_type="ProjectCreated",
        payload={
            "aggregate_id": str(project_id),
            "aggregate_type": "Project",
            "aggregate_version": 1,
            "name": "atlas",
        },
        aggregate_type="Project",
    )
    async with aiosqlite.connect(db_path) as connection:
        await connection.execute(
            "INSERT INTO snapshots (aggregate_id, aggregate_type, version,"
            " schema_version, state, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(project_id),
                "Project",
                1,
                Project.schema_version,
                json.dumps(
                    {
                        "project_id": str(project_id),
                        "status": "created",
                        "name": "atlas-from-snapshot",
                        "member_session_ids": [],
                        "active_session_id": None,
                        "tip_session_id": None,
                        "tip_at_event": 0,
                        "preset_id": "hybrid.default",
                        "preset_version": "1",
                        "current_stage": "hybrid.step1.framing",
                        "stage_history": ["hybrid.step1.framing"],
                    }
                ),
                datetime.now(UTC).isoformat(),
            ),
        )
        await connection.commit()

    snapshots = SQLiteSnapshotStore(db_path)
    try:
        projects = build_project_repository(store, snapshot_store=snapshots)
        project = await projects.load(project_id)

        assert project.state.name == "atlas-from-snapshot"
        assert not hasattr(project.state, "preset_id")
        assert not hasattr(project.state, "stage_history")
    finally:
        await snapshots.close()


REMOVING_THE_WORKFLOW_SYSTEM = """The five shapes the workflow removal dropped.

The workflow system -- presets, stages, stage artifacts and the check library --
was removed whole. Five stored shapes went with it, and per the module
docstring's rule they are pinned below as *refusals* rather than deleted,
because "old data stops loading" should cost a test to change.

**They guard intent, not data.** Measured on 2026-08-27 against the real
`~/.research-team/sessions.db`: zero `ProjectWorkflowSelected` rows, zero
`ProjectStageAdvanced` rows, zero `StageChecksEvaluated` rows, and an empty
`check_outcomes` table. Nothing of these types was ever written outside a test,
so removing them could not break a replay of anything real -- there was nothing
of these types to replay. A later reader who assumes these cases were
load-bearing will conclude the removal was riskier than it was. It was not
risky at all; the cases exist so that a *future* payload of one of these shapes
fails loudly rather than arriving somewhere that shrugs.

The five deleted classes carry no docstring saying what no longer loads,
because there is no class left to carry one. These cases, and the commit that
wrote them, are that record.
"""


async def test_a_workflow_selection_no_longer_loads(repository, started, db_path):
    """`ProjectWorkflowSelected` is unregistered, so the registry cannot name it.

    Loud rather than silent: `eventsource` keys the registry by class name, and
    a name it has never heard of is not a shape it can guess at, so the read
    raises `EventTypeNotFoundError` naming the missing type. Written with a
    valid `ProjectCreated` ahead of it so the failure is provably this event
    rather than an empty or malformed stream.

    This replaces `test_an_event_renamed_by_the_naming_pass_no_longer_loads`,
    which wrote the pre-rename `WorkflowSelected` payload and asserted the same
    mechanism over the same aggregate. Both names are now unregistered, so the
    two had become one test with two spellings; the rename's own record lives
    in the commit that made it.

    See `REMOVING_THE_WORKFLOW_SYSTEM`: this guards intent, not data.
    """
    project_id = uuid4()
    await _write_old_event(
        db_path,
        project_id,
        version=1,
        event_type="ProjectCreated",
        payload={
            "aggregate_id": str(project_id),
            "aggregate_type": "Project",
            "aggregate_version": 1,
            "name": "atlas",
        },
        aggregate_type="Project",
    )
    await _write_old_event(
        db_path,
        project_id,
        version=2,
        event_type="ProjectWorkflowSelected",
        payload={
            "aggregate_id": str(project_id),
            "aggregate_type": "Project",
            "aggregate_version": 2,
            "preset_id": "hybrid.default",
            "preset_version": "1",
        },
        aggregate_type="Project",
    )

    with pytest.raises(EventTypeNotFoundError, match="ProjectWorkflowSelected"):
        await repository.projects.load(project_id)


async def test_a_stage_advance_no_longer_loads(repository, started, db_path):
    """`ProjectStageAdvanced` is unregistered; the same refusal as its sibling.

    Kept as its own case rather than parametrised with the selection above: a
    stream could hold either without the other, and one case covering both
    would let one of the two be quietly re-registered without failing.

    See `REMOVING_THE_WORKFLOW_SYSTEM`: this guards intent, not data.
    """
    project_id = uuid4()
    await _write_old_event(
        db_path,
        project_id,
        version=1,
        event_type="ProjectCreated",
        payload={
            "aggregate_id": str(project_id),
            "aggregate_type": "Project",
            "aggregate_version": 1,
            "name": "atlas",
        },
        aggregate_type="Project",
    )
    await _write_old_event(
        db_path,
        project_id,
        version=2,
        event_type="ProjectStageAdvanced",
        payload={
            "aggregate_id": str(project_id),
            "aggregate_type": "Project",
            "aggregate_version": 2,
            "from_stage": "tyler.step0.intake",
            "to_stage": "hybrid.step1.framing",
            "decided_by": "human",
            "gate_decision": "written while the workflow existed",
            "decision": "approve",
        },
        aggregate_type="Project",
    )

    with pytest.raises(EventTypeNotFoundError, match="ProjectStageAdvanced"):
        await repository.projects.load(project_id)


async def test_a_stage_check_evaluation_no_longer_loads(repository, started, db_path):
    """`StageChecksEvaluated` is unregistered, and it was on the *session* stream.

    Worth its own case for exactly that reason: the two above would both pass
    against a build that had dropped only the project events, and this is the
    one that would otherwise leave a session unreadable.

    See `REMOVING_THE_WORKFLOW_SYSTEM`: this guards intent, not data.
    """
    await _write_old_event(
        db_path,
        started,
        version=2,
        event_type="StageChecksEvaluated",
        payload={
            "aggregate_id": str(started),
            "aggregate_type": "Session",
            "aggregate_version": 2,
            "review_id": str(uuid4()),
            "project_id": str(uuid4()),
            "stage": "hybrid.step1.framing",
            "preset": "hybrid.default",
            "preset_version": "1",
            "evaluated": [],
            "unimplemented": [],
            "posed_by": "runner",
        },
    )

    with pytest.raises(EventTypeNotFoundError, match="StageChecksEvaluated"):
        await repository.events_for(started)


async def test_a_session_started_as_a_workflow_stage_no_longer_loads(
    repository, started, db_path
):
    """The third deliberate break on `SessionStarted.purpose`, in the same shape.

    `SessionPurpose.WORKFLOW_STAGE` named `StageRunner`, which is deleted, so
    the enum has no member left to validate `"workflow_stage"` against. Unlike
    the event refusals above this fails as a `ValidationError` rather than an
    `EventTypeNotFoundError` -- the event type is still registered, it is the
    field's value that has nowhere to land -- and that distinction is why this
    is asserted rather than assumed.

    Deliberately not translated to `CHAT`. A session driven by a stage runner
    was not a person at a keyboard, and defaulting it to one would fold machine
    turns into the count of human ones, which is precisely the collapse the
    enum's own docstring argues against.

    See `REMOVING_THE_WORKFLOW_SYSTEM`: this guards intent, not data.
    """
    session_id = uuid4()
    await _write_old_event(
        db_path,
        session_id,
        version=1,
        event_type="SessionStarted",
        payload={
            "aggregate_id": str(session_id),
            "aggregate_type": "Session",
            "aggregate_version": 1,
            "system_prompt": "p",
            "model_name": "m",
            "project_id": str(uuid4()),
            "purpose": "workflow_stage",
        },
    )

    with pytest.raises(ValidationError, match="purpose"):
        await repository.events_for(session_id)


async def test_a_tool_decision_carrying_a_review_id_no_longer_loads(
    repository, started, db_path
):
    """`ToolCallDecided.review_id` joined a decision to the stage review it answered.

    Nothing poses a stage review any more, so the field is gone and the join
    has no second side. A stored payload still carrying the key is refused
    rather than ignored, and it is `DomainEvent`'s `extra="forbid"` doing that,
    not a rule this file adds. Refusal is the honest outcome: dropping the key
    silently would read the event as a decision that answered nothing, which is
    a different fact from the one that was written down.

    This replaces `test_a_decision_written_before_review_ids_still_loads`,
    which asserted the field defaulted to `None` on a payload that omitted it.
    That assertion cannot be made about a field that does not exist, and
    weakening it to "a payload without the key still loads" would prove only
    what `..._before_edited_args_existed_still_loads` already proves.

    See `REMOVING_THE_WORKFLOW_SYSTEM`: this guards intent, not data.
    """
    await _write_old_event(
        db_path,
        started,
        version=2,
        event_type="ToolCallDecided",
        payload={
            "aggregate_id": str(started),
            "aggregate_type": "Session",
            "aggregate_version": 2,
            "tool_name": "advance_stage",
            "args": {"to_stage": "hybrid.step1.framing"},
            "decision": "approve",
            "decided_by": "human",
            "review_id": str(uuid4()),
        },
    )

    with pytest.raises(ValidationError, match="review_id"):
        await repository.events_for(started)


async def test_a_session_stored_as_codingsession_reads_as_no_session_at_all(
    repository, started, db_path
):
    """The other half of the break, and it fails in a different way.

    `CodingSession` became `Session`, and `aggregate_type` is not just a label
    on a row -- it is half of the stream identity. A stream read asks for
    `(aggregate_id, "Session")`, the stored rows say `"CodingSession"`, and the
    two never meet.

    So this is not the loud `EventTypeNotFoundError` above. `events_for`
    returns an empty list and `load` raises `AggregateNotFoundError` -- which
    is precisely what both do for an id that was never written at all. The old
    session does not fail to load *as a session*; it fails to exist. An
    operator looking at one cannot tell "written by an older build" from
    "wrong id pasted", and no error message will offer the distinction.

    Worth pinning for that reason rather than for the raise itself. The
    rename was still the right call and the cost is still affordable -- the
    project is pre-release and holds no real data -- but the failure mode is
    unhelpful in a way the event-name one is not, and anyone who meets it
    should find this test rather than a mystery.

    Both halves are asserted because they are separately surprising: the empty
    read is what a projection would see, and the raise is what a caller would.
    """
    session_id = uuid4()
    await _write_old_event(
        db_path,
        session_id,
        version=1,
        event_type="SessionStarted",
        payload={
            "aggregate_id": str(session_id),
            "aggregate_type": "CodingSession",
            "aggregate_version": 1,
            "system_prompt": SYSTEM_PROMPT,
            "model_name": MODEL_NAME,
            "project_id": str(uuid4()),
        },
        aggregate_type="CodingSession",
    )

    assert await repository.events_for(session_id) == []

    with pytest.raises(AggregateNotFoundError):
        await repository.load(session_id)
