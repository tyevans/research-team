"""`interrupt_config`'s `when` predicate: the authorization boundary itself.

Unit-level and deliberately not routed through the executor -- what matters
here is the predicate's answer for a given policy level, grant, and request
shape, and that is cheapest and clearest to pin directly. The end-to-end path
(a covered fetch actually skipping the human) belongs to a later task, once
`fetch` itself is grant-aware; this task only has to prove the gate consults
the grant correctly in isolation.

Every existing test in `test_approval.py` calls `interrupt_config(policy)`
with no session or registry -- that call must keep working, unchanged, which
is `test_with_no_registry_behaviour_is_unchanged` below.
"""

from uuid import uuid4

from research_team.application import AutonomyPolicy
from research_team.application.grants import FetchGrant, GrantRegistry
from research_team.infrastructure.agent.approval import interrupt_config


class FakeRequest:
    """Stands in for langchain's `ToolCallRequest`.

    Only `tool_call` is read by `when`, so only it is modelled -- a full
    `ToolCallRequest` needs a `tool`, `state` and `runtime` this gate never
    touches.
    """

    def __init__(self, tool_call):
        self.tool_call = tool_call


def _call(name: str, args: dict, *, call_id: str = "t1") -> FakeRequest:
    return FakeRequest({"name": name, "args": args, "id": call_id})


def _ask_policy(tool: str) -> AutonomyPolicy:
    policy = AutonomyPolicy(default="auto")
    policy.set(tool, "ask")
    return policy


def _when(policy, tool, *, session_id=None, grants=None):
    config = interrupt_config(policy, session_id=session_id, grants=grants)
    return config[tool]["when"]


def test_a_covered_fetch_does_not_interrupt():
    session_id = uuid4()
    grants = GrantRegistry()
    grants.register(
        session_id, FetchGrant(run_id=session_id, hosts=frozenset({"a.example"}), budget=1)
    )
    policy = _ask_policy("fetch")

    when = _when(policy, "fetch", session_id=session_id, grants=grants)

    assert when(_call("fetch", {"url": "https://a.example/page"})) is False


def test_a_host_outside_the_grant_still_interrupts():
    session_id = uuid4()
    grants = GrantRegistry()
    grants.register(
        session_id, FetchGrant(run_id=session_id, hosts=frozenset({"a.example"}), budget=1)
    )
    policy = _ask_policy("fetch")

    when = _when(policy, "fetch", session_id=session_id, grants=grants)

    assert when(_call("fetch", {"url": "https://evil.example/page"})) is True


def test_a_spent_budget_interrupts():
    session_id = uuid4()
    grant = FetchGrant(run_id=session_id, hosts=frozenset({"a.example"}), budget=1)
    grant.spend()
    grants = GrantRegistry()
    grants.register(session_id, grant)
    policy = _ask_policy("fetch")

    when = _when(policy, "fetch", session_id=session_id, grants=grants)

    assert when(_call("fetch", {"url": "https://a.example/page"})) is True


def test_a_denied_tool_still_interrupts_under_a_grant():
    """A grant is not the policy. `deny` must never be resurrected by one."""
    session_id = uuid4()
    grants = GrantRegistry()
    grants.register(
        session_id, FetchGrant(run_id=session_id, hosts=frozenset({"a.example"}), budget=1)
    )
    policy = AutonomyPolicy(default="auto")
    policy.set("fetch", "deny")

    when = _when(policy, "fetch", session_id=session_id, grants=grants)

    assert when(_call("fetch", {"url": "https://a.example/page"})) is True


def test_a_non_fetch_gated_tool_always_interrupts_under_a_grant():
    """Pins rule 2: only `fetch` is ever covered, no matter what the grant
    contains or how permissive it looks."""
    session_id = uuid4()
    grants = GrantRegistry()
    grants.register(
        session_id, FetchGrant(run_id=session_id, hosts=frozenset({"a.example"}), budget=100)
    )
    policy = _ask_policy("write_file")

    when = _when(policy, "write_file", session_id=session_id, grants=grants)

    assert when(_call("write_file", {"url": "https://a.example/page"})) is True


def test_an_unreadable_url_argument_interrupts():
    """No `url` key at all: not covered, by the fail-closed rule -- a request
    the gate cannot parse must never read as authorised."""
    session_id = uuid4()
    grants = GrantRegistry()
    grants.register(
        session_id, FetchGrant(run_id=session_id, hosts=frozenset({"a.example"}), budget=1)
    )
    policy = _ask_policy("fetch")

    when = _when(policy, "fetch", session_id=session_id, grants=grants)

    assert when(_call("fetch", {})) is True


def test_an_absent_tool_call_interrupts():
    """A request whose `tool_call` cannot even be read -- not the args, the
    whole attribute -- is the sharpest version of the same fail-closed rule."""
    session_id = uuid4()
    grants = GrantRegistry()
    grants.register(
        session_id, FetchGrant(run_id=session_id, hosts=frozenset({"a.example"}), budget=1)
    )
    policy = _ask_policy("fetch")

    when = _when(policy, "fetch", session_id=session_id, grants=grants)

    assert when(object()) is True


def test_a_grant_for_one_session_does_not_cover_another():
    session_a = uuid4()
    session_b = uuid4()
    grants = GrantRegistry()
    grants.register(
        session_a, FetchGrant(run_id=session_a, hosts=frozenset({"a.example"}), budget=1)
    )
    policy = _ask_policy("fetch")

    when = _when(policy, "fetch", session_id=session_b, grants=grants)

    assert when(_call("fetch", {"url": "https://a.example/page"})) is True


