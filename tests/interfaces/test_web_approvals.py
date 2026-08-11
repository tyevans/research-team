"""`WebApprovals.decide` bounded on an unattended session, unbounded on a human's.

The distinction under test is not duration -- it's *whether a timeout applies
at all*. A session `GrantRegistry` knows about belongs to a run with nobody
watching, and waiting forever there is the bug this task fixes. A session the
registry has never heard of belongs to a person, who may be away from the
keyboard for reasons no fixed number could accommodate; bounding that would
trade one bug for a worse one.

No test here sleeps. `WebApprovals` takes its wait function as `sleep`, and
every test that needs the timer to fire substitutes one that resolves without
letting real time pass -- the timeout value itself is asserted by inspecting
what duration that fake was asked to wait for, not by waiting it out.
"""

import asyncio
from uuid import uuid4

import pytest

from research_team.application import ApprovalDecision, ApprovalRefused, ApprovalRequest
from research_team.application.grants import FetchGrant, GrantRegistry
from research_team.interfaces.web.approvals import UNATTENDED_TIMEOUT_S, WebApprovals


def _request(session_id) -> ApprovalRequest:
    return ApprovalRequest(
        session_id=session_id,
        tool_name="fetch",
        args={"url": "https://a.example"},
        description="",
        allowed_decisions=("approve", "edit", "reject"),
    )


def _registry_knowing(session_id) -> GrantRegistry:
    """A registry for which `session_id` is unattended -- registered, whether
    or not its grant covers anything, per `is_unattended`'s own contract."""
    registry = GrantRegistry()
    registry.register(session_id, FetchGrant(run_id=uuid4(), hosts=frozenset(), budget=0))
    return registry


async def _fires_immediately(_seconds: float) -> None:
    """Stands in for `asyncio.sleep`: resolves at once regardless of the
    duration asked for, so the timeout branch is reachable without a test
    ever waiting out the real default."""
    await asyncio.sleep(0)


class _RecordingSleep:
    """Same job as `_fires_immediately`, but remembers what it was asked to
    wait for -- how the timeout value itself gets asserted without timing
    anything."""

    def __init__(self) -> None:
        self.seconds: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.seconds.append(seconds)
        await asyncio.sleep(0)


async def test_a_registered_sessions_approval_is_refused_after_the_bound():
    """`WebApprovals.decide` raises `ApprovalRefused` rather than returning a
    `reject` `ApprovalDecision` -- an `ApprovalDecision` is what a human
    chose, and nobody chose this. See `ApprovalRefused`'s docstring: the
    executor (`deep_agent.py`'s `_decide`) is what turns this into a `reject`
    the model reads, recording `decided_by="policy"` rather than the
    `decided_by="human"` every `ApprovalDecision` gets stamped with."""
    session_id = uuid4()
    approvals = WebApprovals(grants=_registry_knowing(session_id), sleep=_fires_immediately)

    with pytest.raises(ApprovalRefused):
        await approvals.decide(_request(session_id))


async def test_the_refusal_carries_a_message_the_model_can_read():
    """The exception's message is what a caller shows the model, the same
    role `ApprovalDecision.message` plays on the ordinary reject path -- it
    must not be empty, and it must not require the caller to invent one."""
    session_id = uuid4()
    approvals = WebApprovals(grants=_registry_knowing(session_id), sleep=_fires_immediately)

    with pytest.raises(ApprovalRefused) as excinfo:
        await approvals.decide(_request(session_id))

    assert str(excinfo.value)


async def test_the_timeout_used_is_the_named_default():
    session_id = uuid4()
    recorder = _RecordingSleep()
    approvals = WebApprovals(grants=_registry_knowing(session_id), sleep=recorder)

    with pytest.raises(ApprovalRefused):
        await approvals.decide(_request(session_id))

    assert recorder.seconds == [UNATTENDED_TIMEOUT_S]


async def test_a_prompt_answer_still_succeeds_under_a_bound():
    """A registered session is bounded, but the bound must not fire on an
    approval that was answered well within it -- the timer and the future
    are racing, not one gating the other."""
    session_id = uuid4()
    approvals = WebApprovals(grants=_registry_knowing(session_id), sleep=asyncio.sleep)

    async def approve_once_parked() -> None:
        while not approvals.pending(session_id):
            await asyncio.sleep(0)
        parked = approvals.pending(session_id)[0]
        approvals.resolve(session_id, parked["id"], ApprovalDecision("approve"))

    async with asyncio.timeout(5):
        _, decision = await asyncio.gather(
            approve_once_parked(), approvals.decide(_request(session_id))
        )

    assert decision == ApprovalDecision("approve")


async def test_an_unregistered_sessions_approval_is_never_bounded():
    """The test whose only job is to fail if a timeout is EVER applied to a
    human's session.

    No `GrantRegistry` is even supplied -- `decide` must never consult one it
    wasn't given, and never manufacture a timeout for a session no registry
    named. `sleep` here raises the moment it is called, so any code path that
    even *starts* a timer for this session fails the test loudly rather than
    hanging it; the approval itself is answered normally afterward to keep
    the test from being the thing that hangs.
    """

    async def _must_not_be_called(_seconds: float) -> None:
        raise AssertionError("an unregistered session's approval was bounded by a timeout")

    session_id = uuid4()
    approvals = WebApprovals(sleep=_must_not_be_called)

    async def approve_once_parked() -> None:
        while not approvals.pending(session_id):
            await asyncio.sleep(0)
        parked = approvals.pending(session_id)[0]
        approvals.resolve(session_id, parked["id"], ApprovalDecision("approve"))

    async with asyncio.timeout(5):
        _, decision = await asyncio.gather(
            approve_once_parked(), approvals.decide(_request(session_id))
        )

    assert decision == ApprovalDecision("approve")


async def test_an_unregistered_session_with_no_grants_registry_at_all_is_unbounded():
    """`WebApprovals()` with no `grants` argument -- how every existing
    caller and every existing test constructs it -- must behave exactly as
    it always has: nothing ever times out."""

    async def _must_not_be_called(_seconds: float) -> None:
        raise AssertionError("decide() consulted a timeout with no registry supplied")

    session_id = uuid4()
    approvals = WebApprovals(sleep=_must_not_be_called)
    assert approvals._grants is None

    async def approve_once_parked() -> None:
        while not approvals.pending(session_id):
            await asyncio.sleep(0)
        parked = approvals.pending(session_id)[0]
        approvals.resolve(session_id, parked["id"], ApprovalDecision("approve"))

    async with asyncio.timeout(5):
        _, decision = await asyncio.gather(
            approve_once_parked(), approvals.decide(_request(session_id))
        )

    assert decision == ApprovalDecision("approve")
