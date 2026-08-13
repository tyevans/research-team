"""`advance_stage`, against a fake port that runs the real domain rules.

The fake folds `decide`/`evolve` rather than stubbing rejections, because the
whole point of this tool is that it does *not* own the ordering rules: the
interesting question is whether a real `CommandRejectedError` reaches the model
as prose it can act on, and a stub raising a message of its own would test the
message these tests wrote.

The recurring assertion is that a refusal keeps its specifics. "Could not
advance" is a dead end -- a model that is told the next stage is
`hybrid.step1.framing`, or that no workflow was ever selected, has somewhere to
go next.
"""

import re
from uuid import UUID, uuid4

import pytest
from eventsource import CommandRejectedError, DomainEvent

from research_team.application.autonomy import (
    ADVANCE_STAGE_TOOL,
    GATED_TOOLS,
    TOOL_FLOORS,
    AutonomyPolicy,
)
from research_team.domain.project import (
    AdvanceStage,
    ProjectCreated,
    ProjectDeleted,
    ProjectState,
    ProjectWorkflowSelected,
    decide,
    evolve,
    initial_state,
)
from research_team.domain.workflow import Preset
from research_team.infrastructure.agent.workflow_tools import build_workflow_tools
from research_team.workflows import hybrid_default, ubd_pure


def _created(project_id: UUID) -> ProjectState:
    return evolve(initial_state(), ProjectCreated(aggregate_id=project_id, name="research"))


def _with_workflow(project_id: UUID, preset: Preset = hybrid_default) -> ProjectState:
    return evolve(
        _created(project_id),
        ProjectWorkflowSelected(
            aggregate_id=project_id, preset_id=preset.id, preset_version=preset.version
        ),
    )


class FakeWorkflow:
    """One project's state, advanced through the real `decide`/`evolve` pair."""

    def __init__(self, state: ProjectState) -> None:
        self.state = state
        self.calls: list[AdvanceStage] = []

    async def project_state(self) -> ProjectState:
        return self.state

    async def advance(self, command: AdvanceStage) -> ProjectState:
        self.calls.append(command)
        events: list[DomainEvent] = decide(command, self.state)
        for event in events:
            self.state = evolve(self.state, event)
        return self.state


def _tool(port: FakeWorkflow, preset: Preset = hybrid_default):
    (advance,) = build_workflow_tools(port, preset=preset)
    return advance


async def _advance(port: FakeWorkflow, rationale: str, preset: Preset = hybrid_default) -> str:
    return await _tool(port, preset).ainvoke({"rationale": rationale})


def test_advance_stage_is_gated_and_floored_to_ask():
    """The floor is the whole design: the gate *is* the existing approval path.

    Pinned against `TOOL_FLOORS` and `AutonomyPolicy` together, because a
    constant in the dict that `level_for` never consults would look right and
    gate nothing.
    """
    assert ADVANCE_STAGE_TOOL in GATED_TOOLS
    assert TOOL_FLOORS[ADVANCE_STAGE_TOOL] == "ask"
    assert AutonomyPolicy(default="auto").level_for(ADVANCE_STAGE_TOOL) == "ask"


def test_a_deny_all_policy_still_denies_advancing():
    """A floor raises a default and never lowers one."""
    assert AutonomyPolicy(default="deny").level_for(ADVANCE_STAGE_TOOL) == "deny"


async def test_advancing_names_the_stage_left_the_stage_entered_and_its_purpose():
    port = FakeWorkflow(_with_workflow(uuid4()))

    answer = await _advance(port, "the intake is complete and every claim is cited")

    assert "tyler.step0.intake" in answer
    assert "hybrid.step1.framing" in answer
    assert "Context framing" in answer
    assert port.state.current_stage == "hybrid.step1.framing"


async def test_the_rationale_is_recorded_as_the_gate_decision():
    """An advance that cannot say why it was crossed is not a gate."""
    port = FakeWorkflow(_with_workflow(uuid4()))

    await _advance(port, "screening produced twelve cited verdicts")

    [command] = port.calls
    assert command.gate_decision == "screening produced twelve cited verdicts"
    assert command.to_stage == "hybrid.step1.framing"


