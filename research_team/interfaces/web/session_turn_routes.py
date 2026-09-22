"""Turn execution, cancellation, live activity, approvals, and autonomy policy routes."""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from eventsource import OptimisticLockError
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from research_team.interfaces.web.approvals import UnknownApproval
from research_team.interfaces.web.presenters import autonomy_view
from research_team.interfaces.web.session_deps import SessionDeps
from research_team.platform.shared.ports import ApprovalDecision
from research_team.session.application.autonomy import AutonomyPolicy
from research_team.session.application.turn_supervisor import (
    TurnAlreadyRunning,
    TurnCancelled,
    TurnTimeout,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AutonomyChoice",
    "Decision",
    "NewTurn",
    "session_turn_router",
]


class NewTurn(BaseModel):
    input: str


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


def session_turn_router(
    deps: SessionDeps,
    load: Callable[[UUID], Awaitable[Any]],
) -> APIRouter:
    """The turn, approval, and autonomy routes, ready for `app.include_router`."""
    router = APIRouter()
    service = deps.service
    turns = deps.turns
    approvals = deps.approvals
    activity = deps.activity
    policy = deps.policy

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

    @router.post("/api/sessions/{session_id}/turns")
    async def run_turn(session_id: UUID, body: NewTurn):
        await load(session_id)
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
        except TurnTimeout as error:
            raise HTTPException(status_code=504, detail=str(error)) from error
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
        await load(session_id)
        cancellation = await turns.cancel(session_id)
        return {
            "cancelled": cancellation.cancelled,
            "settled": cancellation.settled,
        }

    @router.get("/api/sessions/{session_id}/turns/current")
    async def current_turn(session_id: UUID):
        """What is in flight -- so a tab that arrived mid-turn can say so."""
        await load(session_id)
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
        await load(session_id)
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
        await load(session_id)
        return [] if approvals is None else approvals.pending(session_id)

    @router.post("/api/sessions/{session_id}/approvals/{approval_id}")
    async def decide_approval(session_id: UUID, approval_id: str, body: Decision):
        """Answer one parked approval, unblocking the turn waiting on it."""
        if approvals is None:
            raise HTTPException(status_code=404, detail="approvals are not wired up")
        await load(session_id)
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
        await load(session_id)
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
        await load(session_id)
        changed = instance.relax_all()
        # One append, not one per tool. Each append is a chance for a turn
        # running on this session to lose its version, and this route issues
        # its writes back to back -- see `record_autonomy_changes`.
        await service.record_autonomy_changes(session_id, changed)
        return {"changed": changed} | autonomy_view(instance)

    @router.post("/api/sessions/{session_id}/autonomy/restrict-all")
    async def restrict_all_autonomy(session_id: UUID, level: str = "ask"):
        """Require approval for all hazards (or set to specified level)."""
        instance = _policy()
        await load(session_id)
        try:
            changed = instance.restrict_all(level)  # type: ignore[arg-type]
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        await service.record_autonomy_changes(session_id, changed)
        return {"changed": changed} | autonomy_view(instance)

    return router
