"""A real OIDC issuer, small enough to run in-process.

Not a mock of `OidcClient` and not a stub of `exchange`. CLAUDE.md's co-mention
section names the failure this avoids: a port stubbed on one side and unit
tested on the other proves both halves work and cannot prove they meet. The
half that matters here is signature verification, and a stub that returns a
`Claims` cannot exercise it at all -- every check in `_verified_claims` would
be dead code that no test has ever run.

So this serves a genuine discovery document, a genuine JWKS, and a genuine
token endpoint returning an RS256 ID token signed with the key the JWKS
advertises. `OidcClient` is driven against it over `httpx.ASGITransport`, so
the code path is byte-identical to production minus the socket.

It is deliberately steerable into being *wrong* -- `sign_id_token` takes every
claim as an argument -- because the tests that matter most are the ones where
the issuer lies: a token for the wrong audience, from the wrong issuer, with a
stale nonce, or signed with a key nobody advertises.
"""

import time

from joserfc import jwt
from joserfc.jwk import RSAKey
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

ISSUER = "https://issuer.test"
CLIENT_ID = "research-team-console"


class FakeIssuer:
    """An OIDC provider whose answers a test can dictate.

    `next_id_token` is the seam: the token endpoint hands back whatever was
    put there, so a test writes the token it wants examined rather than
    describing it. `last_form` records what was posted, which is how the PKCE
    verifier's presence is asserted -- there is no other way to see it, since
    a correct exchange is indistinguishable from one that dropped the verifier
    unless the issuer is the thing checking.
    """

    def __init__(self, issuer: str = ISSUER) -> None:
        self.issuer = issuer
        self.key = RSAKey.generate_key(2048, parameters={"kid": "test-key-1"})
        # A second key, generated and never published. Signing with it is how
        # "the signature does not verify" is produced without corrupting bytes
        # -- a mangled token fails at parsing, which is a different code path
        # from a well-formed token signed by a stranger, and only the second
        # is the attack worth testing.
        self.unpublished_key = RSAKey.generate_key(2048, parameters={"kid": "rogue"})
        self.next_id_token: str | None = None
        self.last_form: dict[str, str] = {}
        self.app = Starlette(
            routes=[
                Route("/.well-known/openid-configuration", self._discovery),
                Route("/jwks", self._jwks),
                Route("/token", self._token, methods=["POST"]),
                Route("/authorize", self._authorize),
            ]
        )

    def sign_id_token(
        self,
        *,
        subject: str = "user-1",
        nonce: str = "n",
        audience: str | None = None,
        issuer: str | None = None,
        email: str = "ada@example.test",
        name: str = "Ada Lovelace",
        picture: str = "https://pictures.test/ada.png",
        tenant_id: str = "org-42",
        expires_in: int = 300,
        key: RSAKey | None = None,
    ) -> str:
        now = int(time.time())
        claims = {
            "iss": issuer if issuer is not None else self.issuer,
            "sub": subject,
            "aud": audience if audience is not None else CLIENT_ID,
            "iat": now,
            "exp": now + expires_in,
            "nonce": nonce,
            "email": email,
            "name": name,
            "picture": picture,
            "urn:zitadel:iam:user:resourceowner:id": tenant_id,
        }
        return jwt.encode({"alg": "RS256", "kid": "test-key-1"}, claims, key or self.key)

    async def _discovery(self, request):
        return JSONResponse(
            {
                "issuer": self.issuer,
                "authorization_endpoint": f"{self.issuer}/authorize",
                "token_endpoint": f"{self.issuer}/token",
                "jwks_uri": f"{self.issuer}/jwks",
                "end_session_endpoint": f"{self.issuer}/logout",
            }
        )

    async def _jwks(self, request):
        # Only the published key. `unpublished_key` never appears here, which
        # is what makes a token signed with it unverifiable rather than merely
        # unexpected.
        return JSONResponse({"keys": [self.key.as_dict(private=False)]})

    async def _token(self, request):
        form = await request.form()
        self.last_form = {key: str(value) for key, value in form.items()}
        return JSONResponse(
            {
                "access_token": "at",
                "token_type": "Bearer",
                "expires_in": 300,
                "id_token": self.next_id_token,
            }
        )

    async def _authorize(self, request):
        # Never reached: the tests drive `/auth/callback` directly rather than
        # following the redirect, because following it would mean this fake
        # also implementing a login form. What the redirect *contains* is
        # asserted from the `Location` header instead.
        return JSONResponse({"detail": "not implemented"}, status_code=501)
