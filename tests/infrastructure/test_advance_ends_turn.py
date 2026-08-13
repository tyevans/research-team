"""Crossing a stage boundary ends the turn that crossed it.

Two reasons, and they are the whole of why this file exists. A turn is what
makes its events durable -- `run_turn` appends once, at the end -- so a stage
advanced in the middle of a turn is a transition whose durability depends on
everything after it succeeding. And a stage boundary exists to break the
conversation: a stage that carries on in the same context inherits the previous
stage's messages, which is precisely what the boundary is for.

The distinction these tests are really about is refused-versus-accepted. A
refused advance must *not* end the turn: the model has feedback to act on and
no way to act on it if the turn is over. So the same tool has two exits, and
only one of them stops the graph.
"""

from uuid import uuid4

from langchain_core.messages import AIMessage

from research_team.application import ApprovalDecision, AutonomyPolicy
from research_team.application.ports import GateReview
from research_team.domain import Session, StartSession
from research_team.domain.project import (
    AdvanceStage,
    ProjectCreated,
    ProjectState,
    ProjectWorkflowSelected,
    decide,
    evolve,
    initial_state,
)
from research_team.infrastructure.agent.deep_agent import DeepAgentTurnExecutor
from research_team.infrastructure.agent.workflow_tools import (
    EndTurnOnStageAdvance,
    build_workflow_tools,
)
from research_team.workflows import hybrid_default
from tests.conftest import ToolAwareFakeChatModel


class FakeWorkflow:
    """One project's stage position, moved through the real domain rules.

    The real `decide`/`evolve` rather than a stub, for the reason
    `test_workflow_tools.py` gives: the refusals these tests care about are the
    domain's own, and a stub would test the messages the test wrote.
    """

    def __init__(self, state: ProjectState) -> None:
        self.state = state
        self.advances = 0

    async def project_state(self) -> ProjectState:
        return self.state

    async def advance(self, command: AdvanceStage) -> ProjectState:
        for event in decide(command, self.state):
            self.state = evolve(self.state, event)
        self.advances += 1
        return self.state


def _project(preset=hybrid_default) -> FakeWorkflow:
    project_id = uuid4()
    state = evolve(initial_state(), ProjectCreated(aggregate_id=project_id, name="research"))
    state = evolve(
        state,
        ProjectWorkflowSelected(
            aggregate_id=project_id, preset_id=preset.id, preset_version=preset.version
        ),
    )
    return FakeWorkflow(state)


def _session() -> Session:
    session = Session(uuid4())
    session.execute(
        StartSession(
            session_id=session.aggregate_id,
            system_prompt="You are a coding agent.",
            model_name="test-model",
            project_id=uuid4(),
        )
    )
    return session


AFTER_THE_ADVANCE = "and now the next stage's work"


def _advancing_model(rationale: str = "the framing artifacts are written and cited"):
    """Calls `advance_stage`, then -- if it is ever asked again -- keeps going.

    The second response is the defect made visible. A model that gets another
    turn of the graph after the tool has returned will say this, and a test
    that finds it in the transcript has found a stage advanced in the middle of
    a turn rather than at the end of one.
    """
    return ToolAwareFakeChatModel(
        responses=[
            AIMessage(
                content="",
                id="a1",
                tool_calls=[
                    {"name": "advance_stage", "args": {"rationale": rationale}, "id": "t0"}
                ],
            ),
            AIMessage(content=AFTER_THE_ADVANCE, id="a2"),
        ]
    )


class ScriptedApprovals:
    def __init__(self, decisions=()) -> None:
        self._decisions = list(decisions)
        self.seen: list = []

    async def decide(self, request):
        self.seen.append(request)
        return self._decisions.pop(0) if self._decisions else ApprovalDecision("approve")


async def _run(session, model, tools, *, approvals=None, gate_reviewer=None):
    policy = AutonomyPolicy(default="auto")
    executor = DeepAgentTurnExecutor(
        model,
        tools=list(tools),
        policy=policy,
        approvals=approvals if approvals is not None else ScriptedApprovals(),
        gate_reviewer=gate_reviewer,
        middleware=[EndTurnOnStageAdvance()],
    )
    return await executor.execute(
        session,
        messages=[executor.encode_user_message("finish this stage")],
        system_prompt="You are a coding agent.",
    )


def _kept_going(result) -> bool:
    return any(AFTER_THE_ADVANCE in str(message.payload) for message in result.messages)


async def test_an_approved_advance_ends_the_turn():
    """The model does not get another pass after the stage moves.

    Red before the fix: the tool returned prose, the graph looped back to the
    model, and `AFTER_THE_ADVANCE` appeared in the turn's recorded messages.
    """
    workflow = _project()
    session = _session()
    approvals = ScriptedApprovals([ApprovalDecision("approve")])

    result = await _run(
        session,
        _advancing_model(),
        build_workflow_tools(workflow, preset=hybrid_default),
        approvals=approvals,
    )

    assert workflow.advances == 1, "the advance did not happen; this tests the wrong thing"
    assert len(approvals.seen) == 1, "the floor did not put the advance to a human"
    assert not _kept_going(result), "the turn continued after the stage advanced"


