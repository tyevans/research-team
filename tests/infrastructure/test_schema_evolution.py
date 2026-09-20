"""Reading events written by an older version of this code.

Every event here has grown fields since it was first written -- `cancelled` on
`TurnFailed`, `tokens_before`/`tokens_after` on `ConversationCompacted` -- and
each of those was migrated by giving the new field a default. That works, and
nothing tested that it works, which is the same thing as it working by luck.

These tests write payloads in the *old* shape, straight into the events table,
and read them back through the ordinary path. They are the regression guard on
the migration strategy this project already relies on, and the place to add a
case the next time an event changes shape.
"""

import json
from datetime import UTC, datetime
from uuid import uuid4

import aiosqlite
import pytest
from eventsource import (
    AggregateNotFoundError,
    EventTypeNotFoundError,
    StreamId,
    collect,
)
from eventsource.adapters.sqlite.snapshots import SQLiteSnapshotStore
from pydantic import ValidationError

from research_team.domain import (
    ConversationCompacted,
    Project,
    SendUserMessage,
    Session,
    SessionPurpose,
    SessionStarted,
    StartSession,
    ToolCallDecided,
    TurnFailed,
)
from research_team.domain.research_run import ResearchRunStarted
from research_team.domain.topic import OpenTopic, TopicInvestigated
from research_team.infrastructure.persistence.event_store import (
    build_project_repository,
    build_research_run_repository,
    build_topic_repository,
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


async def test_a_turn_failure_written_before_cancellation_existed_still_loads(
    repository, started, db_path
):
    """`cancelled` defaults to False, which is what those events meant."""
    await _write_old_event(
        db_path,
        started,
        version=2,
        event_type="TurnFailed",
        payload={
            "aggregate_id": str(started),
            "aggregate_type": "Session",
            "aggregate_version": 2,
            "turn_index": 1,
            "error_type": "RuntimeError",
            "error_message": "boom",
        },
    )

    events = await repository.events_for(started)

    failure = events[-1]
    assert isinstance(failure, TurnFailed)
    assert failure.cancelled is False
    assert failure.error_type == "RuntimeError"


async def test_a_compaction_written_before_token_counts_existed_still_loads(
    repository, started, db_path
):
    """0 means "unrecorded", and reads as such rather than as a real count."""
    await _write_old_event(
        db_path,
        started,
        version=2,
        event_type="ConversationCompacted",
        payload={
            "aggregate_id": str(started),
            "aggregate_type": "Session",
            "aggregate_version": 2,
            "summary": "they talked about files",
            "through_index": 4,
            "strategy": "summarizing",
        },
    )

    events = await repository.events_for(started)

    compaction = events[-1]
    assert isinstance(compaction, ConversationCompacted)
    assert (compaction.tokens_before, compaction.tokens_after) == (0, 0)


async def test_an_old_event_still_folds_into_state(repository, started, db_path):
    """Loading is not enough -- the reducer has to accept it too."""
    await _write_old_event(
        db_path,
        started,
        version=2,
        event_type="TurnFailed",
        payload={
            "aggregate_id": str(started),
            "aggregate_type": "Session",
            "aggregate_version": 2,
            "turn_index": 1,
            "error_type": "RuntimeError",
            "error_message": "boom",
        },
    )

    session = await repository.load(started)

    assert session.state.failed_turns == 1
    assert session.state.turn_index == 0  # a failed turn did not happen


async def test_a_tool_call_decision_written_before_edited_args_existed_still_loads(
    repository, started, db_path
):
    """`edited_args` defaults to None, which is what its absence meant."""
    await _write_old_event(
        db_path,
        started,
        version=2,
        event_type="ToolCallDecided",
        payload={
            "aggregate_id": str(started),
            "aggregate_type": "Session",
            "aggregate_version": 2,
            "tool_name": "web_search",
            "args": {"query": "x"},
            "decision": "approve",
            "decided_by": "human",
        },
    )

    events = await repository.events_for(started)

    decision = events[-1]
    assert isinstance(decision, ToolCallDecided)
    assert decision.edited_args is None


async def test_an_investigation_written_before_outcome_existed_still_loads(store, db_path):
    """Reads back with `outcome` absent, not defaulted to a real value. A
    default of "produced" would claim every historic round found something.

    Builds its own topic repository because the shared `repository` fixture
    is a `Session` repository, and `Topic` is a different aggregate
    type over the same log.
    """
    topic_id = uuid4()
    topics = build_topic_repository(store)
    topic = topics.create_new(topic_id)
    topic.execute(
        OpenTopic(
            topic_id=topic_id,
            project_id=uuid4(),
            question="does the thing work?",
            rationale="it is on the critical path",
        )
    )
    await topics.save(topic)
    await _write_old_event(
        db_path,
        topic_id,
        version=2,
        event_type="TopicInvestigated",
        payload={
            "aggregate_id": str(topic_id),
            "aggregate_type": "Topic",
            "aggregate_version": 2,
            "at_position": "000000000042",
            "summary": "nothing recorded",
        },
        aggregate_type="Topic",
    )

    stream = StreamId(topic_id, "Topic")
    events = [envelope.event for envelope in await collect(store.read_stream(stream))]

    investigation = events[-1]
    assert isinstance(investigation, TopicInvestigated)
    assert investigation.outcome is None


async def test_an_auto_run_started_before_the_fetch_grant_existed_still_loads(store, db_path):
    """`fetch_hosts`/`fetch_budget` are a case-1 addition to a run's creation
    event; absence must mean "granted nothing", which is what every run
    before this feature actually was.

    Builds its own repository because the shared `repository` fixture is a
    `Session` repository, and `ResearchRun` is a different
    aggregate over the same log -- the same reason the topic test above does.
    Writes the payload with neither key present, which is the only shape that
    proves the defaults fill in; constructing the event through today's model
    would supply them.
    """
    run_id = uuid4()
    # Applies the schema, which the library does lazily on first use of the
    # connection -- writing the raw payload below is the store's first
    # touch otherwise, and `events` would not exist yet to insert into.
    await collect(store.read_stream(StreamId(run_id, "ResearchRun")))
    await _write_old_event(
        db_path,
        run_id,
        version=1,
        event_type="ResearchRunStarted",
        payload={
            "aggregate_id": str(run_id),
            "aggregate_type": "ResearchRun",
            "aggregate_version": 1,
            "project_id": str(uuid4()),
            "session_id": str(uuid4()),
        },
        aggregate_type="ResearchRun",
    )

    stream = StreamId(run_id, "ResearchRun")
    events = [envelope.event for envelope in await collect(store.read_stream(stream))]
    started = events[0]
    assert isinstance(started, ResearchRunStarted)
    assert started.fetch_hosts == []
    assert started.fetch_budget == 0

    runs = build_research_run_repository(store)
    run = await runs.load(run_id)
    assert run.state.fetch_hosts == []
    assert run.state.fetch_budget == 0


async def test_a_schema_version_bump_falls_back_to_replay(repository, session_id, monkeypatch):
    """The snapshot cliff, made explicit.

    Bumping `schema_version` invalidates every stored snapshot -- the library
    treats a mismatch as "no snapshot" and replays instead. That is the right
    default (a stale snapshot is a wrong answer; a slow load is a slow answer),
    but it means a bump silently costs a full replay per session until each one
    snapshots again. This test is what says the fallback is correct rather than
    fatal, so a future bump is a performance decision and not a gamble.
    """
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
    for index in range(60):  # comfortably past the snapshot threshold
        session.execute(
            SendUserMessage(message={"type": "human", "data": {"content": str(index)}})
        )
    await repository.save(session)
    await repository.drain_snapshots()

    monkeypatch.setattr(Session, "schema_version", Session.schema_version + 1)
    reloaded = await repository.load(session_id)

    assert reloaded.version == session.version
    assert len(reloaded.state.messages) == 60


async def test_session_started_without_project_id_no_longer_loads(
    repository, started, db_path
):
    """The deliberate exception to everything else in this file.

    Every other case here shows an old payload still reading correctly, by a
    default or a validator. This one shows the one shape that was dropped
    instead: `SessionStarted` with no `project_id`. It used to load with
    `project_id=None`, meaning "written before projects existed". A session now
    belongs to a project always, so `None` would mean a session with no
    filesystem, no knowledge graph and no course -- nothing downstream has
    handling for that, and there is no target shape to translate the old
    payload *to*, which is what a validator would need.

    So the payload is rejected, loudly, at read. Pinned here rather than left
    implicit because "old data stops loading" is exactly the kind of decision
    that should cost a test to change. It was affordable only because the
    project is pre-release and holds no real data.

    Written against a fresh id rather than `started`'s own session_id:
    `SessionStarted` must be the stream's first event, and that fixture
    already wrote one through the ordinary path. Depending on `started`
    anyway (rather than just `db_path`) is what guarantees the `events`
    table already exists -- schema init happens on first save, and this
    test is the only one that never calls it otherwise.
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
        },
    )

    with pytest.raises(ValidationError, match="project_id"):
        await repository.events_for(session_id)


async def test_session_started_without_purpose_no_longer_loads(repository, started, db_path):
    """The second deliberate break in this file, and it reads like the first.

    `SessionStarted` gained a required `purpose` so that a workflow attaches
    only to the kinds of turn that should drive it. A payload written before
    the field existed cannot be translated: the only available default is
    `CHAT`, and the sessions in an old database this build would be wrong
    about are exactly the auto-research ones the field was added to fix.

    So the payload is rejected at read. Pinned here because "old data stops
    loading" should cost a test to change. Affordable only because the project
    is pre-release and holds no real data.

    Proved non-vacuous by temporarily giving `SessionStarted.purpose` a
    `= SessionPurpose.CHAT` default and re-running: the test failed, because
    the default is exactly what would let this payload load silently.
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
        },
    )

    with pytest.raises(ValidationError, match="purpose"):
        await repository.events_for(session_id)


