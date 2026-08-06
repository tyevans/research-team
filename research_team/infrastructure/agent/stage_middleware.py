"""Stage enforcement as a tool filter, not as a prompt request.

A workflow stage is only real if the model *cannot* do the next stage's work.
Telling it "you are in the draft stage, do not advance yet" is a suggestion; a
model that never sees `advance_stage` bound cannot call it. So the gate lives
here, between the agent and the model, and the prompt merely explains a
restriction the tool list already imposes.

Two constraints from langchain shape everything below, both verified against
1.3.14 and written up in `docs/research/course-design/deepagents-integration.md`
section 5:

*The hook must be the async one.* `AgentMiddleware.awrap_model_call`'s default
body raises `NotImplementedError` naming precisely this mistake, and
`DeepAgentTurnExecutor._invoke` streams -- a sync-only implementation fails on
the first turn, not in review.

*The filter only ever removes.* `factory.py` rejects a tool that appears in
`request.tools` without having been registered at agent creation, so a stage
cannot conjure a tool. The composition is therefore: the executor registers the
union of every stage's tools once, and this hides the ones the current stage
does not allow. That inverts the natural design -- an allowlist would be the
obvious shape, but by the time this middleware runs `request.tools` already
carries the deepagents built-ins injected upstream, and an allowlist over a
stage's declared tools would strip `read_file` and `write_file` and leave the
agent unable to do anything at all. Hence a denylist over stage-specific tools,
with the built-ins never in scope to begin with.

Stage arrives through the constructor rather than off graph state because there
is no graph state to read: `_invoke` builds a `MemorySaver()` inline per turn
and the `thread_id` embeds `turn_index`, so nothing survives to the next turn.
The event log is the source of truth and the fold happens at agent-build time.
"""

from collections.abc import Collection, Iterable
from typing import Any, Protocol, runtime_checkable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import SystemMessage

CORE_TOOLS = frozenset({"read_file", "write_file", "edit_file", "ls", "task"})
"""Tools no stage may withdraw.

The deepagents built-ins: the filesystem the agent records its work through and
the delegation tool subagents are reached by. A stage that took these away
would not be a narrower stage, it would be a broken agent.
"""


@runtime_checkable
class StageLike(Protocol):
    """What this middleware needs of a stage, and no more.

    Structural rather than an import of `research_team.domain.workflow`, whose
    stage kinds are five frozen classes sharing a `StageBase` -- depending on
    the base would tie this to a hierarchy it has no opinion about, and only
    three of those fields are the gate's business.

    Notably absent: the prompt. The real stage carries a `generator.prompt_ref`
    and a screen stage carries no generator at all, so resolving a reference
    into text is composition's problem, not this one's. The resolved text
    arrives through the constructor instead.
    """

    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def tools(self) -> Collection[str]: ...


def managed_tools_for(stages: Iterable[StageLike]) -> frozenset[str]:
    """Every tool some stage claims -- the set this gate is entitled to hide.

    Taking the union from the preset rather than assuming "everything not core"
    is what lets an unrelated tool wired into the executor keep working: if no
    stage names it, no stage is expressing an opinion about it, and silently
    withdrawing it would be the gate overreaching.

    `CORE_TOOLS` is subtracted so that a stage listing `write_file` among its
    tools cannot accidentally make the built-in withdrawable everywhere else.
    """
    claimed: set[str] = set()
    for stage in stages:
        claimed.update(stage.tools)
    return frozenset(claimed - CORE_TOOLS)


def stage_prompt(stage: StageLike, instructions: str | None = None) -> str:
    """The block appended to the system prompt for one stage.

    Names the stage even when there are no instructions to add -- a screen
    stage has no generator by construction, and an agent that cannot say which
    stage it is in cannot explain its own refusals to the person watching.
    """
    lines = [f"## Current stage: {stage.name} ({stage.id})"]
    if instructions:
        lines.append(instructions)
    return "\n\n".join(lines)


class StageMiddleware(AgentMiddleware):
    """Binds only the tools the current stage allows, and says which stage it is."""

    def __init__(
        self,
        stage: StageLike,
        *,
        managed_tools: Iterable[str],
        instructions: str | None = None,
    ) -> None:
        super().__init__()
        self._stage = stage
        self._managed = frozenset(managed_tools) - CORE_TOOLS
        self._instructions = instructions

    @property
    def name(self) -> str:
        """Explicit because `factory.py` raises on two middleware sharing a name.

        The default is the class name, which would collide the moment anything
        subclassed this -- a cheap thing to rule out now.
        """
        return "stage_gate"

    async def awrap_model_call(self, request: ModelRequest, handler: Any) -> Any:
        """Narrow the request to this stage, then let the call proceed.

        Async, not sync: see the module docstring. `override` returns a new
        request rather than mutating -- direct assignment still writes through
        but is deprecated per field, so the overridden request is what gets
        passed on, and the original is left for whatever else holds it.
        """
        return await handler(
            request.override(
                tools=[t for t in request.tools if self._permits(t)],
                system_message=self._system_message(request.system_message),
            )
        )

    def _permits(self, candidate: Any) -> bool:
        """Whether one entry of `request.tools` survives into the bound set.

        Dict-shaped entries are server-side built-ins that no stage declares;
        they are passed through rather than name-matched, since the name a
        provider gives them is not the name a stage would use.
        """
        name = getattr(candidate, "name", None)
        if not isinstance(name, str):
            return True
        return name not in self._managed or name in self._stage.tools

    def _system_message(self, existing: SystemMessage | None) -> SystemMessage:
        """The stage block appended to whatever was already there.

        Appended, never substituted. On the current local endpoint the harness
        profile resolves bare and there is nothing to lose, but a switch to an
        Anthropic model resolves a profile with real content, and replacing the
        message wholesale would discard it with no error and no symptom beyond
        an agent that behaves slightly worse.
        """
        block = stage_prompt(self._stage, self._instructions)
        if existing is None:
            return SystemMessage(block)
        return SystemMessage(f"{existing.text}\n\n{block}")
