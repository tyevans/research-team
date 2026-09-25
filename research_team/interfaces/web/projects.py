"""The Project HTTP surface.

Creation, listing, retirement, joining, extraction, and embeddings.

Its own module and its own router, following `sessions.py`, `knowledge.py`,
`topics.py`, `sources.py`, `catalog.py`, and `dialogues.py`: `create_app` is thousands
of lines of closures and modularizing these routes extracts project-scoped endpoints
from `app.py`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from eventsource import CommandRejectedError
from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel

from research_team.curriculum.application import CurriculumService
from research_team.interfaces.web.extraction import ExtractionActivity
from research_team.interfaces.web.presenters import (
    project_detail_view,
    project_view,
    reading_head,
)
from research_team.knowledge.application import KnowledgeError
from research_team.session.application.session_service import SessionService
from research_team.session.application.turn_supervisor import TurnSupervisor
from research_team.session.domain import SessionPurpose
from research_team.tenancy.application.project_sessions import ProjectSessions
from research_team.tenancy.application.project_summaries import ProjectSummaries
from research_team.tenancy.domain import CreateProject

logger = logging.getLogger(__name__)


class NewProject(BaseModel):
    name: str


class JoinOptions(BaseModel):
    """Whether a join may end the session currently holding the project."""

    take_over: bool = False


ReembedProject = Callable[[UUID], Awaitable[int]]
"""Re-embed one project's entities from its current graph. Returns how many.

