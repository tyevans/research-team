"""The Session, Turn, Approval, and Autonomy HTTP surface.

Its own module and its own router, following `knowledge.py`, `topics.py`,
`sources.py`, `catalog.py`, and `dialogues.py`: `create_app` is thousands
of lines of closures and modularizing these routes extracts ~400 lines
from `app.py`.
"""

import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from eventsource import CommandRejectedError, OptimisticLockError
from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, Field

from research_team.application import (
    ApprovalDecision,
    AutonomyPolicy,
    SessionService,
    TurnAlreadyRunning,
    TurnCancelled,
    TurnSupervisor,
)
from research_team.application.components import View, parse_document, project
from research_team.application.curriculum.grading import GradingError, grade
from research_team.interfaces.web.activity import TurnActivity
from research_team.interfaces.web.approvals import UnknownApproval, WebApprovals
from research_team.interfaces.web.dialogues import Attempt
from research_team.interfaces.web.presenters import (
    autonomy_view,
    event_rows,
    file_history,
    item_view,
    progress_view,
    session_view,
)

logger = logging.getLogger(__name__)


class NewTurn(BaseModel):
    input: str


class NewFork(BaseModel):
    at: int


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


class Decision(BaseModel):
    """A human's answer to a parked approval. `type` is langchain's vocabulary."""

    type: str
    edited_args: dict | None = None
    message: str | None = None


class AutonomyChoice(BaseModel):
    """One tool's new autonomy level.

    Both fields are plain `str` rather than the `Level` literal and a tool
    enum, so that a bad value reaches `AutonomyPolicy.set` and comes back as
    that method's own complaint -- which names the offending value and says
    whether the problem was the level or the tool. FastAPI's 422 for a
    `Literal` mismatch is machine-readable and says neither, and this is a
    message a person reads off a switch they just flipped.
    """

    tool: str
    level: str


@dataclass(frozen=True)
class SessionDeps:
    """What the session, turn, approval, and autonomy routes need from
    `create_app`'s closure.

    A record rather than a long parameter list, matching `TopicDeps`,
    `KnowledgeDeps`, and `DialogueDeps`.
    """

    service: SessionService
    turns: TurnSupervisor
    approvals: WebApprovals | None = None
    activity: TurnActivity | None = None
    policy: AutonomyPolicy | None = None
    load: Callable[[UUID], Awaitable[Any]] | None = None