async def test_an_empty_rationale_is_refused_without_touching_the_project():
    port = FakeWorkflow(_with_workflow(uuid4()))

    answer = await _advance(port, "   ")

    assert "rationale" in answer.lower()
    assert port.calls == []
    assert port.state.current_stage is None


async def test_successive_advances_read_the_stage_fresh():
    """State is fetched per call, not captured at build time.

    An agent can be approved for two advances in one turn, and a tool holding
    the state it was constructed with would compute the same `to_stage` twice
    and be rejected for skipping.
    """
    port = FakeWorkflow(_with_workflow(uuid4()))
    tool = _tool(port)

    await tool.ainvoke({"rationale": "intake complete"})
    answer = await tool.ainvoke({"rationale": "framing says this should be a course"})

    assert port.state.current_stage == "tyler.step1a.source_analysis"
    assert "tyler.step1a.source_analysis" in answer


async def test_a_project_with_no_workflow_gets_the_domains_own_refusal():
    port = FakeWorkflow(_created(uuid4()))

    answer = await _advance(port, "ready to move on")

    assert "no workflow" in answer.lower()
    assert port.state.current_stage is None


async def test_a_preset_disagreement_is_reported_naming_both_workflows():
    """The tool's preset and the project's can diverge; the domain says so."""
    port = FakeWorkflow(_with_workflow(uuid4(), hybrid_default))

    answer = await _advance(port, "ready", preset=ubd_pure)

    assert "hybrid.default" in answer
    assert "ubd.pure" in answer
    assert port.state.current_stage is None


async def test_a_deleted_project_refuses_and_says_so():
    project_id = uuid4()
    state = evolve(_with_workflow(project_id), ProjectDeleted(aggregate_id=project_id))
    port = FakeWorkflow(state)

    answer = await _advance(port, "ready")

    assert "deleted" in answer.lower()


async def test_the_final_stage_answers_plainly_rather_than_being_rejected():
    """Nothing is wrong at the end of a preset, so nothing should read as an error."""
    last = hybrid_default.stages[-1]
    port = FakeWorkflow(_with_workflow(uuid4()).model_copy(update={"current_stage": last.id}))

    answer = await _advance(port, "the outcomes review is done")

    assert last.id in answer
    assert "last stage" in answer.lower()
    assert port.calls == []
    assert port.state.current_stage == last.id


async def test_a_stage_the_preset_does_not_know_is_reported_not_guessed():
    """A preset swapped under a running project: say so rather than restart it.

    `current_stage_of` returns `None` here, and treating that as "start at the
    first stage" would advance a project into stage two of a workflow it never
    ran.
    """
    port = FakeWorkflow(
        _with_workflow(uuid4()).model_copy(update={"current_stage": "tyler.step99.invented"})
    )

    answer = await _advance(port, "ready")

    assert "tyler.step99.invented" in answer
    assert "hybrid.default" in answer
    assert port.calls == []


async def test_a_storage_failure_comes_back_as_prose():
    """A tool that raises turns an outage into a broken turn."""

    class Broken(FakeWorkflow):
        async def advance(self, command: AdvanceStage) -> ProjectState:
            raise RuntimeError("the event store is unreachable")

    port = Broken(_with_workflow(uuid4()))

    answer = await _advance(port, "intake complete")

    assert "unreachable" in answer


def test_the_domain_still_owns_the_ordering_rule():
    """Guards the division of labour these tests assume.

    If the tool ever grew its own ordering check, this rule would have two
    implementations and one of them would drift.
    """
    state = _with_workflow(uuid4())
    with pytest.raises(CommandRejectedError, match=re.escape("hybrid.step1.framing")):
        decide(
            AdvanceStage(
                preset=hybrid_default,
                to_stage="hybrid.step10.outcomes",
                decided_by="agent",
                gate_decision="skipping ahead",
            ),
            state,
        )
