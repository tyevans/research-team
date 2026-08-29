"""`AGENT_AUTH` in both of its states, because the default is the hard part.

This is the test the brief calls a hard requirement, and the reason is not
subtle: five other branches are in flight against `main`, none of them knows
identity exists, and every one of them has tests that call `/api/*` with no
cookie. If `AGENT_AUTH=off` is not byte-identical to the world before this
branch, all five go red at once and the cause looks like their change.

So the two halves are asserted separately and neither is enough alone. A build
that 401s everything passes the "on" half. A build with no gate at all passes
the "off" half. Only both together say what the flag means.
"""

import pytest
from fastapi.testclient import TestClient

from research_team.domain.settings import SettingError
from research_team.infrastructure import config
from research_team.interfaces.web import create_app
from research_team.interfaces.web.auth import (
    SESSION_COOKIE,
    AuthConfig,
    SessionSigner,
    SessionStore,
)

SECRET = "gate-test-secret"


def _app(*, enabled: bool):
    return create_app(
        service=None,
        feed=None,
        turns=None,
        auth=AuthConfig(
            enabled=enabled,
            client=None,
            signer=SessionSigner.from_config(SECRET),
            sessions=SessionStore(),
            public_url="http://console.test",
        ),
    )


def _client(*, enabled: bool) -> TestClient:
    # `raise_server_exceptions=False`, because these routes are deliberately
    # unwired: `/api/sessions` calls `service.list_sessions()` on a `None`
    # service and raises. Re-raising it into the test would hide the only
    # thing being measured -- whether the request *reached* the route at all,
    # which a 500 answers just as well as a 200 and a 401 does not.
    return TestClient(_app(enabled=enabled), raise_server_exceptions=False)


def _session_cookie(subject: str = "user-1") -> str:
    import time

    return SessionSigner.from_config(SECRET).sign(
        {
            "sid": "session-1",
            "sub": subject,
            "tid": "org-1",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
    )


# Routes chosen for what they *are*, not because they are convenient: one that
# needs no wiring at all (`/api/projects` 500s without a service, which is
# still not a 401), one that answers 503 when unwired, and one that is exempt.
# A gate that only covered the first would look correct on a test that only
# used the first.
GATED = ("/api/sessions", "/api/health", "/api/projects/anything/sources")
EXEMPT = ("/api/auth/status", "/api/docs")


@pytest.mark.parametrize("path", GATED)
def test_with_auth_on_an_unauthenticated_api_request_is_401(path):
    """The enabled half.

    Asserts 401 specifically, not "not 200": a 503 from an unwired dependency
    would satisfy a looser assertion while proving the gate never ran.
    """
    response = _client(enabled=True).get(path)
    assert response.status_code == 401
    assert response.json()["detail"] == "not signed in"


@pytest.mark.parametrize("path", GATED)
def test_with_auth_on_a_signed_in_request_passes_the_gate(path):
    """The other side of the enabled half.

    Without this, a gate that 401s unconditionally passes the test above. What
    is asserted is only that the answer is *not* 401 -- these routes are
    unwired in this app and answer 503 or 500, which is the correct behaviour
    for an app built with no service and says nothing about auth.
    """
    client = _client(enabled=True)
    client.cookies.set(SESSION_COOKIE, _session_cookie())
    assert client.get(path).status_code != 401


@pytest.mark.parametrize("path", GATED)
def test_with_auth_off_every_api_route_answers_as_it_did(path):
    """The default, and the thing this flag exists for.

    An unauthenticated request must reach the route. The status it then gets
    is whatever an unwired app gives -- what matters is that it is not 401,
    because 401 is the only status this branch can have introduced.

    This test fails if `AuthGate` is ever changed to check a cookie before
    reading `enabled`, which is the shape of the mistake that would break the
    other five branches.
    """
    assert _client(enabled=False).get(path).status_code != 401


@pytest.mark.parametrize("path", EXEMPT)
def test_the_routes_a_signed_out_browser_needs_are_never_gated(path):
    """A signed-out console has to be able to ask whether to show a login.

    `/api/auth/status` behind the gate would make that question unanswerable
    without already having answered it.
    """
    assert _client(enabled=True).get(path).status_code == 200


def test_the_flag_defaults_to_off():
    """`config.auth_enabled()` with nothing set.

    Read from `config` rather than from a constant, because the default is a
    string comparison and `AGENT_AUTH=off` reading as true under a bare
    truthiness test is exactly the bug this guards.
    """
    assert config.auth_enabled() is False


@pytest.mark.parametrize(("value", "expected"), [("on", True), ("off", False), ("", False)])
def test_the_flag_accepts_exactly_two_words(monkeypatch, value, expected):
    """`on`, `off`, and unset. Nothing else.

    This list used to hold `1`/`true`/`yes` and their negatives, because the
    reader was a word set of the kind every other flag in `config.py` uses.
    `AGENT_AUTH` is declared as an **enum** now and those are refused -- see
    the test below, which is the half that matters.
    """
    monkeypatch.setenv("AGENT_AUTH", value)
    assert config.auth_enabled() is expected


@pytest.mark.parametrize("refused", ["onn", "enabled", "yess", "0ff", "1", "true", "yes"])
def test_a_value_that_is_neither_on_nor_off_is_refused(monkeypatch, refused):
    """A typo must not read as "off".

    The asymmetry is the point, and it is why this flag is an enum where every
    other boolean in `config.py` is a forgiving word set: the two directions of
    a mistake are not equivalent. A spelling that silently turns authentication
    *off* is an open server nobody notices; one that raises at startup is an
    outage somebody fixes in a second. For `AGENT_TRACING` the same typo costs a
    missing span.

    `0ff` is the case that earns the parametrisation: a typo of a value meaning
    *off*, where a reader falling back to off gives the intended answer for the
    wrong reason and this test is the only thing that would notice.

    `1`, `true` and `yes` are here as a *contract* rather than as typos. They
    are what every other flag in this module accepts, so somebody will write
    one, and it must fail loudly rather than being guessed at -- which also
    documents that this list changed deliberately when the enum landed.
    """
    monkeypatch.setenv("AGENT_AUTH", refused)
    with pytest.raises(SettingError):
        config.auth_enabled()


def test_an_app_built_with_no_auth_argument_at_all_is_ungated():
    """Every existing test builds `create_app` without `auth=`.

    There are dozens of them across `tests/interfaces/`, and this asserts the
    property they all silently depend on: the default `AuthConfig` is
    disabled. It would pass with the default removed entirely and
    `app.state.auth` absent, which is also fine -- `principal_of` handles that
    -- so what this really pins is "no argument never means gated".
    """
    http = TestClient(
        create_app(service=None, feed=None, turns=None), raise_server_exceptions=False
    )
    assert http.get("/api/sessions").status_code != 401
