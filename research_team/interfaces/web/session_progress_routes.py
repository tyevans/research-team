"""Learner progress, interactive grading, and checklist HTTP routes."""

import hashlib
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from research_team.curriculum.application.grading import GradingError, grade
from research_team.interfaces.web.dialogues import Attempt
from research_team.interfaces.web.presenters import item_view, progress_view
from research_team.interfaces.web.session_deps import SessionDeps
from research_team.platform.components import View, parse_document, project

__all__ = [
    "ChecklistState",
    "session_progress_router",
]


class ChecklistState(BaseModel):
    """Which boxes are ticked on one checklist, addressed like an `Attempt`.

    Absolute rather than a toggle: the client sends the full set every time, so
    a dropped request costs one stale render rather than a box that is ticked
    in the log and clear on the screen forever.
    """

    path: str
    component_id: str
    checked: list[int] = Field(default_factory=list)
    at: int | None = None


def session_progress_router(
    deps: SessionDeps,
    read_file: Callable[[UUID, str, int | None], Awaitable[str]],
    load: Callable[[UUID], Awaitable[Any]],
) -> APIRouter:
    """The learner progress, grading, and checklist routes, ready for `app.include_router`."""
    router = APIRouter()
    service = deps.service

    @router.get("/api/sessions/{session_id}/files/parsed")
    async def get_file_parsed(
        session_id: UUID,
        path: str,
        at: int | None = None,
        view: View = "author",
    ):
        """A markdown file as blocks, with interactive components resolved.

        `view` is a `Literal`, so FastAPI rejects `learnr` with a 422 rather
        than falling back to a default. A typo that quietly returned the author
        view would hand back the answer key on exactly the request that meant
        to ask for it to be withheld -- the one failure mode of this route that
        is worth a hard edge.
        """
        content = await read_file(session_id, path, at)
        return project(parse_document(content, path=path), view=view) | {"at": at}

    @router.post("/api/sessions/{session_id}/attempts")
    async def post_attempt(session_id: UUID, body: Attempt):
        """Mark one attempt. The server holds the key; the browser was not given it.

        A wrong answer is a 200 with `correct: false` -- it is a result, not an
        error. The 400s here are all malformed *requests*: a response shape the
        item cannot interpret, or an item that has no answer to mark.
        """
        content = await read_file(session_id, body.path, body.at)
        component = parse_document(content, path=body.path).component(body.component_id)
        if component is None:
            raise HTTPException(
                status_code=404,
                detail=f"{body.path} has no component {body.component_id!r}",
            )
        try:
            verdict = grade(component, body.response)
        except GradingError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        # Recorded after grading and before answering, so a verdict the learner
        # was shown is never one the log has no record of. The digest is of the
        # body as it stood, which is what lets a later reader see that an item
        # was rewritten under someone mid-course.
        progress = await service.record_attempt(
            session_id,
            path=body.path,
            component_id=body.component_id,
            component_type=component.type,
            digest=hashlib.sha256(component.raw.encode("utf-8")).hexdigest(),
            response=body.response,
            correct=verdict.correct,
            score=verdict.score,
            at=body.at,
        )
        item = item_view(progress, body.path, body.component_id)
        return verdict.as_json() | {"progress": item}

    @router.get("/api/sessions/{session_id}/progress")
    async def get_progress(session_id: UUID, path: str | None = None):
        """What this learner has done, for the whole session or one file.

        `path` narrows it, because the browser asks on opening a document and
        has no use for the other twelve. Answers an empty mapping for a session
        nobody has answered anything in -- that is the ordinary case for every
        course before its first learner, not a 404.
        """
        await load(session_id)
        state = await service.learner_progress(session_id)
        return progress_view(state, path=path)

    @router.post("/api/sessions/{session_id}/progress/checklist")
    async def post_checklist(session_id: UUID, body: ChecklistState):
        """Remember which boxes are ticked on a `persist: true` checklist.

        A separate route from `/attempts` rather than a shape of it, because a
        checklist has no answer key: there is no verdict, nothing to be right
        about, and `grade` refuses it by design. Folding the two together would
        mean an endpoint that sometimes marks and sometimes just remembers.

        `persist` is honoured rather than assumed: a checklist that did not ask
        to be remembered is a 400, so a client cannot quietly accumulate state
        the author never opted into.
        """
        content = await read_file(session_id, body.path, body.at)
        component = parse_document(content, path=body.path).component(body.component_id)
        if component is None:
            raise HTTPException(
                status_code=404,
                detail=f"{body.path} has no component {body.component_id!r}",
            )
        if component.type != "checklist":
            raise HTTPException(
                status_code=400,
                detail=f"{body.component_id!r} is a {component.type}, not a checklist",
            )
        if component.data.get("persist") is not True:
            raise HTTPException(
                status_code=400,
                detail=f"checklist {body.component_id!r} does not set `persist: true`",
            )
        items = component.data.get("items", [])
        for index in body.checked:
            if not 0 <= index < len(items):
                raise HTTPException(
                    status_code=400,
                    detail=f"there is no item {index}; this checklist has {len(items)}",
                )
        progress = await service.record_checklist(
            session_id,
            path=body.path,
            component_id=body.component_id,
            checked=list(body.checked),
        )
        return item_view(progress, body.path, body.component_id)

    return router