def test_with_no_registry_behaviour_is_unchanged():
    """Every existing caller passes neither keyword. `ask` still interrupts,
    `auto` still doesn't -- exactly today's rule, since there is no grant to
    consult.

    `fetch` floors at `ask` (`TOOL_FLOORS`), so `web_search` is what exercises
    the `auto` branch here -- `fetch` can never reach `auto` regardless of
    this predicate.
    """
    ask_policy = _ask_policy("fetch")
    auto_policy = AutonomyPolicy(default="auto")

    ask_when = _when(ask_policy, "fetch")
    auto_when = _when(auto_policy, "web_search")

    assert ask_when(_call("fetch", {"url": "https://a.example/page"})) is True
    assert auto_when(_call("web_search", {"query": "x"})) is False


def test_a_covered_fetch_with_no_session_still_interrupts():
    """A registry with nothing to key it by cannot cover anything -- the same
    fail-closed rule applied to a missing coordinate rather than a missing
    field."""
    grants = GrantRegistry()
    session_id = uuid4()
    grants.register(
        session_id, FetchGrant(run_id=session_id, hosts=frozenset({"a.example"}), budget=1)
    )
    policy = _ask_policy("fetch")

    when = _when(policy, "fetch", session_id=None, grants=grants)

    assert when(_call("fetch", {"url": "https://a.example/page"})) is True


def test_ten_covered_calls_in_one_batch_admit_only_one_on_a_budget_of_one():
    """The over-spend `task-5-review.md` reproduced against the real tool:
    ten covered `fetch` calls in one assistant message, a budget of one, ten
    requests out. `HumanInTheLoopMiddleware.after_model` evaluates `when` for
    every call in the message synchronously before any tool runs, which is
    exactly what this loop reproduces -- calling `when` ten times in a row,
    the way the middleware does, rather than through any tool or transport.
    Ten distinct call ids, as a real message would carry -- each tool call in
    an `AIMessage` has its own id, which is what `reserve()` now keys on.

    Fixed by `_covered` reserving against the budget instead of merely
    reading it (`grant.reserve(call_id, url)`, not `grant.covers(url)`): the
    second call in the batch sees the first one's claim. Only one of the ten
    should come back `False` (not interrupted); the other nine must be told
    to ask a human, because there is no budget left to admit them.
    """
    session_id = uuid4()
    grants = GrantRegistry()
    grants.register(
        session_id, FetchGrant(run_id=session_id, hosts=frozenset({"a.example"}), budget=1)
    )
    policy = _ask_policy("fetch")
    when = _when(policy, "fetch", session_id=session_id, grants=grants)

    decisions = [
        when(_call("fetch", {"url": "https://a.example/page"}, call_id=f"t{i}"))
        for i in range(10)
    ]

    admitted = decisions.count(False)  # False means "does not interrupt"
    assert admitted == 1
    assert decisions.count(True) == 9


def test_reevaluating_the_same_call_id_stays_admitted_on_resume():
    """The Critical a whole-branch review reproduced: langgraph re-executes
    `after_model` from the top on `Command(resume=...)` (`interrupt()` raises
    `GraphInterrupt`), so `when` -- and `_covered` -- is called *again* for
    every covered call in a message that also contains an interrupting one.
    Before `reserve()` was keyed by call id, the second evaluation of the
    *same* covered call was indistinguishable from a brand-new claim and, at
    low remaining budget, could be refused where the first evaluation was
    not -- flipping an already-admitted call to interrupted mid-turn.
    """
    session_id = uuid4()
    grants = GrantRegistry()
    grants.register(
        session_id, FetchGrant(run_id=session_id, hosts=frozenset({"a.example"}), budget=1)
    )
    policy = _ask_policy("fetch")
    when = _when(policy, "fetch", session_id=session_id, grants=grants)
    call = _call("fetch", {"url": "https://a.example/page"}, call_id="t1")

    first_pass = when(call)
    # The resume pass: after_model walks the same message's tool calls again.
    second_pass = when(call)

    assert first_pass is False  # not interrupted
    assert second_pass is False  # still not interrupted, not flipped


def test_a_missing_call_id_interrupts():
    """The same fail-closed rule extended to the id `reserve()` claims
    under: a request this gate cannot read a call id from must never read as
    covered, the same as a missing `url`."""
    session_id = uuid4()
    grants = GrantRegistry()
    grants.register(
        session_id, FetchGrant(run_id=session_id, hosts=frozenset({"a.example"}), budget=1)
    )
    policy = _ask_policy("fetch")
    when = _when(policy, "fetch", session_id=session_id, grants=grants)
    request = FakeRequest({"name": "fetch", "args": {"url": "https://a.example/page"}})

    assert when(request) is True


def test_reusing_a_call_id_for_a_host_the_grant_does_not_cover_still_interrupts():
    """The scope-escape Critical a whole-branch re-review reproduced through
    this exact gate: `reserve()`'s idempotency short-circuit used to run
    before the scope check, so a second call sharing an id with a covered
    call was waved through no matter what host it named. Two calls in one
    `when` pass -- the shape `HumanInTheLoopMiddleware.after_model` walks a
    message's tool calls in -- sharing an id, the second naming a host the
    grant never listed, must interrupt.
    """
    session_id = uuid4()
    grants = GrantRegistry()
    grants.register(
        session_id, FetchGrant(run_id=session_id, hosts=frozenset({"a.example"}), budget=5)
    )
    policy = _ask_policy("fetch")
    when = _when(policy, "fetch", session_id=session_id, grants=grants)

    covered = when(_call("fetch", {"url": "https://a.example/page"}, call_id="toolu_1"))
    # Same call id, a host this grant does not name.
    uncovered = when(_call("fetch", {"url": "https://evil.example/page"}, call_id="toolu_1"))

    assert covered is False  # admitted, as expected
    assert uncovered is True  # must interrupt -- the scope escape, closed
