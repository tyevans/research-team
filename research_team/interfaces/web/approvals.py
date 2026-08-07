"""An `ApprovalPort` whose human is somewhere on the other end of an HTTP call.

The terminal port can simply block on a prompt; this one cannot. A turn runs
inside the server, the person deciding is in a browser, and the two are joined
only by the SSE feed going out and a `POST` coming back. So the request is
parked as a future, announced on the feed, and resolved when the `POST`
arrives.

The parking is what makes cancellation matter. A browser that closes leaves a
turn waiting on a future nobody will ever resolve, and the only thing that can
free it is the turn's own cancellation -- which reaches the `await` below and
unwinds it into a recorded `TurnFailed`. The registry is cleaned up in a
`finally` for exactly that path.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from research_team.application import ApprovalDecision, ApprovalRequest

REQUESTED = "ApprovalRequested"
SETTLED = "ApprovalSettled"
"""Frame types on the live feed. PascalCase like the event names beside them,
because the browser switches on one `type` field for everything it receives."""


@dataclass
class PendingApproval:
    """One gated call, waiting for a person."""

    id: str
    request: ApprovalRequest
    future: asyncio.Future = field(repr=False)

    def view(self) -> dict[str, Any]:
        """The frame a browser receives for one pending call.

        `context` appears only when there is one, so an ordinary tool gate's
        payload is byte-identical to what it was before stage reviews existed
        -- a client switching on the presence of the key gets a reliable
        answer, and no existing client sees a field it does not know.
        """
        view = {
            "id": self.id,
            "session_id": str(self.request.session_id),
            "tool_name": self.request.tool_name,
            "args": self.request.args,
            "description": self.request.description,
            "allowed_decisions": list(self.request.allowed_decisions),
        }
        if self.request.context is not None:
            view["context"] = self.request.context
        return view


class UnknownApproval(LookupError):
    """No approval by that id is pending on that session.

    Ordinary rather than exceptional: two tabs can answer the same request, or
    one can answer a request the turn has already abandoned, and the loser of
    that race deserves a plain 404 rather than a 500.
    """


class WebApprovals:
    """Pending approvals, keyed by session, plus the feed that announces them."""

    def __init__(self) -> None:
        self._pending: dict[UUID, dict[str, PendingApproval]] = {}
        self._listeners: set[asyncio.Queue] = set()

    # ---------------- the port ----------------

    async def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        approval = PendingApproval(
            id=str(uuid4()),
            request=request,
            future=asyncio.get_running_loop().create_future(),
        )
        self._pending.setdefault(request.session_id, {})[approval.id] = approval
        self._announce({"type": REQUESTED, **approval.view()})
        try:
            return await approval.future
        finally:
            # Reached on cancellation as well as on an answer, which is the
            # point: a turn stopped mid-approval must not leave a row in here
            # for a browser to answer into nothing.
            self._forget(request.session_id, approval.id)
            self._announce(
                {
                    "type": SETTLED,
                    "id": approval.id,
                    "session_id": str(request.session_id),
                }
            )

    # ---------------- what the HTTP layer drives ----------------

    def pending(self, session_id: UUID) -> list[dict[str, Any]]:
        """Everything awaiting a decision, for a tab that arrived mid-turn."""
        return [approval.view() for approval in self._pending.get(session_id, {}).values()]

    def resolve(self, session_id: UUID, approval_id: str, decision: ApprovalDecision) -> None:
        approval = self._pending.get(session_id, {}).get(approval_id)
        if approval is None or approval.future.done():
            raise UnknownApproval(f"no approval {approval_id} pending on {session_id}")
        approval.future.set_result(decision)

    def cancel(self, session_id: UUID) -> int:
        """Free every approval parked on a session. Returns how many there were.

        Belt to the `finally`'s braces: cancelling the turn task already
        unblocks the `await`, but a caller that tears a session down without
        going through the supervisor should not have to know that.
        """
        parked = list(self._pending.get(session_id, {}).values())
        for approval in parked:
            if not approval.future.done():
                approval.future.cancel()
        return len(parked)

    # ---------------- the feed ----------------

    def listen(self) -> asyncio.Queue:
        """Subscribe to approval frames, starting with whatever is already parked.

        Unbounded, because dropping a frame strands a turn. Seeded, because
        these frames carry no feed position and so cannot be replayed by
        `Last-Event-ID`: a browser that connects a moment after a call was
        gated would otherwise see nothing until the next one.
        """
        queue: asyncio.Queue = asyncio.Queue()
        for session in self._pending.values():
            for approval in session.values():
                queue.put_nowait({"type": REQUESTED, **approval.view()})
        self._listeners.add(queue)
        return queue

    def stop_listening(self, queue: asyncio.Queue) -> None:
        self._listeners.discard(queue)

    def _announce(self, payload: dict[str, Any]) -> None:
        for queue in self._listeners:
            queue.put_nowait(payload)

    def _forget(self, session_id: UUID, approval_id: str) -> None:
        session = self._pending.get(session_id)
        if session is None:
            return
        session.pop(approval_id, None)
        if not session:
            del self._pending[session_id]
