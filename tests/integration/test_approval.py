"""Approval, end to end: from a policy that gates to events in the log.

The resume-loop tests already cover the executor in isolation. What these add
is the whole path -- service, executor, port, adapter -- and they assert on
recorded events rather than on anything printed, because the log is the only
thing that survives the process and the only thing an audit can read.

Nothing here touches the network: the search tool is built over a
`MockTransport`, and the composition root's own `build_search_tool` is
replaced so a configured instance never turns into a real request.
"""

from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import AIMessage

from research_team import composition
from research_team.infrastructure.agent.fetch import build_fetch_tool
from research_team.infrastructure.agent.search import build_search_tool
from research_team.interfaces.cli import TerminalApprovals, repl
from research_team.platform.shared.ports import (
    ApprovalDecision,
    ApprovalRequest,
)
from research_team.session.application.autonomy import FETCH_TOOL, AutonomyPolicy
from research_team.session.domain import (
    AutonomyChanged,
    ToolCallDecided,
    ToolResultRecorded,
)
from research_team.tenancy.application.grants import FetchGrant, GrantRegistry
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


class Fetches:
    """Records every URL the stubbed transport was asked for."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.urls.append(str(request.url))
        return httpx.Response(200, html="<html><body><p>a page.</p></body></html>")

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


@pytest.fixture
def fetches(monkeypatch) -> Fetches:
    """`fetch` built over a `MockTransport`, for the same reason `searches` is:
    Task 7's own wiring must be provable without ever reaching the network.
    """
    recorder = Fetches()

    def build(
        *,
        max_chars=None,
        max_bytes=None,
        client=None,
        recall=None,
        corpus=None,
        pages=None,
        grant=None,
        keep=None,
    ):
        # Mirrors `build_fetch_tool`'s signature and forwards every argument
        # rather than dropping it -- `grant` especially, since that is the
        # one this task adds and the one a silently-dropped stub would stop
        # testing. `keep` is forwarded on the same reasoning: it is only ever
        # non-None on the granted path this fixture exists to exercise, so a
        # stub that dropped it would leave the autonomous run's automatic
        # corpus save untested by exactly the tests that reach it.
        kwargs = {
            "client": recorder.client(),
            "recall": recall,
            "corpus": corpus,
            "pages": pages,
            "grant": grant,
            "keep": keep,
        }
        if max_chars is not None:
            kwargs["max_chars"] = max_chars
        if max_bytes is not None:
            kwargs["max_bytes"] = max_bytes
        return build_fetch_tool(**kwargs)

    monkeypatch.setattr(composition, "build_fetch_tool", build)
    return recorder


def _fetch_asking_policy() -> AutonomyPolicy:
    policy = AutonomyPolicy(default="auto")
    policy.set(FETCH_TOOL, "ask")
    return policy


def _fetching_model(url: str) -> ToolAwareFakeChatModel:
    """Asks to fetch one URL, then replies."""
    return ToolAwareFakeChatModel(
        responses=[
            AIMessage(
                content="",
                id="a1",
                tool_calls=[{"name": FETCH_TOOL, "args": {"url": url}, "id": "t1"}],
            ),
            AIMessage(content="done", id="a2"),
        ]
    )


def _fetch_results(events) -> list[ToolResultRecorded]:
    return [
        event
        for event in events
        if isinstance(event, ToolResultRecorded)
        and "a page." in str(event.message.get("data", {}).get("content", ""))
    ]


# ---------------- the grant: gate and tool wired together ----------------


async def test_a_granted_fetch_is_not_decided_at_all(build_application, fetches):
    """The negative of `test_an_approved_search_is_decided_before_it_is_run`:
    a covered fetch under a grant never reaches a human, so there is no
    `ToolCallDecided` in the log at all -- not one that approves it, one that
    simply never happens.
    """
    grants = GrantRegistry()
    application = await build_application(
        model=_fetching_model("https://a.example/page"),
        policy=_fetch_asking_policy(),
        grants=grants,
    )
    session_id = await start_session(application.service)
    # Registered directly, standing in for the driver's registration
    # (Task 7's other half): the gate and the tool consult the registry, not
    # how something got into it.
    grants.register(
        session_id,
        FetchGrant(run_id=session_id, hosts=frozenset({"a.example"}), budget=1),
    )

    await application.service.run_turn(session_id, "read that page")

    events = await application.service.history(session_id)
    kinds = _types(events)
    assert "ToolCallDecided" not in kinds, kinds
    assert _fetch_results(events), "the granted fetch left no result in the log"
    assert fetches.urls == ["https://a.example/page"]


async def test_a_fetch_to_a_disallowed_host_under_a_grant_is_still_decided(
    build_application, fetches
):
    """Scope holds regardless of the grant: a host it does not name still
    goes to a human, the same as an ungranted run."""
    port = FixedPort(ApprovalDecision("approve"))
    grants = GrantRegistry()
    application = await build_application(
        model=_fetching_model("https://evil.example/page"),
        policy=_fetch_asking_policy(),
        approvals=port,
        grants=grants,
    )
    session_id = await start_session(application.service)
    grants.register(
        session_id,
        FetchGrant(run_id=session_id, hosts=frozenset({"a.example"}), budget=1),
    )

    await application.service.run_turn(session_id, "read that page")

    events = await application.service.history(session_id)
    assert "ToolCallDecided" in _types(events)
    assert fetches.urls == ["https://evil.example/page"]


async def test_a_run_with_no_grant_still_asks_a_human_for_fetch(build_application, fetches):
    """Today's behaviour, unchanged: no registry entry for this session at
    all, so `fetch` is decided exactly as it always was."""
    port = FixedPort(ApprovalDecision("approve"))
    application = await build_application(
        model=_fetching_model("https://a.example/page"),
        policy=_fetch_asking_policy(),
        approvals=port,
    )
    session_id = await start_session(application.service)

    await application.service.run_turn(session_id, "read that page")

    events = await application.service.history(session_id)
    assert "ToolCallDecided" in _types(events)
    assert fetches.urls == ["https://a.example/page"]


def _mixed_batch_model(covered_url: str, uncovered_url: str) -> ToolAwareFakeChatModel:
    """One assistant message with two `fetch` calls: one the grant covers,
    one it does not -- the exact shape that crashed the turn before the
    id-keyed reservation fix (see `test_a_mixed_batch...` below)."""
    return ToolAwareFakeChatModel(
        responses=[
            AIMessage(
                content="",
                id="a1",
                tool_calls=[
                    {"name": FETCH_TOOL, "args": {"url": covered_url}, "id": "t1"},
                    {"name": FETCH_TOOL, "args": {"url": uncovered_url}, "id": "t2"},
                ],
            ),
            AIMessage(content="done", id="a2"),
        ]
    )


async def test_a_covered_and_an_uncovered_fetch_in_one_message_do_not_crash_the_turn(
    build_application, fetches
):
    """The Critical a whole-branch review reproduced and traced to langgraph
    re-executing `after_model` on resume: `interrupt()` raises
    `GraphInterrupt`, and `Command(resume=...)` re-walks the *whole* message's
    tool calls, calling `when` (and, before the fix, `reserve()`) again for
    the covered call even though it already holds a claim. On a budget of
    one, the covered call's second evaluation used to see no room left,
    flip to refused, and leave one human decision answering two now-hanging
    calls -- `ValueError: Number of human decisions (1) does not match
    number of hanging tool calls (2)` raised inside langchain, failing the
    turn (and, in an auto run, burning `error_rate`, a granted run failing
    *because* it was granted).

    This drives the real `HumanInTheLoopMiddleware`, the real resume loop in
    `DeepAgentTurnExecutor._invoke`, and the real `FetchGrant` over a budget
    of exactly one -- the tightest case, and the one that crashed.
    """
    port = FixedPort(ApprovalDecision("approve"))
    grants = GrantRegistry()
    application = await build_application(
        model=_mixed_batch_model("https://a.example/page", "https://evil.example/page"),
        policy=_fetch_asking_policy(),
        approvals=port,
        grants=grants,
    )
    session_id = await start_session(application.service)
    grants.register(
        session_id,
        FetchGrant(run_id=session_id, hosts=frozenset({"a.example"}), budget=1),
    )

    # No exception: this is the assertion. Before the fix this raised
    # ValueError from inside langchain's HumanInTheLoopMiddleware.
    await application.service.run_turn(session_id, "read both pages")

    events = await application.service.history(session_id)
    # Exactly one call went to the human -- the uncovered one. The covered
    # call was never interrupted, on either evaluation.
    decisions = [e for e in events if isinstance(e, ToolCallDecided)]
    assert len(decisions) == 1
    assert decisions[0].args["url"] == "https://evil.example/page"
    # Both pages were actually fetched: the covered one via the grant, the
    # uncovered one via the human's approval.
    assert sorted(fetches.urls) == [
        "https://a.example/page",
        "https://evil.example/page",
    ]


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
