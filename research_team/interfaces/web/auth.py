"""Sign-in, sign-out, the session cookie, and the dependency routes ask for.

Four routes (`/auth/login`, `/auth/callback`, `/auth/logout`, `/api/me`), one
cookie format, one FastAPI dependency and its optional variant. Everything
about *who* a person is comes from `infrastructure/identity/oidc.py`; nothing
here decodes a token.

## Why a cookie and not a bearer token in localStorage

A token in `localStorage` is readable by any script that runs on the origin.
This console renders model output, document text, course markdown and entity
definitions -- all of it produced by an LLM over text this system fetched from
the web -- so "any script that runs on the origin" is not a hypothetical
category here. One successful injection anywhere in that chain reads the token
and it is exfiltrated with no trace in any log this project keeps, and it
remains valid until it expires.

An `httpOnly` cookie is unreadable from JavaScript by construction, so the
same injection can *use* the session (it can issue requests, which is real and
not fixed by this) but cannot take it away. That distinction -- forge requests
from inside the page versus hold the credential afterwards -- is the whole of
the trade, and it is worth the costs, which are real:

- Cookies are sent automatically, so CSRF becomes this app's problem where a
  bearer header made it structurally impossible. `SameSite=Lax` is the answer
  taken here: it withholds the cookie on cross-site POST/PUT/DELETE, which is
  every state-changing route in this app, while still sending it on the
  top-level GET navigation the OIDC callback *is* -- which is exactly why
  `Lax` and not `Strict`. `Strict` would drop the cookie on the redirect back
  from Zitadel and the callback would set a session the very next request
  could not see.
- A cookie is per-origin, so a future native or CLI client cannot reuse this
  path and will need a token endpoint of its own. Deliberately not built:
  there is no such client, and an unused credential-issuing endpoint is
  attack surface with no user.

`Secure` is set whenever the configured public URL is https, and not otherwise
-- a `Secure` cookie on `http://localhost:8000` is silently discarded by the
browser, which presents as "sign-in succeeds and then nothing is signed in".

## Why the flow's state lives in a cookie too

`state`, `nonce` and the PKCE verifier have to survive from `/auth/login` to
`/auth/callback`. A dict on the app object would work in one process and fail
under more than one worker, intermittently and only under load -- the worst
available failure. They go in a second short-lived signed cookie instead,
which is stateless, correct under any number of workers, and deleted the
moment the callback consumes it.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.datastructures import Headers

from research_team.infrastructure.identity import Claims, OidcClient, OidcError
from research_team.infrastructure.identity.oidc import new_pkce_pair

SESSION_COOKIE = "rt_session"
FLOW_COOKIE = "rt_auth_flow"

SESSION_MAX_AGE = 60 * 60 * 12
"""Twelve hours: one working day, and no more.

Chosen rather than defaulted. Longer means a stolen laptop stays signed in
overnight; shorter means being signed out mid-afternoon, which people work
around by never signing out at all. There is no refresh path (see `SCOPES` in
`oidc.py` for why `offline_access` is not requested), so this number is the
whole session lifetime and not a token's -- re-authenticating is one redirect
through an IdP that usually still has its own session, so the cost of being
wrong on the short side is a flicker.
"""

FLOW_MAX_AGE = 10 * 60
"""How long a half-finished login stays resumable.

