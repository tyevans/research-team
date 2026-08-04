"""Where the autonomy policy meets langchain's interrupt machinery.

The policy itself names no framework -- the architecture test holds the
application layer to that -- so the adaptation lives here. `when` answers only
`auto` vs. not-auto, because it returns a bool; the difference between `ask`
and `deny` is settled by the resume loop, which can refuse without asking.
"""

from collections.abc import Callable

from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig

from research_team.application import GATED_TOOLS, AutonomyPolicy

ALLOWED_DECISIONS = ["approve", "edit", "reject"]
"""No `respond`: answering on a tool's behalf invents a result, and this log is
supposed to record what actually happened."""


def interrupt_config(policy: AutonomyPolicy) -> dict[str, InterruptOnConfig]:
    """One entry per gated tool, each consulting the live policy per call."""
    return {
        tool: InterruptOnConfig(
            allowed_decisions=ALLOWED_DECISIONS,
            when=_gate_for(policy, tool),
        )
        for tool in GATED_TOOLS
    }


def _gate_for(policy: AutonomyPolicy, tool: str) -> Callable[[object], bool]:
    """Closes over the policy rather than its current value.

    This is what makes autonomy adjustable at any time: langchain calls the
    predicate once per tool call, so a level raised mid-turn is honoured on the
    very next call rather than at the next restart.
    """

    def when(request: object) -> bool:
        """`request` is langchain's ToolCallRequest; the tool name is already
        fixed by which entry of the config this predicate was built for."""
        return policy.level_for(tool) != "auto"

    return when
