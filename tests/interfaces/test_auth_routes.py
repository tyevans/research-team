"""The OIDC flow, end to end, against an issuer that really signs tokens.

Every test here drives `create_app`'s own routes with a real `OidcClient`
pointed at `FakeIssuer` over an ASGI transport, so the token is genuinely
verified rather than a `Claims` handed straight back by a double. The
alternative -- stubbing `OidcClient.exchange` -- would leave every check in
`_verified_claims` untested, and those checks are the entire security
argument of this feature.

The tests that matter most are the refusals. A happy-path sign-in passes with
`iss`, `aud`, `nonce` and signature checking all deleted, so the happy path
proves almost nothing on its own.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from research_team.infrastructure.identity import OidcClient
from research_team.interfaces.web import create_app
from research_team.interfaces.web.auth import (
    FLOW_COOKIE,
    SESSION_COOKIE,
    AuthConfig,
    SessionSigner,
    SessionStore,
    _safe_next,
)
from tests.interfaces.fake_issuer import CLIENT_ID, FakeIssuer


class RecordingRecorder:
    """Captures what the callback recorded, and answers no read model.

    A recorder rather than the real one because these tests are about the HTTP
    flow, not the projection -- the projection is driven over a real event
    store in
    `tests/integration/test_a_sign_in_reaches_the_user_read_model.py`, which
    is where CLAUDE.md's "assert the row exists" rule is discharged. Asserting
    on this object here would be asserting on the double, and is only done to
    check that recording happens *at all*.
    """

    def __init__(self) -> None:
        self.recorded = []

    async def record_sign_in(self, claims):
        self.recorded.append(claims)
        return claims


@pytest.fixture
def issuer() -> FakeIssuer:
    return FakeIssuer()


@pytest.fixture
def recorder() -> RecordingRecorder:
    return RecordingRecorder()


@pytest.fixture
def auth(issuer, recorder) -> AuthConfig:
    return AuthConfig(
        enabled=True,
        client=OidcClient(
            issuer=issuer.issuer,
            client_id=CLIENT_ID,
            client_secret="shh",
            transport=httpx.ASGITransport(app=issuer.app),
        ),
        # A fixed secret, so the cookies a test mints and the cookies the app
        # verifies are signed with the same key. `from_config("")` mints a
        # random one per call, which is correct in production and would make
        # every assertion here depend on object identity.
        signer=SessionSigner.from_config("test-secret"),
        sessions=SessionStore(),
        public_url="http://console.test",
        recorder=recorder,
        users=None,
    )


@pytest.fixture
def client(auth) -> TestClient:
    # `follow_redirects=False` throughout: every interesting assertion here is
    # about a `Location` header or a `Set-Cookie`, and following would replace
    # both with whatever the destination answered.
    return TestClient(
        create_app(service=None, feed=None, turns=None, auth=auth),
        follow_redirects=False,
    )


def _start_flow(client: TestClient, **params) -> httpx.Response:
    response = client.get("/auth/login", params=params)
    assert response.status_code == 302
    return response


def _flow_values(auth: AuthConfig, client: TestClient) -> dict:
    return auth.signer.verify(client.cookies[FLOW_COOKIE])


def test_login_redirects_to_the_issuer_with_pkce_and_a_nonce(client, auth, issuer):
    """The authorization request carries every parameter the callback checks.

    Asserted on the `Location` rather than on `OidcClient`, because a
    parameter this app builds correctly and then fails to *send* is
    indistinguishable from one it never built.
    """
    response = _start_flow(client)
    location = httpx.URL(response.headers["location"])
    assert str(location).startswith(f"{issuer.issuer}/authorize")
    assert location.params["response_type"] == "code"
    assert location.params["client_id"] == CLIENT_ID
    assert location.params["code_challenge_method"] == "S256"
    assert location.params["code_challenge"]
    assert location.params["nonce"]
    assert location.params["redirect_uri"] == "http://console.test/auth/callback"
    # The flow cookie holds the verifier, and the challenge in the URL must be
    # its S256 digest -- otherwise the issuer would reject the exchange and
    # this test would still pass with a challenge derived from nothing.
    flow = _flow_values(auth, client)
    assert flow["verifier"]
    assert flow["state"] == location.params["state"]
    assert flow["nonce"] == location.params["nonce"]


def test_signup_asks_the_issuer_for_the_registration_screen(client):
    """`prompt=create` is the whole of the sign-up handoff.

    Would pass with the parameter hard-coded, so the negative is asserted
    beside it: an ordinary login must *not* carry it, or every sign-in would
    land on a register form.
    """
    with_signup = httpx.URL(_start_flow(client, signup="true").headers["location"])
    without = httpx.URL(_start_flow(client).headers["location"])
    assert with_signup.params["prompt"] == "create"
    assert "prompt" not in without.params


def test_a_completed_flow_sets_a_session_cookie_and_records_the_sign_in(
    client, auth, issuer, recorder
):
    """The happy path: verified claims become a session and an appended event.

    Weak on its own -- see the module docstring -- so it asserts the *claims*
    that came out of verification rather than only the status, and the
    refusals below are what give it meaning.
    """
    _start_flow(client, next="/p/abc")
    flow = _flow_values(auth, client)
    issuer.next_id_token = issuer.sign_id_token(nonce=flow["nonce"], subject="user-7")

    response = client.get("/auth/callback", params={"code": "c", "state": flow["state"]})

    assert response.status_code == 302
    assert response.headers["location"] == "/p/abc"
    assert client.cookies.get(SESSION_COOKIE)
    session = auth.signer.verify(client.cookies[SESSION_COOKIE])
    assert session["sub"] == "user-7"
    assert session["tid"] == "org-42"
    assert len(recorder.recorded) == 1
    assert recorder.recorded[0].email == "ada@example.test"
    assert recorder.recorded[0].display_name == "Ada Lovelace"
    # The verifier reached the issuer. Nothing else can see this: an exchange
    # that silently dropped `code_verifier` succeeds against a fake that does
    # not check, and against a real issuer fails only in production.
    assert issuer.last_form.get("code_verifier") == flow["verifier"]


def test_the_session_id_is_fresh_on_every_sign_in(client, auth, issuer):
    """Rotation, which is what defeats session fixation.

    Signs in twice in the same client -- so the second callback sees the first
    sign-in's cookie already present -- and requires the ids to differ. Reusing
    the existing cookie's `sid` would pass every other test in this file.
    """
    seen = []
    for _ in range(2):
        _start_flow(client)
        flow = _flow_values(auth, client)
        issuer.next_id_token = issuer.sign_id_token(nonce=flow["nonce"])
        client.get("/auth/callback", params={"code": "c", "state": flow["state"]})
        seen.append(auth.signer.verify(client.cookies[SESSION_COOKIE])["sid"])
    assert seen[0] != seen[1]


def test_the_session_cookie_is_httponly_and_samesite_lax(client, auth, issuer):
    """The cookie attributes are the whole reason a cookie was chosen.

    Asserted on the raw `set-cookie` header rather than on the jar, because
    `http.cookiejar` discards the attributes this test exists to check.
    """
    _start_flow(client)
    flow = _flow_values(auth, client)
    issuer.next_id_token = issuer.sign_id_token(nonce=flow["nonce"])
    response = client.get("/auth/callback", params={"code": "c", "state": flow["state"]})
    header = next(
        value
        for key, value in response.headers.multi_items()
        if key.lower() == "set-cookie" and value.startswith(f"{SESSION_COOKIE}=")
    )
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    # No `Secure`, because `public_url` is http. A `Secure` cookie on a plain
    # origin is dropped by the browser, which presents as "sign-in works and
    # nothing is signed in" -- the failure this asymmetry avoids.
    assert "Secure" not in header


@pytest.mark.parametrize(
    ("name", "mutate"),
    [
        # Each of these is a token an attacker could plausibly obtain or mint.
        # Parametrised over what *distinguishes* the checks rather than over a
        # representative sample, per CLAUDE.md: a single "bad token" case would
        # pass with three of the four checks deleted.
        ("wrong audience", {"audience": "some-other-client"}),
        ("wrong issuer", {"issuer": "https://evil.test"}),
        ("stale nonce", {"nonce": "a-nonce-from-another-flow"}),
        ("expired", {"expires_in": -60}),
    ],
)
def test_a_token_that_fails_any_check_is_not_a_sign_in(client, auth, issuer, name, mutate):
    """Four separate refusals, each isolated to one claim.

    Every one of these produced a 302 and a session cookie before the check it
    exercises existed; each fails alone if that check is removed.
    """
    _start_flow(client)
    flow = _flow_values(auth, client)
    issuer.next_id_token = issuer.sign_id_token(**{"nonce": flow["nonce"], **mutate})

    response = client.get("/auth/callback", params={"code": "c", "state": flow["state"]})

    assert response.status_code == 400, name
    assert client.cookies.get(SESSION_COOKIE) is None, name


def test_a_token_signed_by_an_unpublished_key_is_not_a_sign_in(client, auth, issuer):
    """A well-formed token from a stranger.

    Distinct from the parametrised cases above and worth its own test: those
    are claim checks over a validly signed token, and this is the signature
    check itself. A build that decoded the token without verifying passes
    every case above and fails only here.
    """
    _start_flow(client)
    flow = _flow_values(auth, client)
    issuer.next_id_token = issuer.sign_id_token(
        nonce=flow["nonce"], key=issuer.unpublished_key
    )

    response = client.get("/auth/callback", params={"code": "c", "state": flow["state"]})

    assert response.status_code == 400
    assert client.cookies.get(SESSION_COOKIE) is None


def test_a_callback_with_a_mismatched_state_is_refused(client, auth, issuer):
    """Login CSRF: a code the victim's browser did not ask for.

    Invisible to every functional test, because a real flow never has a
    mismatched state. Deleting the comparison in `callback` turns only this
    test red.
    """
    _start_flow(client)
    flow = _flow_values(auth, client)
    issuer.next_id_token = issuer.sign_id_token(nonce=flow["nonce"])

    response = client.get("/auth/callback", params={"code": "c", "state": "not-the-state"})

    assert response.status_code == 400
    assert client.cookies.get(SESSION_COOKIE) is None


def test_a_callback_with_no_flow_cookie_is_refused(client, issuer):
    """A callback that did not start here.

    The flow cookie is deleted by the callback that consumes it, so this is
    also what a replayed callback URL meets.
    """
    issuer.next_id_token = issuer.sign_id_token()
    response = client.get("/auth/callback", params={"code": "c", "state": "s"})
    assert response.status_code == 400


def test_logout_clears_the_cookie_and_revokes_the_session(client, auth, issuer):
    """Both halves: the browser's copy and this process's record.

    The revocation is the half that is easy to omit and impossible to see --
    clearing the cookie alone makes logout *look* complete, and a copied
    cookie goes on working. Asserted by replaying the session cookie after
    logout, which is exactly the thing revocation exists to stop.
    """
    _start_flow(client)
    flow = _flow_values(auth, client)
    issuer.next_id_token = issuer.sign_id_token(nonce=flow["nonce"])
    client.get("/auth/callback", params={"code": "c", "state": flow["state"]})
    stolen = client.cookies[SESSION_COOKIE]

    assert client.get("/api/me", cookies={SESSION_COOKIE: stolen}).status_code == 200

    response = client.get("/auth/logout")
    assert response.status_code == 302
    assert response.headers["location"].startswith(f"{issuer.issuer}/logout")
    assert client.get("/api/me", cookies={SESSION_COOKIE: stolen}).status_code == 401


def test_a_forged_session_cookie_is_not_a_session(client, auth):
    """An unsigned payload naming any subject.

    The one thing the signature buys. Built by hand rather than by tampering
    with a real cookie, so the payload is exactly what an attacker would want
    and the only thing missing is the HMAC.
    """
    import base64
    import json

    payload = base64.urlsafe_b64encode(
        json.dumps({"sid": "x", "sub": "admin", "exp": 9999999999}).encode()
    ).rstrip(b"=")
    forged = f"{payload.decode()}.{payload.decode()}"
    assert client.get("/api/me", cookies={SESSION_COOKIE: forged}).status_code == 401


def test_me_is_401_without_a_session(client):
    """`CurrentUser`, applied to the one route W-A owns.

    A 401 rather than 200-with-nulls, because the console reads this status as
    "send me to login"; a 200 would need the body inspected to tell a signed-in
    person from a signed-out one.
    """
    assert client.get("/api/me").status_code == 401


def test_auth_status_answers_without_a_session(client):
    """The gate exempts this route, so a signed-out console can ask.

    Fails if `/api/auth/status` is ever moved behind the gate -- which would
    make the console guess whether to show a login screen.
    """
    body = client.get("/api/auth/status").json()
    assert body == {
        "auth_required": True,
        "authenticated": False,
        "configured": True,
        "subject": None,
    }


def test_login_answers_503_when_no_issuer_is_configured():
    """A build with identity code and no identity provider says so.

    503 rather than 404: a 404 could not be told apart from a mistyped URL,
    and the login screen needs to be able to say "this instance has no
    identity provider" out loud.
    """
    unconfigured = AuthConfig(
        enabled=False,
        client=None,
        signer=SessionSigner.from_config("x"),
        sessions=SessionStore(),
        public_url="http://console.test",
    )
    http = TestClient(
        create_app(service=None, feed=None, turns=None, auth=unconfigured),
        follow_redirects=False,
    )
    assert http.get("/auth/login").status_code == 503


@pytest.mark.parametrize(
    "candidate",
    [
        "https://evil.test/steal",
        "//evil.test/steal",
        "/\\evil.test",
        "http://evil.test",
        "javascript:alert(1)",
    ],
)
def test_an_off_origin_next_is_discarded(candidate):
    """Open redirect, closed by refusal rather than by sanitising.

    Parametrised over the *shapes* that defeat a naive check rather than over
    a sample of URLs: `//host` and `/\\host` both start with `/` and are both
    off-origin, and a check that only looked for a scheme would pass them.
    """
    assert _safe_next(candidate) == "/"


def test_a_same_origin_next_survives():
    """The other half, without which the test above passes on a function that
    always returns `/`."""
    assert _safe_next("/p/abc?tab=graph") == "/p/abc?tab=graph"


def test_a_thin_id_token_is_filled_in_from_userinfo(client, auth, issuer, recorder):
    """The account menu drew a snowflake id until this existed.

    Found by signing in to a live Zitadel on 2026-08-29, not by a test: the
    flow completed, the cookie was set and the `users` row was written, with
    `email`, `display_name` and `tenant_id` all empty. Zitadel does not assert
    profile claims into an ID token unless the application opts in, and OIDC
    permits that -- so `Claims` built from the ID token alone was a display
    surface with nothing on it.

    The ID token here carries `sub` and nothing else, which is the shape that
    was shipping.
    """
    issuer.userinfo = {
        "sub": "user-7",
        "email": "ada@example.test",
        "name": "Ada Lovelace",
        "urn:zitadel:iam:user:resourceowner:id": "org-42",
    }
    _start_flow(client)
    flow = _flow_values(auth, client)
    issuer.next_id_token = issuer.sign_id_token(
        nonce=flow["nonce"], subject="user-7", email="", name="", tenant_id=""
    )

    response = client.get("/auth/callback", params={"code": "c", "state": flow["state"]})

    assert response.status_code == 302
    assert recorder.recorded[0].display_name == "Ada Lovelace"
    assert recorder.recorded[0].email == "ada@example.test"
    assert recorder.recorded[0].tenant_id == "org-42"


def test_userinfo_is_not_asked_when_the_id_token_already_answers(client, auth, issuer):
    """A well-configured issuer pays nothing.

    The half that stops the fallback becoming an unconditional second round
    trip on every sign-in. Deleting the `if claims.email or ...` guard leaves
    every other test in this file green and turns only this one red.
    """
    _start_flow(client)
    flow = _flow_values(auth, client)
    issuer.next_id_token = issuer.sign_id_token(nonce=flow["nonce"])

    client.get("/auth/callback", params={"code": "c", "state": flow["state"]})

    assert issuer.userinfo_calls == 0


def test_a_userinfo_answer_for_another_subject_is_discarded(client, auth, issuer, recorder):
    """Userinfo is a bearer-token response, not a signed assertion.

    So it may not decide who the person is. A build that merged it blindly
    would let whatever answered that endpoint rename -- and, once W-B reads
    `tenant_id`, re-scope -- an authenticated subject. The sign-in still
    succeeds, under the thin profile the verified token actually carried.
    """
    issuer.userinfo = {"sub": "somebody-else", "email": "mallory@example.test"}
    _start_flow(client)
    flow = _flow_values(auth, client)
    issuer.next_id_token = issuer.sign_id_token(
        nonce=flow["nonce"], subject="user-7", email="", name="", tenant_id=""
    )

    response = client.get("/auth/callback", params={"code": "c", "state": flow["state"]})

    assert response.status_code == 302
    assert recorder.recorded[0].subject == "user-7"
    assert recorder.recorded[0].email == ""


def test_a_refused_userinfo_is_not_a_failed_sign_in(client, auth, issuer, recorder):
    """A cosmetic gap must not become a login outage.

    `issuer.userinfo` is `None`, so the endpoint answers 404. The person is
    signed in with the thin profile the token carried, which `AccountMenu`'s
    `NothingButASubject` story is the rendering of.
    """
    _start_flow(client)
    flow = _flow_values(auth, client)
    issuer.next_id_token = issuer.sign_id_token(
        nonce=flow["nonce"], subject="user-7", email="", name="", tenant_id=""
    )

    response = client.get("/auth/callback", params={"code": "c", "state": flow["state"]})

    assert response.status_code == 302
    assert client.cookies.get(SESSION_COOKIE)
    assert recorder.recorded[0].subject == "user-7"
