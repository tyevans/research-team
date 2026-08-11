"""`FetchGrant` and `GrantRegistry`: what authorizes a fetch, and where that lives.

`covers` is an authorization decision, so every test here that names an
uncertain input (a malformed URL, a near-miss host) asserts the refusal, not
the happy path -- see `research_team/application/grants.py` for the totality
argument this mirrors from `normalize_url`.
"""

from uuid import uuid4

from research_team.application.grants import FetchGrant, GrantRegistry


def _grant(hosts: frozenset[str] | None = None, budget: int = 3) -> FetchGrant:
    return FetchGrant(run_id=uuid4(), hosts=hosts or frozenset({"example.com"}), budget=budget)


class TestCovers:
    def test_exact_host_is_covered(self) -> None:
        grant = _grant()
        assert grant.covers("https://example.com/page") is True

    def test_subdomain_is_not_covered(self) -> None:
        grant = _grant()
        assert grant.covers("https://www.example.com/page") is False

    def test_lookalike_prefix_host_is_not_covered(self) -> None:
        grant = _grant()
        assert grant.covers("https://evil-example.com/page") is False

    def test_lookalike_suffix_host_is_not_covered(self) -> None:
        grant = _grant()
        assert grant.covers("https://example.com.attacker.net/page") is False

    def test_matching_is_case_insensitive(self) -> None:
        grant = _grant()
        assert grant.covers("https://EXAMPLE.COM/page") is True

    def test_matching_is_case_insensitive_on_the_stored_host(self) -> None:
        """The other direction of case-insensitivity, missed the first time.

        `hosts` arrives from `NewRun.fetch_hosts` -- strings a person typed
        into an HTTP request body -- so a mixed-case stored host is a real
        input, not just the URL side. A grant built with `Example.COM` must
        still cover the lowercase URL, or it silently authorizes nothing.
        """
        grant = _grant(hosts=frozenset({"Example.COM"}))
        assert grant.covers("https://example.com/page") is True

    def test_stray_whitespace_in_a_stored_host_does_not_match(self) -> None:
        """Pins the no-strip decision: whitespace is not silently forgiven.

        `hosts` is lowercased but not trimmed. A host with leading or
        trailing space is not a value this class should guess the meaning
        of -- forgiving it here means guessing which host was actually
        meant, so a stray space is treated as a different host and simply
        does not match.
        """
        grant = _grant(hosts=frozenset({" example.com"}))
        assert grant.covers("https://example.com/page") is False

    def test_userinfo_in_url_is_handled(self) -> None:
        grant = _grant()
        assert grant.covers("https://user:pass@example.com/page") is True

    def test_malformed_url_is_not_covered_and_does_not_raise(self) -> None:
        grant = _grant()
        # An unclosed IPv6 literal is what makes urlsplit(...).hostname raise
        # -- the same shape recall.py's normalize_url is total against.
        assert grant.covers("http://[::1/x") is False

    def test_host_not_in_grant_is_not_covered(self) -> None:
        grant = _grant()
        assert grant.covers("https://other.com/page") is False

    def test_spent_budget_covers_nothing(self) -> None:
        grant = _grant(budget=1)
        grant.spend()
        assert grant.covers("https://example.com/page") is False

    def test_a_file_url_against_an_allowlisted_host_is_not_covered(self) -> None:
        """`file://example.com/etc/passwd` yields hostname `example.com`, so a
        host check alone would call this covered. `fetch.py` also refuses any
        non-http(s) scheme before the transport, but the grant must refuse it
        independently -- the authorization boundary should not depend on a
        guard that lives in a different file, changed by a different task.
        """
        grant = _grant()
        assert grant.covers("file://example.com/etc/passwd") is False

    def test_a_scheme_relative_url_against_an_allowlisted_host_is_not_covered(self) -> None:
        """`//example.com/p` has no scheme at all; `urlsplit` still resolves a
        hostname, so this is the same failure mode as the `file://` case with
        the scheme omitted rather than swapped."""
        grant = _grant()
        assert grant.covers("//example.com/page") is False

    def test_covers_does_not_spend(self) -> None:
        grant = _grant(budget=1)
        grant.covers("https://example.com/page")
        grant.covers("https://example.com/page")
        grant.covers("https://example.com/page")
        # Budget must still be intact -- repeated covers() calls are free.
        assert grant.covers("https://example.com/page") is True
        grant.spend()
        assert grant.covers("https://example.com/page") is False


