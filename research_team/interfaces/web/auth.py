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

from __future__ import annotations

import time

from fastapi.responses import JSONResponse
from starlette.datastructures import Headers

from research_team.interfaces.web.auth_routes import register_auth_routes
from research_team.interfaces.web.auth_session import (
    FLOW_COOKIE,
    FLOW_MAX_AGE,
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    AuthConfig,
    CurrentUser,
    OptionalUser,
    Principal,
    SessionSigner,
    SessionStore,
    _b64decode,
    _b64decode_bytes,
    _b64encode,
    _b64encode_bytes,
    _safe_next,
    _set_session,
    _unauthenticated,
    current_user,
    optional_user,
    principal_of,
)


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


__all__ = [
    "FLOW_COOKIE",
    "FLOW_MAX_AGE",
    "SESSION_COOKIE",
    "SESSION_MAX_AGE",
    "AuthConfig",
    "AuthGate",
    "CurrentUser",
    "OptionalUser",
    "Principal",
    "SessionSigner",
    "SessionStore",
    "_b64decode",
    "_b64decode_bytes",
    "_b64encode",
    "_b64encode_bytes",
    "_principal_from_scope",
    "_safe_next",
    "_set_session",
    "_unauthenticated",
    "current_user",
    "optional_user",
    "principal_of",
    "register_auth_routes",
]
