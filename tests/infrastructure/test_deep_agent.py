"""Middleware on the executor: what it may change, and what it must not.

`StageMiddleware` is tested in isolation next door. What these tests are about
is the seam it arrives through -- the executor rebuilds its agent on every turn,
so middleware has to be resolved on every turn too, and two things that already
work must survive being wrapped: the prose stream a person is watching, and the
approval interrupt a person is answering.

Nothing here reaches a network. The search tool exists only so there is a
*gated* tool to argue about; its transport is a mock.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import httpx
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage

from research_team.application import ApprovalDecision, AutonomyPolicy
from research_team.application.ports import ActivityDelta, GateReview
from research_team.domain import CodingSession, StartSession
from research_team.infrastructure.agent.deep_agent import DeepAgentTurnExecutor
from research_team.infrastructure.agent.search import build_search_tool
from research_team.infrastructure.agent.stage_middleware import StageMiddleware
from tests.conftest import ToolAwareFakeChatModel

PAYLOAD = {"results": [{"title": "Hit", "url": "https://a.example", "content": "A snippet."}]}


@dataclass(frozen=True)
class FakeStage:
    """The three fields `StageLike` asks for, and nothing else."""

    id: str
    name: str
    tools: tuple[str, ...]


class ToolRecordingChatModel(ToolAwareFakeChatModel):
    """Remembers what it was bound, which is the only way to see the filter work.

    The tools reaching `bind_tools` are the tools the model can call; asserting
    on the executor's registered set instead would pass no matter what the
    middleware did.
    """

    seen: list[list[str]] = []

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ToolRecordingChatModel":
        self.seen.append([getattr(tool, "name", str(tool)) for tool in tools])
        return self

    @property
    def last_bound(self) -> list[str]:
        return self.seen[-1] if self.seen else []


class PromptRecordingChatModel(ToolAwareFakeChatModel):
    """Remembers what it was sent, so the appended stage block is observable."""

    prompts: list[str] = []

    def _generate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ):
        self.prompts.append("\n".join(str(message.content) for message in messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


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

    async def __call__(self, session: CodingSession) -> tuple[AgentMiddleware, ...]:
        self.sessions.append(session.aggregate_id)
        return self.middleware


def _session() -> CodingSession:
    session = CodingSession(uuid4())
    session.execute(
        StartSession(
            session_id=session.aggregate_id,
            system_prompt="be brief",
            model_name="fake",
            project_id=uuid4(),
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


async def _run(executor: DeepAgentTurnExecutor, session: CodingSession) -> Any:
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


async def test_a_stage_hides_a_registered_tool_from_the_model():
    """The whole point: registered is not the same as callable."""
    model = ToolRecordingChatModel(responses=[AIMessage(content="done", id="a1")])
    stage = FakeStage(id="s.read", name="Read", tools=("list_sources",))
    executor = DeepAgentTurnExecutor(
        model,
        tools=(_search_tool(),),
        middleware=(StageMiddleware(stage, managed_tools=("web_search", "list_sources")),),
    )
    await _run(executor, _session())
    assert "web_search" not in model.last_bound


async def test_a_tool_no_stage_claims_survives_the_filter():
    """A gate that hid tools nobody had an opinion about would be overreaching."""
    model = ToolRecordingChatModel(responses=[AIMessage(content="done", id="a1")])
    stage = FakeStage(id="s.read", name="Read", tools=())
    executor = DeepAgentTurnExecutor(
        model,
        tools=(_search_tool(),),
        middleware=(StageMiddleware(stage, managed_tools=("list_sources",)),),
    )
    await _run(executor, _session())
    assert "web_search" in model.last_bound


async def test_the_builtin_filesystem_tools_survive_a_stage():
    model = ToolRecordingChatModel(responses=[AIMessage(content="done", id="a1")])
    stage = FakeStage(id="s.read", name="Read", tools=())
    executor = DeepAgentTurnExecutor(
        model,
        middleware=(StageMiddleware(stage, managed_tools=("write_file", "ls")),),
    )
    await _run(executor, _session())
    assert {"write_file", "ls"} <= set(model.last_bound)


async def test_the_stage_block_is_appended_to_the_system_prompt():
    """Appended, not substituted -- the turn's own prompt has to survive."""
    model = PromptRecordingChatModel(responses=[AIMessage(content="done", id="a1")])
    stage = FakeStage(id="s.read", name="Read the corpus", tools=())
    executor = DeepAgentTurnExecutor(
        model, middleware=(StageMiddleware(stage, managed_tools=()),)
    )
    await executor.execute(
        _session(),
        messages=[executor.encode_user_message("hi")],
        system_prompt="be brief",
    )
    [sent] = model.prompts
    assert "be brief" in sent
    assert "Read the corpus" in sent
    assert "s.read" in sent


