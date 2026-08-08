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
FETCH_TOOL = "fetch"
ADVANCE_STAGE_TOOL = "advance_stage"
"""Defined here rather than beside its tool because a workflow application port
does not exist -- there is nothing above `domain.workflow` for the name to live
in, and the tool module importing this is the same direction `corpus_read` and
`knowledge` already point."""

GATED_TOOLS: tuple[str, ...] = (
    SEARCH_TOOL,
    FETCH_TOOL,
    ADVANCE_STAGE_TOOL,
    "write_file",
    "edit_file",
    "delete_file",
    REMEMBER_TOOL,
    UNMERGE_TOOL,
)
"""What can be gated. Read-only file tools are absent deliberately: they cost
nothing and escape nothing, and gating them would train people to click
through approvals without reading them."""

STAGE_GATE_TOOLS: tuple[str, ...] = (ADVANCE_STAGE_TOOL,)
"""The gated tools that are review gates rather than hazards.

Named as a set rather than special-cased inline wherever it matters, because
"relax everything except the workflow review" is a rule that will be stated in
more than one place (`relax_all`, the routes over it, whatever UI offers the
switch) and each restatement is a chance for one of them to forget."""

STRICTNESS: tuple[Level, ...] = ("auto", "ask", "deny")
"""The levels in increasing order, so two of them can be compared."""

TOOL_FLOORS: dict[str, Level] = {FETCH_TOOL: "ask", ADVANCE_STAGE_TOOL: "ask"}
"""The least autonomy a tool gets when nobody has said otherwise.

`advance_stage` has one for a different reason than the others: it is not
dangerous, it *is* the review gate. A stage boundary is where a person is
supposed to look at what was produced before the run builds on it, and the
approval path this floor puts in front of the tool -- interrupt, announce,
prompt, recorded decision -- is exactly that review, already built. Without the
floor a default-`auto` policy would let a run cross every gate in a workflow
without anyone seeing it, which is the silent-progress failure the whole
staging design exists to prevent.

`fetch`'s floor is what lets that tool be registered unconditionally.
Search is opt-in by configuration -- no SearXNG instance, no
tool -- but fetch has no instance to configure and would otherwise be a network
tool present in a default install with nothing standing in front of it. A floor
of `ask` means it is there, discoverable, and cannot leave the process until a
person says so.

A floor, not an override: it raises the default and never lowers it, so a
policy built to deny everything is not read as "except fetch". An explicit
`set()` still wins in both directions -- someone who turns fetch to `auto` for a
research session meant it."""


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

    def relax_all(self, *, include_stage_gates: bool = False) -> dict[str, Level]:
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

        `advance_stage` (see `STAGE_GATE_TOOLS`) is excluded unless asked for
        by name. Its floor is not about danger -- it *is* the workflow review
        gate. A stage boundary is where a person is supposed to look at what
        was produced before the run builds on it, and the approval path is that
        review, already built. Auto-ing it lets a run cross every gate in a
        workflow with nobody seeing it, which is the silent-progress failure
        the staging design exists to prevent. So relaxing it stays a separate,
        deliberate act rather than a side effect of not wanting to be asked
        about `fetch`. The alternative -- excluding it outright, with no flag --
        was rejected because a single-operator run where the operator *is* the
        review is a real way to work, and the honest shape for that is an
        option they have to reach for, not a rule they have to route around.
        """
        changed: dict[str, Level] = {}
        for tool in GATED_TOOLS:
            if tool in STAGE_GATE_TOOLS and not include_stage_gates:
                continue
            if self.level_for(tool) == "auto":
                continue
            self.set(tool, "auto")
            changed[tool] = "auto"
        return changed

    def levels(self) -> dict[str, Level]:
        """Every gated tool's current level, for display."""
        return {tool: self.level_for(tool) for tool in GATED_TOOLS}
