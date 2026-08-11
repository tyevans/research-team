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
    """`reserve()`: the gate-side claim that closes the batch over-spend.

    See `FetchGrant`'s docstring and `task-5-review.md` for what this closes:
    every call in one assistant message is evaluated against the same
    unspent budget before any of them runs, so a plain `covers()` check at
    the gate lets all of them through. `reserve()` decrements as it goes, so
    the second covered call in a batch sees the first one's claim.
    """

    def test_a_covered_url_may_be_reserved(self) -> None:
        grant = _grant(budget=1)
        assert grant.reserve("https://example.com/page") is True

    def test_reserving_does_not_touch_remaining(self) -> None:
        """`covers()`/`spend()` in `fetch.py` must see the real budget,
        untouched by an outstanding reservation -- see the class docstring."""
        grant = _grant(budget=1)
        grant.reserve("https://example.com/page")
        assert grant.remaining == 1
        assert grant.covers("https://example.com/page") is True

    def test_a_second_reservation_on_a_budget_of_one_is_refused(self) -> None:
        """The batch fix itself: two claims, one unit of budget."""
        grant = _grant(budget=1)
        assert grant.reserve("https://example.com/page") is True
        assert grant.reserve("https://example.com/page") is False

    def test_ten_reservations_on_a_budget_of_one_admit_exactly_one(self) -> None:
        """The shape of the actual reproduction: N covered calls evaluated
        one after another (as `HumanInTheLoopMiddleware` walks one message's
        tool calls) against a budget of one."""
        grant = _grant(budget=1)
        admitted = sum(grant.reserve("https://example.com/page") for _ in range(10))
        assert admitted == 1

    def test_an_uncovered_url_is_never_reserved(self) -> None:
        grant = _grant(budget=3)
        assert grant.reserve("https://other.com/page") is False
        assert grant.reserve("https://example.com/page") is True
        assert grant.reserve("https://example.com/page") is True
        assert grant.reserve("https://example.com/page") is True
        # The refused claim above cost nothing; three, not two, were left.
        assert grant.reserve("https://example.com/page") is False

    def test_spend_releases_the_reservation_it_corresponds_to(self) -> None:
        grant = _grant(budget=2)
        grant.reserve("https://example.com/page")
        grant.spend()
        # The reservation is gone, so a second claim now has room again.
        assert grant.reserve("https://example.com/page") is True
        assert grant.reserve("https://example.com/page") is False

    def test_spend_with_no_outstanding_reservation_does_not_go_negative(self) -> None:
        """Every direct-tool test in `test_fetch.py` calls `spend()` without
        ever reserving -- `_reserved` must floor at zero rather than go
        negative and quietly grant extra room to a later `reserve()`."""
        grant = _grant(budget=2)
        grant.spend()
        grant.spend()
        assert grant.reserve("https://example.com/page") is False

    def test_an_unspent_reservation_leaks_toward_fewer_fetches_not_more(self) -> None:
        """The accepted trade, pinned: a reservation nothing ever spends
        makes the grant strictly more conservative, never less."""
        grant = _grant(budget=1)
        grant.reserve("https://example.com/page")
        # Nothing ever called spend() for that reservation -- refused by a
        # human, say, or the call errored before reaching its own spend().
        assert grant.reserve("https://example.com/page") is False
        assert grant.covers("https://example.com/page") is True
        assert grant.remaining == 1


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
