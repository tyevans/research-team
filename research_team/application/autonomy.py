"""How much the agent may do without asking.

Held as a mutable object rather than passed at construction time, because the
question "may this agent search the web right now?" has a different answer at
different moments and nobody wants to restart a session to change it. The
predicate that consults this runs once per tool call, so a change lands on the
next call -- including partway through a turn already in flight.

Framework-free on purpose: `tests/test_architecture.py` holds this layer to
importing nothing but `eventsource`, and the closure that adapts this to
langchain's `when` predicate lives in `infrastructure` instead.
"""

from typing import Literal

from research_team.application.knowledge import REMEMBER_TOOL, UNMERGE_TOOL

Level = Literal["auto", "ask", "deny"]
"""`auto` runs it, `ask` interrupts for a human, `deny` refuses without asking."""

LEVELS: tuple[Level, ...] = ("auto", "ask", "deny")

SEARCH_TOOL = "web_search"

GATED_TOOLS: tuple[str, ...] = (
    SEARCH_TOOL,
    "write_file",
    "edit_file",
    "delete_file",
    REMEMBER_TOOL,
    UNMERGE_TOOL,
)
"""What can be gated. Read-only file tools are absent deliberately: they cost
nothing and escape nothing, and gating them would train people to click
through approvals without reading them."""


class AutonomyPolicy:
    """Per-tool autonomy levels, mutable at any time."""

    def __init__(self, default: Level = "auto") -> None:
        self._default: Level = default
        self._levels: dict[str, Level] = {}

    def level_for(self, tool_name: str) -> Level:
        """The level for a tool. Ungated tools are always `auto`."""
        if tool_name not in GATED_TOOLS:
            return "auto"
        return self._levels.get(tool_name, self._default)

    def set(self, tool_name: str, level: Level) -> None:
        if level not in LEVELS:
            raise ValueError(f"unknown autonomy level: {level!r}")
        if tool_name not in GATED_TOOLS:
            raise ValueError(f"not a gated tool: {tool_name!r}")
        self._levels[tool_name] = level

    def levels(self) -> dict[str, Level]:
        """Every gated tool's current level, for display."""
        return {tool: self.level_for(tool) for tool in GATED_TOOLS}