async def test_the_advance_is_still_recorded_in_the_turn_that_ended():
    """Ending the turn must not cost the tool result.

    A `ToolMessage` for the call has to be in the transcript, or the next turn
    resumes from a history whose last AI message asked for a tool nobody
    answered -- which most providers reject outright.

    This passes with the change reverted: it is a guard against a fix that
    ended the turn by cutting the tool node short, not a demonstration of the
    defect.
    """
    workflow = _project()
    session = _session()

    result = await _run(
        session,
        _advancing_model(),
        build_workflow_tools(workflow, preset=hybrid_default),
        approvals=ScriptedApprovals([ApprovalDecision("approve")]),
    )

    tool_results = [message for message in result.messages if message.kind == "tool"]
    assert tool_results, "the advance left no tool result in the transcript"
    assert any("Advanced out of" in str(message.payload) for message in tool_results)


async def test_a_refused_advance_does_not_end_the_turn():
    """A harness refusal leaves the agent working, with the feedback delivered.

    This is the distinction the whole change turns on. The gate reviewer
    refuses before the human is consulted -- the `self_review_separation`
    shape -- and the model must get another pass to fix what was caught.

    Passes with the change reverted, like the three refusal tests after it:
    before the fix nothing ended any turn, so nothing could end the wrong one.
    They are here because an over-reaching fix is the likeliest way to get this
    wrong, and they are the only thing that would catch it.
    """
    workflow = _project()
    session = _session()

    async def refusing_gate(session, tool_name, args):
        return GateReview(context={}, refusal="Stage not advanced: an invariant failed.")

    result = await _run(
        session,
        _advancing_model(),
        build_workflow_tools(workflow, preset=hybrid_default),
        gate_reviewer=refusing_gate,
    )

    assert workflow.advances == 0
    assert _kept_going(result), "a refused advance ended the turn and stranded the agent"


async def test_a_human_rejected_advance_does_not_end_the_turn():
    """A human saying no is a refusal too, and the same rule applies."""
    workflow = _project()
    session = _session()

    result = await _run(
        session,
        _advancing_model(),
        build_workflow_tools(workflow, preset=hybrid_default),
        approvals=ScriptedApprovals([ApprovalDecision("reject", message="not yet")]),
    )

    assert workflow.advances == 0
    assert _kept_going(result), "a rejected advance ended the turn"


async def test_a_tool_level_refusal_does_not_end_the_turn():
    """An empty rationale is refused by the tool itself, before any command."""
    workflow = _project()
    session = _session()

    result = await _run(
        session,
        _advancing_model(rationale="   "),
        build_workflow_tools(workflow, preset=hybrid_default),
        approvals=ScriptedApprovals([ApprovalDecision("approve")]),
    )

    assert workflow.advances == 0
    assert _kept_going(result), "a refused-for-no-rationale advance ended the turn"


async def test_nothing_the_turn_wrote_is_durable_when_the_reviewer_is_asked():
    """The approval is posed against state that is still only in memory.

    Not a test of this change -- it passes with it reverted, and it documents
    a limitation rather than a fix. It is here because a comment in
    `composition.gate_review` claimed the opposite for some time ("the file is
    in the log and in the viewer immediately"), and a claim about durability is
    exactly the kind that nobody re-checks. If mid-turn committing is ever
    built, this test is what should fail and be rewritten.

    The mechanism is not subtle: `DeepAgentTurnExecutor` is constructed with no
    repository, so there is nothing it could commit through even in principle.
    Everything reaches the store in `SessionService._save_turn`, after the turn.
    """
    workflow = _project()
    session = _session()
    committed_at_decision: list[int] = []

    class Watching(ScriptedApprovals):
        async def decide(self, request):
            # `version` counts events the store has; `uncommitted_events` is
            # everything the turn has produced and not yet appended.
            committed_at_decision.append(len(session.uncommitted_events))
            return await super().decide(request)

    await _run(
        session,
        _advancing_model(),
        build_workflow_tools(workflow, preset=hybrid_default),
        approvals=Watching([ApprovalDecision("approve")]),
    )

    assert committed_at_decision, "the approval was never posed"
    assert committed_at_decision[0] > 0, (
        "the turn had produced no pending events at all; this no longer tests "
        "what it says it tests"
    )


async def test_a_sibling_call_in_the_same_step_still_runs_before_the_turn_ends():
    """`advance_stage` beside a `write_file`: the write happens, then it stops.

    The decision this pins is what becomes of work proposed alongside the
    advance. The tool node executes every call in the step before anything
    routes, so the write is already an event on the aggregate and its result is
    already in the transcript; what is given up is the model's chance to *read*
    that result, which it would have read in the next stage's shoes. Losing the
    write instead would be the worse answer and is what a fix that cut the tool
    node short would have done.
    """
    workflow = _project()
    session = _session()
    model = ToolAwareFakeChatModel(
        responses=[
            AIMessage(
                content="",
                id="a1",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {"file_path": "/course/00-note.md", "content": "last word"},
                        "id": "t0",
                    },
                    {
                        "name": "advance_stage",
                        "args": {"rationale": "the intake artifacts are written"},
                        "id": "t1",
                    },
                ],
            ),
            AIMessage(content=AFTER_THE_ADVANCE, id="a2"),
        ]
    )

    result = await _run(
        session,
        model,
        build_workflow_tools(workflow, preset=hybrid_default),
        approvals=ScriptedApprovals([ApprovalDecision("approve")]),
    )

    assert workflow.advances == 1
    assert session.state.files.get("/course/00-note.md"), "the sibling write was lost"
    assert not _kept_going(result), "the turn continued past the advance"