def session_router(deps: SessionDeps) -> APIRouter:
    """The session, turn, approval, and autonomy router, ready for
    `app.include_router`.
    """
    router = APIRouter()
    service = deps.service
    turns = deps.turns
    approvals = deps.approvals
    activity = deps.activity
    policy = deps.policy

    async def _load(session_id: UUID):
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

    def _policy() -> AutonomyPolicy:
        """The instance's policy, or a 404 saying this build has none.

        404 rather than a permissive default, matching `/workers`: "this build
        cannot tell you what the agent may do without asking" is a different
        claim from "everything is automatic", and a UI that read the second off
        the first would show a row of green switches for a policy it has no
        handle on.
        """
        if policy is None:
            raise HTTPException(status_code=404, detail="the autonomy policy is not wired up")
        return policy

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
        content = await _read_file(session_id, path, at)
        return project(parse_document(content, path=path), view=view) | {"at": at}

    @router.post("/api/sessions/{session_id}/attempts")
    async def post_attempt(session_id: UUID, body: Attempt):
        """Mark one attempt. The server holds the key; the browser was not given it.

        A wrong answer is a 200 with `correct: false` -- it is a result, not an
        error. The 400s here are all malformed *requests*: a response shape the
        item cannot interpret, or an item that has no answer to mark.
        """
        content = await _read_file(session_id, body.path, body.at)
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
        await _load(session_id)
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
        content = await _read_file(session_id, body.path, body.at)
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

    @router.post("/api/sessions/{session_id}/turns")
    async def run_turn(session_id: UUID, body: NewTurn):
        await _load(session_id)
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
        # No `noqa` needed: ruff accepts a bare `except Exception` whose handler
        # logs it with `exc_info=True`, which is what the warning below does.
        except Exception:
            logger.warning(
                "could not attach knowledge graph for %s", session_id, exc_info=True
            )
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

    @router.post("/api/sessions/{session_id}/turns/cancel")
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

    @router.get("/api/sessions/{session_id}/turns/current")
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

    @router.get("/api/sessions/{session_id}/turns/current/activity")
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

    @router.get("/api/sessions/{session_id}/approvals")
    async def pending_approvals(session_id: UUID):
        """Gated calls this session is waiting on.

        The live feed announces each one as it is parked, but a tab that opened
        mid-turn never saw that frame -- this is how it catches up.
        """
        await _load(session_id)
        return [] if approvals is None else approvals.pending(session_id)

    @router.post("/api/sessions/{session_id}/approvals/{approval_id}")
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

    @router.get("/api/autonomy")
    async def get_autonomy():
        """What the agent may currently do without asking.

        No session in the path, because there is no per-session answer to give:
        one `AutonomyPolicy` serves the whole process, so this is a read of
        instance state. See the POST routes for why the *writes* name a session
        even though the state they change does not belong to one.
        """
        return autonomy_view(_policy())

    @router.post("/api/sessions/{session_id}/autonomy")
    async def set_autonomy(session_id: UUID, body: AutonomyChoice):
        """Set one tool's level, and record that it was set.

        Two steps, both required, exactly as `/autonomy` in the REPL does them.
        The policy is what the executor consults, so mutating it is what
        changes behaviour -- but a level that changed mid-session and left no
        trace makes every surrounding decision unreadable afterwards, in a
        system whose whole point is a complete audit trail. See
        `SessionService.record_autonomy_change`.

        The asymmetry is real and worth stating plainly rather than leaving to
        be discovered: **the policy is instance-wide and the record is
        per-session.** One object answers for every session in this process, so
        this call changes what the agent may do in all of them, while the
        `AutonomyChanged` event lands on this session's stream alone. That is
        what the REPL does, and it is the right trade for a local single-user
        tool -- the same trade `join_project` documents for graph attachment.
        The session in the path is therefore "who is answering for this
        change", not "where it applies". A per-session policy map would make the
        two agree, but nothing has asked for concurrent untrusted users, and
        splitting the policy would silently change what the executor consults
        for every other caller.

        A bad tool or level is a 400 carrying the policy's own message, and
        nothing is recorded: a rejected `set` changed nothing, so a log entry
        would describe a change that did not happen.
        """
        instance = _policy()
        await _load(session_id)
        try:
            instance.set(body.tool, body.level)  # type: ignore[arg-type]
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        await service.record_autonomy_change(session_id, body.tool, body.level)
        # The full map, so a client that just flipped one switch does not need a
        # second request to redraw the rest -- and cannot drift from the server
        # by assuming its own change was the only one.
        return autonomy_view(instance)

    @router.post("/api/sessions/{session_id}/autonomy/allow-all")
    async def allow_all_autonomy(session_id: UUID):
        """Stop asking about every hazard. No body, because there is nothing
        left to ask for.

        It used to take `include_stage_gates`, which crossed the workflow
        review gate as well. The console stopped sending it a slice before
        this and the gate itself is deleted a slice after, so the flag would
        be a switch over a tool that is on its way out. `relax_all`'s own
        parameter goes with that tool; this call takes its default until then,
        which is the behaviour a client omitting the flag already got.

        The instance-wide/per-session asymmetry described on `set_autonomy`
        applies here too, and more loudly: this relaxes every hazard for every
        session in the process, and records it on one.

        `changed` is only what actually moved, and one `AutonomyChanged` is
        recorded per entry -- never one per gated tool. A log that claimed eight
        decisions where a person made one is as unreadable as a log that
        omitted them, and it is `changed` the UI should report back so it says
        what it did rather than claiming more.
        """
        instance = _policy()
        await _load(session_id)
        changed = instance.relax_all()
        # One append, not one per tool. Each append is a chance for a turn
        # running on this session to lose its version, and this route issues
        # its writes back to back -- see `record_autonomy_changes`.
        await service.record_autonomy_changes(session_id, changed)
        return {"changed": changed} | autonomy_view(instance)

    @router.post("/api/sessions/{session_id}/forks")
    async def fork_session(session_id: UUID, body: NewFork):
        await _load(session_id)
        try:
            return {"id": str(await service.fork(session_id, body.at))}
        except (ValueError, CommandRejectedError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    return router


sessions_router = session_router


def mount_session_routes(app: FastAPI, deps: SessionDeps) -> None:
    """Mount the session router on the given FastAPI app."""
    app.include_router(session_router(deps))
