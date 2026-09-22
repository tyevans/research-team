"""The Topic Dispatch and Worker Roster HTTP surface.

Extracted from `topics.py` to separate dispatch queue orchestration and worker
status routes from topic CRUD, seeding, and question management.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from research_team.interfaces.web.dispatch import DispatchQueue
from research_team.interfaces.web.presenters import dispatch_view, roster_view
from research_team.research.application.topic_dispatch import (
    DISPATCH_ACTIONS,
    TopicDispatcher,
)
from research_team.research.application.topic_read import TopicReadPort
from research_team.research.application.topics import MAX_OPEN_TOPICS
from research_team.session.application.workers import WorkerRoster


class NewDispatch(BaseModel):
    """What an agent dispatched at one topic is being asked to do.

    Plain `str` rather than a `Literal`, so a bad value comes back from the
    route naming the actions that exist -- the same reasoning `AutonomyChoice`
    gives for its two fields. FastAPI's 422 for a `Literal` mismatch is
    machine-readable and names none of them, and `lesson` is exactly the value
    a caller will reasonably try: it is designed, in
    `docs/design/topic-dispatch.md`, and not built.

    Defaults to `understanding` rather than being required, which is now a
    weaker justification than it was: with three actions the default is a
    choice among them rather than the only one on offer. Kept because changing
    it would break every existing caller that omits the field, and because
    `understanding` is the one action that neither fetches nor proposes an
    edit -- the safest thing to do by omission.
    """

    action: str = "understanding"


MAX_BULK_DISPATCH = MAX_OPEN_TOPICS
"""Most topics one bulk dispatch may name.

Tied to `MAX_OPEN_TOPICS` rather than chosen independently, and that is the
whole argument: fifty is the most live topics a project can hold, so "every
topic the filter is showing me" always fits. A smaller cap would refuse the
one request this route exists to serve -- the `All 50` case -- and a larger
one would be a number that could never be reached.

