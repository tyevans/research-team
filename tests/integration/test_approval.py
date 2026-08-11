"""Approval, end to end: from a policy that gates to events in the log.

The resume-loop tests already cover the executor in isolation. What these add
is the whole path -- service, executor, port, adapter -- and they assert on
recorded events rather than on anything printed, because the log is the only
thing that survives the process and the only thing an audit can read.

Nothing here touches the network: the search tool is built over a
`MockTransport`, and the composition root's own `build_search_tool` is
replaced so a configured instance never turns into a real request.
"""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from research_team import composition
from research_team.application import (
    ApprovalDecision,
    ApprovalRequest,
    AutonomyPolicy,
    TurnCancelled,
)
from research_team.domain import (
    AutonomyChanged,
    ToolCallDecided,
    ToolResultRecorded,
    TurnFailed,
)
from research_team.infrastructure.agent.search import build_search_tool
from research_team.interfaces.cli import TerminalApprovals, repl
from research_team.interfaces.web import WebApprovals, create_app
from research_team.interfaces.web.app import _sse
from tests.conftest import ToolAwareFakeChatModel, start_session

RESULT_TITLE = "Event Sourcing Explained"
PAYLOAD = {
    "results": [{"title": RESULT_TITLE, "url": "https://a.example", "content": "A snippet."}]
}


