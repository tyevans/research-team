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

from typing import Any, Literal

from research_team.knowledge.application import (
    REMEMBER_PAGE_TOOL,
    REMEMBER_TOOL,
    UNMERGE_TOOL,
)

Level = Literal["auto", "ask", "deny"]
"""`auto` runs it, `ask` interrupts for a human, `deny` refuses without asking."""

LEVELS: tuple[Level, ...] = ("auto", "ask", "deny")

SEARCH_TOOL = "web_search"
FETCH_TOOL = "fetch"
FETCH_MEDIA_TOOL = "fetch_media"

GATED_TOOLS: tuple[str, ...] = (
    SEARCH_TOOL,
    FETCH_TOOL,
    FETCH_MEDIA_TOOL,
    "write_file",
    "edit_file",
    "delete_file",
    REMEMBER_TOOL,
    # Gated beside `remember` for the same reason and not a weaker one: a
    # commit changes what every later session in the project sees, however the
    # bytes reached it. An ungated by-reference path would be a way around the
    # gate on the by-value one.
    REMEMBER_PAGE_TOOL,
    UNMERGE_TOOL,
)
"""What can be gated. Read-only file tools are absent deliberately: they cost
nothing and escape nothing, and gating them would train people to click
through approvals without reading them."""

STRICTNESS: tuple[Level, ...] = ("auto", "ask", "deny")
"""The levels in increasing order, so two of them can be compared."""

TOOL_FLOORS: dict[str, Level] = {
    FETCH_TOOL: "ask",
    FETCH_MEDIA_TOOL: "ask",
}
"""The least autonomy a tool gets when nobody has said otherwise.

`fetch`'s floor is what lets that tool be registered unconditionally.
Search is opt-in by configuration -- no SearXNG instance, no
tool -- but fetch has no instance to configure and would otherwise be a network
tool present in a default install with nothing standing in front of it. A floor
of `ask` means it is there, discoverable, and cannot leave the process until a
person says so.

`fetch_media`'s floor is the same argument, with the stakes raised rather than
changed: it is also a network tool present unconditionally, reaching a URL the
model chose, and it additionally pulls megabytes to disk and can trigger a
perception pass -- costs `fetch` does not have. Nothing about that extra cost
is enforced by this floor, though; see `MAX_UPLOAD_BYTES` in
`application/media_acquisition.py` for why the byte ceiling is a separate,
unconditional refusal rather than something raising this tool to `auto` could
ever lift.

A floor, not an override: it raises the default and never lowers it, so a
policy built to deny everything is not read as "except fetch". An explicit
`set()` still wins in both directions -- someone who turns fetch to `auto` for a
research session meant it, and the same is true of `fetch_media`."""


