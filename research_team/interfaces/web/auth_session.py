"""Session cookie management, HMAC signing, principals, and user dependencies.

Provides session state signing/verification with HMAC-SHA256, session revocation,
the authenticated Principal model, and FastAPI CurrentUser/OptionalUser dependencies.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response

from research_team.infrastructure.identity import Claims, OidcClient

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
    def from_config(cls, secret: str) -> SessionSigner:
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


__all__ = [
    "FLOW_COOKIE",
    "FLOW_MAX_AGE",
    "SESSION_COOKIE",
    "SESSION_MAX_AGE",
    "AuthConfig",
    "CurrentUser",
    "OptionalUser",
    "Principal",
    "SessionSigner",
    "SessionStore",
    "_b64decode",
    "_b64decode_bytes",
    "_b64encode",
    "_b64encode_bytes",
    "_safe_next",
    "_set_session",
    "_unauthenticated",
    "current_user",
    "optional_user",
    "principal_of",
]
