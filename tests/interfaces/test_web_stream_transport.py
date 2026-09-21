"""SSE transport lifecycle, live socket, and reconnection cursor tests."""

import asyncio
import json
from uuid import uuid4

from httpx import AsyncClient

from research_team.composition import build_application as _build_application
from research_team.interfaces.web import create_app
from research_team.session.domain import (
    SendUserMessage,
    SessionPurpose,
    StartSession,
)
from tests.conftest import start_session


async def _started(**kwargs):
    """Build an application and start its projection.

    These tests construct their own applications rather than take the fixture,
    because they need the FastAPI app wired around the same instance. Starting
    is still not optional -- `/sessions` reads a projection that has to be
    following the log before it can answer.
    """
    application = _build_application(**kwargs)
    await application.start()
    return application


class StubRequest:
    """The only thing `_sse` asks a request: have you gone away yet."""

    def __init__(self, disconnect_after: int = 10_000) -> None:
        self._checks = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._checks += 1
        return self._checks > self._disconnect_after


async def _subscribed(generator) -> None:
    """Advance a stream to the point where it is actually listening.

    `_sse` takes its feed position and then yields `: ready`, so receiving that
    comment is a *fact* about the subscription rather than a guess about how
    long one takes to establish. Every test below that appends an event and
    expects to see it needs this first: an append that lands before the cursor
    is taken is not in the stream, and the test reads as "the feed is broken".

    It replaces `await asyncio.sleep(0.05)` -- and in the two tests that talk
    to a real server, `sleep(0.4)`. `BACKLOG.md` B4 is what those cost: a
    precondition expressed as a duration fails on a machine that is merely
    busy, and the failure looks exactly like a defect in the thing under test.
    """
    ready = await anext(generator)
    assert ready.startswith(": ready"), f"expected the ready comment, got {ready!r}"


async def _drain(generator, frames: list[str], *, wanted: int) -> None:
    """Collect `wanted` data frames, then shut the generator down.

    Leaving it suspended would leave its poll loop holding the store open past
    the end of the test, which surfaces much later as a stray database error.
    """
    try:
        async for frame in generator:
            # Event frames carry an id line ahead of their data; the only other
            # thing on the wire is a `:` keepalive comment.
            if not frame.startswith(":"):
                frames.append(frame)
                if len(frames) >= wanted:
                    return
    finally:
        await generator.aclose()


def _cursor_of(frame: str) -> str:
    return frame.split("id: ", 1)[1].split("\n", 1)[0]


async def _watch(feed, resume_from=None, wanted: int = 1):
    """Start an `_sse` stream and collect frames in the background.

    Returns the task and the list it fills. Subscribing *before* the events are
    appended is what makes the test meaningful: a stream takes its position
    when it is first iterated, not when it is constructed. `_subscribed` is
    what makes "before" a fact rather than a hope -- it used to be a 0.05s
    sleep, and the whole point of these tests is which side of the cursor an
    event landed on.
    """
    from research_team.interfaces.web.app import _sse

    frames: list[str] = []
    generator = _sse(StubRequest(), feed, resume_from)
    await _subscribed(generator)
    task = asyncio.create_task(_drain(generator, frames, wanted=wanted))
    return task, frames


async def test_sse_emits_a_keepalive_while_the_log_is_idle(repository, monkeypatch):
    """A minute of model thinking must not look like a dead connection."""
    from research_team.interfaces.web import app as web_app
    from research_team.interfaces.web.app import _sse
    from research_team.platform.shared.live_feed import LiveFeed

    monkeypatch.setattr(web_app, "KEEPALIVE_SECONDS", 0.05)
    generator = _sse(StubRequest(), LiveFeed(repository, poll_interval=0.01))
    await _subscribed(generator)
    frame = await asyncio.wait_for(anext(generator), timeout=5)
    assert frame == ": keepalive\n\n"
    await generator.aclose()


async def test_sse_stops_when_the_client_goes_away(repository, monkeypatch):
    from research_team.interfaces.web import app as web_app
    from research_team.interfaces.web.app import _sse
    from research_team.platform.shared.live_feed import LiveFeed

    monkeypatch.setattr(web_app, "KEEPALIVE_SECONDS", 0.01)
    generator = _sse(StubRequest(disconnect_after=2), LiveFeed(repository, poll_interval=0.01))
    frames = [frame async for frame in generator]
    # The stream announces itself, then keeps the connection warm, then ends.
    assert frames[0] == ": ready\n\n"
    assert all(frame == ": keepalive\n\n" for frame in frames[1:])