class Searches:
    """Records every query the stubbed SearXNG transport is asked for."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.queries.append(request.url.params.get("q"))
        return httpx.Response(200, json=PAYLOAD)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def searches(monkeypatch) -> Searches:
    """A configured search instance that is entirely made of mock transport."""
    recorder = Searches()
    monkeypatch.setenv("AGENT_SEARXNG_URL", "http://searx.local")

    def build(base_url: str, *, limit: int = 5, client=None, recall=None, attempts=None):
        # Mirrors `build_search_tool`'s signature rather than taking `**kwargs`,
        # and forwards `recall` and `attempts` rather than dropping them: a
        # stub that silently ignores an argument the real builder honours
        # stops testing the thing it stands in for, and the divergence
        # surfaces as a passing suite over code that behaves differently in
        # production. `attempts` is the object Task 6 wires the composition
        # root's own `SearchAttempts` through -- dropping it here would still
        # exercise the middleware but never the counter it resets.
        return build_search_tool(
            base_url, limit=limit, client=recorder.client(), recall=recall, attempts=attempts
        )

    monkeypatch.setattr(composition, "build_search_tool", build)
    return recorder


@pytest.fixture
def searching_model() -> ToolAwareFakeChatModel:
    """Asks for one search, then replies."""
    return ToolAwareFakeChatModel(
        responses=[
            AIMessage(
                content="",
                id="a1",
                tool_calls=[
                    {"name": "web_search", "args": {"query": "event sourcing"}, "id": "t1"}
                ],
            ),
            AIMessage(content="done", id="a2"),
        ]
    )


def _asking_policy() -> AutonomyPolicy:
    policy = AutonomyPolicy(default="auto")
    policy.set("web_search", "ask")
    return policy


class FixedPort:
    """An ApprovalPort answering the same way every time, recording requests."""

    def __init__(self, decision: ApprovalDecision) -> None:
        self._decision = decision
        self.seen: list[ApprovalRequest] = []

    async def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        self.seen.append(request)
        return self._decision


def _types(events) -> list[str]:
    return [type(event).__name__ for event in events]


def _search_results(events) -> list[ToolResultRecorded]:
    return [
        event
        for event in events
        if isinstance(event, ToolResultRecorded)
        and RESULT_TITLE in str(event.message.get("data", {}).get("content", ""))
    ]


# ---------------- the whole path, through the service ----------------


async def test_an_approved_search_is_decided_before_it_is_run(
    build_application, searches, searching_model
):
    """The decision must be in the log *before* the result it authorised.

    Order is the claim being made here. A result recorded ahead of its
    decision would describe a system that searched first and asked after.
    """
    port = FixedPort(ApprovalDecision("approve"))
    application = await build_application(
        model=searching_model, policy=_asking_policy(), approvals=port
    )
    session_id = await start_session(application.service)

    await application.service.run_turn(session_id, "what is event sourcing?")

    events = await application.service.history(session_id)
    kinds = _types(events)
    assert "ToolCallDecided" in kinds, kinds
    decided = kinds.index("ToolCallDecided")
    results = _search_results(events)
    assert results, "the approved search left no result in the log"
    assert decided < events.index(results[0])
    assert searches.queries == ["event sourcing"]


async def test_a_rejected_search_records_the_decision_and_no_result(
    build_application, searches, searching_model
):
    port = FixedPort(ApprovalDecision("reject", message="not now"))
    application = await build_application(
        model=searching_model, policy=_asking_policy(), approvals=port
    )
    session_id = await start_session(application.service)

    await application.service.run_turn(session_id, "what is event sourcing?")

    events = await application.service.history(session_id)
    decisions = [e for e in events if isinstance(e, ToolCallDecided)]
    assert [(d.decision, d.decided_by) for d in decisions] == [("reject", "human")]
    assert _search_results(events) == []
    assert searches.queries == [], "a rejected search still went out"


async def test_an_edited_search_records_both_the_original_and_the_amendment(
    build_application, searches, searching_model
):
    port = FixedPort(ApprovalDecision("edit", edited_args={"query": "CQRS"}))
    application = await build_application(
        model=searching_model, policy=_asking_policy(), approvals=port
    )
    session_id = await start_session(application.service)

    await application.service.run_turn(session_id, "what is event sourcing?")

    events = await application.service.history(session_id)
    (decided,) = [e for e in events if isinstance(e, ToolCallDecided)]
    assert decided.args == {"query": "event sourcing"}
    assert decided.edited_args == {"query": "CQRS"}
    assert searches.queries == ["CQRS"]


# ---------------- the terminal adapter ----------------


class Typed:
    """A person at a terminal, scripted. Records the prompts they were shown."""

    def __init__(self, keys: list[str]) -> None:
        self._keys = list(keys)
        self.prompts: list[str] = []
        self.shown: list[str] = []

    async def ask(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._keys.pop(0) if self._keys else ""


async def test_the_terminal_port_shows_the_call_and_reads_one_key():
    typed = Typed(["a"])
    port = TerminalApprovals(ask=typed.ask, show=typed.shown.append)

    decision = await port.decide(
        ApprovalRequest(
            session_id=uuid4(),
            tool_name="web_search",
            args={"query": "event sourcing"},
            description="",
            allowed_decisions=("approve", "edit", "reject"),
        )
    )

    assert decision == ApprovalDecision("approve")
    assert any("web_search" in line for line in typed.shown)
    assert any("event sourcing" in line for line in typed.shown)


async def test_the_terminal_port_rejects_when_nobody_answers():
    """An empty line -- EOF, a closed pipe -- is not consent."""
    port = TerminalApprovals(ask=Typed([]).ask, show=lambda _: None)

    decision = await port.decide(
        ApprovalRequest(
            session_id=uuid4(),
            tool_name="web_search",
            args={"query": "q"},
            description="",
            allowed_decisions=(),
        )
    )

    assert decision.type == "reject"


async def test_the_terminal_port_amends_arguments_on_edit():
    typed = Typed(["e", "CQRS"])
    port = TerminalApprovals(ask=typed.ask, show=lambda _: None)

    decision = await port.decide(
        ApprovalRequest(
            session_id=uuid4(),
            tool_name="web_search",
            args={"query": "event sourcing"},
            description="",
            allowed_decisions=(),
        )
    )

    assert decision == ApprovalDecision("edit", edited_args={"query": "CQRS"})


async def test_an_unreadable_key_is_asked_again_rather_than_assumed():
    typed = Typed(["z", "r"])
    port = TerminalApprovals(ask=typed.ask, show=lambda _: None)

    decision = await port.decide(
        ApprovalRequest(
            session_id=uuid4(),
            tool_name="web_search",
            args={},
            description="",
            allowed_decisions=(),
        )
    )

    assert decision.type == "reject"
    assert len(typed.prompts) == 2


# ---------------- /autonomy ----------------


async def test_autonomy_lists_every_gated_tool(build_service, fake_model):
    current = await repl.Repl.start(await build_service(model=fake_model))
    current.session_id = await start_session(current.service)

    output = await repl.handle_command(current, "/autonomy")

    assert "web_search" in output and "auto" in output
    assert "write_file" in output


async def test_autonomy_sets_a_level_and_records_it(build_service, fake_model):
    """Setting a level changes the live policy *and* leaves a trace.

    The policy is what the executor consults; the event is what makes the
    decisions around it readable a month later.
    """
    service = await build_service(model=fake_model)
    current = await repl.Repl.start(service)
    current.session_id = await start_session(service)

    output = await repl.handle_command(current, "/autonomy web_search ask")

    assert current.policy.level_for("web_search") == "ask"
    assert "ask" in output
    events = await service.history(current.session_id)
    changes = [e for e in events if isinstance(e, AutonomyChanged)]
    assert [(c.tool_name, c.level) for c in changes] == [("web_search", "ask")]


async def test_autonomy_complains_about_a_bad_level_without_dying(build_service, fake_model):
    current = await repl.Repl.start(await build_service(model=fake_model))
    current.session_id = await start_session(current.service)

    output = await repl.handle_command(current, "/autonomy web_search whenever")

    assert "whenever" in output
    assert current.policy.level_for("web_search") == "auto"


async def test_autonomy_complains_about_an_ungated_tool(build_service, fake_model):
    current = await repl.Repl.start(await build_service(model=fake_model))
    current.session_id = await start_session(current.service)

    output = await repl.handle_command(current, "/autonomy read_file ask")

    assert "read_file" in output


async def test_autonomy_reports_its_usage_when_given_nonsense(build_service, fake_model):
    current = await repl.Repl.start(await build_service(model=fake_model))
    current.session_id = await start_session(current.service)

    assert "usage" in await repl.handle_command(current, "/autonomy web_search")


# ---------------- the web adapter ----------------


async def _web(build_application, model, policy, approvals):
    application = await build_application(model=model, policy=policy, approvals=approvals)
    api = create_app(
        application.service, application.feed, application.turns, approvals=approvals
    )
    transport = ASGITransport(app=api)
    client = AsyncClient(transport=transport, base_url="http://test")
    return application, client


async def _wait_for_pending(approvals: WebApprovals, session_id, timeout: float = 5.0):
    """Poll until a request is parked, so tests never sleep on a guess."""
    async with asyncio.timeout(timeout):
        while True:
            parked = approvals.pending(session_id)
            if parked:
                return parked[0]
            await asyncio.sleep(0.01)


async def test_a_browser_approval_unblocks_the_turn_and_the_search_runs(
    build_application, searches, searching_model
):
    approvals = WebApprovals()
    application, client = await _web(
        build_application, searching_model, _asking_policy(), approvals
    )
    async with client:
        session_id = await start_session(application.service)
        turn = asyncio.ensure_future(application.turns.run(session_id, "search please"))

        parked = await _wait_for_pending(approvals, session_id)
        assert parked["tool_name"] == "web_search"
        assert parked["args"] == {"query": "event sourcing"}

        listed = await client.get(f"/api/sessions/{session_id}/approvals")
        assert [row["id"] for row in listed.json()] == [parked["id"]]

        answered = await client.post(
            f"/api/sessions/{session_id}/approvals/{parked['id']}",
            json={"type": "approve"},
        )
        assert answered.status_code == 200
        await turn

    events = await application.service.history(session_id)
    assert [(d.decision, d.decided_by) for d in _decisions(events)] == [("approve", "human")]
    assert _search_results(events)
    assert searches.queries == ["event sourcing"]


def _decisions(events) -> list[ToolCallDecided]:
    return [e for e in events if isinstance(e, ToolCallDecided)]


async def test_a_browser_rejection_stops_the_call(
    build_application, searches, searching_model
):
    approvals = WebApprovals()
    application, client = await _web(
        build_application, searching_model, _asking_policy(), approvals
    )
    async with client:
        session_id = await start_session(application.service)
        turn = asyncio.ensure_future(application.turns.run(session_id, "search please"))
        parked = await _wait_for_pending(approvals, session_id)

        await client.post(
            f"/api/sessions/{session_id}/approvals/{parked['id']}",
            json={"type": "reject", "message": "not now"},
        )
        await turn

    events = await application.service.history(session_id)
    assert [(d.decision, d.decided_by) for d in _decisions(events)] == [("reject", "human")]
    assert _search_results(events) == []
    assert searches.queries == []


async def test_an_edit_from_the_browser_amends_the_arguments(
    build_application, searches, searching_model
):
    approvals = WebApprovals()
    application, client = await _web(
        build_application, searching_model, _asking_policy(), approvals
    )
    async with client:
        session_id = await start_session(application.service)
        turn = asyncio.ensure_future(application.turns.run(session_id, "search please"))
        parked = await _wait_for_pending(approvals, session_id)

        await client.post(
            f"/api/sessions/{session_id}/approvals/{parked['id']}",
            json={"type": "edit", "edited_args": {"query": "CQRS"}},
        )
        await turn

    assert searches.queries == ["CQRS"]


async def test_answering_the_same_approval_twice_is_a_404(
    build_application, searches, searching_model
):
    approvals = WebApprovals()
    application, client = await _web(
        build_application, searching_model, _asking_policy(), approvals
    )
    async with client:
        session_id = await start_session(application.service)
        turn = asyncio.ensure_future(application.turns.run(session_id, "search please"))
        parked = await _wait_for_pending(approvals, session_id)
        url = f"/api/sessions/{session_id}/approvals/{parked['id']}"

        assert (await client.post(url, json={"type": "approve"})).status_code == 200
        await turn
        assert (await client.post(url, json={"type": "approve"})).status_code == 404


async def test_the_request_is_published_on_the_existing_sse_feed(
    build_application, searches, searching_model
):
    """One channel, not two: the browser learns about a parked call on the
    same connection that brings it every event.

    Driven against the generator rather than over the ASGI transport, which
    buffers a whole response and so can never read an endless stream -- the
    same reason the existing SSE tests are written this way.
    """
    approvals = WebApprovals()
    application = await build_application(
        model=searching_model, policy=_asking_policy(), approvals=approvals
    )
    session_id = await start_session(application.service)

    frames: list[str] = []
    generator = _sse(_StillHere(), application.feed, None, approvals)
    reading = asyncio.ensure_future(_read_until_approval(generator, frames))
    turn = asyncio.ensure_future(application.turns.run(session_id, "search please"))
    parked = await _wait_for_pending(approvals, session_id)
    async with asyncio.timeout(5):
        await reading

    approvals.resolve(session_id, parked["id"], ApprovalDecision("approve"))
    await turn

    payloads = [json.loads(frame.split("data: ", 1)[1]) for frame in frames]
    requested = [p for p in payloads if p["type"] == "ApprovalRequested"]
    assert requested, f"the approval never reached the feed: {payloads}"
    assert requested[0]["tool_name"] == "web_search"
    assert requested[0]["session_id"] == str(session_id)
    assert requested[0]["args"] == {"query": "event sourcing"}


class _StillHere:
    """A request that never disconnects. All `_sse` asks of one."""

    async def is_disconnected(self) -> bool:
        return False


async def _read_until_approval(generator, frames: list[str]) -> None:
    """Collect frames until the approval arrives, then shut the generator down.

    Leaving it suspended would leave its poll loop holding the store open past
    the end of the test.
    """
    try:
        async for frame in generator:
            if frame.startswith(":"):
                continue
            frames.append(frame)
            if "ApprovalRequested" in frame:
                return
    finally:
        await generator.aclose()


async def test_cancelling_the_turn_unblocks_a_waiting_approval(
    build_application, searches, searching_model
):
    """The browser went away. Nothing will ever answer.

    Cancellation is the only thing that can free the turn, and it has to leave
    a recorded `TurnFailed` rather than a coroutine parked forever on a future.
    """
    approvals = WebApprovals()
    application, client = await _web(
        build_application, searching_model, _asking_policy(), approvals
    )
    async with client:
        session_id = await start_session(application.service)
        turn = asyncio.ensure_future(application.turns.run(session_id, "search please"))
        await _wait_for_pending(approvals, session_id)

        cancellation = await application.turns.cancel(session_id)
        assert cancellation.cancelled
        with pytest.raises(TurnCancelled):
            await turn

    assert approvals.pending(session_id) == [], "the future outlived the turn"
    events = await application.service.history(session_id)
    failures = [e for e in events if isinstance(e, TurnFailed)]
    assert failures and failures[-1].cancelled
    assert searches.queries == []


async def test_cancelling_a_session_directly_frees_its_approvals(
    build_application, searches, searching_model
):
    """`cancel` is the belt to the turn task's braces, for a caller that tears
    a session down without going through the supervisor."""
    approvals = WebApprovals()
    application, client = await _web(
        build_application, searching_model, _asking_policy(), approvals
    )
    async with client:
        session_id = await start_session(application.service)
        turn = asyncio.ensure_future(application.turns.run(session_id, "search please"))
        await _wait_for_pending(approvals, session_id)

        assert approvals.cancel(session_id) == 1
        with pytest.raises(TurnCancelled):
            await turn

    assert approvals.pending(session_id) == []


# --- gate context on the wire -------------------------------------------------


def _pending(request: ApprovalRequest) -> dict:
    from research_team.interfaces.web.approvals import PendingApproval

    return PendingApproval(id="p1", request=request, future=None).view()


def test_an_ordinary_approval_frame_is_unchanged_by_gate_context_existing():
    """Every client already parsing these must see exactly what it saw before."""
    view = _pending(
        ApprovalRequest(
            session_id=uuid4(),
            tool_name="web_search",
            args={"query": "x"},
            description="",
            allowed_decisions=("approve", "reject"),
        )
    )
    assert set(view) == {
        "id",
        "session_id",
        "tool_name",
        "args",
        "description",
        "allowed_decisions",
    }


def test_a_reviewed_gate_puts_its_findings_on_the_frame():
    view = _pending(
        ApprovalRequest(
            session_id=uuid4(),
            tool_name="advance_stage",
            args={"rationale": "done"},
            description="",
            allowed_decisions=("approve", "reject"),
            context={"stage": "s.one", "findings": []},
        )
    )
    assert view["context"] == {"stage": "s.one", "findings": []}