async def test_prose_still_streams_with_middleware_installed():
    """Middleware nodes are named `<name>.before_model`, never `model`.

    `to_activity_delta` discriminates on exactly that, so a middleware whose
    node happened to be called `model` would silently double the reply in the
    browser. Pinned rather than assumed.
    """
    stage = FakeStage(id="s.read", name="Read", tools=())
    executor = DeepAgentTurnExecutor(
        ToolAwareFakeChatModel(responses=[AIMessage(content="the streamed reply", id="a1")]),
        middleware=(StageMiddleware(stage, managed_tools=("web_search",)),),
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


async def test_a_gated_tool_the_stage_allows_still_interrupts():
    """Stage filtering runs first; HITL gates whatever survives it."""
    approvals = ScriptedApprovals(ApprovalDecision("approve"))
    stage = FakeStage(id="s.search", name="Search", tools=("web_search",))
    policy = AutonomyPolicy()
    policy.set("web_search", "ask")
    executor = DeepAgentTurnExecutor(
        _searching_model(),
        tools=(_search_tool(),),
        policy=policy,
        approvals=approvals,
        middleware=(StageMiddleware(stage, managed_tools=("web_search",)),),
    )
    await _run(executor, _session())
    assert [request.tool_name for request in approvals.seen] == ["web_search"]


async def test_a_gated_tool_the_stage_hides_is_never_bound():
    """Hidden means the model cannot ask, so the approval is never posed."""
    approvals = ScriptedApprovals(ApprovalDecision("approve"))
    model = ToolRecordingChatModel(responses=[AIMessage(content="done", id="a1")])
    stage = FakeStage(id="s.read", name="Read", tools=())
    policy = AutonomyPolicy()
    policy.set("web_search", "ask")
    executor = DeepAgentTurnExecutor(
        model,
        tools=(_search_tool(),),
        policy=policy,
        approvals=approvals,
        middleware=(StageMiddleware(stage, managed_tools=("web_search",)),),
    )
    await _run(executor, _session())
    assert "web_search" not in model.last_bound
    assert approvals.seen == []


# --- the gate reviewer -------------------------------------------------------


def _gated_executor(approvals: Any, reviewer: Any) -> DeepAgentTurnExecutor:
    policy = AutonomyPolicy()
    policy.set("web_search", "ask")
    return DeepAgentTurnExecutor(
        _searching_model(),
        tools=(_search_tool(),),
        policy=policy,
        approvals=approvals,
        gate_reviewer=reviewer,
    )


async def test_the_reviewers_context_reaches_the_approval():
    async def reviewer(session: CodingSession, name: str, args: dict) -> GateReview:
        return GateReview(context={"stage": "s.one", "findings": []})

    approvals = ScriptedApprovals(ApprovalDecision("approve"))
    await _run(_gated_executor(approvals, reviewer), _session())
    assert approvals.seen[0].context == {"stage": "s.one", "findings": []}


async def test_a_refusal_settles_the_call_without_asking_anybody():
    """An invariant failure is not a judgement, so there is nobody to put it to."""

    async def reviewer(session: CodingSession, name: str, args: dict) -> GateReview:
        return GateReview(context={}, refusal="a harness invariant failed")

    approvals = ScriptedApprovals(ApprovalDecision("approve"))
    await _run(_gated_executor(approvals, reviewer), _session())
    assert approvals.seen == []


async def test_a_refusal_is_recorded_as_the_harness_deciding():
    """Not `policy`, which permitted the call, and not `human`, who never saw it."""

    async def reviewer(session: CodingSession, name: str, args: dict) -> GateReview:
        return GateReview(context={}, refusal="a harness invariant failed")

    session = _session()
    await _run(_gated_executor(ScriptedApprovals(), reviewer), session)
    [decided] = [
        event
        for event in session.uncommitted_events
        if type(event).__name__ == "ToolCallDecided"
    ]
    assert (decided.decision, decided.decided_by) == ("reject", "harness")


async def test_a_reviewer_that_raises_still_lets_the_approval_be_posed():
    """A bug in the advice must not cost a call the model already earned."""

    async def reviewer(session: CodingSession, name: str, args: dict) -> GateReview:
        raise RuntimeError("the reviewer is broken")

    approvals = ScriptedApprovals(ApprovalDecision("approve"))
    await _run(_gated_executor(approvals, reviewer), _session())
    assert [request.tool_name for request in approvals.seen] == ["web_search"]
    assert approvals.seen[0].context is None


async def test_no_reviewer_means_no_context_and_no_change():
    approvals = ScriptedApprovals(ApprovalDecision("approve"))
    await _run(_gated_executor(approvals, None), _session())
    assert approvals.seen[0].context is None