class TestReserve:
    """`reserve()`: the gate-side claim that closes the batch over-spend,
    keyed by tool-call id.

    See `FetchGrant`'s docstring and `task-5-review.md` for what this closes:
    every call in one assistant message is evaluated against the same
    unspent budget before any of them runs, so a plain `covers()` check at
    the gate lets all of them through. `reserve()` claims as it goes, so
    the second covered call in a batch sees the first one's claim -- and
    keying by call id (rather than a plain count, the first version) is what
    makes re-evaluating the *same* call on langgraph's resume pass safe: see
    `TestReserveIsIdempotentPerCall` below for the crash that motivated it.
    """

    def test_a_covered_url_may_be_reserved(self) -> None:
        grant = _grant(budget=1)
        assert grant.reserve("t1", "https://example.com/page") is True

    def test_reserving_does_not_touch_remaining(self) -> None:
        """`covers()`/`spend()` in `fetch.py` must see the real budget,
        untouched by an outstanding reservation -- see the class docstring."""
        grant = _grant(budget=1)
        grant.reserve("t1", "https://example.com/page")
        assert grant.remaining == 1
        assert grant.covers("https://example.com/page") is True

    def test_a_second_call_on_a_budget_of_one_is_refused(self) -> None:
        """The batch fix itself: two different calls, one unit of budget."""
        grant = _grant(budget=1)
        assert grant.reserve("t1", "https://example.com/page") is True
        assert grant.reserve("t2", "https://example.com/page") is False

    def test_ten_calls_on_a_budget_of_one_admit_exactly_one(self) -> None:
        """The shape of the actual reproduction: N covered calls evaluated
        one after another (as `HumanInTheLoopMiddleware` walks one message's
        tool calls) against a budget of one."""
        grant = _grant(budget=1)
        admitted = sum(grant.reserve(f"t{i}", "https://example.com/page") for i in range(10))
        assert admitted == 1

    def test_an_uncovered_url_is_never_reserved(self) -> None:
        grant = _grant(budget=3)
        assert grant.reserve("t0", "https://other.com/page") is False
        assert grant.reserve("t1", "https://example.com/page") is True
        assert grant.reserve("t2", "https://example.com/page") is True
        assert grant.reserve("t3", "https://example.com/page") is True
        # The refused claim above cost nothing; three, not two, were left.
        assert grant.reserve("t4", "https://example.com/page") is False

    def test_spend_releases_the_reservation_it_corresponds_to(self) -> None:
        grant = _grant(budget=2)
        grant.reserve("t1", "https://example.com/page")
        grant.spend("t1")
        # The reservation is gone, so a second claim now has room again.
        assert grant.reserve("t2", "https://example.com/page") is True
        assert grant.reserve("t3", "https://example.com/page") is False

    def test_spend_with_no_call_id_does_not_release_anything(self) -> None:
        """Every direct-tool test in `test_fetch.py` calls `spend()` with no
        id (no gate in the loop) -- it must decrement the real budget and
        leave `_reserved` alone rather than erroring on a missing id."""
        grant = _grant(budget=2)
        grant.reserve("t1", "https://example.com/page")
        grant.spend()
        assert grant.remaining == 1
        # t1's claim is still outstanding -- an id-less spend didn't touch it.
        assert grant.reserve("t1", "https://example.com/page") is True

    def test_an_unspent_reservation_leaks_toward_fewer_fetches_not_more(self) -> None:
        """The accepted trade, pinned: a reservation nothing ever spends
        makes the grant strictly more conservative, never less."""
        grant = _grant(budget=1)
        grant.reserve("t1", "https://example.com/page")
        # Nothing ever released t1's claim -- refused by a human, say, or the
        # call errored before `fetch.py`'s `finally` releases it.
        assert grant.reserve("t2", "https://example.com/page") is False
        assert grant.covers("https://example.com/page") is True
        assert grant.remaining == 1


