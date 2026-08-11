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
from eventsource import StreamId, collect
from eventsource.adapters.sqlite.snapshots import SQLiteSnapshotStore
from pydantic import ValidationError

from research_team.domain import (
    CodingSession,
    ConversationCompacted,
    Project,
    SendUserMessage,
    SessionStarted,
    StageAdvanced,
    StartSession,
    ToolCallDecided,
    TurnFailed,
    current_stage_of,
)
from research_team.domain.topic import OpenTopic, TopicInvestigated
from research_team.infrastructure.persistence.event_store import (
    build_project_repository,
    build_topic_repository,
)
from research_team.workflows import hybrid_default
from tests.conftest import MODEL_NAME, SYSTEM_PROMPT


async def _write_old_event(
    db_path: str,
    session_id,
    version: int,
    event_type: str,
    payload: dict,
    aggregate_type: str = "CodingSession",
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
            "aggregate_type": "CodingSession",
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
            "aggregate_type": "CodingSession",
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
            "aggregate_type": "CodingSession",
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
            "aggregate_type": "CodingSession",
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
    is a `CodingSession` repository, and `Topic` is a different aggregate
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
        )
    )
    for index in range(60):  # comfortably past the snapshot threshold
        session.execute(
            SendUserMessage(message={"type": "human", "data": {"content": str(index)}})
        )
    await repository.save(session)
    await repository.drain_snapshots()

    monkeypatch.setattr(CodingSession, "schema_version", CodingSession.schema_version + 1)
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
            "aggregate_type": "CodingSession",
            "aggregate_version": 1,
            "system_prompt": "p",
            "model_name": "m",
        },
    )

    with pytest.raises(ValidationError, match="project_id"):
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
            "aggregate_type": "CodingSession",
            "aggregate_version": 1,
            "system_prompt": "p",
            "model_name": "m",
            "project_id": str(project_id),
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
        aggregate_type: str = "CodingSession"
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
            "aggregate_type": "CodingSession",
            "aggregate_version": 2,
            "reason": "written by the old shape",
        },
    )

    events = await repository.events_for(started)

    assert events[-1].error_message == "written by the old shape"


async def test_a_project_written_before_workflows_existed_still_loads(
    repository, started, db_path
):
    """`ProjectState` grew four workflow fields; every stored project predates them.

    The events did not change shape here -- the *state* did, which is the case
    the module docstring's rule 1 covers from the other side. An old project's
    stream simply has no `WorkflowSelected` in it, so the defaults have to mean
    "runs no workflow" rather than crash or, worse, imply a preset.

    Depends on `started` only to guarantee the tables exist; schema init
    happens on first save and nothing else here calls it.
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

    project = await repository.projects.load(project_id)

    assert project.state.name == "atlas"
    assert project.state.preset_id is None
    assert project.state.preset_version is None
    assert project.state.current_stage is None
    assert project.state.stage_history == []
    assert current_stage_of(project.state, hybrid_default) is None


async def test_an_old_project_snapshot_without_workflow_fields_still_loads(
    store, repository, started, db_path
):
    """The riskier half: projects are snapshotted, and a snapshot *is* the state.

    A stored snapshot is a serialized `ProjectState` from whenever it was
    taken, and unlike an event it is not reconstructed field by field from a
    stream -- it is handed to the model whole. So a snapshot written before
    these fields existed is the payload most likely to stop validating, and it
    is loaded in preference to replaying, which means the failure would be
    silent until some specific old project was opened.

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
        assert project.state.preset_id is None
        assert project.state.stage_history == []
    finally:
        await snapshots.close()


async def test_a_stage_advance_written_before_decision_existed_reads_as_approved(
    store, repository, started, db_path
):
    """`StageAdvanced.decision` is a case-1 addition; absence must mean `approve`.

    Every advance stored before the field existed had a human behind it -- the
    tool floors at `ask` and nothing else could call the command -- so the
    default reads the old payloads correctly rather than guessing at them.

    Written as a raw payload with no `decision` key, which is the only shape
    that proves the default fills in: constructing the event through today's
    model would supply it. The assertion on `decision` is the load-bearing one;
    the rest would pass against any build that could read the stream at all.
    """
    project_id = uuid4()
    payloads = (
        (1, "ProjectCreated", {"name": "atlas"}),
        (2, "WorkflowSelected", {"preset_id": "hybrid.default", "preset_version": "1"}),
        (
            3,
            "StageAdvanced",
            {
                "from_stage": "tyler.step0.intake",
                "to_stage": "hybrid.step1.framing",
                "decided_by": "human",
                "gate_decision": "written before the field existed",
            },
        ),
    )
    for version, event_type, payload in payloads:
        await _write_old_event(
            db_path,
            project_id,
            version=version,
            event_type=event_type,
            payload={
                "aggregate_id": str(project_id),
                "aggregate_type": "Project",
                "aggregate_version": version,
                **payload,
            },
            aggregate_type="Project",
        )

    project = await repository.projects.load(project_id)
    advanced = [
        envelope.event
        for envelope in await collect(
            store.read_stream(StreamId(project_id, Project.aggregate_type))
        )
        if isinstance(envelope.event, StageAdvanced)
    ]

    assert advanced[-1].decision == "approve"
    assert advanced[-1].gate_decision == "written before the field existed"
    assert project.state.current_stage == "hybrid.step1.framing"
    assert current_stage_of(project.state, hybrid_default).id == "hybrid.step1.framing"
