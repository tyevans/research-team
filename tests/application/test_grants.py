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

    def test_covers_does_not_spend(self) -> None:
        grant = _grant(budget=1)
        grant.covers("https://example.com/page")
        grant.covers("https://example.com/page")
        grant.covers("https://example.com/page")
        # Budget must still be intact -- repeated covers() calls are free.
        assert grant.covers("https://example.com/page") is True
        grant.spend()
        assert grant.covers("https://example.com/page") is False


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
