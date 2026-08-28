"""Middleware on the executor: what it may change, and what it must not.

These tests are about the seam middleware arrives through -- the executor
rebuilds its agent on every turn, so middleware has to be resolved on every turn
too, and two things that already work must survive being wrapped: the prose
stream a person is watching, and the approval interrupt a person is answering.

Nothing here reaches a network. The search tool exists only so there is a
*gated* tool to argue about; its transport is a mock.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import httpx
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from research_team.application import ApprovalDecision, ApprovalRefused, AutonomyPolicy
from research_team.application.ports import ActivityDelta
from research_team.domain import Session, SessionPurpose, StartSession
from research_team.infrastructure.agent.deep_agent import DeepAgentTurnExecutor
from research_team.infrastructure.agent.search import build_search_tool
from tests.conftest import ToolAwareFakeChatModel

PAYLOAD = {"results": [{"title": "Hit", "url": "https://a.example", "content": "A snippet."}]}


class Recording(AgentMiddleware):
    """A middleware that only counts, so "was it installed" is answerable."""

    calls: int = 0

    @property
    def name(self) -> str:
        return "recording"

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        Recording.calls += 1
        return await handler(request)


class ScriptedApprovals:
    def __init__(self, decision: ApprovalDecision | None = None) -> None:
        self._decision = decision or ApprovalDecision("reject")
        self.seen: list[Any] = []

    async def decide(self, request: Any) -> ApprovalDecision:
        self.seen.append(request)
        return self._decision


@dataclass
class ProviderSpy:
    """A per-turn middleware provider that records what it was asked."""

    middleware: tuple[AgentMiddleware, ...] = ()
    sessions: list[UUID] = field(default_factory=list)

    async def __call__(self, session: Session) -> tuple[AgentMiddleware, ...]:
        self.sessions.append(session.aggregate_id)
        return self.middleware


def _session() -> Session:
    session = Session(uuid4())
    session.execute(
        StartSession(
            session_id=session.aggregate_id,
            system_prompt="be brief",
            model_name="fake",
            project_id=uuid4(),
            purpose=SessionPurpose.CHAT,
        )
    )
    return session


def _search_tool() -> Any:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=PAYLOAD))
    )
    return build_search_tool("http://searx.local", limit=5, client=client)


def _searching_model(model_cls: type = ToolAwareFakeChatModel) -> Any:
    return model_cls(
        responses=[
            AIMessage(
                content="",
                id="a1",
                tool_calls=[{"name": "web_search", "args": {"query": "q"}, "id": "t1"}],
            ),
            AIMessage(content="done", id="a2"),
        ]
    )


async def _run(executor: DeepAgentTurnExecutor, session: Session) -> Any:
    return await executor.execute(
        session,
        messages=[executor.encode_user_message("hi")],
        system_prompt="be brief",
    )


async def test_an_executor_with_no_middleware_runs_a_turn_unchanged():
    """The default has to be inert, or every existing caller changes behaviour."""
    executor = DeepAgentTurnExecutor(
        ToolAwareFakeChatModel(responses=[AIMessage(content="the reply", id="a1")])
    )
    assert (await _run(executor, _session())).reply_text == "the reply"


async def test_static_middleware_wraps_the_model_call():
    Recording.calls = 0
    executor = DeepAgentTurnExecutor(
        ToolAwareFakeChatModel(responses=[AIMessage(content="hi", id="a1")]),
        middleware=(Recording(),),
    )
    await _run(executor, _session())
    assert Recording.calls == 1


async def test_the_provider_is_consulted_once_per_turn():
    """Stage can change between turns, so a provider asked once would go stale."""
    spy = ProviderSpy()
    session = _session()
    executor = DeepAgentTurnExecutor(
        ToolAwareFakeChatModel(
            responses=[AIMessage(content="a", id="a1"), AIMessage(content="b", id="a2")]
        ),
        middleware_provider=spy,
    )
    await _run(executor, session)
    await _run(executor, session)
    assert spy.sessions == [session.aggregate_id, session.aggregate_id]


async def test_provided_middleware_wraps_the_model_call():
    Recording.calls = 0
    executor = DeepAgentTurnExecutor(
        ToolAwareFakeChatModel(responses=[AIMessage(content="hi", id="a1")]),
        middleware_provider=ProviderSpy(middleware=(Recording(),)),
    )
    await _run(executor, _session())
    assert Recording.calls == 1


async def test_a_per_turn_tool_shadows_a_registered_tool_of_the_same_name():
    """The per-turn tool must replace the registered one, not sit beside it.

    Both tools below are named `web_search`; the registered one records a
    call and raises if reached, the per-turn one answers. If `_invoke` ever
    goes back to appending (`[*self._tools, *await self._resolved_tools(...)]`)
    rather than shadowing, langgraph would bind two tools of one name -- and
    whichever the model happened to reach could be either, including the one
    that raises. This asserts the outcome as well as the identity: the
    registered tool must never run.
    """
    registered_calls: list[str] = []

    @tool("web_search")
    def registered(query: str) -> str:
        """The registered tool -- must be shadowed, never invoked."""
        registered_calls.append(query)
        raise AssertionError("the shadowed registered tool must never run")

    @tool("web_search")
    def per_turn(query: str) -> str:
        """The per-turn tool -- must win over the registered one."""
        return "shadow-response"

    async def provide_tools(session: Session) -> tuple[Any, ...]:
        return (per_turn,)

    model = _searching_model()
    executor = DeepAgentTurnExecutor(
        model,
        tools=(registered,),
        tools_provider=provide_tools,
    )
    await _run(executor, _session())
    assert registered_calls == []


async def test_prose_still_streams_with_middleware_installed():
    """Middleware nodes are named `<name>.before_model`, never `model`.

    `to_activity_delta` discriminates on exactly that, so a middleware whose
    node happened to be called `model` would silently double the reply in the
    browser. Pinned rather than assumed.
    """
    executor = DeepAgentTurnExecutor(
        ToolAwareFakeChatModel(responses=[AIMessage(content="the streamed reply", id="a1")]),
        middleware=(Recording(),),
    )
    seen: list[Any] = []
    await executor.execute(
        _session(),
        messages=[executor.encode_user_message("hi")],
        system_prompt="be brief",
        on_activity=seen.append,
    )
    deltas = [note for note in seen if isinstance(note, ActivityDelta)]
    assert deltas, "expected at least one prose delta"
    assert "".join(delta.text for delta in deltas) == "the streamed reply"


async def test_a_gated_tool_still_interrupts_with_middleware_installed():
    """Wrapping the model call must not swallow the HITL interrupt.

    The interrupt is raised from inside the tool node, below whatever
    `awrap_model_call` wraps; a middleware that resolved the graph differently
    would let the call through unasked, and the only visible symptom would be a
    tool running that a person was supposed to approve.
    """
    approvals = ScriptedApprovals(ApprovalDecision("approve"))
    policy = AutonomyPolicy()
    policy.set("web_search", "ask")
    executor = DeepAgentTurnExecutor(
        _searching_model(),
        tools=(_search_tool(),),
        policy=policy,
        approvals=approvals,
        middleware=(Recording(),),
    )
    await _run(executor, _session())
    assert [request.tool_name for request in approvals.seen] == ["web_search"]


def _gated_executor(approvals: Any) -> DeepAgentTurnExecutor:
    """An executor whose one gated tool is `web_search`, floored at `ask`."""
    policy = AutonomyPolicy()
    policy.set("web_search", "ask")
    return DeepAgentTurnExecutor(
        _searching_model(),
        tools=(_search_tool(),),
        policy=policy,
        approvals=approvals,
    )


class RefusingApprovals:
    """An `ApprovalPort` that raises `ApprovalRefused` rather than ever
    returning a decision -- what `WebApprovals.decide` does when an
    unattended session's timeout wins. Standing in for it here means this
    behaviour is asserted against the `ApprovalPort` contract, not against
    `WebApprovals`'s own internals a second time."""

    def __init__(self, message: str = "nobody answered in time") -> None:
        self._message = message
        self.seen: list[Any] = []

    async def decide(self, request: Any) -> ApprovalDecision:
        self.seen.append(request)
        raise ApprovalRefused(self._message)