It is a cap on the *request*, not on the queue. Fifty one-turn dispatches is a
long afternoon of model time, and the thing that makes that acceptable is not
this number: it is that the queue renders all fifty, drains one at a time, and
`Stop` drops the lot. That surface is the budget control; this is only a
refusal of a request nobody meant to make.
"""


class BulkDispatch(BaseModel):
    """One action, across a list of topics the client chose.

    **`topic_ids` is required and there is no "all".** The server does not get
    to decide the scope, and the reason is not caution -- it is that "all" has
    no server-side definition that stays true. The queue the person is looking
    at is filtered in the browser (`All 12`, `Needs you 3`), so a route that
    took "all" would have to re-derive that filter from a client that owns it,
    and the two definitions would drift the first time a tab was added. Sending
    the ids makes the count on screen and the count enqueued the same number by
    construction.

    `action` is a plain `str` for `NewDispatch`'s reason and has no default:
    the per-topic route backs a single button whose meaning is obvious, and
    this one backs several.
    """

    action: str
    topic_ids: list[UUID] = Field(min_length=1, max_length=MAX_BULK_DISPATCH)


@dataclass(frozen=True)
class DispatchDeps:
    """Dependencies needed for topic dispatch and worker roster endpoints."""

    require_project: Callable[[UUID], Awaitable[None]] | None = None
    dispatcher: TopicDispatcher | None = None
    dispatch: DispatchQueue | None = None
    workers: WorkerRoster | None = None
    topic_reader: Callable[[UUID], TopicReadPort] | None = None
    topics: Callable[[UUID], TopicReadPort] | None = None


def dispatch_router(deps: Any) -> APIRouter:
    """The topic dispatch and worker roster router."""
    router = APIRouter()

    async def _check_project(project_id: UUID) -> None:
        if getattr(deps, "require_project", None) is not None:
            await deps.require_project(project_id)

    def _topic_reader(project_id: UUID) -> TopicReadPort:
        if getattr(deps, "topic_reader", None) is not None:
            return deps.topic_reader(project_id)
        if getattr(deps, "topics", None) is None:
            raise HTTPException(status_code=503, detail="no topic read model is configured")
        return deps.topics(project_id)

    @router.post("/api/projects/{project_id}/topics/{topic_id}/dispatch")
    async def dispatch_topic(
        project_id: UUID, topic_id: UUID, body: NewDispatch | None = None
    ):
        """Send an agent at one topic. 202, because it has not run when this answers."""
        if deps.dispatcher is None or deps.dispatch is None:
            raise HTTPException(status_code=503, detail="topic dispatch is not configured")
        await _check_project(project_id)

        action = (body or NewDispatch()).action
        if action not in DISPATCH_ACTIONS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"no dispatch action {action!r}; this build offers "
                    f"{', '.join(sorted(DISPATCH_ACTIONS))}"
                ),
            )

        detail = await _topic_reader(project_id).read_topic(topic_id)
        if detail is None:
            raise HTTPException(
                status_code=404, detail=f"no such topic in project {project_id}"
            )

        frame = deps.dispatch.start(
            project_id,
            topic_id,
            action,
            lambda dispatch_id: deps.dispatcher.dispatch(
                project_id, topic_id, action, dispatch_id=dispatch_id
            ),
            question=detail.view.summary.question,
        )
        return JSONResponse(status_code=202, content=dispatch_view(frame))

    @router.get("/api/projects/{project_id}/dispatch")
    async def get_dispatch(project_id: UUID):
        """What is running, what is waiting, and how each topic's last one went."""
        await _check_project(project_id)
        if deps.dispatch is None:
            return {"running": None, "queued": [], "finished": []}
        return {
            "running": dispatch_view(deps.dispatch.current(project_id)),
            "queued": [dispatch_view(frame) for frame in deps.dispatch.queued(project_id)],
            "finished": [dispatch_view(frame) for frame in deps.dispatch.finished(project_id)],
        }

    @router.post("/api/projects/{project_id}/dispatch/cancel")
    async def cancel_dispatch(project_id: UUID):
        """Stop what is running and drop everything waiting, for this project."""
        await _check_project(project_id)
        if deps.dispatch is None:
            raise HTTPException(status_code=503, detail="topic dispatch is not configured")
        return {"cancelled": deps.dispatch.cancel(project_id)}

    @router.post("/api/projects/{project_id}/dispatch/bulk")
    async def dispatch_topics(project_id: UUID, body: BulkDispatch):
        """Enqueue one action across the topics the client named. 202, like the one."""
        if deps.dispatcher is None or deps.dispatch is None:
            raise HTTPException(status_code=503, detail="topic dispatch is not configured")
        await _check_project(project_id)

        if body.action not in DISPATCH_ACTIONS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"no dispatch action {body.action!r}; this build offers "
                    f"{', '.join(sorted(DISPATCH_ACTIONS))}"
                ),
            )

        reader = _topic_reader(project_id)
        queued: list[dict[str, Any]] = []
        unknown: list[str] = []
        for topic_id in body.topic_ids:
            detail = await reader.read_topic(topic_id)
            if detail is None:
                unknown.append(str(topic_id))
                continue
            queued.append(
                deps.dispatch.start(
                    project_id,
                    topic_id,
                    body.action,
                    lambda dispatch_id, topic_id=topic_id: deps.dispatcher.dispatch(
                        project_id, topic_id, body.action, dispatch_id=dispatch_id
                    ),
                    question=detail.view.summary.question,
                )
            )
        return JSONResponse(
            status_code=202,
            content={
                "queued": [dispatch_view(frame) for frame in queued],
                "unknown": unknown,
            },
        )

    @router.get("/api/workers")
    async def get_all_workers():
        """Everything in flight anywhere, in one request."""
        if deps.workers is None:
            raise HTTPException(status_code=404, detail="the worker roster is not enabled")
        return [roster_view(roster) for roster in await deps.workers.everywhere()]

    return router


__all__ = [
    "MAX_BULK_DISPATCH",
    "BulkDispatch",
    "DispatchDeps",
    "NewDispatch",
    "dispatch_router",
]