class TestReserveIsIdempotentPerCall:
    """The Critical a whole-branch review reproduced: `reserve()`'s first
    version was a plain counter, and langgraph re-executes `after_model`
    (and therefore re-calls `when` / `reserve()`) for every tool call in a
    message on `Command(resume=...)`, because `interrupt()` raises
    `GraphInterrupt` and the whole node reruns from the top. A message with
    one covered call and one interrupting call, on a budget of one: pass one
    reserves the covered call and interrupts the other; the resume pass
    re-evaluates BOTH, and a plain counter saw the covered call's *second*
    evaluation as a brand-new claim with no room left, flipping it to
    refused -- one decision came back for two hanging calls, and langchain
    raised `ValueError`. These tests pin the fix directly against the
    mechanism, without needing langgraph in the loop.
    """

    def test_reevaluating_the_same_call_id_does_not_claim_twice(self) -> None:
        grant = _grant(budget=1)
        assert grant.reserve("t1", "https://example.com/page") is True
        # The resume pass, re-evaluating the identical call.
        assert grant.reserve("t1", "https://example.com/page") is True
        assert grant.remaining == 1  # still unspent -- reserving never spends

    def test_a_second_call_stays_refused_across_reevaluation(self) -> None:
        """The crash's exact shape: t2 was refused on pass one, and pass two
        (the resume) must refuse it again, not flip it to admitted or crash
        trying to double-count t1's still-outstanding claim."""
        grant = _grant(budget=1)
        assert grant.reserve("t1", "https://example.com/page") is True
        assert grant.reserve("t2", "https://example.com/page") is False
        # Resume: after_model walks the whole message again.
        assert grant.reserve("t1", "https://example.com/page") is True
        assert grant.reserve("t2", "https://example.com/page") is False

    def test_many_reevaluations_of_one_call_never_exhaust_a_budget_of_one(self) -> None:
        grant = _grant(budget=1)
        results = [grant.reserve("t1", "https://example.com/page") for _ in range(20)]
        assert all(results)
        assert grant.remaining == 1


class TestRelease:
    """`release()`: giving back a claim `fetch.py` never redeemed.

    Important, not Critical, but real: a corpus hit, a memo hit, an httpx
    error and an HTTP error status all reserve at the gate and then never
    call `spend()` -- and in a research run over a growing corpus, cache
    hits are the common case, not the exception. Without `release()`, a
    grant of N degrades toward zero admissible claims after a handful of
    real requests, long before N fetches actually happened.
    """

    def test_releasing_a_claim_frees_its_room(self) -> None:
        grant = _grant(budget=1)
        grant.reserve("t1", "https://example.com/page")
        assert grant.reserve("t2", "https://example.com/page") is False
        grant.release("t1")
        assert grant.reserve("t2", "https://example.com/page") is True

    def test_releasing_does_not_touch_remaining(self) -> None:
        """Giving back a claim restores room for a future `reserve()`; it
        must not un-spend a unit that was never actually charged."""
        grant = _grant(budget=1)
        grant.reserve("t1", "https://example.com/page")
        grant.release("t1")
        assert grant.remaining == 1

    def test_releasing_an_id_that_was_never_reserved_is_a_no_op(self) -> None:
        """A human-approved, out-of-scope call never held a claim -- `fetch.py`
        still calls `release()` on it in its `finally`, and that must not
        raise or disturb anything else outstanding."""
        grant = _grant(budget=1)
        grant.reserve("t1", "https://example.com/page")
        grant.release("never-reserved")
        assert grant.reserve("t1", "https://example.com/page") is True  # still held
        assert grant.reserve("t2", "https://example.com/page") is False  # still no room

    def test_releasing_after_spend_is_a_harmless_no_op(self) -> None:
        """`fetch.py` calls `spend(call_id)` on success and then `release
        (call_id)` in its `finally` regardless -- `spend()` already
        discarded the id, so the second discard must do nothing."""
        grant = _grant(budget=1)
        grant.reserve("t1", "https://example.com/page")
        grant.spend("t1")
        grant.release("t1")
        assert grant.remaining == 0
        # No claim was un-spent by the redundant release.
        assert grant.reserve("t2", "https://example.com/page") is False


class TestGrantRegistry:
    def test_register_and_get_round_trips(self) -> None:
        registry = GrantRegistry()
        session_id = uuid4()
        grant = _grant()
        registry.register(session_id, grant)
        assert registry.get(session_id) is grant

    def test_get_on_unknown_session_is_none(self) -> None:
        registry = GrantRegistry()
        assert registry.get(uuid4()) is None

    def test_release_removes_the_grant(self) -> None:
        registry = GrantRegistry()
        session_id = uuid4()
        registry.register(session_id, _grant())
        registry.release(session_id)
        assert registry.get(session_id) is None

    def test_release_of_unregistered_session_does_not_raise(self) -> None:
        registry = GrantRegistry()
        registry.release(uuid4())

    def test_is_unattended_true_when_registered(self) -> None:
        registry = GrantRegistry()
        session_id = uuid4()
        registry.register(session_id, _grant())
        assert registry.is_unattended(session_id) is True

    def test_is_unattended_false_when_not_registered(self) -> None:
        registry = GrantRegistry()
        assert registry.is_unattended(uuid4()) is False

    def test_is_unattended_false_after_release(self) -> None:
        registry = GrantRegistry()
        session_id = uuid4()
        registry.register(session_id, _grant())
        registry.release(session_id)
        assert registry.is_unattended(session_id) is False