async def test_a_ports_refusal_is_recorded_as_policy_deciding_not_a_human():
    """The invariant this test exists to protect: a timeout is not a person.

    `_apply` stamps every `ApprovalDecision` it receives with
    `decided_by="human"`, which is correct because every `ApprovalDecision`
    a port returns is, by the port's own contract, what a human chose. A
    port that instead raises `ApprovalRefused` is explicitly saying no human
    chose anything -- and if a future refactor routed that exception through
    `_apply` anyway (or turned it back into an ordinary reject decision), this
    is the test that would catch a rejection nobody made getting logged as
    one a person made.
    """
    approvals = RefusingApprovals()
    session = _session()

    await _run(_gated_executor(approvals), session)

    [decided] = [
        event
        for event in session.uncommitted_events
        if type(event).__name__ == "ToolCallDecided"
    ]
    assert decided.decision == "reject"
    assert decided.decided_by == "policy"
    assert decided.decided_by != "human"


async def test_a_ports_refusal_still_lets_the_turn_finish():
    """The turn must read the refusal and continue, not unwind into an
    unhandled exception -- the same requirement `_decide`'s `deny` arm and
    harness-refusal arm already meet."""
    approvals = RefusingApprovals("timed out waiting for a person")

    result = await _run(_gated_executor(approvals), _session())

    assert "done" in result.reply_text
