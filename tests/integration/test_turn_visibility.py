"""When a turn becomes visible to everyone else.

The answer is "all at once, when it commits", and that is not a detail -- it is
the all-or-nothing guarantee observed from outside the turn. A watcher never
sees half a turn, and equally never sees a turn in progress.
"""

import asyncio
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from research_team.application import FeedEntry, TurnCancelled
from research_team.application.ports import ActivityDelta, ActivityMessage
from research_team.domain import (
    AssistantMessageAdded,
    FileWritten,
    ToolResultRecorded,
    TurnCompleted,
    TurnFailed,
    UserMessageSent,
)
from research_team.interfaces.web import TurnActivity
from tests.conftest import ToolAwareFakeChatModel


class SlowWritingModel(ToolAwareFakeChatModel):
    """Writes a file, slowly enough that a watcher could see it mid-turn."""

    delay: float = 1.0

    async def _agenerate(self, *args: Any, **kwargs: Any):
        await asyncio.sleep(self.delay)
        return await super()._agenerate(*args, **kwargs)


@pytest.fixture
def writing_model() -> SlowWritingModel:
    return SlowWritingModel(
        responses=[
            AIMessage(
                content="",
                id="w1",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {"file_path": "/a.py", "content": "x\n"},
                        "id": "k1",
                    }
                ],
            ),
            AIMessage(content="done", id="w2"),
        ]
    )


async def _watch(feed, collected: list[FeedEntry]) -> None:
    async for entry in feed.follow():
        collected.append(entry)


async def _settle(seen: list[FeedEntry], count: int, timeout: float = 5.0) -> None:
    """Wait until `count` frames have been delivered.

    The feed polls, so "has it arrived yet" is a question with an answer worth
    waiting for rather than guessing at with a fixed sleep.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while len(seen) < count:
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"only {len(seen)} of {count} frames arrived")
        await asyncio.sleep(0.05)


async def test_a_turns_events_all_become_visible_at_once(build_application, writing_model):
    """A watcher sees nothing until the turn commits, then sees all of it.

    This is what makes the log safe to read at any moment: there is no instant
    at which it holds half a turn.
    """
    application = await build_application(model=writing_model)
    seen: list[FeedEntry] = []
    watcher = asyncio.create_task(_watch(application.feed, seen))
    await asyncio.sleep(0.2)

    session_id = await application.service.create_session()
    await _settle(seen, 1)  # the session's own creation event
    before_turn = len(seen)

    turn = asyncio.create_task(application.turns.run(session_id, "write a file"))
    await asyncio.sleep(0.5)  # mid-turn: the model has not answered yet
    during_turn = len(seen)

    await turn
    await _settle(seen, before_turn + 6)
    watcher.cancel()

    assert during_turn == before_turn, "a turn must not be visible while it runs"
    appeared = [type(entry.event) for entry in seen[before_turn:]]
    assert appeared == [
        UserMessageSent,
        FileWritten,
        AssistantMessageAdded,
        ToolResultRecorded,
        AssistantMessageAdded,
        TurnCompleted,
    ]


async def test_a_cancelled_turns_events_never_become_visible(build_application, writing_model):
    """Discarded events are not "removed" from the feed -- they never reach it."""
    writing_model.delay = 5.0
    application = await build_application(model=writing_model)
    seen: list[FeedEntry] = []
    watcher = asyncio.create_task(_watch(application.feed, seen))
    await asyncio.sleep(0.2)

    session_id = await application.service.create_session()
    turn = asyncio.create_task(application.turns.run(session_id, "write a file"))
    await asyncio.sleep(0.4)
    await application.turns.cancel(session_id)
    with pytest.raises(TurnCancelled):
        await turn
    await _settle(seen, 2)  # the session start, then the failure marker
    watcher.cancel()

    kinds = [type(entry.event) for entry in seen]
    assert TurnFailed in kinds
    assert UserMessageSent not in kinds
    assert FileWritten not in kinds


async def test_the_reported_span_matches_what_the_watcher_saw(
    build_application, writing_model
):
    """A watching tab can derive the turn's span from the frames alone."""
    application = await build_application(model=writing_model)
    seen: list[FeedEntry] = []
    watcher = asyncio.create_task(_watch(application.feed, seen))
    await asyncio.sleep(0.2)

    session_id = await application.service.create_session()
    await _settle(seen, 1)
    first_new = len(seen)

    outcome = await application.turns.run(session_id, "write a file")
    await _settle(seen, first_new + 6)
    watcher.cancel()

    frames = seen[first_new:]
    versions = [entry.event.aggregate_version for entry in frames]
    assert versions[0] == outcome.from_index
    assert versions[-1] == outcome.to_index


async def test_activity_streams_without_appending_to_the_log(build_application, writing_model):
    """The whole design in one assertion: content streams, the log does not move.

    `TurnActivity` exists so a browser tab can watch a turn happen -- prose
    and tool notes as they are produced, well before the turn commits. But
    that channel is deliberately *not* the log: it is a provisional, throwaway
    buffer, wired up beside the atomic append rather than folded into it. This
    test proves that "beside" holds: while a turn is running and reporting
    activity, the session's event count does not move. It changes exactly
    once, when the turn commits.

    If this ever fails, someone has made the turn incremental -- appending
    events as they happen instead of once at the end -- which means a failed
    or cancelled turn could no longer be discarded whole, and the guarantee
    the other tests in this file exist to protect is gone.
    """
    application = await build_application(model=writing_model)
    activity = TurnActivity()
    session_id = await application.service.create_session()

    observed: list[ActivityMessage | ActivityDelta] = []
    first_note = asyncio.Event()

    def watch(note: ActivityMessage | ActivityDelta) -> None:
        # Recorded before the real reporter runs, so `during` below is read
        # at the earliest possible instant -- the moment the turn first has
        # something to show, not some point later in its run.
        observed.append(note)
        first_note.set()

    activity.begin(session_id)
    reporter = activity.reporter(session_id)

    def wrapped(note: ActivityMessage | ActivityDelta) -> None:
        watch(note)
        reporter(note)

    before = len(await application.service.history(session_id))
    turn = asyncio.create_task(application.turns.run(session_id, "write a file", wrapped))
    await asyncio.wait_for(first_note.wait(), timeout=5.0)
    during = len(await application.service.history(session_id))

    try:
        await turn
    except BaseException:
        activity.settle(session_id, committed=False)
        raise
    else:
        activity.settle(session_id, committed=True)
    after = len(await application.service.history(session_id))

    assert observed, "the turn reported no activity at all -- this test would pass vacuously"
    assert during == before, "the log grew while the turn was still streaming activity"
    assert after > before, "the turn's events never made it to the log"
    # The buffer is provisional; once the log has the real thing, nothing of
    # it should survive to be shown as if it were still in flight.
    assert activity.current(session_id) == []