Ten minutes bounds how long a `state`/`nonce`/verifier triple is worth
replaying if it leaks, and it is comfortably longer than any human sign-in
including a password reset detour. An expired flow cookie is a 400 telling the
person to start again, not a silent redirect loop.
"""


class SessionSigner:
    """Signs and verifies the session payload with HMAC-SHA256.

    Stdlib `hmac`, not `itsdangerous` and not JWT. The payload is four short
    fields this process both writes and reads; there is no second party to
    interoperate with, so a JWT would buy a header, an algorithm negotiation
    and the `alg: none` family of mistakes in exchange for nothing. What is
    actually needed -- "this string came from this process and has not been
    edited" -- is one HMAC and a constant-time compare.

    The signature covers the *encoded* payload rather than the decoded dict,
    so there is no canonicalisation question: what was signed is byte-for-byte
    what is verified.
    """

    def __init__(self, key: bytes) -> None:
        self._key = key

    @classmethod
    def from_config(cls, secret: str) -> "SessionSigner":
        """Derive a key from the configured secret, or mint one at random.

        Minting rather than falling back to a constant, per
        `config.session_secret`'s docstring: a shipped default key is the same
        as no signature. The cost is stated there too -- an unconfigured
        instance signs everybody out on restart, which is loud and harmless,
        where a shared default is silent and not.

        The configured secret is hashed rather than used raw so that a short
        or low-entropy value still yields a full-length key. That does not
        *add* entropy and is not pretending to; it only stops a two-character
        secret producing a two-byte HMAC key.
        """
        if secret:
            return cls(hashlib.sha256(secret.encode("utf-8")).digest())
        return cls(secrets.token_bytes(32))

    def sign(self, payload: dict) -> str:
        encoded = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True))
        signature = hmac.new(self._key, encoded.encode("ascii"), hashlib.sha256).digest()
        return f"{encoded}.{_b64encode_bytes(signature)}"

    def verify(self, token: str) -> dict | None:
        """The payload, or None for anything that is not a valid signature.

        `None` rather than an exception for every failure mode -- a malformed
        cookie, a truncated one, a forged one -- because every caller treats
        them identically as "not signed in", and distinguishing them in a
        response would tell an attacker which half of their forgery was
        wrong.
        """
        encoded, _, provided = token.partition(".")
        if not encoded or not provided:
            return None
        expected = hmac.new(self._key, encoded.encode("ascii"), hashlib.sha256).digest()
        try:
            given = _b64decode_bytes(provided)
        except Exception:  # noqa: BLE001 - any decode failure is "not signed in"
            return None
        if not hmac.compare_digest(expected, given):
            return None
        try:
            payload = json.loads(_b64decode(encoded))
        except Exception:  # noqa: BLE001
            return None
        return payload if isinstance(payload, dict) else None


@dataclass(frozen=True)
class Principal:
    """The authenticated person, as far as any route is concerned.

    Assembled from the *cookie*, not from the read model, and that is the
    choice worth defending: reading `users` per request would make every
    authenticated call a database read, and would make the whole app fail
    when the projection is behind. The cookie carries what routes need to
    make decisions (`subject`, `tenant_id`) and `/api/me` alone joins to the
    read model for the things that are only for display.

    The cost: a display name changed in Zitadel is stale in this object until
    the next sign-in. Nothing decides anything on `display_name`, so that is a
    cosmetic staleness -- and `/api/me` reads the mirror, so the account menu
    is right as soon as the projection is.
    """

    subject: str
    tenant_id: str
    session_id: str
    issued_at: int


class SessionStore:
    """Which sessions have been signed out, so a live cookie stops working.

    A process-local set of revoked session ids, and the honesty about what
    that is worth matters more than the code. Deleting the cookie is what
    actually signs a person out of their own browser; this set exists for the
    case the cookie was *copied* before logout, where deletion reaches only
    one of the two holders.

    What it does not survive: a restart, and a second process. Both re-admit a
    copied cookie until it expires. Making it survive means a table and a
    write on every request to check it, which is a real cost for a threat
    (a stolen cookie, revoked, replayed across a redeploy) that this
    single-instance, locally-run application does not plausibly face today.
    Named here rather than left as an unstated gap: the moment this is
    deployed as more than one process, this class has to become a row.
    """

    def __init__(self) -> None:
        self._revoked: set[str] = set()

    def revoke(self, session_id: str) -> None:
        self._revoked.add(session_id)

    def is_revoked(self, session_id: str) -> bool:
        return session_id in self._revoked


@dataclass
class AuthConfig:
    """Everything the auth routes need, resolved once at wiring time.

    A record rather than reading `config` inside the routes, so that a test
    can build an app whose issuer is a fake ASGI app without touching the
    environment -- and so that `enabled` is decided at startup rather than
    re-read per request, which would let a route's behaviour change under a
    running process.
    """

    enabled: bool
    client: OidcClient | None
    signer: SessionSigner
    sessions: SessionStore
    public_url: str
    recorder: object | None = None
    """`EventStoreUserRecorder`, or None when nothing should be written.

    Typed as `object` because `interfaces/` importing a concrete
    `infrastructure/` class for a *type* is the direction the architecture
    test allows but the layering discourages; the only thing called on it is
    `record_sign_in`.
    """

    users: object | None = None
    """The started `UserRunner`, for `/api/me` to join display fields from."""

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_url}/auth/callback"

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")


def _unauthenticated() -> HTTPException:
    return HTTPException(status_code=401, detail="not signed in")


def principal_of(request: Request) -> Principal | None:
    """The signed-in person, or None. The one place a cookie becomes a person.

    Reads `app.state.auth`, so an app built without auth wiring answers None
    rather than raising -- which is what keeps `OptionalUser` usable on a
    route in an app that has no identity configured at all.
    """
    auth: AuthConfig | None = getattr(request.app.state, "auth", None)
    if auth is None:
        return None
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    payload = auth.signer.verify(raw)
    if payload is None:
        return None
    session_id = str(payload.get("sid", ""))
    subject = str(payload.get("sub", ""))
    expires = int(payload.get("exp", 0))
    if not session_id or not subject:
        return None
    # Expiry is checked here as well as being set as the cookie's `Max-Age`,
    # because `Max-Age` is a request the browser is free to ignore and a
    # copied cookie is replayed by something that is not a browser at all. The
    # signed `exp` is the one an attacker cannot edit.
    if expires and expires < int(time.time()):
        return None
    if auth.sessions.is_revoked(session_id):
        return None
    return Principal(
        subject=subject,
        tenant_id=str(payload.get("tid", "")),
        session_id=session_id,
        issued_at=int(payload.get("iat", 0)),
    )


def current_user(request: Request) -> Principal:
    """The signed-in person, or 401.

    When `AGENT_AUTH` is off this always raises, and that is the intended
    reading rather than an oversight: with auth off there is genuinely nobody
    to describe, and inventing an anonymous principal would mean every route
    W-B later protects silently passing for everyone. A route that needs a
    person needs auth on.
    """
    person = principal_of(request)
    if person is None:
        raise _unauthenticated()
    return person


def optional_user(request: Request) -> Principal | None:
    """The signed-in person, or None -- never a 401.

    For routes that render differently for a known person but must still
    answer for an unknown one. W-B will need far more of these than of
    `CurrentUser`: most of this app's routes are readable by a signed-out
    developer today, and turning all ninety into 401s in one commit is
    precisely what `AGENT_AUTH` exists to avoid.
    """
    return principal_of(request)


CurrentUser = Annotated[Principal, Depends(current_user)]
OptionalUser = Annotated[Principal | None, Depends(optional_user)]


class AuthGate:
    """401s unauthenticated `/api/*` requests when auth is on.

    A plain ASGI callable and not `@app.middleware("http")`, for the measured
    reason `_InteractionBodyCap`'s docstring in `app.py` gives: the decorator
    is `BaseHTTPMiddleware`, which runs endpoints inside its own anyio task
    group and breaks every route here that schedules fire-and-forget work.
    That failure names nothing about middleware, so it is worth stating twice.

    **Off means absent, not permissive.** When `AGENT_AUTH` is off this
    forwards unconditionally on the first line, so an instance with auth off
    is byte-identical to one built before this class existed. That is what
    keeps the other five workstreams' branches green, and
    `test_auth_gate.py::test_with_auth_off_every_api_route_answers_as_it_did`
    is the assertion.

    The exemptions are the routes a signed-out browser must be able to reach
    to *become* signed in, plus the API docs. `/api/me` is deliberately not
    exempt: the console reads a 401 there as "send me to login", which is the
    signal it needs, and an exempt `/api/me` answering 200-with-nobody would
    be indistinguishable from an instance with auth off.
    """

    EXEMPT_PREFIXES = ("/auth/", "/api/auth/", "/api/docs", "/api/openapi.json", "/api/redoc")

    def __init__(self, app) -> None:
        self._app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        auth: AuthConfig | None = getattr(
            getattr(scope.get("app"), "state", None), "auth", None
        )
        if auth is None or not auth.enabled:
            await self._app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith("/api/") or path.startswith(self.EXEMPT_PREFIXES):
            await self._app(scope, receive, send)
            return
        if _principal_from_scope(scope, auth) is None:
            response = JSONResponse(status_code=401, content={"detail": "not signed in"})
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)


def _principal_from_scope(scope, auth: AuthConfig) -> Principal | None:
    """`principal_of` without a `Request`.

    The gate runs before routing, so there is no `Request` object yet -- and
    constructing one to reuse `principal_of` would mean building the whole
    request abstraction per call to read one header. This parses the cookie
    header directly and then hands the value to the same signer, so the
    *verification* is not duplicated; only the retrieval is.
    """
    header = Headers(scope=scope).get("cookie", "")
    raw = ""
    for part in header.split(";"):
        name, _, value = part.strip().partition("=")
        if name == SESSION_COOKIE:
            raw = value
            break
    if not raw:
        return None
    payload = auth.signer.verify(raw)
    if payload is None:
        return None
    session_id = str(payload.get("sid", ""))
    subject = str(payload.get("sub", ""))
    expires = int(payload.get("exp", 0))
    if not session_id or not subject:
        return None
    if expires and expires < int(time.time()):
        return None
    if auth.sessions.is_revoked(session_id):
        return None
    return Principal(
        subject=subject,
        tenant_id=str(payload.get("tid", "")),
        session_id=session_id,
        issued_at=int(payload.get("iat", 0)),
    )


def register_auth_routes(app: FastAPI, auth: AuthConfig) -> None:
    """Mount the four routes and put the config where the dependency finds it.

    Called unconditionally from `create_app`, even with auth off. The routes
    exist either way and answer 503 when there is no issuer configured, rather
    than being absent: a console that got a 404 from `/auth/login` could not
    tell "this build has no identity" from "this build has identity and I
    typed the URL wrong", and the first is a thing the login screen needs to
    say out loud.
    """
    app.state.auth = auth

    @app.get("/auth/login")
    async def login(request: Request, next: str = "/", signup: bool = False):
        """Start the flow: mint state, nonce and PKCE, redirect to the issuer.

        `next` is where to land afterwards, and it is validated rather than
        trusted: an unchecked value here is an open redirect, which is a
        phishing primitive that costs nothing to close. See `_safe_next`.

        `signup=true` is the whole of the sign-up deliverable's backend. There
        is no local registration to build because Zitadel hosts it; what this
        app owes is a path that reaches the register screen and lands the new
        account back here provisioned. `prompt=create` does the first half and
        the callback below does the second -- a brand-new subject gets a
        `UserSignedIn`, which creates the `users` row, on exactly the same
        code path as any other sign-in. There is deliberately no separate
        "provision a user" step: one path means a new account cannot arrive in
        a state an existing account never reaches.
        """
        if auth.client is None:
            raise HTTPException(status_code=503, detail="no identity provider is configured")
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        pkce = new_pkce_pair()
        try:
            destination = await auth.client.authorization_url(
                redirect_uri=auth.redirect_uri,
                state=state,
                nonce=nonce,
                challenge=pkce.challenge,
                prompt="create" if signup else None,
            )
        except OidcError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

        response = RedirectResponse(destination, status_code=302)
        response.set_cookie(
            FLOW_COOKIE,
            auth.signer.sign(
                {
                    "state": state,
                    "nonce": nonce,
                    "verifier": pkce.verifier,
                    "next": _safe_next(next),
                    "exp": int(time.time()) + FLOW_MAX_AGE,
                }
            ),
            max_age=FLOW_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=auth.secure_cookies,
            path="/",
        )
        return response

    @app.get("/auth/callback")
    async def callback(request: Request, code: str = "", state: str = "", error: str = ""):
        """Finish the flow: verify, record, mint a session, redirect home.

        Every failure here is a 400 with a short message, never a redirect
        back to `/auth/login`. A redirect would be friendlier and would also
        make a misconfiguration an infinite loop between two endpoints that
        each think the other is at fault -- which is a bug report reading
        "the page flickers".
        """
        if auth.client is None:
            raise HTTPException(status_code=503, detail="no identity provider is configured")
        if error:
            # The issuer refused, and it said why. Relayed rather than
            # swallowed: `access_denied` (the person pressed cancel) and
            # `invalid_client` (this app is misconfigured) look identical from
            # the browser otherwise, and only one of them is worth waking
            # somebody up for.
            raise HTTPException(status_code=400, detail=f"the identity provider said: {error}")
        raw_flow = request.cookies.get(FLOW_COOKIE)
        flow = auth.signer.verify(raw_flow) if raw_flow else None
        if flow is None:
            raise HTTPException(
                status_code=400, detail="this sign-in did not start here, or it expired"
            )
        if int(flow.get("exp", 0)) < int(time.time()):
            raise HTTPException(
                status_code=400, detail="this sign-in took too long; try again"
            )
        # Constant-time, and more importantly compared at all: `state` is the
        # only thing standing between this callback and an attacker feeding a
        # victim's browser a code the attacker obtained. A missing comparison
        # here is a login-CSRF, and it is invisible to every functional test
        # because the happy path never has a mismatched state.
        if not code or not secrets.compare_digest(state, str(flow.get("state", ""))):
            raise HTTPException(status_code=400, detail="the sign-in state did not match")

        try:
            claims: Claims = await auth.client.exchange(
                code=code,
                redirect_uri=auth.redirect_uri,
                verifier=str(flow.get("verifier", "")),
                nonce=str(flow.get("nonce", "")),
            )
        except OidcError as failure:
            raise HTTPException(status_code=400, detail=str(failure)) from failure

        if auth.recorder is not None:
            # Awaited, not scheduled. A fire-and-forget append would let the
            # browser arrive at `/api/me` before the projection had a row, and
            # the console would render a signed-in person as a stranger for
            # one page load -- intermittently, which is the hardest kind of
            # wrong to report.
            await auth.recorder.record_sign_in(claims)

        destination = _safe_next(str(flow.get("next", "/")))
        response = RedirectResponse(destination, status_code=302)
        _set_session(response, auth, claims)
        response.delete_cookie(FLOW_COOKIE, path="/")
        return response

    @app.get("/auth/logout")
    async def logout(request: Request):
        """Revoke, clear the cookie, and hand off to the issuer if it can.

        Three steps, in that order, and the order is what makes it safe to
        fail partway: the session is dead in this process before the browser
        is told anything, so an abandoned redirect still leaves a signed-out
        session rather than a live one.

        Redirects to the issuer's `end_session_endpoint` when it advertises
        one. Without that, signing out of the app leaves the IdP's own session
        untouched and the next sign-in click goes straight back in with no
        prompt -- which reads as "logout is broken" and is worth the extra
        redirect to avoid.
        """
        person = principal_of(request)
        if person is not None:
            auth.sessions.revoke(person.session_id)

        destination = "/"
        if auth.client is not None:
            try:
                discovery = await auth.client.discover()
                if discovery.end_session_endpoint:
                    destination = (
                        f"{discovery.end_session_endpoint}"
                        f"?post_logout_redirect_uri={auth.public_url}/"
                    )
            except OidcError:
                # An issuer that cannot be reached must not stop somebody
                # signing out of *this* app. The local half already happened
                # above; this is only the courtesy half.
                destination = "/"

        response = RedirectResponse(destination, status_code=302)
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie(FLOW_COOKIE, path="/")
        return response

    @app.get("/api/auth/status")
    async def auth_status(person: OptionalUser):
        """Whether this build requires a sign-in, and whether there is one.

        Exempt from the gate -- see `AuthGate.EXEMPT_PREFIXES` -- because it
        is the question a signed-out console asks before it knows whether to
        show a login screen or the app. Answering it with a 401 would make the
        console guess.

        Carries no personal detail beyond the subject: a route reachable
        without a session must not leak an email address to whoever asks.
        """
        return {
            "auth_required": auth.enabled,
            "authenticated": person is not None,
            "configured": auth.client is not None,
            "subject": person.subject if person is not None else None,
        }

    @app.get("/api/me")
    async def me(person: CurrentUser):
        """The signed-in person, joined to the mirrored profile.

        The one route W-A applies `CurrentUser` to. The other ninety are
        W-B's sweep, deliberately untouched -- applying the dependency here
        and nowhere else is what lets this branch land while five others are
        in flight.

        Falls back to the cookie's own fields when the read model has no row.
        That is not defensive padding: it is the honest answer during the
        window between the callback's append and the projection catching up,
        and it means a person is never shown as nobody just because a
        subscription is a few milliseconds behind.
        """
        row = None
        if auth.users is not None:
            try:
                row = await auth.users.get(person.subject)
            except RuntimeError:
                # The runner exists but was never started -- a wiring bug, not
                # a user-facing one. Degrading to the cookie keeps the console
                # usable while `test_a_sign_in_reaches_the_user_read_model`
                # is what actually fails on it.
                row = None
        return {
            "subject": person.subject,
            "tenant_id": row.tenant_id if row is not None else person.tenant_id,
            "email": row.email if row is not None else "",
            "display_name": row.display_name if row is not None else "",
            "avatar_url": row.avatar_url if row is not None else "",
            "first_seen_at": row.first_seen_at if row is not None else "",
            "last_seen_at": row.last_seen_at if row is not None else "",
            "mirrored": row is not None,
        }


def _set_session(response: Response, auth: AuthConfig, claims: Claims) -> None:
    """Mint a fresh session id and write the cookie.

    **Rotation is the point.** A new `sid` on every sign-in means a session
    fixation attempt -- planting a known cookie on a victim before they
    authenticate -- ends with the attacker holding an id that names nobody.
    Reusing an existing cookie's id "because they are already signed in" is
    the mistake this function exists to not make, which is why it takes no
    existing session as an argument: there is no parameter to pass one
    through.
    """
    now = int(time.time())
    response.set_cookie(
        SESSION_COOKIE,
        auth.signer.sign(
            {
                "sid": secrets.token_urlsafe(24),
                "sub": claims.subject,
                "tid": claims.tenant_id,
                "iat": now,
                "exp": now + SESSION_MAX_AGE,
            }
        ),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=auth.secure_cookies,
        path="/",
    )


def _safe_next(candidate: str) -> str:
    """A same-origin path, or `/`.

    Anything with a scheme, a host, or a protocol-relative `//` prefix is
    discarded rather than sanitised. Sanitising an attacker-supplied URL is a
    game of parser differentials nobody wins; refusing everything that is not
    a bare rooted path is one comparison and has no interesting cases.

    `\\` is rejected alongside `/` because several browsers normalise
    backslashes to forward slashes in URLs, so `/\\evil.example` is a
    protocol-relative URL to some of them and a path to others.
    """
    if not candidate.startswith("/"):
        return "/"
    if candidate.startswith("//") or candidate.startswith("/\\"):
        return "/"
    return candidate


def _b64encode(value: str) -> str:
    return _b64encode_bytes(value.encode("utf-8"))


def _b64encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> str:
    return _b64decode_bytes(value).decode("utf-8")


def _b64decode_bytes(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
