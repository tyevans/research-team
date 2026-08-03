"""HTTP + SSE adapter over the same use cases the REPL drives.

Stateless by construction: every route names the session it acts on, so any
number of browsers can look at any number of sessions at once. That is the
whole reason the application layer stopped holding a "current session".
"""

import asyncio
import json
from contextlib import suppress
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

from eventsource import OptimisticLockError
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from research_team.application import LiveFeed, SessionService, build_fork_tree
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


def create_app(service: SessionService, feed: LiveFeed) -> FastAPI:
    """Build the app around an already-wired service. Composition stays outside."""
    app = FastAPI(title="research-team", docs_url="/api/docs")

    async def _load(session_id: UUID):
        try:
            return await service.load(session_id)
        except Exception as error:  # noqa: BLE001 -- any load failure is a 404 here
            raise HTTPException(status_code=404, detail=f"no session {session_id}") from error

    @app.get("/api/sessions")
    async def list_sessions():
        return [summary_view(summary) for summary in await service.list_sessions()]

    @app.post("/api/sessions")
    async def create_session(body: NewSession | None = None):
        prompt = body.system_prompt if body else None
        return {"id": str(await service.create_session(prompt))}

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
    async def get_file(session_id: UUID, path: str):
        session = await _load(session_id)
        entry = session.state.files.get(path)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"{path}: not found")
        return {"path": path, "content": entry.get("content", "")}

    @app.get("/api/sessions/{session_id}/files/history")
    async def get_file_history(session_id: UUID, path: str):
        await _load(session_id)
        return file_history(await service.history(session_id), path)

    @app.post("/api/sessions/{session_id}/turns")
    async def run_turn(session_id: UUID, body: NewTurn):
        await _load(session_id)
        try:
            reply = await service.run_turn(session_id, body.input)
        except OptimisticLockError as error:
            # Two clients took a turn on one session at once. The log is
            # append-only and the loser's events were discarded whole, so
            # nothing happened -- this is a retry, not a failure.
            raise HTTPException(
                status_code=409,
                detail="another turn was recorded on this session first; reload and retry",
            ) from error
        return {"reply": reply}

    @app.post("/api/sessions/{session_id}/forks")
    async def fork_session(session_id: UUID, body: NewFork):
        await _load(session_id)
        try:
            return {"id": str(await service.fork(session_id, body.at))}
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/stream")
    async def stream(request: Request) -> StreamingResponse:
        """Every event, as it is appended, to every listening browser."""
        return StreamingResponse(
            _sse(request, feed),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/")
        async def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    return app


async def _sse(request: Request, feed: LiveFeed) -> AsyncIterator[str]:
    """Serialise the live feed as server-sent events.

    Keepalive comments keep intermediaries from closing an idle connection --
    a session can sit silent for a minute while the model thinks, which is
    exactly when the browser most needs the connection to still be there.
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def pump() -> None:
        async for entry in feed.follow():
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
            yield f"data: {json.dumps(payload)}\n\n"
    finally:
        pumping.cancel()
        with suppress(asyncio.CancelledError):
            await pumping