async def test_stream_reaches_a_real_browser_over_a_real_socket(db_path, fake_model):
    """One end-to-end proof over the wire, since the ASGI transport cannot."""
    import uvicorn

    application = await _started(model=fake_model, db_path=db_path)
    api = create_app(application.service, application.feed, application.turns)
    config = uvicorn.Config(api, host="127.0.0.1", port=8749, log_level="error")
    server = uvicorn.Server(config)
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)

    received: list[dict] = []
    # Set when the server says it is subscribed. `response.headers` arriving is
    # not that -- the route returns before the generator has taken its feed
    # position -- which is why this used to be a 0.4s sleep and why a busy
    # machine could put the write in front of the subscription.
    subscribed = asyncio.Event()

    async def listen() -> None:
        async with (
            AsyncClient(timeout=20) as browser,
            browser.stream("GET", "http://127.0.0.1:8749/api/stream") as response,
        ):
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            async for line in response.aiter_lines():
                if line.startswith(": ready"):
                    subscribed.set()
                    continue
                if not line.startswith("data: "):
                    continue
                received.append(json.loads(line[len("data: ") :]))
                # Read until the session's own frame rather than stopping at
                # the first one. `start_session` also writes to the `Project`
                # stream, and since the feed learned to carry `Project` those
                # frames arrive first -- so "the first frame" stopped being
                # the session's and this test failed asserting the wire was
                # broken when it was carrying more than before.
                if received[-1].get("type") == "SessionStarted":
                    return

    listener = asyncio.create_task(listen())
    try:
        await asyncio.wait_for(subscribed.wait(), timeout=10)
        session_id = await start_session(application.service)
        await asyncio.wait_for(listener, timeout=10)
    finally:
        # Let the server notice the browser has gone and unwind the streaming
        # response before shutting down: a poll still in flight when the store
        # closes is harmless but noisy.
        await asyncio.sleep(0.3)
        server.should_exit = True
        await serving
        await application.close()

    assert received[-1]["session_id"] == str(session_id)
    assert received[-1]["type"] == "SessionStarted"


async def test_each_frame_carries_the_cursor_that_follows_it(repository, session_id):
    """Without an id, a browser has nothing to reconnect with."""
    from research_team.platform.shared.live_feed import LiveFeed

    feed = LiveFeed(repository, poll_interval=0.01)
    aggregate = repository.create(session_id)
    aggregate.execute(
        StartSession(
            session_id=aggregate.aggregate_id,
            system_prompt="prompt",
            model_name="test-model",
            project_id=uuid4(),
            purpose=SessionPurpose.CHAT,
        )
    )
    await repository.save(aggregate)

    task, frames = await _watch(feed)
    aggregate.execute(SendUserMessage(message={"type": "human", "data": {"content": "hi"}}))
    await repository.save(aggregate)
    await asyncio.wait_for(task, timeout=5)

    assert frames[0].startswith("id: ")
    assert repository.decode_position(_cursor_of(frames[0])) is not None


async def test_reconnecting_with_a_cursor_delivers_what_was_missed(repository, session_id):
    """The gap a dropped connection leaves is the whole point of the id.

    The second message is appended while no stream is open at all, so a feed
    that started at the live end would never show it -- and the browser would
    have no way to know it had missed anything.
    """
    from research_team.platform.shared.live_feed import LiveFeed

    feed = LiveFeed(repository, poll_interval=0.01)
    aggregate = repository.create(session_id)
    aggregate.execute(
        StartSession(
            session_id=aggregate.aggregate_id,
            system_prompt="prompt",
            model_name="test-model",
            project_id=uuid4(),
            purpose=SessionPurpose.CHAT,
        )
    )
    await repository.save(aggregate)

    task, frames = await _watch(feed)
    aggregate.execute(SendUserMessage(message={"type": "human", "data": {"content": "seen"}}))
    await repository.save(aggregate)
    await asyncio.wait_for(task, timeout=5)
    cursor = _cursor_of(frames[0])

    # Nobody is listening for this one.
    aggregate.execute(
        SendUserMessage(message={"type": "human", "data": {"content": "missed"}})
    )
    await repository.save(aggregate)

    resumed, recovered = await _watch(feed, resume_from=cursor)
    await asyncio.wait_for(resumed, timeout=5)

    assert json.loads(recovered[0].split("data: ", 1)[1])["type"] == "UserMessageSent"
    assert _cursor_of(recovered[0]) != cursor


async def test_an_unplaceable_cursor_falls_back_to_the_live_end(repository, session_id):
    """A stale or foreign id must not replay the whole log at a browser."""
    from research_team.platform.shared.live_feed import LiveFeed

    feed = LiveFeed(repository, poll_interval=0.01)
    aggregate = repository.create(session_id)
    aggregate.execute(
        StartSession(
            session_id=aggregate.aggregate_id,
            system_prompt="prompt",
            model_name="test-model",
            project_id=uuid4(),
            purpose=SessionPurpose.CHAT,
        )
    )
    await repository.save(aggregate)  # already in the log, must not be replayed

    task, frames = await _watch(feed, resume_from="junk-from-another-database")
    aggregate.execute(SendUserMessage(message={"type": "human", "data": {"content": "after"}}))
    await repository.save(aggregate)
    await asyncio.wait_for(task, timeout=5)

    payload = json.loads(frames[0].split("data: ", 1)[1])
    assert payload["type"] == "UserMessageSent"
