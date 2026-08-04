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

from research_team.domain import CodingSession, ConversationCompacted, TurnFailed
from tests.conftest import MODEL_NAME, SYSTEM_PROMPT


async def _write_old_event(
    db_path: str, session_id, version: int, event_type: str, payload: dict
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
                "CodingSession",
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
    session.start(SYSTEM_PROMPT, MODEL_NAME)
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


async def test_a_schema_version_bump_falls_back_to_replay(
    repository, session_id, monkeypatch
):
    """The snapshot cliff, made explicit.

    Bumping `schema_version` invalidates every stored snapshot -- the library
    treats a mismatch as "no snapshot" and replays instead. That is the right
    default (a stale snapshot is a wrong answer; a slow load is a slow answer),
    but it means a bump silently costs a full replay per session until each one
    snapshots again. This test is what says the fallback is correct rather than
    fatal, so a future bump is a performance decision and not a gamble.
    """
    session = repository.create(session_id)
    session.start(SYSTEM_PROMPT, MODEL_NAME)
    for index in range(60):  # comfortably past the snapshot threshold
        session.send_user_message({"type": "human", "data": {"content": str(index)}})
    await repository.save(session)
    await repository.drain_snapshots()

    monkeypatch.setattr(
        CodingSession, "schema_version", CodingSession.schema_version + 1
    )
    reloaded = await repository.load(session_id)

    assert reloaded.version == session.version
    assert len(reloaded.state.messages) == 60


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

    @register_event
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
        event_type="RenamedFieldEvent",
        payload={
            "aggregate_id": str(started),
            "aggregate_type": "CodingSession",
            "aggregate_version": 2,
            "reason": "written by the old shape",
        },
    )

    events = await repository.events_for(started)

    assert events[-1].error_message == "written by the old shape"