class AutonomyPolicy:
    """Per-tool autonomy levels, mutable at any time."""

    def __init__(self, default: Level = "auto") -> None:
        self._default: Level = default
        self._levels: dict[str, Level] = {}

    def level_for(self, tool_name: str) -> Level:
        """The level for a tool. Ungated tools are always `auto`.

        An explicit setting is the answer whenever there is one. Otherwise the
        answer is the stricter of this policy's default and the tool's floor,
        so `TOOL_FLOORS` can raise a permissive default without overriding a
        deliberately restrictive one.
        """
        if tool_name not in GATED_TOOLS:
            return "auto"
        if tool_name in self._levels:
            return self._levels[tool_name]
        floor = TOOL_FLOORS.get(tool_name, "auto")
        return max(self._default, floor, key=STRICTNESS.index)

    def set(self, tool_name: str, level: Level) -> None:
        if level not in LEVELS:
            raise ValueError(f"unknown autonomy level: {level!r}")
        if tool_name not in GATED_TOOLS:
            raise ValueError(f"not a gated tool: {tool_name!r}")
        self._levels[tool_name] = level

    def relax_all(self) -> dict[str, Level]:
        """Set gated tools to `auto`, and report only what actually changed.

        The answer to "stop asking me about every fetch". Answering it one tool
        at a time is the thing people give up on, and giving up means clicking
        through approvals without reading them -- the failure `GATED_TOOLS`
        avoids by not gating the harmless reads in the first place.

        Only the changes are returned, keyed by tool, so a caller recording
        this can append exactly one `AutonomyChanged` per level that really
        moved. Returning every tool would have the log claim eight decisions
        where a person made one, and a log that overstates is as unreadable as
        one that omits.

        A `deny` is relaxed to `auto` like anything else. This is a relax-all,
        not a raise-only: someone who denied `delete_file` an hour ago and now
        asks for everything to be automatic has said something later and more
        general, and silently keeping the deny would leave a switch labelled
        "allow all" that does not.

        `fetch_media` is swept in like any other hazard, and that is intended
        rather than inherited: it is the first tool where "allow all" means an
        unattended run can pull megabytes to disk and trigger a perception
        pass on the model's own say-so, with nobody in the loop to notice
        before it happens. Stated here because a reader auditing what
        `relax_all` actually grants should not have to discover that
        consequence by tracing `TOOL_FLOORS` to `fetch_media.py` themselves.

        Every gated tool, with no exemption and no flag to grant one. There
        was one -- `advance_stage` was a review gate rather than a hazard, and
        `relax_all` withheld it unless asked -- and it went with the tool. What
        remains in `GATED_TOOLS` is hazards only, and "relax everything except
        the ones that are dangerous" is not a rule anybody wants.
        """
        changed: dict[str, Level] = {}
        for tool in GATED_TOOLS:
            if self.level_for(tool) == "auto":
                continue
            self.set(tool, "auto")
            changed[tool] = "auto"
        return changed

    def levels(self) -> dict[str, Level]:
        """Every gated tool's current level, for display."""
        return {tool: self.level_for(tool) for tool in GATED_TOOLS}

    def restrict_all(self, level: Level = "ask") -> dict[str, Level]:
        """Set all gated tools to `level` (default 'ask'), and report what changed.

        The natural counterpart to `relax_all()`: someone who wants full
        supervision across hazards switches everything back to `ask` (or `deny`).
        Only tools whose effective level actually changed are returned.
        """
        if level not in LEVELS:
            raise ValueError(f"unknown autonomy level: {level!r}")
        changed: dict[str, Level] = {}
        for tool in GATED_TOOLS:
            current = self.level_for(tool)
            if current != level:
                self.set(tool, level)
                changed[tool] = level
        return changed

    def reset(self, tool_name: str | None = None) -> dict[str, Level]:
        """Reset one or all explicit tool overrides back to policy default/floor.

        Reports which tools changed their effective level as a result.
        """
        changed: dict[str, Level] = {}
        if tool_name is not None:
            if tool_name not in GATED_TOOLS:
                raise ValueError(f"not a gated tool: {tool_name!r}")
            if tool_name in self._levels:
                old_level = self._levels.pop(tool_name)
                new_level = self.level_for(tool_name)
                if old_level != new_level:
                    changed[tool_name] = new_level
            return changed

        for tool in list(self._levels):
            old_level = self._levels.pop(tool)
            new_level = self.level_for(tool)
            if old_level != new_level:
                changed[tool] = new_level
        return changed

    @staticmethod
    def is_gated(tool_name: str) -> bool:
        """Whether `tool_name` is in the gated tools registry."""
        return tool_name in GATED_TOOLS

    def explain(self, tool_name: str) -> dict[str, Any]:
        """Explain how the autonomy level for `tool_name` is determined."""
        if not self.is_gated(tool_name):
            return {
                "tool_name": tool_name,
                "level": "auto",
                "gated": False,
                "explicit": False,
                "floor": None,
                "default": self._default,
            }
        explicit = tool_name in self._levels
        level = self.level_for(tool_name)
        floor = TOOL_FLOORS.get(tool_name)
        return {
            "tool_name": tool_name,
            "level": level,
            "gated": True,
            "explicit": explicit,
            "floor": floor,
            "default": self._default,
        }

    def copy(self) -> "AutonomyPolicy":
        """Create an independent copy of this policy with identical settings."""
        cloned = AutonomyPolicy(default=self._default)
        cloned._levels = dict(self._levels)
        return cloned


class ScopedAutonomyPolicy(AutonomyPolicy):
    """A session- or context-scoped policy layered over a parent policy.

    Queries fall through to `parent` unless explicitly set in this scope.
    Changes made via `set()`, `relax_all()`, or `restrict_all()` stay process-local
    to this scope and do not mutate the parent.
    """

    def __init__(self, parent: AutonomyPolicy) -> None:
        super().__init__(default=parent._default)
        self._parent = parent

    def level_for(self, tool_name: str) -> Level:
        if tool_name not in GATED_TOOLS:
            return "auto"
        if tool_name in self._levels:
            return self._levels[tool_name]
        return self._parent.level_for(tool_name)

    def levels(self) -> dict[str, Level]:
        combined = self._parent.levels()
        for tool, level in self._levels.items():
            combined[tool] = level
        return combined