async def test_session_started_with_a_project_id_loads(repository, started, db_path):
    """The shape that replaced it, read back the same way.

    The counterpart to the rejection above: without this, that test would
    still pass if `SessionStarted` had stopped loading for some other reason
    entirely.
    """
    session_id = uuid4()
    project_id = uuid4()
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
            "project_id": str(project_id),
            "purpose": "chat",
        },
    )

    events = await repository.events_for(session_id)

    event = events[0]
    assert isinstance(event, SessionStarted)
    assert event.project_id == project_id


async def test_a_before_validator_can_reshape_an_old_payload(repository, started, db_path):
    """The seam for changes a default cannot express.

    Adding a field is easy: give it a default and old payloads read correctly,
    which is what the tests above pin down. Renaming or restructuring one is
    not -- there is no default that turns `reason` into `error_message`.

    The hook for that is a pydantic `model_validator(mode="before")` on the
    event class. It sees the stored dict before validation, which is exactly
    where an upcast belongs, and it needs nothing from the library: events are
    reconstructed through their own model on the way out of the registry. This
    test proves the mechanism on a throwaway event rather than a real one, so
    the pattern is established and checked before the first migration needs it.
    """
    from eventsource import DomainEvent, register_event
    from pydantic import model_validator

    # The registry is process-global and this class is registered at call
    # time rather than at import time, so its wire name has to be unique per
    # call: a test runner that executes the whole suite more than once in
    # the same process (mutation testing tools do this deliberately, to get
    # a clean baseline before mutating) would otherwise register
    # "RenamedFieldEvent" twice and raise DuplicateEventTypeError on the
    # second pass -- a self-inflicted failure that has nothing to do with
    # the mechanism under test.
    event_type = f"RenamedFieldEvent-{uuid4().hex}"

    @register_event(event_type=event_type)
    class RenamedFieldEvent(DomainEvent):
        aggregate_type: str = "Session"
        error_message: str

        @model_validator(mode="before")
        @classmethod
        def _upcast(cls, data):
            # v1 called this `reason`. Anything still carrying that key was
            # written before the rename, so translate rather than reject.
            if isinstance(data, dict) and "reason" in data:
                # Copy first, then move the key. `{**data, ...: data.pop(...)}`
                # spreads before it pops, so the old key survives into the copy
                # and the model rejects it as an extra field.
                data = dict(data)
                data["error_message"] = data.pop("reason")
            return data

    await _write_old_event(
        db_path,
        started,
        version=2,
        event_type=event_type,
        payload={
            "aggregate_id": str(started),
            "aggregate_type": "Session",
            "aggregate_version": 2,
            "reason": "written by the old shape",
        },
    )

    events = await repository.events_for(started)

    assert events[-1].error_message == "written by the old shape"


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
