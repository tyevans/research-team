"""The store-backed feed's wakeup signal.

`LiveFeed` reads through the store, but it asks the feed when to bother
looking. These tests are about that signal -- that a local write raises it
promptly, and that its absence costs nothing worse than the poll interval.
"""

import asyncio
from uuid import uuid4

from research_team.domain import (
    StartSession,
)
from tests.conftest import MODEL_NAME, SYSTEM_PROMPT


async def test_a_local_save_wakes_a_waiting_reader(repository, session_id):
    session = repository.create(session_id)
    session.execute(
        StartSession(
            session_id=session.aggregate_id,
            system_prompt=SYSTEM_PROMPT,
            model_name=MODEL_NAME,
            project_id=uuid4(),
        )
    )

    # A long timeout, so returning quickly can only mean the save signalled.
    waiting = asyncio.create_task(repository.wait_for_append(timeout=30.0))
    await asyncio.sleep(0)
    await repository.save(session)

    await asyncio.wait_for(waiting, timeout=2)


async def test_waiting_gives_up_after_the_timeout_when_nothing_is_written(repository):
    """No writer, no signal -- the wait has to end on its own.

    This is the out-of-process case: another process appending to the same
    file raises nothing on our bus, so the timeout is what bounds staleness.
    """
    await asyncio.wait_for(repository.wait_for_append(timeout=0.05), timeout=2)


async def test_a_save_before_the_wait_does_not_leave_a_signal_standing(repository, session_id):
    """The signal means "something happened while you were waiting".

    A latch left set by an earlier write would make the next wait return
    immediately and read nothing, and the one after that too -- a busy loop
    dressed up as a push feed.
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
    await repository.save(session)

    # A long timeout and a short look, rather than the reverse. What is being
    # asserted is that the wait does *not* return early, and there is no event
    # to wait on for a thing that must not happen -- so this one keeps a
    # duration. What it does not keep is a narrow margin: it used to wait 0.3s
    # and look after 0.1s, so a machine three times slower than expected would
    # see the wait time out on its own and report a standing latch that was
    # never there. A hundredfold is not a race.
    with_stale_signal = asyncio.create_task(repository.wait_for_append(timeout=10.0))
    await asyncio.sleep(0.1)

    assert not with_stale_signal.done()
    with_stale_signal.cancel()


async def test_a_position_survives_a_round_trip_through_text(repository, session_id):
    """Positions are opaque, but they still have to fit in an SSE event id."""
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
    position = await repository.latest_position()

    restored = repository.decode_position(repository.encode_position(position))

    assert restored == position


async def test_a_position_from_somewhere_else_is_refused(repository):
    """Better a clean rejection than a cursor silently meaning nothing.

    An event id comes back from a browser, and a browser is free to send
    anything -- including one it kept from a different database.
    """
    assert repository.decode_position("not-a-position") is None
    assert repository.decode_position('{"s":"some-other-store","k":[7]}') is None
