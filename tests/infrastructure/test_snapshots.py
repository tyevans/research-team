"""Snapshot scheduling: a save must not wait on the snapshot it triggers.

Snapshotting is an optimisation for later reads. Paying for it inside the
`save()` that a user's turn is waiting on trades a fast turn for a fast replay,
which is the wrong way round -- replays are rare and turns are not.
"""

from uuid import uuid4

from research_team.domain import (
    SendUserMessage,
    Session,
    SessionPurpose,
    StartSession,
)
from research_team.infrastructure.persistence import SNAPSHOT_THRESHOLD
from tests.conftest import MODEL_NAME, SYSTEM_PROMPT


async def _grow_past_threshold(session: Session) -> None:
    """Append enough events that the next save crosses the snapshot threshold."""
    for index in range(SNAPSHOT_THRESHOLD + 1):
        session.execute(
            SendUserMessage(message={"type": "human", "data": {"content": str(index)}})
        )


async def test_save_does_not_wait_for_the_snapshot_it_triggers(aggregates, session_id):
    session = aggregates.create_new(session_id)
    session.execute(
        StartSession(
            session_id=session.aggregate_id,
            system_prompt=SYSTEM_PROMPT,
            model_name=MODEL_NAME,
            project_id=uuid4(),
            purpose=SessionPurpose.CHAT,
        )
    )
    await _grow_past_threshold(session)

    await aggregates.save(session)

    # The snapshot is owed but not yet taken: `save` handed it to a scheduler
    # and returned. Under sync mode this count is always 0, because the write
    # already happened before `save` came back.
    assert aggregates.pending_snapshot_count > 0


async def test_the_backgrounded_snapshot_still_gets_written(aggregates, session_id):
    session = aggregates.create_new(session_id)
    session.execute(
        StartSession(
            session_id=session.aggregate_id,
            system_prompt=SYSTEM_PROMPT,
            model_name=MODEL_NAME,
            project_id=uuid4(),
            purpose=SessionPurpose.CHAT,
        )
    )
    await _grow_past_threshold(session)
    await aggregates.save(session)

    await aggregates.await_pending_snapshots()

    # Deferred, not skipped: a later load starts from the snapshot.
    reloaded = await aggregates.load(session_id)
    assert reloaded.version == session.version
    assert len(reloaded.state.messages) == SNAPSHOT_THRESHOLD + 1


async def test_closing_waits_for_snapshots_still_in_flight(repository, session_id):
    """Shutdown must not pull the connection out from under a running snapshot.

    Backgrounding the write means there is now a window where the process is
    told to stop while a snapshot is mid-flight. Closing the store first would
    turn that into an error on a task nobody is awaiting -- so `close` drains
    before it releases.
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
    await _grow_past_threshold(session)
    await repository.save(session)
    assert repository.pending_snapshot_count > 0

    await repository.close()

    assert repository.pending_snapshot_count == 0
