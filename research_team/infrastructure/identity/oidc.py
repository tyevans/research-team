"""The OIDC authorization-code flow, with PKCE, against a discovered issuer.

Three things happen here and nothing else does: discovery is fetched and
cached, an authorization URL is built, and a code is exchanged for tokens
whose ID token is then *verified* against the issuer's JWKS. The web layer
above holds no knowledge of any of it beyond `Claims`.

**Why the ID token is verified rather than read.** The token comes back over a
TLS connection to the token endpoint, which is why a lot of code decodes it
with `base64` and moves on. That is safe only for as long as the connection is
the only thing an attacker would have to beat, and it stops being true the
moment anything else can reach the callback -- a misconfigured proxy, a
`redirect_uri` that survives a hostname change, an issuer that turns out to be
answering on plaintext HTTP inside a compose network, which is exactly the
local development setup this ships with. So the signature is checked, the
`iss` and `aud` are checked, and the `nonce` is checked against one this
process minted. Any of those failing is an `OidcError` and a 400, never a
sign-in.

**Why `joserfc` rather than `authlib.jose`.** They are the same code -- authlib
1.6 moved its JOSE implementation there and its own `authlib.jose` import now
raises a deprecation warning pointing here. Importing the shim would mean
writing new code against a module its author has already labelled for removal.
"""

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from joserfc import jwt
from joserfc.jwk import KeySet

SCOPES = "openid profile email urn:zitadel:iam:user:resourceowner"
"""What the app asks for, and the reason it is this short.

`openid` is mandatory. `profile` carries `name`/`preferred_username`/`picture`,
which is the whole of the account menu. `email` carries the address, which is
how a person recognises their own account when they have two.

`urn:zitadel:iam:user:resourceowner` is the one non-standard entry, and it is
here because **`tenant_id` was empty without it** -- measured by signing in to
a live Zitadel on 2026-08-29, where neither the ID token nor userinfo carried
`urn:zitadel:iam:user:resourceowner:id` until this scope was asked for. That
field is the whole seam W-B's tenancy work keys on, so shipping without it
would have handed W-B a column that is always the empty string.

It is issuer-specific, which is a real cost rather than a tidy one. The spec
lets an authorization server ignore a scope it does not recognise, and most do;
an issuer that answers `invalid_scope` instead would refuse every sign-in.
`AGENT_OIDC_SCOPES` is the escape -- it replaces this string wholesale, so
pointing the app at Okta or Auth0 is one environment variable rather than a
patch. The default is set for the identity provider this repository actually
ships a compose file for.

Not asked for: `offline_access`. A refresh token would let this app act as the
person while they are away from the browser, and nothing here has any use for
that -- every call this system makes to a model or to the network is made as
*itself*, not on a user's behalf. Asking for a credential with no consumer is
how a breach gets worse than it needed to be. The cost is that a session
outlives its access token and this app has no way to renew it, which is fine
because it never uses the access token for anything: the session cookie is the
only credential the app checks after the callback, and it has its own lifetime.

`urn:zitadel:iam:org:project:id:...:aud` is deliberately absent too -- adding
a project audience is what makes Zitadel put role claims in the token, and
roles are W-B's. Adding it now would ship a claim nothing reads.
"""


class OidcError(RuntimeError):
    """Anything that must not become a sign-in.

    One exception type for discovery failures, exchange failures and token
    validation failures alike, because the route above treats them
    identically: none of them is the user's fault in a way they can act on,
    and telling a browser *which* check failed is telling an attacker which
    check to work on next. The detail is in the message for the log; the
    status is 400 either way.
    """


@dataclass(frozen=True)
class DiscoveryDocument:
    """The three endpoints and the issuer, out of `openid-configuration`.

    A frozen record of four strings rather than the raw dict, so that a typo
    in a key name fails where the document is parsed rather than at the moment
    it is used, three requests later.
    """

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    end_session_endpoint: str | None
    """Absent on issuers that do not implement RP-initiated logout.

    Optional rather than required because that absence is a legitimate
    configuration, not an error: an issuer without it simply cannot be told to
    end its own session, and the app clears its cookie and stops there. The
    consequence is worth being explicit about, because it is surprising --
    signing out of the app then clicking sign-in again goes straight back in
    without a password prompt, since the IdP's own session is untouched.
    """

    userinfo_endpoint: str | None = None
    """Where to ask for the claims the ID token did not carry.

    Optional because the spec makes it optional, and unread on any issuer whose
    ID token is already complete -- see `_with_userinfo` for when it is called
    and why what comes back is display-only.
    """


