"""The resume loop: what happens when a gated tool call is interrupted.

The failure mode this guards is a miscount. All of one AI message's
interrupted calls arrive as a single interrupt carrying parallel lists, and
langchain raises if the number of decisions coming back does not match. A
loop that resumes more than once must not lose track across passes.
"""

from uuid import uuid4

import httpx
from hypothesis import given, settings
from hypothesis import strategies as st
from langchain_core.messages import AIMessage

from research_team.application import ApprovalDecision, AutonomyPolicy
from research_team.domain import CodingSession, StartSession, ToolCallDecided
from research_team.infrastructure.agent.deep_agent import DeepAgentTurnExecutor
from research_team.infrastructure.agent.search import build_search_tool
from tests.conftest import ToolAwareFakeChatModel

PAYLOAD = {"results": [{"title": "Hit", "url": "https://a.example", "content": "A snippet."}]}


class ScriptedApprovals:
    """An ApprovalPort that answers from a list and records what it was asked."""

    def __init__(self, decisions):
        self._decisions = list(decisions)
        self.seen = []

    async def decide(self, request):
        self.seen.append(request)
        return self._decisions.pop(0) if self._decisions else ApprovalDecision("approve")


class Searches:
    """Records every query the stubbed SearXNG transport is asked for."""

    def __init__(self):
        self.queries = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.queries.append(request.url.params.get("q"))
        return httpx.Response(200, json=PAYLOAD)

    def tool(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        return build_search_tool("http://searx.local", limit=5, client=client)


def _session() -> CodingSession:
    session = CodingSession(uuid4())
    session.execute(
        StartSession(system_prompt="You are a coding agent.", model_name="test-model")
    )
    return session


def _searching_model(queries: list[str]) -> ToolAwareFakeChatModel:
    """One AI message asking for every query at once, then a plain reply.

    A single message is the interesting shape: langchain folds all of its
    gated calls into one interrupt carrying parallel lists.
    """
    return ToolAwareFakeChatModel(
        responses=[
            AIMessage(
                content="",
                id="a1",
                tool_calls=[
                    {"name": "web_search", "args": {"query": query}, "id": f"t{index}"}
                    for index, query in enumerate(queries)
                ],
            ),
            AIMessage(content="done", id="a2"),
        ]
    )


async def _run(session, model, tool, policy, approvals=None, on_activity=None):
    executor = DeepAgentTurnExecutor(model, tools=[tool], policy=policy, approvals=approvals)
    return await executor.execute(
        session,
        messages=[executor.encode_user_message("search for something")],
        system_prompt="You are a coding agent.",
        on_activity=on_activity,
    )


def _decisions(session) -> list[ToolCallDecided]:
    return [e for e in session.uncommitted_events if isinstance(e, ToolCallDecided)]


async def test_an_approved_search_runs():
    """policy=ask, human approves -> the tool executes and its result is recorded."""
    session = _session()
    searches = Searches()
    policy = AutonomyPolicy(default="auto")
    policy.set("web_search", "ask")
    approvals = ScriptedApprovals([ApprovalDecision("approve")])

    result = await _run(
        session, _searching_model(["event sourcing"]), searches.tool(), policy, approvals
    )

    assert searches.queries == ["event sourcing"]
    assert [(d.tool_name, d.decision, d.decided_by) for d in _decisions(session)] == [
        ("web_search", "approve", "human")
    ]
    assert any("Hit" in str(m) for m in result.messages)


async def test_a_rejected_search_does_not_run_and_the_model_is_told():
    """policy=ask, human rejects -> no network call, a ToolMessage explains."""
    session = _session()
    searches = Searches()
    policy = AutonomyPolicy(default="auto")
    policy.set("web_search", "ask")
    approvals = ScriptedApprovals([ApprovalDecision("reject", message="not now")])

    result = await _run(
        session, _searching_model(["event sourcing"]), searches.tool(), policy, approvals
    )

    assert searches.queries == []
    assert [(d.decision, d.decided_by) for d in _decisions(session)] == [("reject", "human")]
    assert any("not now" in str(m) for m in result.messages)


async def test_a_denied_search_never_reaches_the_human():
    """policy=deny -> approvals.seen is empty, and a ToolCallDecided is
    recorded with decided_by='policy'."""
    session = _session()
    searches = Searches()
    policy = AutonomyPolicy(default="auto")
    policy.set("web_search", "deny")
    approvals = ScriptedApprovals([])

    await _run(
        session, _searching_model(["event sourcing"]), searches.tool(), policy, approvals
    )

    assert approvals.seen == []
    assert searches.queries == []
    assert [(d.decision, d.decided_by) for d in _decisions(session)] == [("reject", "policy")]


async def test_an_edited_call_runs_with_the_amended_arguments():
    """policy=ask, human edits the query -> the tool sees the new query and
    ToolCallDecided.edited_args carries it."""
    session = _session()
    searches = Searches()
    policy = AutonomyPolicy(default="auto")
    policy.set("web_search", "ask")
    approvals = ScriptedApprovals([ApprovalDecision("edit", edited_args={"query": "CQRS"})])

    await _run(
        session, _searching_model(["event sourcing"]), searches.tool(), policy, approvals
    )

    assert searches.queries == ["CQRS"]
    decided = _decisions(session)
    assert [(d.decision, d.decided_by) for d in decided] == [("edit", "human")]
    assert decided[0].args == {"query": "event sourcing"}
    assert decided[0].edited_args == {"query": "CQRS"}


async def test_an_auto_tool_is_never_interrupted():
    """policy=auto -> approvals.seen is empty and no ToolCallDecided appears."""
    session = _session()
    searches = Searches()
    approvals = ScriptedApprovals([])

    await _run(
        session,
        _searching_model(["event sourcing"]),
        searches.tool(),
        AutonomyPolicy(default="auto"),
        approvals,
    )

    assert approvals.seen == []
    assert searches.queries == ["event sourcing"]
    assert _decisions(session) == []


async def test_activity_is_not_re_reported_across_resumed_passes():
    """`reported` survives the loop, or the caller sees every line twice."""
    session = _session()
    searches = Searches()
    policy = AutonomyPolicy(default="auto")
    policy.set("web_search", "ask")
    notes: list = []

    await _run(
        session,
        _searching_model(["event sourcing"]),
        searches.tool(),
        policy,
        ScriptedApprovals([ApprovalDecision("approve")]),
        on_activity=notes.append,
    )

    # Deduplicate by message_id for ActivityMessage objects, or use identity for others.
    # The test ensures that the reported variable survives the loop and prevents
    # re-reporting of the same activity.
    seen_ids = set()
    for note in notes:
        note_id = getattr(note, "message_id", id(note))
        assert note_id not in seen_ids, f"activity was reported twice: {note}"
        seen_ids.add(note_id)


async def test_a_level_raised_mid_turn_gates_the_next_call():
    """Two search calls in one turn. The port sets the policy to `deny` while
    answering the first. The second must not reach the human -- this is the
    whole point of a live policy object."""
    session = _session()
    searches = Searches()
    policy = AutonomyPolicy(default="auto")
    policy.set("web_search", "ask")

    class Tightening(ScriptedApprovals):
        async def decide(self, request):
            policy.set("web_search", "deny")
            return await super().decide(request)

    approvals = Tightening([ApprovalDecision("approve")])

    await _run(
        session, _searching_model(["first", "second"]), searches.tool(), policy, approvals
    )

    assert len(approvals.seen) == 1, "the tightened policy still reached the human"
    assert searches.queries == ["first"]
    assert [(d.decision, d.decided_by) for d in _decisions(session)] == [
        ("approve", "human"),
        ("reject", "policy"),
    ]


@settings(deadline=None, max_examples=25)
@given(st.lists(st.sampled_from(["approve", "reject"]), min_size=1, max_size=6))
async def test_every_interrupted_call_gets_exactly_one_decision(decisions):
    """For any sequence of decisions the loop terminates, and exactly one
    ToolCallDecided is recorded per interrupted call -- no double-counting
    across resumed passes, no dropped decision."""
    session = _session()
    searches = Searches()
    policy = AutonomyPolicy(default="auto")
    policy.set("web_search", "ask")
    approvals = ScriptedApprovals([ApprovalDecision(kind) for kind in decisions])
    queries = [f"q{index}" for index in range(len(decisions))]

    await _run(session, _searching_model(queries), searches.tool(), policy, approvals)

    recorded = _decisions(session)
    assert len(recorded) == len(decisions)
    assert [d.decision for d in recorded] == decisions
    assert [r.args["query"] for r in approvals.seen] == queries
