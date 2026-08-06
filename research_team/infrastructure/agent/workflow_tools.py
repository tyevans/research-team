"""Crossing a stage boundary, as one gated tool.

`advance_stage` is the only tool in the system whose value is that a human sees
it. Everything else here is gated because it costs money or leaves the process;
this one is gated because *advancing is the review gate*. Putting it in
`GATED_TOOLS` with a floor of `ask` buys the interrupt, the SSE announce, the
browser prompt and the recorded `ToolCallDecided` from the machinery that
already exists -- which is the entire reason the gate model in the spec is
cheap. A second approval path built for stages would be the same feature twice,
diverging.

The tool owns no ordering rules. `domain/project.py` already rejects advancing
out of order, advancing to an unknown stage, advancing with no workflow
selected, and anything at all on a deleted project, and those refusals name
specifics -- which stage, which workflow, which one is next. This module's job
is to compute the one legal `to_stage`, run the command, and turn either
outcome into prose. Re-checking the rules here would put the most important
invariant in the system in two places.

Two situations are answered *before* the command rather than through it. A
project sitting on the preset's last stage is not in error, and a
`CommandRejectedError` would tell a model to try something when there is
nothing to try; and a `current_stage` the preset does not contain leaves
nothing legal to compute, where falling back to "the first stage" would advance
a project into stage two of a workflow it never ran. Both come back as plain
statements of where the project stands.
"""

from typing import Protocol

from eventsource import CommandRejectedError
from langchain_core.tools import BaseTool, tool

from research_team.application.autonomy import ADVANCE_STAGE_TOOL
from research_team.domain.project import AdvanceStage, ProjectState, current_stage_of
from research_team.domain.workflow import Preset, Stage


class WorkflowPort(Protocol):
    """One project's stage position, read and moved.

    The project id is not a parameter, for the reason it is not one on
    `KnowledgePort` or `CorpusReadPort`: an instance belongs to one project and
    supplies it, and a caller that could pass a different id is a caller that
    could advance somebody else's run.

    `project_state` is a call rather than a value handed over at construction
    because a turn can advance twice -- an approval per boundary -- and a tool
    holding the state it was built with would compute the same `to_stage` the
    second time and be rejected for skipping. The stage the *middleware* uses
    is still folded once per turn; that one is a filter over tools and cannot
    change mid-turn without rebuilding the agent, and this one is a decision
    that can.
    """

    async def project_state(self) -> ProjectState: ...

    async def advance(self, command: AdvanceStage) -> ProjectState: ...


def describe_stage(stage: Stage) -> str:
    """A stage in one line: what it is called, and what leaving it should produce.

    Built from `outputs` rather than from a hand-written blurb because the
    outputs are the stage's contract -- a description that drifted from them
    would tell the model to write the wrong artifacts, and there is no second
    place to keep in sync if there is no second text.
    """
    produced = ", ".join(output.artifact_type.value for output in stage.outputs)
    line = f"{stage.name} ({stage.id})"
    if produced:
        line += f" -- produces {produced}"
    return line


def _next_stage(preset: Preset, current: Stage) -> Stage | None:
    ids = [stage.id for stage in preset.stages]
    at = ids.index(current.id)
    return preset.stages[at + 1] if at + 1 < len(preset.stages) else None


def build_workflow_tools(
    workflow: WorkflowPort, *, preset: Preset, decided_by: str = "agent"
) -> tuple[BaseTool, ...]:
    """`advance_stage` over one project running one preset.

    `decided_by` records who is credited with the decision. It defaults to the
    agent because the agent is what calls this; the human's part is recorded by
    the approval that let the call through, on its own event, and collapsing
    the two would lose which of them proposed the move.
    """

    async def _attempt(to_stage: str, rationale: str) -> str | None:
        """Run the command; prose if it was refused, `None` if it went through.

        The refusal is passed through rather than summarised. `decide`'s
        messages name the workflow, the current stage and the one that is
        actually next, and flattening them to "could not advance" would leave
        the model with nowhere to go -- which is the failure mode a gate is
        supposed to prevent, arriving from the other direction.
        """
        try:
            await workflow.advance(
                AdvanceStage(
                    preset=preset,
                    to_stage=to_stage,
                    decided_by=decided_by,
                    gate_decision=rationale,
                )
            )
        except CommandRejectedError as error:
            return (
                f"Stage not advanced: {error}. The project is unchanged; nothing "
                f"about this stage's work was lost."
            )
        except Exception as error:  # noqa: BLE001 -- a raising tool breaks the turn
            return f"Stage not advanced: {error}. The project is unchanged."
        return None

    @tool(ADVANCE_STAGE_TOOL)
    async def advance_stage(rationale: str) -> str:
        """Move this project to the next stage of its workflow.

        `rationale` says why this stage's work is finished and must be
        specific: it is recorded on the event and is what a reviewer reads.
        """
        if not rationale.strip():
            return (
                "Refused: `rationale` is required and must say why this stage's work "
                "is finished. A stage boundary crossed for no stated reason is not a "
                "gate -- call this again with what was produced and why it is enough."
            )

        state = await workflow.project_state()
        current = current_stage_of(state, preset)
        if current is None:
            if state.preset_id is None:
                # No workflow at all: the domain's own refusal is the better
                # answer, and it is one command away. Any `to_stage` reaches
                # it, since that arm is checked before the stage list is.
                refusal = await _attempt(preset.stages[0].id, rationale)
                return refusal or "Stage advanced."
            return (
                f"This project's recorded stage {state.current_stage!r} is not a stage "
                f"of workflow {preset.id}, so there is no next stage to move to. "
                f"Report this rather than working around it: the project and the "
                f"workflow it is being run under disagree."
            )

        following = _next_stage(preset, current)
        if following is None:
            return (
                f"Already at the last stage of {preset.name} ({preset.id}): "
                f"{describe_stage(current)}. There is nothing to advance to -- "
                f"the remaining work is finishing this stage's artifacts."
            )

        refusal = await _attempt(following.id, rationale)
        if refusal is not None:
            return refusal

        return (
            f"Advanced out of {describe_stage(current)}.\n"
            f"Now in {describe_stage(following)}.\n"
            f"Work in this stage only; the previous stage's artifacts are settled "
            f"and revising one is an amendment, not a return to it."
        )

    return (advance_stage,)


WORKFLOW_PROMPT = (
    "\n\nThis project runs a staged workflow. You can only see the tools the "
    "current stage allows, and `advance_stage` is how the run moves on -- it "
    "asks a human, so expect to wait and expect to be refused.\n\n"
    "Advance when this stage's outputs exist and are cited, not when you have "
    "run out of things to say. The `rationale` you pass is what the reviewer "
    "reads to decide, so name what was produced and what it rests on. A stage "
    "you advanced past is settled: revising its artifacts later is an "
    "amendment recorded against it, never a return to it."
)