@dataclass(frozen=True)
class Claims:
    """What the verified ID token said, reduced to what this app stores.

    Deliberately not the raw claim dict. A dict invites reading a claim
    somewhere far from here without anyone checking whether it was verified,
    and the whole argument of this module is that only verified claims count.
    """

    subject: str
    tenant_id: str
    email: str
    display_name: str
    avatar_url: str


@dataclass(frozen=True)
class PkcePair:
    """A verifier and the challenge derived from it.

    Both are carried out of `new_pkce_pair` rather than the challenge being
    recomputed at the callback, because recomputing means the derivation lives
    in two places and a mismatch between them is a flow that fails only in
    production.
    """

    verifier: str
    challenge: str


def new_pkce_pair() -> PkcePair:
    """A fresh S256 PKCE pair.

    `token_urlsafe(64)` gives ~86 characters, comfortably inside RFC 7636's
    43-128 range and comfortably above its 32-byte entropy floor. Plain
    (non-hashed) challenges are not offered at all: an issuer that accepts
    `plain` accepts a challenge an interceptor can replay, and offering the
    weaker method is how a negotiation ends up on it.
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PkcePair(verifier=verifier, challenge=challenge)


class OidcClient:
    """Discovery, the authorization URL, and the verified exchange.

    Holds no per-request state. The state, nonce and PKCE verifier that bind
    one authorization request to one callback live in a signed cookie on the
    browser, not here -- see `interfaces/web/auth.py`, which explains why that
    is the choice rather than a dict on this object.
    """

    def __init__(
        self,
        issuer: str,
        client_id: str,
        client_secret: str = "",
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        discovery_ttl: float = 300.0,
        scopes: str = SCOPES,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._scopes = scopes
        # A *transport*, not a client, and the difference is what makes the
        # tests real. The token exchange goes through authlib's own
        # `AsyncOAuth2Client`, which is an `httpx.AsyncClient` subclass it
        # constructs itself -- so an injected client would be used for
        # discovery and JWKS and quietly bypassed for the one request that
        # matters. That is not hypothetical: the first draft injected a client,
        # every discovery assertion passed, and the exchange resolved
        # `issuer.test` against real DNS and failed with `Name or service not
        # known`. A transport is the layer both clients accept, so
        # `ASGITransport(app=fake_issuer)` covers all three requests.
        self._transport = transport
        self._http = httpx.AsyncClient(timeout=10.0, transport=transport)
        self._discovery: DiscoveryDocument | None = None
        self._discovered_at = 0.0
        self._keys: KeySet | None = None
        self._discovery_ttl = discovery_ttl

    async def discover(self) -> DiscoveryDocument:
        """The issuer's `openid-configuration`, cached for `discovery_ttl`.

        Cached rather than fetched per request, because a login would
        otherwise be three round trips to the IdP instead of two -- and
        expired rather than cached forever, because an issuer that moves its
        token endpoint (or rotates into a new JWKS URI) must not require a
        restart of this process to be noticed. Five minutes is short enough
        that a rotation is invisible to a person and long enough that the
        document is fetched once per burst of logins, not once per login.
        """
        now = time.monotonic()
        if self._discovery is not None and now - self._discovered_at < self._discovery_ttl:
            return self._discovery
        url = f"{self._issuer}/.well-known/openid-configuration"
        try:
            response = await self._http.get(url)
            response.raise_for_status()
            document = response.json()
        except Exception as error:
            raise OidcError(f"could not discover the issuer at {url}: {error}") from error

        try:
            discovered = DiscoveryDocument(
                issuer=str(document["issuer"]).rstrip("/"),
                authorization_endpoint=str(document["authorization_endpoint"]),
                token_endpoint=str(document["token_endpoint"]),
                jwks_uri=str(document["jwks_uri"]),
                end_session_endpoint=(
                    str(document["end_session_endpoint"])
                    if document.get("end_session_endpoint")
                    else None
                ),
                userinfo_endpoint=(
                    str(document["userinfo_endpoint"])
                    if document.get("userinfo_endpoint")
                    else None
                ),
            )
        except KeyError as error:
            raise OidcError(f"{url} is missing {error}, which OIDC requires") from error

        # A document whose `issuer` disagrees with the URL it was fetched from
        # is the classic issuer-confusion setup: every later `iss` check would
        # then pass against the wrong authority. Refused here, once, rather
        # than trusted and re-checked downstream.
        if discovered.issuer != self._issuer:
            raise OidcError(
                f"{url} declares issuer {discovered.issuer!r}, not {self._issuer!r}"
            )
        # The key set is dropped whenever discovery is, so a rotated
        # `jwks_uri` cannot be served keys fetched from the old one.
        self._keys = None
        self._discovery = discovered
        self._discovered_at = now
        return discovered

    async def authorization_url(
        self, *, redirect_uri: str, state: str, nonce: str, challenge: str, prompt: str | None
    ) -> str:
        """Where to send the browser to sign in.

        `prompt` is the sign-up seam and the only reason it is a parameter:
        Zitadel hosts registration, and `prompt=create` (OIDC's "Initiating
        User Registration" extension) is how a relying party asks for the
        create-account screen rather than the sign-in one. An issuer that does
        not implement it shows the ordinary login page, which has a register
        link on it -- so the degradation is one extra click, not a broken
        flow, and that is why this is sent rather than feature-detected.
        """
        discovery = await self.discover()
        parameters = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "scope": self._scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if prompt:
            parameters["prompt"] = prompt
        return f"{discovery.authorization_endpoint}?{httpx.QueryParams(parameters)}"

    async def exchange(
        self, *, code: str, redirect_uri: str, verifier: str, nonce: str
    ) -> Claims:
        """Trade the code for tokens, verify the ID token, return its claims.

        One method rather than exchange-then-verify as two, deliberately:
        there is no legitimate caller for an unverified ID token, and a
        separate `exchange` returning one would be the thing somebody reaches
        for at 5pm. The only value that leaves here has been checked.
        """
        discovery = await self.discover()
        # authlib's client, rather than a hand-written form POST, for the
        # parts that are easy to get subtly wrong: it picks `client_secret_post`
        # or `client_secret_basic` per the issuer's advertised support, and it
        # is what carries `code_verifier` into the body in the form the spec
        # names. A raw POST works against Zitadel and then does not against
        # the next issuer.
        client = AsyncOAuth2Client(
            client_id=self._client_id,
            client_secret=self._client_secret or None,
            redirect_uri=redirect_uri,
            code_challenge_method="S256",
            transport=self._transport,
        )
        try:
            async with client:
                token = await client.fetch_token(
                    discovery.token_endpoint,
                    grant_type="authorization_code",
                    code=code,
                    redirect_uri=redirect_uri,
                    code_verifier=verifier,
                )
        except Exception as error:
            raise OidcError(f"the token exchange was refused: {error}") from error

        id_token = token.get("id_token")
        if not id_token:
            # A token response with no `id_token` means this was an OAuth2
            # exchange, not an OIDC one -- usually a client configured without
            # the `openid` scope. Refused rather than falling back to a
            # userinfo call: userinfo answers for whoever holds the access
            # token, which is a weaker statement than a signed assertion about
            # who authenticated.
            raise OidcError("the token response carried no id_token")

        claims = await self._verified_claims(id_token, discovery=discovery, nonce=nonce)
        return await self._with_userinfo(claims, discovery, token.get("access_token"))

    async def _with_userinfo(
        self, claims: Claims, discovery: DiscoveryDocument, access_token: str | None
    ) -> Claims:
        """Fill in display claims the ID token did not carry.

        **This exists because it shipped without it, and the account menu drew
        a snowflake id.** Measured on 2026-08-29 by signing in to a live
        Zitadel: the flow completed, the cookie was set, the `users` row was
        written -- and `email`, `display_name` and `tenant_id` were all empty,
        because Zitadel does not assert profile claims into an ID token unless
        the application turns on `idTokenUserinfoAssertion`. That is not a
        Zitadel quirk to work around. OIDC explicitly permits an ID token to
        carry `sub` and little else and to leave the rest to this endpoint, so
        any issuer may do it, and the fix belongs here rather than in the
        bootstrap that configures one particular provider.

        Called only when the token came up short, so a well-configured issuer
        pays nothing. One request per *sign-in*, never per request -- the
        mirror is what every page load reads afterwards.

        **Display-only, and the subject is re-checked.** Nothing here can
        change who the person is: `subject` comes from the verified ID token,
        and a userinfo response naming a different `sub` is discarded whole
        rather than merged. Without that check this would be a second,
        *unverified* channel into the identity the rest of this module exists
        to establish -- userinfo is a bearer-token response, not a signed
        assertion, and the two must not be treated alike.

        A failure here is not a failed sign-in. An issuer that refuses userinfo
        leaves a person signed in under a thin profile, which the account menu
        already renders -- `AccountMenu`'s `NothingButASubject` story is
        exactly that case. Raising would turn a cosmetic gap into a login
        outage.
        """
        if claims.email or claims.display_name:
            return claims
        if not access_token or not discovery.userinfo_endpoint:
            return claims
        try:
            response = await self._http.get(
                discovery.userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            response.raise_for_status()
            info = response.json()
        except Exception:  # noqa: BLE001 - cosmetic, not fatal; see the docstring
            return claims
        if str(info.get("sub", "")) != claims.subject:
            return claims
        return Claims(
            subject=claims.subject,
            tenant_id=(
                str(info.get("urn:zitadel:iam:user:resourceowner:id", "")) or claims.tenant_id
            ),
            email=str(info.get("email", "")) or claims.email,
            display_name=_display_name(info) or claims.display_name,
            avatar_url=str(info.get("picture", "")) or claims.avatar_url,
        )

    async def _verified_claims(
        self, id_token: str, *, discovery: DiscoveryDocument, nonce: str
    ) -> Claims:
        keys = await self._key_set(discovery)
        try:
            decoded = jwt.decode(id_token, keys)
        except Exception as error:  # noqa: BLE001 - see OidcError's docstring
            # The most common cause is a key this process has not seen: the
            # issuer rotated while we held a cached set. Retried once against
            # a freshly fetched set before giving up, because the alternative
            # is every session in flight failing until something restarts.
            self._keys = None
            try:
                decoded = jwt.decode(id_token, await self._key_set(discovery))
            except Exception as retried:  # noqa: BLE001
                raise OidcError(f"the id_token signature did not verify: {retried}") from error

        registry = jwt.JWTClaimsRegistry(
            iss={"essential": True, "value": discovery.issuer},
            aud={"essential": True, "value": self._client_id},
            exp={"essential": True},
            # `essential` rather than `value`: the registry's value check is
            # equality, and a `nonce` is compared below where a mismatch can
            # be named. Requiring its presence here is what stops a token
            # minted for a different flow -- which would carry no nonce at all
            # -- passing the comparison against an empty string.
            nonce={"essential": True},
        )
        try:
            registry.validate(decoded.claims)
        except Exception as error:
            raise OidcError(f"the id_token claims did not validate: {error}") from error

        # Compared with `compare_digest` rather than `==`, and the reason is
        # honesty about what it buys: a timing oracle on a nonce is close to
        # unexploitable, since the value is single-use and the attacker would
        # need it before the flow it belongs to completes. It costs nothing
        # and it means no future reader has to reconstruct that argument.
        if not secrets.compare_digest(str(decoded.claims.get("nonce", "")), nonce):
            raise OidcError("the id_token's nonce is not the one this flow issued")

        claims = decoded.claims
        subject = str(claims.get("sub", ""))
        if not subject:
            raise OidcError("the id_token carried no subject")

        return Claims(
            subject=subject,
            # Zitadel puts the organisation id in a namespaced claim rather
            # than a standard one, because OIDC has no standard notion of a
            # tenant. Falling back to the empty string rather than raising: an
            # issuer that is not Zitadel has no org id to give, and refusing
            # sign-in on its absence would make this app Zitadel-only for no
            # benefit W-A can name. W-B decides what an empty tenant means.
            tenant_id=str(claims.get("urn:zitadel:iam:user:resourceowner:id", "")),
            email=str(claims.get("email", "")),
            display_name=_display_name(claims),
            avatar_url=str(claims.get("picture", "")),
        )

    async def _key_set(self, discovery: DiscoveryDocument) -> KeySet:
        if self._keys is not None:
            return self._keys
        try:
            response = await self._http.get(discovery.jwks_uri)
            response.raise_for_status()
            self._keys = KeySet.import_key_set(response.json())
        except Exception as error:
            raise OidcError(
                f"could not fetch the issuer's keys from {discovery.jwks_uri}: {error}"
            ) from error
        return self._keys


def _display_name(claims) -> str:
    """The best name the token offers, or the local part of the email.

    Four fallbacks rather than one, because which claim carries a usable name
    is an issuer-by-issuer decision and an account menu reading "unknown" is a
    bug report. The last resort is the email's local part rather than the
    subject: a subject is a snowflake id, and showing one to a person tells
    them nothing about which of their accounts they are in.
    """
    for key in ("name", "preferred_username", "nickname", "given_name"):
        value = claims.get(key)
        if value:
            return str(value)
    email = str(claims.get("email", ""))
    return email.split("@", 1)[0] if email else ""
