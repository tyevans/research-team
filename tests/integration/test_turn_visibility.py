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
    Session,
    ToolResultRecorded,
    TurnCompleted,
    TurnFailed,
    UserMessageSent,
)
from research_team.interfaces.web import TurnActivity
from tests.application.test_turn_supervisor import CountingModel, once_inside_the_model
from tests.conftest import start_session


class SlowWritingModel(CountingModel):
    """Writes a file, slowly enough that a watcher could see it mid-turn.

    A `CountingModel` so a test can wait for "the turn has reached the model"
    rather than sleeping for longer than it hopes that takes. That distinction
    is `BACKLOG.md` B4's, and this file had four sleeps standing in for it.
    """

    delay: float = 1.0

    async def _agenerate(self, *args: Any, **kwargs: Any):
        self._enter()
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


async def _watching(feed, collected: list[FeedEntry]):
    """Start a watcher and return once it is genuinely subscribed.

    The position is taken *here*, before the task exists, so "the watcher is
    listening" is established rather than waited out -- `feed.follow()` would
    take it on the task's first turn, some time after `create_task` returns,
    and every test below writes immediately afterwards. Three of them used
    `await asyncio.sleep(0.2)` to cover that gap.

    `from_start` when the log is empty, for the reason `_sse` does the same:
    an empty log has no position, and `None` is also how `follow` is told to
    choose for itself. `test_web.py`'s
    `first_event_in_an_empty_log_still_reaches_a_subscriber` is where that is
    pinned.
    """
    start_at = await feed.position_now()
    return asyncio.create_task(_watch(feed, collected, start_at))


async def _watch(feed, collected: list[FeedEntry], start_at=None) -> None:
    """Collect the session's own frames, and only those.

    Filtered rather than taking everything the feed hands over, because these
    tests are about a *turn* and the feed carries more than one aggregate.
    `start_session` writes to the `Project` stream as well as the session's,
    and once the feed learned to carry `Project` those frames landed in this
    list -- arriving on a later poll than the session's, so they counted as a
    turn being visible while it ran and failed three tests here that were
    describing something true.

    Scoping to `Session` is what these tests always meant. Left
    unfiltered they would fail again on the next aggregate admitted to the
    feed, and the failure would look like a broken atomicity guarantee rather
    than a widened feed -- the expensive kind of wrong.
    """
    async for entry in feed.follow(from_position=start_at, from_start=start_at is None):
        if entry.aggregate_type == Session.aggregate_type:
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
    watcher = await _watching(application.feed, seen)

    session_id = await start_session(application.service)
    await _settle(seen, 1)  # the session's own creation event
    before_turn = len(seen)

    turn = asyncio.create_task(application.turns.run(session_id, "write a file"))
    # Mid-turn: inside the model, which has not answered yet.
    await once_inside_the_model(writing_model)
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
    watcher = await _watching(application.feed, seen)

    session_id = await start_session(application.service)
    turn = asyncio.create_task(application.turns.run(session_id, "write a file"))
    await once_inside_the_model(writing_model)
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
    watcher = await _watching(application.feed, seen)

    session_id = await start_session(application.service)
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
    session_id = await start_session(application.service)

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
