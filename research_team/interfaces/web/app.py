"""HTTP + SSE adapter over the same use cases the REPL drives.

Stateless by construction: every route names the session it acts on, so any
number of browsers can look at any number of sessions at once. That is the
whole reason the application layer stopped holding a "current session".
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from eventsource import CommandRejectedError, OptimisticLockError
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from research_team.application import (
    ApprovalDecision,
    LiveFeed,
    SessionService,
    TurnAlreadyRunning,
    TurnCancelled,
    TurnSupervisor,
    build_fork_tree,
)
from research_team.application.corpus_spans import quote
from research_team.domain import CreateProject, ProjectState, SelectWorkflow
from research_team.domain.project import current_stage_of
from research_team.infrastructure.persistence import CorpusRunner
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.interfaces.web.activity import TurnActivity
from research_team.interfaces.web.approvals import UnknownApproval, WebApprovals
from research_team.interfaces.web.presenters import (
    event_rows,
    feed_event,
    file_history,
    preset_view,
    project_view,
    session_view,
    source_text_view,
    source_view,
    stage_view,
    summary_view,
    tree_view,
)
from research_team.workflows import PRESETS

logger = logging.getLogger(__name__)

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


class NewProject(BaseModel):
    name: str


class JoinOptions(BaseModel):
    """Whether a join may end the session currently holding the project."""

    take_over: bool = False


class WorkflowChoice(BaseModel):
    """Which preset a project runs. Chosen once; `decide` refuses a second."""

    preset_id: str


class Decision(BaseModel):
    """A human's answer to a parked approval. `type` is langchain's vocabulary."""

    type: str
    edited_args: dict | None = None
    message: str | None = None


def create_app(
    service: SessionService,
    feed: LiveFeed,
    turns: TurnSupervisor,
    lifespan=None,
    approvals: WebApprovals | None = None,
    activity: TurnActivity | None = None,
    corpus: CorpusRunner | None = None,
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

    def _workflow_of(state: ProjectState) -> dict[str, Any]:
        """Which preset a project runs and where it stands in it, both nullable.

        Two absences, kept distinct. No preset selected is the ordinary case
        and answers `None` for both. A preset id this build does not ship --
        a project started against a preset since renamed or removed -- still
        reports the workflow, because the id is the only honest thing to say,
        but reports no stage: resolving a position needs the stage list, and
        inventing one would be worse than admitting the gap. Neither is a
        server error, so neither raises; a listing that 500s because one row
        names an unknown preset is a listing nobody can use to fix it.
        """
        if state.preset_id is None:
            return {"workflow": None, "stage": None}
        preset = PRESETS.get(state.preset_id)
        if preset is None:
            return {
                "workflow": {
                    "id": state.preset_id,
                    "name": state.preset_id,
                    "version": state.preset_version,
                },
                "stage": None,
            }
        stage = current_stage_of(state, preset)
        return {
            "workflow": {"id": preset.id, "name": preset.name, "version": preset.version},
            "stage": stage_view(preset, stage) if stage is not None else None,
        }

    @app.get("/api/projects")
    async def list_projects():
        projects = await service.list_projects()
        rows = []
        for project_id, name in projects:
            state = await service.project_state(project_id)
            rows.append(
                project_view(
                    project_id,
                    name,
                    active_session_id=state.active_session_id,
                    tip_at_event=state.tip_at_event,
                    **_workflow_of(state),
                )
            )
        return rows

    @app.get("/api/workflows")
    async def list_workflows():
        """The presets on offer, in recommendation order.

        Order is the recommendation, and it is load-bearing: whichever pure
        methodology a user picks they inherit that tradition's structural
        defect, and knowing which defect to tolerate takes exactly the
        expertise they came here without. The hybrid is first because it is
        the one that does not require that judgement.

        Static: presets are code in `research_team/workflows/`, validated at
        import, so there is nothing to load and nothing that can fail here.
        """
        return [preset_view(preset) for preset in PRESETS.values()]

    @app.post("/api/projects")
    async def create_project(body: NewProject):
        """Create a project by name. A name collision is a 409, not a second project.

        Mirrors `/project new` in the REPL: check-then-create over
        `list_projects` rather than letting the aggregate itself reject a
        duplicate name, because `Project` has no notion of "the project
        called X" -- names are only unique by convention of this list, and
        that convention is enforced here, the one place both front ends
        share through `SessionService`.
        """
        existing = await service.list_projects()
        collision = next((pid for pid, name in existing if name == body.name), None)
        if collision is not None:
            raise HTTPException(
                status_code=409,
                detail=f"project {body.name!r} already exists ({collision})",
            )
        aggregate = service.projects.create_new(uuid4())
        aggregate.execute(CreateProject(name=body.name))
        await service.projects.save(aggregate)
        return project_view(aggregate.aggregate_id, body.name)

    @app.delete("/api/projects/{project_id}")
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
        try:
            state = await service.project_state(project_id)
        except Exception as error:
            raise HTTPException(status_code=404, detail=f"no project {project_id}") from error
        if state.status == "new":
            raise HTTPException(status_code=404, detail=f"no project {project_id}")
        holder = state.active_session_id
        if holder is not None:
            if not release_holder:
                raise HTTPException(
                    status_code=409,
                    detail=f"project is held by session {holder}; end that session first",
                )
            if turns.is_running(holder):
                raise HTTPException(
                    status_code=409,
                    detail="the holding session has a turn running; cancel it first",
                )
            await service.release_project(holder)
        try:
            await service.delete_project(project_id)
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if service.attached_project_id == project_id:
            await service.detach_project()
        return {"deleted": True, "project_id": str(project_id)}

    async def _require_project(project_id: UUID) -> None:
        """404 unless `project_id` names a project that exists.

        Checked before touching the corpus so that "no such project" and "that
        project has no sources" stay different answers. Without it an unknown
        id would list empty and read 404, which reads as a project that exists
        and happens to be bare -- and the caller's next move (store something)
        would be the wrong one.
        """
        try:
            state = await service.project_state(project_id)
        except Exception as error:
            raise HTTPException(status_code=404, detail=f"no project {project_id}") from error
        if state.status == "new":
            raise HTTPException(status_code=404, detail=f"no project {project_id}")

    @app.get("/api/projects/{project_id}/workflow")
    async def get_workflow(project_id: UUID):
        """Which workflow this project runs, and the stage it is at."""
        await _require_project(project_id)
        return _workflow_of(await service.project_state(project_id))

    @app.post("/api/projects/{project_id}/workflow")
    async def select_workflow(project_id: UUID, body: WorkflowChoice):
        """Bind a project to a preset. Once only -- a second is the domain's 409.

        Goes through the aggregate the way `create_project` does, rather than
        adding a use case to `SessionService`: there is no cross-front-end
        convention to enforce here (unlike project names, which are only
        unique because that route says so), so the one rule that exists is
        already in `decide` and reaching it directly keeps it that way.

        A re-selection is relayed with the domain's own message because that
        message names the preset already running. "Already selected" would
        leave the user knowing they cannot choose without knowing what they
        chose -- and re-selection is refused precisely because a run's audit
        trail is gated by one preset's stage list, so what that list is is the
        first thing they need.
        """
        await _require_project(project_id)
        preset = PRESETS.get(body.preset_id)
        if preset is None:
            raise HTTPException(
                status_code=404,
                detail=f"no workflow {body.preset_id!r}; try one of {', '.join(PRESETS)}",
            )
        project = await service.projects.load(project_id)
        try:
            project.execute(SelectWorkflow(preset=preset))
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        await service.projects.save(project)
        return _workflow_of(project.state)

    def _reader(project_id: UUID) -> ProjectCorpusReader:
        """This project's corpus, through the same port the agent's tools use.

        Built per request rather than held, because it is two attributes over
        a shared runner and binding the project is the entire point -- a
        long-lived one would have to take the project as an argument again,
        which is what the port refuses so that no caller can read another
        project's sources.

        503 rather than 404 when nothing was wired: an application assembled
        without a corpus read model is a valid thing to serve (as with
        `approvals` and `activity`), and the caller needs to know the server
        cannot answer rather than that the project has nothing.
        """
        if corpus is None:
            raise HTTPException(status_code=503, detail="no corpus read model is configured")
        return ProjectCorpusReader(corpus, project_id)

    @app.get("/api/projects/{project_id}/sources")
    async def list_sources(project_id: UUID):
        """Every source this project has stored. Metadata only, never text."""
        reader = _reader(project_id)
        await _require_project(project_id)
        return [source_view(summary) for summary in await reader.list_documents()]

    @app.get("/api/projects/{project_id}/sources/{source_id}")
    async def read_source(
        project_id: UUID, source_id: str, start: int | None = None, end: int | None = None
    ):
        """One source's text, or a character range of it, with its real offsets.

        The range is clamped rather than validated: `quote` returns what the
        document actually has for the range asked, and the response reports
        those offsets. A caller guessing past the end of a document is the
        ordinary case -- it is how you page through one -- so answering with
        the last characters and honest offsets is more useful than a 422 that
        makes the caller compute the bound it was asking the server for.
        """
        reader = _reader(project_id)
        await _require_project(project_id)
        document = await reader.read_document(source_id)
        if document is None:
            raise HTTPException(
                status_code=404, detail=f"no source {source_id!r} in project {project_id}"
            )
        text = document.text
        span = quote(text, start or 0, len(text) if end is None else end)
        return source_text_view(document, span)

    @app.post("/api/sessions/{session_id}/release")
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

    @app.post("/api/projects/{project_id}/join")
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
        if body is not None and body.take_over:
            state = await service.project_state(project_id)
            if state.active_session_id is not None:
                if turns.is_running(state.active_session_id):
                    raise HTTPException(
                        status_code=409,
                        detail="the holding session has a turn running; cancel it first",
                    )
                await service.release_project(state.active_session_id)
        try:
            session_id = await service.start_in_project(project_id)
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        try:
            await service.attach_project(project_id)
        except Exception as error:  # noqa: BLE001 -- report, do not fail the join
            return {
                "id": str(session_id),
                "project_id": str(project_id),
                "warning": str(error),
            }
        return {"id": str(session_id), "project_id": str(project_id), "warning": None}

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

    @app.get("/api/sessions/{session_id}/events")
    async def get_events(session_id: UUID):
        await _load(session_id)
        return event_rows(await service.history(session_id))

    @app.get("/api/sessions/{session_id}/at/{at}")
    async def get_session_at(session_id: UUID, at: int):
        """Time travel: the workspace as of event `at`. Folds, never writes."""
        try:
            session = await service.state_at(session_id, at)
        except (ValueError, CommandRejectedError) as error:
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
            except (ValueError, CommandRejectedError) as error:
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
        if turns.is_running(session_id):
            # Checked here as well as in the supervisor so that a refused
            # second turn cannot reach `begin` and wipe the buffer of the turn
            # that is legitimately running.
            raise HTTPException(
                status_code=409,
                detail="a turn is already running on this session",
            )
        # Re-attach per turn rather than only at join. One process serves
        # every browser session, so by the time this session takes a turn the
        # attached graph may belong to a project joined in another tab -- or,
        # after a restart, to nothing at all. A session whose recorded prompt
        # promises knowledge tools has to get them on every turn, not just the
        # request that happened to join. A no-op for a session in no project,
        # and for a graph that will not open: knowledge is degraded then, and
        # the turn is still worth running.
        try:
            await service.ensure_project_attached(session_id)
        except Exception:  # noqa: BLE001 -- a turn without the graph beats no turn
            logger.warning(
                "could not attach knowledge graph for %s", session_id, exc_info=True
            )
        reporter = None
        if activity is not None:
            activity.begin(session_id)
            reporter = activity.reporter(session_id)
        try:
            outcome = await turns.run(session_id, body.input, reporter)
        except TurnAlreadyRunning as error:
            # No activity.settle() here on purpose: this request's own
            # activity.begin() above raced the supervisor's check and lost --
            # the buffer it opened belongs to the turn that is actually
            # running, and that turn's own call to run() owns settling it.
            raise HTTPException(
                status_code=409,
                detail="a turn is already running on this session",
            ) from error
        except TurnCancelled as error:
            if activity is not None:
                activity.settle(session_id, committed=False)
            # Not a failure: someone asked for this. 499 is nginx's
            # "client closed request" -- the closest thing to a standard code
            # for work abandoned on purpose.
            raise HTTPException(status_code=499, detail=str(error)) from error
        except OptimisticLockError as error:
            if activity is not None:
                activity.settle(session_id, committed=False)
            # Another writer -- the REPL, or a second process -- got there
            # first. The log is append-only and the loser's events were
            # discarded whole, so nothing happened; this is a retry.
            raise HTTPException(
                status_code=409,
                detail="another turn was recorded on this session first; reload and retry",
            ) from error
        except BaseException:
            if activity is not None:
                activity.settle(session_id, committed=False)
            raise
        else:
            if activity is not None:
                activity.settle(session_id, committed=True)
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

    @app.get("/api/sessions/{session_id}/turns/current/activity")
    async def current_activity(session_id: UUID):
        """What the running turn has produced so far, and what the last failed
        one threw away.

        The live feed announces each note as it arrives, but a tab that opened
        mid-turn never saw those frames -- and unlike log events they carry no
        position, so `Last-Event-ID` cannot replay them. This is how it
        catches up, exactly as `/approvals` is for a parked approval.
        """
        await _load(session_id)
        if activity is None:
            return {"running": [], "discarded": []}
        return {
            "running": activity.current(session_id),
            "discarded": activity.discarded(session_id),
        }

    @app.get("/api/sessions/{session_id}/approvals")
    async def pending_approvals(session_id: UUID):
        """Gated calls this session is waiting on.

        The live feed announces each one as it is parked, but a tab that opened
        mid-turn never saw that frame -- this is how it catches up.
        """
        await _load(session_id)
        return [] if approvals is None else approvals.pending(session_id)

    @app.post("/api/sessions/{session_id}/approvals/{approval_id}")
    async def decide_approval(session_id: UUID, approval_id: str, body: Decision):
        """Answer one parked approval, unblocking the turn waiting on it."""
        if approvals is None:
            raise HTTPException(status_code=404, detail="approvals are not wired up")
        await _load(session_id)
        try:
            approvals.resolve(
                session_id,
                approval_id,
                ApprovalDecision(
                    type=body.type,
                    edited_args=body.edited_args,
                    message=body.message,
                ),
            )
        except UnknownApproval as error:
            # Already answered, or the turn behind it was cancelled. Both are
            # races a second tab can lose honestly.
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"decided": True}

    @app.post("/api/sessions/{session_id}/forks")
    async def fork_session(session_id: UUID, body: NewFork):
        await _load(session_id)
        try:
            return {"id": str(await service.fork(session_id, body.at))}
        except (ValueError, CommandRejectedError) as error:
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
            _sse(request, feed, resume_from, approvals, activity),
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
    request: Request,
    feed: LiveFeed,
    resume_from: str | None = None,
    approvals: WebApprovals | None = None,
    activity: TurnActivity | None = None,
) -> AsyncIterator[str]:
    """Serialise the live feed as server-sent events.

    Keepalive comments keep intermediaries from closing an idle connection --
    a session can sit silent for a minute while the model thinks, which is
    exactly when the browser most needs the connection to still be there.

    Every logged frame carries the position that follows it as its id, so a
    browser that drops can say where it got to. An id we cannot place --
    stale, or from a database since replaced -- is treated as no id at all:
    starting at the live end shows less than the client wanted, while
    replaying the entire log at it would be worse than the gap.

    Approval requests, and turn activity notes, ride this same connection
    rather than one of their own, for the same reason each other: neither is
    a log entry -- an approval that is never answered, and provisional turn
    content, both leave no event behind -- so neither carries an id, and a
    reconnecting browser refetches what it missed (`/approvals`, or the
    activity catch-up route) instead of replaying them. But a second channel
    per concern would multiply the ways a tab can be half-connected, and a
    turn that halts for a person, or is still streaming its reply, is exactly
    the moment when being half-connected is worst.
    """
    queue: asyncio.Queue = asyncio.Queue()
    start_at = feed.decode_position(resume_from) if resume_from else None

    async def pump() -> None:
        async for entry in feed.follow(from_position=start_at):
            await queue.put(("event", entry))

    # The feed is drained by its own task rather than awaited inline, so waiting
    # for the next event never means being unable to notice anything else. What
    # this coroutine waits on is a queue, which is safe to cancel; cancelling a
    # database poll mid-flight is not.
    pumps = [asyncio.create_task(pump())]
    listening = None
    if approvals is not None:
        listening = approvals.listen()

        async def pump_approvals() -> None:
            while True:
                await queue.put(("approval", await listening.get()))

        pumps.append(asyncio.create_task(pump_approvals()))

    watching = None
    if activity is not None:
        watching = activity.listen()

        async def pump_activity() -> None:
            while True:
                await queue.put(("activity", await watching.get()))

        pumps.append(asyncio.create_task(pump_activity()))

    idle = 0.0
    try:
        while not await request.is_disconnected():
            try:
                kind, item = await asyncio.wait_for(queue.get(), timeout=DISCONNECT_CHECK)
            except TimeoutError:
                idle += DISCONNECT_CHECK
                if idle >= KEEPALIVE_SECONDS:
                    # Long enough that an intermediary might give up on us --
                    # a turn can sit silent for a minute while the model thinks.
                    yield ": keepalive\n\n"
                    idle = 0.0
                continue
            idle = 0.0
            if kind in ("approval", "activity"):
                yield f"data: {json.dumps(item)}\n\n"
                continue
            payload = feed_event(
                item.session_id,
                item.event,
                getattr(item.event, "aggregate_version", None),
            )
            # One yield, not two: an id and its data are a single SSE frame,
            # and splitting them would let a cancellation land between the
            # cursor and the event it belongs to.
            cursor = feed.encode_position(item.position)
            yield f"id: {cursor}\ndata: {json.dumps(payload)}\n\n"
    finally:
        if approvals is not None and listening is not None:
            approvals.stop_listening(listening)
        if activity is not None and watching is not None:
            activity.stop_listening(watching)
        for pumping in pumps:
            pumping.cancel()
            with suppress(asyncio.CancelledError):
                await pumping
