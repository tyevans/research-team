"""Authentication and identity HTTP route handlers.

Mounts `/auth/login`, `/auth/callback`, `/auth/logout`, `/api/auth/status`, and `/api/me`.
"""

from __future__ import annotations

import secrets
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

from research_team.infrastructure.identity import Claims, OidcError
from research_team.infrastructure.identity.oidc import new_pkce_pair
from research_team.interfaces.web.auth_session import (
    FLOW_COOKIE,
    FLOW_MAX_AGE,
    SESSION_COOKIE,
    AuthConfig,
    CurrentUser,
    OptionalUser,
    _safe_next,
    _set_session,
    principal_of,
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


__all__ = ["register_auth_routes"]
