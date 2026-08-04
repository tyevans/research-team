"""HTTP + SSE adapter over the same use cases the REPL drives.

Stateless by construction: every route names the session it acts on, so any
number of browsers can look at any number of sessions at once. That is the
whole reason the application layer stopped holding a "current session".
"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from eventsource import OptimisticLockError
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from research_team.application import (
    LiveFeed,
    SessionService,
    TurnAlreadyRunning,
    TurnCancelled,
    TurnSupervisor,
    build_fork_tree,
)
from research_team.interfaces.web.presenters import (
    event_rows,
    feed_event,
    file_history,
    session_view,
    summary_view,
    tree_view,
)

STATIC_DIR = Path(__file__).parent / "static"

KEEPALIVE_SECONDS = 15.0

DISCONNECT_CHECK = 0.5
"""How long we may sit unaware that the browser has gone."""


class NewSession(BaseModel):
    system_prompt: str | None = None


class NewTurn(BaseModel):
    input: str


class NewFork(BaseModel):
    at: int


def create_app(
    service: SessionService,
    feed: LiveFeed,
    turns: TurnSupervisor,
    lifespan=None,
) -> FastAPI:
    """Build the app around an already-wired service. Composition stays outside.

    `lifespan` is how the composition root gets a foot inside the server's
    event loop. Anything holding a connection bound to the loop that opened it
    -- the `/sessions` projection, in particular -- has to be started there
    rather than at construction time, and this is the only hook the server
    offers for that.
    """
    app = FastAPI(title="research-team", docs_url="/api/docs", lifespan=lifespan)

    async def _load(session_id: UUID):
        try:
            return await service.load(session_id)
        except Exception as error:
            raise HTTPException(status_code=404, detail=f"no session {session_id}") from error

    @app.get("/api/sessions")
    async def list_sessions():
        return [summary_view(summary) for summary in await service.list_sessions()]

    @app.post("/api/sessions")
    async def create_session(body: NewSession | None = None):
        prompt = body.system_prompt if body else None
        return {"id": str(await service.create_session(prompt))}

    @app.get("/api/health")
    async def health():
        """Whether the derived views behind this API can be trusted.

        `/sessions` is answered from a projection, so unlike a fold it can be
        wrong -- and a wrong row looks exactly like a right one. This is where
        a UI finds out to say so.
        """
        summaries = await service.summaries_health()
        return {
            "summaries": {
                "healthy": summaries.healthy,
                "failed_events": summaries.failed_events,
                "following": summaries.following,
                "behind": summaries.behind,
            }
        }

    @app.post("/api/summaries/rebuild")
    async def rebuild_summaries():
        """Derive the session list from the log again, and report the result.

        Exposed over HTTP because the browser is the primary surface and a
        problem you can see but not fix is only half-reported. Safe to call at
        any time: it discards derived data and recomputes it, so the worst case
        is wasted work, and the log it derives from is never touched.
        """
        await service.rebuild_summaries()
        health = await service.summaries_health()
        return {"healthy": health.healthy, "failed_events": health.failed_events}

    @app.get("/api/tree")
    async def fork_tree():
        return tree_view(build_fork_tree(await service.list_sessions()))

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: UUID):
        session = await _load(session_id)
        return session_view(session, await service.history(session_id))

    @app.get("/api/sessions/{session_id}/events")
    async def get_events(session_id: UUID):
        await _load(session_id)
        return event_rows(await service.history(session_id))

    @app.get("/api/sessions/{session_id}/at/{at}")
    async def get_session_at(session_id: UUID, at: int):
        """Time travel: the workspace as of event `at`. Folds, never writes."""
        try:
            session = await service.state_at(session_id, at)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return session_view(session, await service.history(session_id), at=at)

    @app.get("/api/sessions/{session_id}/files")
    async def get_file(session_id: UUID, path: str, at: int | None = None):
        """A file's contents, at HEAD or as of event `at`.

        Scrubbing has to be able to read a file that no longer exists at HEAD --
        seeing a deleted file again is the point of time travel, not an error.
        """
        if at is None:
            session = await _load(session_id)
        else:
            try:
                session = await service.state_at(session_id, at)
            except ValueError as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
        entry = session.state.files.get(path)
        if entry is None:
            moment = "at HEAD" if at is None else f"as of event {at}"
            raise HTTPException(status_code=404, detail=f"{path}: not found {moment}")
        return {"path": path, "content": entry.get("content", ""), "at": at}

    @app.get("/api/sessions/{session_id}/files/history")
    async def get_file_history(session_id: UUID, path: str):
        await _load(session_id)
        return file_history(await service.history(session_id), path)

    @app.post("/api/sessions/{session_id}/turns")
    async def run_turn(session_id: UUID, body: NewTurn):
        await _load(session_id)
        try:
            outcome = await turns.run(session_id, body.input)
        except TurnAlreadyRunning as error:
            raise HTTPException(
                status_code=409,
                detail="a turn is already running on this session",
            ) from error
        except TurnCancelled as error:
            # Not a failure: someone asked for this. 499 is nginx's
            # "client closed request" -- the closest thing to a standard code
            # for work abandoned on purpose.
            raise HTTPException(status_code=499, detail=str(error)) from error
        except OptimisticLockError as error:
            # Another writer -- the REPL, or a second process -- got there
            # first. The log is append-only and the loser's events were
            # discarded whole, so nothing happened; this is a retry.
            raise HTTPException(
                status_code=409,
                detail="another turn was recorded on this session first; reload and retry",
            ) from error
        return {
            "reply": outcome.reply,
            "turn_index": outcome.turn_index,
            "from_index": outcome.from_index,
            "to_index": outcome.to_index,
        }

    @app.post("/api/sessions/{session_id}/turns/cancel")
    async def cancel_turn(session_id: UUID):
        """Stop the in-flight turn on this session, if there is one.

        Returns once the turn has actually unwound, so a caller that hears
        "cancelled" can trust the log already reflects it.
        """
        await _load(session_id)
        cancellation = await turns.cancel(session_id)
        return {
            "cancelled": cancellation.cancelled,
            "settled": cancellation.settled,
        }

    @app.get("/api/sessions/{session_id}/turns/current")
    async def current_turn(session_id: UUID):
        """What is in flight -- so a tab that arrived mid-turn can say so."""
        await _load(session_id)
        running = turns.running(session_id)
        if running is None:
            return {
                "running": False,
                "turn_index": None,
                "started_at": None,
                "elapsed_seconds": None,
            }
        return {
            "running": True,
            "turn_index": running.turn_index,
            "started_at": running.started_at.isoformat(),
            "elapsed_seconds": running.elapsed_seconds(datetime.now(UTC)),
        }

    @app.post("/api/sessions/{session_id}/forks")
    async def fork_session(session_id: UUID, body: NewFork):
        await _load(session_id)
        try:
            return {"id": str(await service.fork(session_id, body.at))}
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/stream")
    async def stream(request: Request) -> StreamingResponse:
        """Every event, as it is appended, to every listening browser.

        `Last-Event-ID` is the browser's own reconnect header -- EventSource
        sends it automatically with the id of the last frame it received, so
        resuming costs the client nothing and closes the window where events
        appended during a dropped connection would never be seen.
        """
        resume_from = request.headers.get("last-event-id")
        return StreamingResponse(
            _sse(request, feed, resume_from),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/")
        async def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    return app


async def _sse(
    request: Request, feed: LiveFeed, resume_from: str | None = None
) -> AsyncIterator[str]:
    """Serialise the live feed as server-sent events.

    Keepalive comments keep intermediaries from closing an idle connection --
    a session can sit silent for a minute while the model thinks, which is
    exactly when the browser most needs the connection to still be there.

    Every frame carries the position that follows it as its id, so a browser
    that drops can say where it got to. An id we cannot place -- stale, or
    from a database since replaced -- is treated as no id at all: starting at
    the live end shows less than the client wanted, while replaying the entire
    log at it would be worse than the gap.
    """
    queue: asyncio.Queue = asyncio.Queue()
    start_at = feed.decode_position(resume_from) if resume_from else None

    async def pump() -> None:
        async for entry in feed.follow(from_position=start_at):
            await queue.put(entry)

    # The feed is drained by its own task rather than awaited inline, so waiting
    # for the next event never means being unable to notice anything else. What
    # this coroutine waits on is a queue, which is safe to cancel; cancelling a
    # database poll mid-flight is not.
    pumping = asyncio.create_task(pump())
    idle = 0.0
    try:
        while not await request.is_disconnected():
            try:
                entry = await asyncio.wait_for(queue.get(), timeout=DISCONNECT_CHECK)
            except TimeoutError:
                idle += DISCONNECT_CHECK
                if idle >= KEEPALIVE_SECONDS:
                    # Long enough that an intermediary might give up on us --
                    # a turn can sit silent for a minute while the model thinks.
                    yield ": keepalive\n\n"
                    idle = 0.0
                continue
            idle = 0.0
            payload = feed_event(
                entry.session_id,
                entry.event,
                getattr(entry.event, "aggregate_version", None),
            )
            # One yield, not two: an id and its data are a single SSE frame,
            # and splitting them would let a cancellation land between the
            # cursor and the event it belongs to.
            cursor = feed.encode_position(entry.position)
            yield f"id: {cursor}\ndata: {json.dumps(payload)}\n\n"
    finally:
        pumping.cancel()
        with suppress(asyncio.CancelledError):
            await pumping
