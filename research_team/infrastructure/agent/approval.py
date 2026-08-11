"""Where the autonomy policy meets langchain's interrupt machinery.

The policy itself names no framework -- the architecture test holds the
application layer to that -- so the adaptation lives here. `when` answers only
`auto` vs. not-auto, because it returns a bool; the difference between `ask`
and `deny` is settled by the resume loop, which can refuse without asking.
"""

from collections.abc import Callable
from uuid import UUID

from langchain.agents.middleware.human_in_the_loop import InterruptOnConfig

from research_team.application import GATED_TOOLS, AutonomyPolicy
from research_team.application.autonomy import FETCH_TOOL
from research_team.application.grants import GrantRegistry

ALLOWED_DECISIONS = ["approve", "edit", "reject"]
"""No `respond`: answering on a tool's behalf invents a result, and this log is
supposed to record what actually happened."""


def interrupt_config(
    policy: AutonomyPolicy,
    *,
    session_id: UUID | None = None,
    grants: GrantRegistry | None = None,
) -> dict[str, InterruptOnConfig]:
    """One entry per gated tool, each consulting the live policy per call.

    `session_id` and `grants` are keyword-only with `None` defaults so every
    existing caller -- and every existing test -- is unaffected: with neither
    supplied, `_gate_for` has no grant it could ever find and behaves exactly
    as it did before this parameter existed.
    """
    return {
        tool: InterruptOnConfig(
            allowed_decisions=ALLOWED_DECISIONS,
            when=_gate_for(policy, tool, session_id=session_id, grants=grants),
        )
        for tool in GATED_TOOLS
    }


def _gate_for(
    policy: AutonomyPolicy,
    tool: str,
    *,
    session_id: UUID | None,
    grants: GrantRegistry | None,
) -> Callable[[object], bool]:
    """Closes over the policy rather than its current value.

    This is what makes autonomy adjustable at any time: langchain calls the
    predicate once per tool call, so a level raised mid-turn is honoured on the
    very next call rather than at the next restart.

    Also closes over `session_id`, which is the more dangerous binding of the
    two. `interrupt_config` is called at `deep_agent.py:364`, inside `_invoke`,
    with the session the current pass is actually running -- so the predicate
    this returns is scoped to one turn of one session and must not outlive it.
    Cross-session isolation depends entirely on that: if this config were ever
    hoisted out of `_invoke` and built once for reuse across sessions, the
    closure would pin whichever session built it, and every later session
    would be checked against that session's grant. No test would catch a
    refactor like that going wrong, because each existing test builds its own
    config -- the invariant is "rebuild per pass", not anything this function
    can enforce on its own.
    """

    def when(request: object) -> bool:
        """The authorization boundary: whether this call proceeds unattended.

        `request` is langchain's ToolCallRequest; the tool name is already
        fixed by which entry of the config this predicate was built for.

        `deny` always interrupts -- a grant authorizes *hosts*, not tools, and
        must never resurrect a tool the policy has refused outright. Only past
        that does a grant get a say, and only for `fetch`: a grant is scoped
        to fetching named hosts a bounded number of times, and letting it
        reach any other gated tool would be a scope no one asked to grant.

        `_covered` is the only thing that can turn an `ask` into a pass, and
        it is written to answer "not covered" -- which means "interrupt" --
        on anything it cannot read with confidence: a missing `url`, an
        unexpected request shape, a session with no registered grant. An
        `except` that defaulted to "covered" on a parse failure would be an
        authorization bypass wearing the shape of error handling, so there is
        no such branch here; every uncertain input takes the same path as a
        genuinely uncovered one, straight to a human.
        """
        level = policy.level_for(tool)
        if level == "auto":
            return False
        return not (level == "ask" and _covered(request, tool, session_id, grants))

    return when


def _covered(
    request: object,
    tool: str,
    session_id: UUID | None,
    grants: GrantRegistry | None,
) -> bool:
    """Whether a grant lets this one `fetch` call skip the human.

    Reads `request.tool_call["args"]["url"]` the same defensive way
    `component_feedback.py` reads a write's `file_path`: `getattr(..., None)
    or {}` at every step, because a request built by something other than
    langchain's `ToolNode` -- a test, a future caller -- has no guaranteed
    shape, and this function's only correct answer to a shape it cannot read
    is `False`.

    Calls `grant.reserve(url)`, not `grant.covers(url)` -- this used to be a
    plain read, and a security review reproduced why that was wrong:
    `HumanInTheLoopMiddleware.after_model` evaluates `when` for *every* call
    in one assistant message, synchronously, before any of them runs, so a
    read-only check lets N covered calls in one message all pass against the
    same unspent budget -- ten requests on a budget of one, reproduced
    against the real tool (`task-5-review.md`). `reserve()` claims the unit
    as it answers, so the second call evaluated in the same batch sees the
    first one's claim and is refused here rather than also waved through.
    This is the only place a claim is made; `fetch.py`'s own `covers()` /
    `spend()` pair is unchanged and still decides, after the call actually
    returns, whether the grant is what paid for it. See `FetchGrant.reserve`
    for the full argument and what happens to a claim nothing ever spends.
    """
    if tool != FETCH_TOOL or grants is None or session_id is None:
        return False
    grant = grants.get(session_id)
    if grant is None:
        return False
    call = getattr(request, "tool_call", None) or {}
    args = call.get("args") if isinstance(call, dict) else None
    url = args.get("url") if isinstance(args, dict) else None
    if not isinstance(url, str):
        return False
    return grant.reserve(url)
