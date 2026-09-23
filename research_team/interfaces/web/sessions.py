"""The Session, Turn, Approval, and Autonomy HTTP surface.

Its own module and its own router, following `knowledge.py`, `topics.py`,
`sources.py`, `catalog.py`, and `dialogues.py`: `create_app` is thousands
of lines of closures and modularizing these routes extracts ~400 lines
from `app.py`.
"""

from typing import Any
from uuid import UUID

from eventsource import CommandRejectedError
from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel

from research_team.interfaces.web.deps import SessionDeps
from research_team.interfaces.web.presenters import (
    event_rows,
    file_history,
    session_view,
)
from research_team.interfaces.web.session_progress_routes import (
    ChecklistState,
    session_progress_router,
)
from research_team.interfaces.web.session_turn_routes import (
    AutonomyChoice,
    Decision,
    NewTurn,
    session_turn_router,
)
from research_team.session.domain import SessionPurpose

__all__ = [
    "AutonomyChoice",
    "ChecklistState",
    "Decision",
    "NewFork",
    "NewTurn",
    "SessionDeps",
    "mount_session_routes",
    "session_progress_router",
    "session_router",
    "session_turn_router",
    "sessions_router",
]


class NewFork(BaseModel):
    at: int
    purpose: SessionPurpose | None = None


def session_router(deps: SessionDeps) -> APIRouter:
    """The session, turn, approval, and autonomy router, ready for
    `app.include_router`.
    """
    router = APIRouter()
    service = deps.service
    turns = deps.turns

    async def _load(session_id: UUID) -> Any:
        if deps.load is not None:
            return await deps.load(session_id)
        try:
            return await service.load(session_id)
        except Exception as error:
            raise HTTPException(status_code=404, detail=f"no session {session_id}") from error

    async def _read_file(session_id: UUID, path: str, at: int | None) -> str:
        """One file's contents at HEAD or as of `at`, or a 404 saying which.

        Shared by the raw, parsed and attempt routes so the three cannot drift
        apart on what "not found at this point in the log" means. Time travel
        is not optional on any of them: a learner reading a lesson at a scrub
        point has to be graded against the lesson that was there, and an author
        diffing two revisions of a question needs both of them to parse.
        """
        if at is None:
            session = await _load(session_id)
        else:
            try:
                session = await service.state_at(session_id, at)
            except (ValueError, CommandRejectedError) as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
        entry = session.state.files.get(path)
        if entry is None:
            moment = "at HEAD" if at is None else f"as of event {at}"
            raise HTTPException(status_code=404, detail=f"{path}: not found {moment}")
        return entry.get("content", "")

    # Mount turn, approval, and autonomy routes
    router.include_router(session_turn_router(deps, _load))

    # Mount learner progress, grading, and checklist routes
    router.include_router(session_progress_router(deps, _read_file, _load))

    @router.post("/api/sessions/{session_id}/release")
    async def release_session(session_id: UUID):
        """Finish with this session, handing its work back to its project.

        The counterpart the web app never had. Releasing is not tidying up
        after yourself: `release_project` is what advances the project's tip
        to this session's latest event, so it is also the *only* way work
        done here reaches the next session in the project. Without it a
        project stays held by a session nobody is driving, and its filesystem
        stays frozen at whatever the previous release left behind.

        Detaching is conditional on this being the attached project, because
        one process serves many browser sessions: releasing session A must
        not pull the graph out from under a turn running in session B.
        """
        session = await _load(session_id)
        project_id = session.state.project_id
        if project_id is None:
            return {"released": False, "project_id": None}
        if turns.is_running(session_id):
            raise HTTPException(
                status_code=409,
                detail="a turn is still running on this session; cancel it first",
            )
        await service.release_project(session_id)
        if service.attached_project_id == project_id:
            await service.detach_project()
        return {"released": True, "project_id": str(project_id)}

    @router.get("/api/sessions/{session_id}")
    async def get_session(session_id: UUID):
        session = await _load(session_id)
        project_id = session.state.project_id
        holds = None
        if project_id is not None:
            state = await service.project_state(project_id)
            holds = state.active_session_id == session_id
        return session_view(
            session,
            await service.history(session_id),
            holds_project=holds,
            knowledge_attached=(
                None if project_id is None else service.attached_project_id == project_id
            ),
        )

    @router.get("/api/sessions/{session_id}/events")
    async def get_events(session_id: UUID):
        await _load(session_id)
        return event_rows(await service.history(session_id))

    @router.get("/api/sessions/{session_id}/at/{at}")
    async def get_session_at(session_id: UUID, at: int):
        """Time travel: the workspace as of event `at`. Folds, never writes."""
        try:
            session = await service.state_at(session_id, at)
        except (ValueError, CommandRejectedError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return session_view(session, await service.history(session_id), at=at)

    @router.get("/api/sessions/{session_id}/files")
    async def get_file(session_id: UUID, path: str, at: int | None = None):
        """A file's contents, at HEAD or as of event `at`.

        Scrubbing has to be able to read a file that no longer exists at HEAD --
        seeing a deleted file again is the point of time travel, not an error.
        """
        return {"path": path, "content": await _read_file(session_id, path, at), "at": at}

    @router.get("/api/sessions/{session_id}/files/history")
    async def get_file_history(session_id: UUID, path: str):
        await _load(session_id)
        return file_history(await service.history(session_id), path)

    @router.post("/api/sessions/{session_id}/forks")
    async def fork_session(session_id: UUID, body: NewFork):
        await _load(session_id)
        try:
            return {"id": str(await service.fork(session_id, body.at, purpose=body.purpose))}
        except (ValueError, CommandRejectedError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    return router


sessions_router = session_router


def mount_session_routes(app: FastAPI, deps: SessionDeps) -> None:
    """Mount the session router on the given FastAPI app."""
    app.include_router(session_router(deps))
