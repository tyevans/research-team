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

Each outcome also carries one bit beside the prose -- did the project move --
because a successful advance ends the turn and a refused one must not.
`EndTurnOnStageAdvance` below is the half that acts on it, and it lives here
rather than in `stage_middleware.py` so that the mark and the only thing that
reads it cannot drift apart in separate files.

Two situations are answered *before* the command rather than through it. A
project sitting on the preset's last stage is not in error, and a
`CommandRejectedError` would tell a model to try something when there is
nothing to try; and a `current_stage` the preset does not contain leaves
nothing legal to compute, where falling back to "the first stage" would advance
a project into stage two of a workflow it never ran. Both come back as plain
statements of where the project stands.
"""

from typing import Any, Protocol

from eventsource import CommandRejectedError
from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, tool

from research_team.application.autonomy import ADVANCE_STAGE_TOOL
from research_team.domain.project import AdvanceStage, ProjectState, current_stage_of
from research_team.domain.workflow import Preset, Stage

STAGE_ADVANCED: dict[str, Any] = {"stage_advanced": True}
"""The marker an `advance_stage` result carries when the project actually moved.

Carried on the `ToolMessage.artifact`, which exists for exactly this -- a
structured companion to the prose, invisible to the model. The prose is what
the model and the reviewer read and is free to be reworded; this is what
`EndTurnOnStageAdvance` matches on, so a rewording cannot silently stop ending
turns. A test on the wording alone would not have caught that.
"""


def _advanced(text: str) -> tuple[str, dict[str, Any]]:
    return text, STAGE_ADVANCED


def _refused(text: str) -> tuple[str, None]:
    """A result that left the project where it was.

    Every arm of the tool goes through one of these two, so "did this move the
    project" is answered once per return rather than inferred later. `None`
    rather than a `{"stage_advanced": False}` marker because absence is what
    every other tool in the system already produces, and the middleware then
    has one thing to look for instead of two.
    """
    return text, None


class EndTurnOnStageAdvance(AgentMiddleware):
    """Ends the turn once a stage boundary has actually been crossed.

    Two reasons, both the owner's. A turn is the unit of durability -- events
    are appended once, when it finishes -- so a stage advanced *mid*-turn is a
    transition whose survival depends on the rest of the turn succeeding. And
    the boundary exists to break the conversation: a stage that carries on in
    the same context inherits the previous stage's messages, which is the one
    thing the boundary is for.

    **This runs `before_model`, not at the tool, because the tool cannot end
    the graph.** A tool returning `Command(goto=END)` does not stop the loop
    here: langchain wires `tools -> model` as a conditional edge
    (`_make_tools_to_model_edge` in `langchain/agents/factory.py`), and a
    `Command`'s `goto` is applied *alongside* that edge rather than instead of
    it -- verified against 1.3.14, where the model ran anyway and produced a
    further message. `return_direct` is the framework's own answer and is
    wrong for a different reason: it is a property of the tool, so it would
    end the turn on a *refused* advance too, and it only fires when every call
    in the message has it, so a model that called `advance_stage` beside a
    `write_file` would silently keep going. `jump_to` is the supported hook
    that can be decided per result.

    **A refused advance is not an advance.** Only a result carrying
    `STAGE_ADVANCED` stops the turn; a domain rejection, a harness invariant
    failure, a human saying no, and an empty rationale all leave the agent
    running with its feedback delivered, which is the whole point of telling
    it why.

    **Other tool calls in the same step are not abandoned.** By the time this
    runs the tool node has executed every call in that step and their results
    are already in the transcript -- their file writes are already events on
    the aggregate. What is given up is the model's chance to *read* those
    results, which it would have read in the wrong stage anyway. A model that
    wants to act on them should not have proposed the advance in the same
    step.
    """

    name = "end_turn_on_stage_advance"

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        """Stop before the model is asked anything else.

        Async because `DeepAgentTurnExecutor._invoke` streams, and the sync
        hook is never called on that path -- the same constraint written up in
        `stage_middleware.py`.

        Scans backwards over the trailing tool results rather than only the
        last message, because a step with several tool calls appends several
        `ToolMessage`s and `advance_stage` need not be last among them.
        """
        for message in reversed(state.get("messages") or ()):
            if not isinstance(message, ToolMessage):
                break
            if getattr(message, "artifact", None) == STAGE_ADVANCED:
                return {"jump_to": "end"}
        return None


class WorkflowPort(Protocol):
    """One project's stage position, read and moved.

    The project id is not a parameter, for the reason it is not one on
    `KnowledgePort` or `CorpusReadPort`: an instance belongs to one project and
    supplies it, and a caller that could pass a different id is a caller that
    could advance somebody else's run.

    `project_state` is a call rather than a value handed over at construction.
    The original reason -- that a turn could advance twice, an approval per
    boundary -- stopped being true when `EndTurnOnStageAdvance` made the first
    successful advance the end of the turn. It is still a call, and should
    stay one: the state is read *before* the command that changes it, so the
    tool would be computing `to_stage` from a fold taken at agent-build time
    even within a single advance, and a stage moved by anything other than
    this tool between build and call would be invisible to it. The stage the
    *middleware* uses is still folded once per turn; that one is a filter over
    tools and cannot change mid-turn without rebuilding the agent.
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

    @tool(ADVANCE_STAGE_TOOL, response_format="content_and_artifact")
    async def advance_stage(rationale: str) -> tuple[str, dict[str, Any] | None]:
        """Move this project to the next stage of its workflow.

        `rationale` says why this stage's work is finished and must be
        specific: it is recorded on the event and is what a reviewer reads.

        Returns `(prose, artifact)`. The artifact is `STAGE_ADVANCED` on the
        one path that actually moved the project and `None` on every path that
        did not, which is what `EndTurnOnStageAdvance` reads to decide whether
        this turn is over. Marking it here rather than having the middleware
        recognise the prose is the point: only this function knows whether the
        command went through, and a reader matching on message text would tie
        a control-flow decision to wording anyone might reasonably reword.
        """
        if not rationale.strip():
            return _refused(
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
                return _refused(refusal) if refusal else _advanced("Stage advanced.")
            return _refused(
                f"This project's recorded stage {state.current_stage!r} is not a stage "
                f"of workflow {preset.id}, so there is no next stage to move to. "
                f"Report this rather than working around it: the project and the "
                f"workflow it is being run under disagree."
            )

        following = _next_stage(preset, current)
        if following is None:
            return _refused(
                f"Already at the last stage of {preset.name} ({preset.id}): "
                f"{describe_stage(current)}. There is nothing to advance to -- "
                f"the remaining work is finishing this stage's artifacts."
            )

        refusal = await _attempt(following.id, rationale)
        if refusal is not None:
            return _refused(refusal)

        return _advanced(
            f"Advanced out of {describe_stage(current)}.\n"
            f"Now in {describe_stage(following)}.\n"
            f"Work in this stage only; the previous stage's artifacts are settled "
            f"and revising one is an amendment, not a return to it.\n"
            f"This turn ends here, so that the transition is durable before "
            f"anything is built on it. Whether the next stage starts in a "
            f"fresh session depends on who is driving: a stage runner opens "
            f"one, and a person continuing in this session carries this "
            f"stage's conversation into the next."
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
    "amendment recorded against it, never a return to it.\n\n"
    "A successful `advance_stage` ends your turn. Say what you have to say "
    "before you call it, and do not plan work after it -- the next stage is a "
    "new turn. `EndTurnOnStageAdvance` enforces this, so these two sentences "
    "are not the guarantee; they are what lets you stop on a finished thought "
    "instead of mid-sentence. A *refused* advance does not end anything -- "
    "read what it says and keep working."
)
"""Explaining the gate to a model that has it bound.

The last paragraph is the prompt half of the turn-ending change, and it is
here rather than in the base system prompt for the reason
`component_guidance` gives about widget syntax: this text is only true when
`advance_stage` is bound, and a prompt carrying instructions that mostly do
not apply teaches the model that its instructions mostly do not apply. It is
appended by `StageMiddleware`'s instructions, so a session with no workflow
never sees it.

**"a fresh session" was removed from both this text and the tool's own success
prose.** It was true of what the turn boundary is *for* and false of what any
code did: nothing in the workflow path called `start_in_project` or
`release_project`, so a person whose agent advanced typed their next message
into the same session, still holding the previous stage's whole conversation.
`StageRunner` now keeps that promise for a driven run and cannot keep it for a
hand-run one -- so the tool says which case is which and this prompt, which the
model reads and cannot tell them apart from, says neither.
`stage-boundaries.md` §2.3 is the finding; `gate_review`'s docstring, corrected
in #74, is the precedent for why a prose claim about an ordering the code does
not have is worth removing rather than leaving.

It is not load-bearing. `EndTurnOnStageAdvance` stops the turn whether or not
the model intended to stop, which is the point -- a prompt gives a tendency and
the tendency is weakest on long messy turns, which are exactly the turns where
losing the transition costs most. What the prompt buys is a turn that ends on a
sentence the model meant to finish rather than one cut off after a tool result.
"""