A callable rather than the provider and the stores it needs, for the reason
every other port here is one: this module may not name redstring, and the
work reaches across the graph store, the embedding provider, the event log
and the per-project vector store. Composition owns all four.
"""


async def require_project(
    service: ProjectSessions | SessionService | Any, project_id: UUID
) -> None:
    """404 unless `project_id` names a project that exists and is not deleted.

    Checked before touching the corpus so that "no such project" and "that
    project has no sources" stay different answers. Without it an unknown
    id would list empty and read 404, which reads as a project that exists
    and happens to be bare -- and the caller's next move (store something)
    would be the wrong one.

    **A deleted project is a 404, not a 200 with its name in it**, and this
    function is the only place that can say so once: it guards
    seventy-odd project-scoped routes, and until 2026-08-27 it refused
    only the `new` state, so every one of them answered a deleted
    project's reads in full. The write half was never affected --
    `Project.decide` refuses every command against a deleted project
    ("a deleted project answers nothing but 'deleted'") -- which is
    exactly what made the read half hard to notice: nothing could be
    *changed* through those routes, so nothing broke, and a retired
    project simply kept answering questions about itself.

    The same rule already held one layer down and disagreed with this one.
    `event_store.list_projects` filters deleted ids out and its docstring
    says that filter is "what makes deleted mean gone to every caller that
    lists" -- so a deleted project was absent from `/api/projects` and
    present at `/api/projects/{id}`, which is the shape of a bug rather
    than of a convention.

    What it costs: a client holding a URL to a project deleted in another
    tab now gets 404 rather than a page. That is the point. The
    alternative considered was 410 Gone, which is more precise and which
    no client here distinguishes -- `_require_project`'s callers and the
    console both branch on 404 alone, so 410 would buy accuracy nobody
    reads at the price of a second not-found code to handle.
    """
    try:
        state = await service.project_state(project_id)
    except Exception as error:
        raise HTTPException(status_code=404, detail=f"no project {project_id}") from error
    if state.status in ("new", "deleted"):
        raise HTTPException(status_code=404, detail=f"no project {project_id}")


@dataclass(frozen=True)
class ProjectDeps:
    """What the project routes need from `create_app`'s closure.

    A record rather than a long parameter list, matching `SessionDeps`,
    `TopicDeps`, `KnowledgeDeps`, and `CatalogDeps`.
    """

    projects: ProjectSessions | None = None
    service: SessionService | None = None
    turns: TurnSupervisor | None = None
    curriculum: CurriculumService | None = None
    extraction: ExtractionActivity | None = None
    reembed: ReembedProject | None = None
    project_summaries: ProjectSummaries | None = None
    require_project: Callable[[UUID], Awaitable[None]] | None = None


def project_router(deps: ProjectDeps) -> APIRouter:
    """The project CRUD, join, extraction, and embeddings router, ready for
    `app.include_router`.
    """
    router = APIRouter()
    project_service = (
        deps.projects
        if deps.projects is not None
        else (
            deps.service.project_sessions
            if deps.service is not None and hasattr(deps.service, "project_sessions")
            else deps.service
        )
    )
    turns = deps.turns
    curriculum = deps.curriculum
    extraction = deps.extraction
    reembed = deps.reembed
    project_summaries = deps.project_summaries

    async def _require_project(project_id: UUID) -> None:
        if deps.require_project is not None:
            await deps.require_project(project_id)
        elif project_service is not None:
            await require_project(project_service, project_id)
        else:
            raise HTTPException(status_code=404, detail=f"no project {project_id}")

    @router.get("/api/projects")
    async def list_projects():
        """Every project, with the pipeline position the index draws it from.

        The summaries are read **once for the whole list**, outside the loop,
        which is the only thing worth knowing about this handler. The loop
        below already folds one aggregate per project to find the holder, and
        `domain/project/landing.ts` defers a feature by name on that cost —
        so a summary fetched inside the loop would have doubled the one thing
        this route was already too expensive at, in order to improve the page
        it serves.

        A build with no summaries wired answers zeros rather than 503, which
        is the opposite of what `_reader` and `_topic_reader` do and is
        deliberate: those guard routes that cannot mean anything without their
        collaborator, and this one is the index. A console that cannot count
        a project's sources should still list the project.
        """
        if project_service is None:
            return []
        projects = await project_service.list_projects()
        summaries = await project_summaries.all() if project_summaries else {}
        rows = []
        for project_id, name in projects:
            state = await project_service.project_state(project_id)
            rows.append(
                project_view(
                    project_id,
                    name,
                    active_session_id=state.active_session_id,
                    tip_at_event=state.tip_at_event,
                    summary=summaries.get(project_id),
                )
            )
        return rows

    @router.post("/api/projects")
    async def create_project(body: NewProject):
        """Create a project by name. A name collision is a 409, not a second project.

        Mirrors `/project new` in the REPL: check-then-create over
        `list_projects` rather than letting the aggregate itself reject a
        duplicate name, because `Project` has no notion of "the project
        called X" -- names are only unique by convention of this list, and
        that convention is enforced here, the one place both front ends
        share through `SessionService`.
        """
        existing = await project_service.list_projects()
        collision = next((pid for pid, name in existing if name == body.name), None)
        if collision is not None:
            raise HTTPException(
                status_code=409,
                detail=f"project {body.name!r} already exists ({collision})",
            )
        aggregate = project_service.projects.create_new(uuid4())
        aggregate.execute(CreateProject(project_id=aggregate.aggregate_id, name=body.name))
        await project_service.projects.save(aggregate)
        return project_view(aggregate.aggregate_id, body.name)

    @router.delete("/api/projects/{project_id}")
    async def delete_project(project_id: UUID, release_holder: bool = False):
        """Retire a project. `release_holder` ends the session still driving it.

        The holder is not released implicitly: releasing advances the tip,
        which writes to that session, and a delete that quietly did so would
        make a destructive-sounding verb do an unrelated write. Asking for it
        explicitly keeps both halves visible -- and gives the UI something to
        put in its confirmation prompt rather than a bare 409 to relay.
        """
        # An id nothing was ever written under raises from the repository
        # rather than folding to an empty state, so "no such project" arrives
        # two different ways and both have to become the same 404.
        #
        # Deleted counts as absent here too, so deleting twice is a 404 rather
        # than the domain's 409 "project already deleted". The 409 was the more
        # informative answer and is deliberately given up: a caller who cannot
        # *see* the project through any other route has no way to act on being
        # told it is already gone, and one route treating a deleted project as
        # present -- to refuse it -- is the inconsistency this change exists to
        # remove.
        await _require_project(project_id)
        state = await project_service.project_state(project_id)
        holder = state.active_session_id
        if holder is not None:
            if not release_holder:
                raise HTTPException(
                    status_code=409,
                    detail=f"project is held by session {holder}; end that session first",
                )
            if turns is not None and turns.is_running(holder):
                raise HTTPException(
                    status_code=409,
                    detail="the holding session has a turn running; cancel it first",
                )
            await project_service.release_project(holder)
        try:
            await project_service.delete_project(project_id)
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if project_service.attached_project_id == project_id:
            await project_service.detach_project()
        if curriculum is not None:
            # The projection is cached per project and keyed on graph counts,
            # so a project deleted and a new one created under a recycled id
            # would otherwise be answered from the first one's areas. Ids are
            # not recycled today, which is why this is cheap insurance rather
            # than a fix -- the cache holding a dead project's clusters for the
            # life of the process is reason enough on its own.
            curriculum.forget(project_id)
        return {"deleted": True, "project_id": str(project_id)}

    @router.get("/api/projects/{project_id}")
    async def read_project(project_id: UUID):
        """One project: who it is, and which session holds it.

        Separate from the listing rather than "the row you already fetched",
        because the console reaches a project page by URL as often as by a
        click -- a reload, a bookmark, a link somebody sent -- and on that path
        no listing has been fetched. The alternative was for a project page to
        read `/api/projects` and filter, which is O(projects) of server-side
        fold to answer a question about one.
        """
        await _require_project(project_id)
        state = await project_service.project_state(project_id)
        return project_detail_view(
            project_id,
            state.name,
            active_session_id=state.active_session_id,
            tip_at_event=state.tip_at_event,
            # The one field the listing beside this does not carry. See
            # `project_detail_view`: a page is reached one at a time, and the
            # listing folds an aggregate per row already.
            reading_head_session_id=reading_head(state),
        )

    @router.post("/api/projects/{project_id}/join")
    async def join_project(project_id: UUID, body: JoinOptions | None = None):
        """Start a session that inherits `project_id`'s filesystem, and attach its graph.

        Goes through `SessionService.start_in_project` -- the same use case
        the REPL's `/project use` calls -- so joining is decided in exactly
        one place: the `Project` aggregate. A project already held raises
        `CommandRejectedError` naming the holding session, which this maps to
        409 rather than letting it become an unhandled 500.

        Attachment design: unlike the REPL, this process serves many browser
        sessions at once through one `TurnSupervisor` and (if wired) one
        `KnowledgeAttachment`, so there is no single "current session" whose
        project should stay attached. A per-session attachment map would
        preserve REPL-like isolation between browser tabs, but this app is a
        local single-user tool -- the spec never asks it to serve concurrent
        untrusted users -- so the simpler answer is taken: attach here,
        accept that the most recent join wins process-wide, and say so
        plainly rather than build isolation nothing asked for. A second tab
        joining a different project will change the tools the first tab's
        turns run with; that is a known, accepted limitation of this design,
        not an oversight.

        Taking over: a project held by a session the user has finished with
        is the ordinary case, not an error -- "end this and start fresh" is
        the single most common thing to want from a project, and before
        `take_over` the web app could only report the 409 and offer no way
        out of it. It is spelled as an explicit flag rather than done
        silently because releasing the holder advances the tip, which is a
        write to somebody else's session; a plain join stays a plain join.
        """
        # Ahead of `take_over`, so that a deleted project is 404 rather than
        # reaching `release_project` and advancing a retired project's tip on
        # the way to the domain's refusal. Joining one used to answer the
        # domain's 409 "project has been deleted", which both refused the join
        # and confirmed the project existed; 404 is the same refusal without
        # the confirmation, and matches every other project-scoped route.
        await _require_project(project_id)
        if body is not None and body.take_over:
            state = await project_service.project_state(project_id)
            if state.active_session_id is not None:
                if turns is not None and turns.is_running(state.active_session_id):
                    raise HTTPException(
                        status_code=409,
                        detail="the holding session has a turn running; cancel it first",
                    )
                await project_service.release_project(state.active_session_id)
        try:
            session_id = await project_service.start_in_project(
                project_id, SessionPurpose.CHAT
            )
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        try:
            await project_service.attach_project(project_id)
        except Exception as error:  # noqa: BLE001 -- report, do not fail the join
            return {
                "id": str(session_id),
                "project_id": str(project_id),
                "warning": str(error),
            }
        return {"id": str(session_id), "project_id": str(project_id), "warning": None}

    @router.get("/api/projects/{project_id}/extraction")
    async def get_extraction(project_id: UUID):
        """What the running extraction has done so far, and the last one's account.

        A tab that arrived mid-ingest, or one whose connection dropped, has no
        other way back: these frames carry no feed position, so
        `Last-Event-ID` cannot replay them. 200 with two empty lists when
        nothing has run -- an absent extraction is a state, not a missing
        resource, and unlike `/workers` there is no claim being made about
        what is running elsewhere.
        """
        await _require_project(project_id)
        if extraction is None:
            return {"current": [], "last": []}
        return {
            "current": extraction.current(project_id),
            "last": extraction.last(project_id),
        }

    @router.post("/api/projects/{project_id}/embeddings", status_code=202)
    async def refresh_embeddings(project_id: UUID):
        """Re-embed every entity in this project, from the graph as it stands.

        **Why this exists rather than embeddings simply being current.** A
        vector is written when its entity is extracted, and it encodes the card
        the entity had *then*. Nothing re-embeds at project open, deliberately:
        `rebuild_graph` must not depend on a live endpoint, or a session
        refolded years from now would not open. So an entity that gained six
        relationships after it was first seen carries a vector that knows about
        none of them, and this is the button that fixes it.

        It is also the repair for the whole class of projects ingested before
        embeddings were durable at all, which is every project written before
        2026-08-22: their logs carry no `EntitiesEmbedded`, so they fold to an
        empty vector store and cluster on the graph alone until this runs.

        **202 and synchronous, which is a contradiction worth admitting.** The
        work is one embedding call per 64 entities and returns before the
        response does; the status is 202 because the *effect* a caller cares
        about -- a curriculum clustered with the new vectors -- lands on the
        next projection rather than in this response body. What it costs is a
        request held open proportional to the graph: about eight calls for a
        five-hundred-entity project, and a route that is no longer reasonable
        somewhere north of a few thousand. `BACKLOG.md` B131 has the
        background-run version; this is deliberately the small one.

        The cached curriculum is forgotten here rather than left to expire,
        because the cache is keyed on entity and relationship counts and
        re-embedding moves neither -- so without this, the run would succeed
        and change nothing anybody could see until the next extraction.
        """
        await _require_project(project_id)
        if reembed is None:
            raise HTTPException(status_code=503, detail="embeddings are not configured")
        try:
            embedded = await reembed(project_id)
        except KnowledgeError as error:
            # 502 rather than 500: the fault is upstream and the operator can
            # act on it. Distinct from the 503 above, which says this build was
            # never wired for embeddings, and from a 202 carrying `embedded: 0`,
            # which says the feature is off on purpose. Three different things
            # a browser would otherwise have to guess at from one status.
            raise HTTPException(status_code=502, detail=str(error)) from error
        if curriculum is not None:
            curriculum.forget(project_id)
        return {"embedded": embedded}

    return router


projects_router = project_router


def mount_project_routes(app: FastAPI, deps: ProjectDeps) -> None:
    """Mount the project router on the given FastAPI app."""
    app.include_router(project_router(deps))
