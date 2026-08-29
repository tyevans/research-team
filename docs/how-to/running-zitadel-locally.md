# Running Zitadel locally

Zitadel is the identity provider this project signs users in against. It comes
up with the rest of the stack and provisions itself; there is nothing to click.

```
docker compose up -d
```

Wait for `zitadel-bootstrap` to exit 0:

```
docker compose ps -a zitadel-bootstrap
```

Then open <http://localhost:8000> and press **Sign in**.

## The admin credentials

| | |
| --- | --- |
| username | `admin@research-team.localhost` |
| password | `Password1!` |

**These are for local development only.** They are written into
`docker-compose.yml` in plain text, this document publishes them, and the
password-change prompt is deliberately switched off
(`ZITADEL_FIRSTINSTANCE_ORG_HUMAN_PASSWORDCHANGEREQUIRED: false`). Anything
reachable from outside your machine needs a different instance, a different
password, and `devMode` off — see "What must not survive" below.

The Zitadel console itself is at <http://localhost:8081>, with the same
credentials. You need it for anything this bootstrap does not do: adding users
by hand, changing password policy, or reading what a token will contain.

## Creating an account instead of using the admin one

The app's login screen has a **Create an account** link. It sends the browser
to Zitadel with `prompt=create`, which is OIDC's way of asking a provider for
its registration screen rather than its sign-in one. Registration is Zitadel's
to host — this project stores no passwords and never sees one.

A brand-new account lands back in the app on the same code path as any other
sign-in: `UserSignedIn` is appended, the `users` projection writes the row, and
the console shows an empty project list with a first-run prompt. There is
deliberately no separate "provision a user" step, so a new account cannot
arrive in a state an existing account never reaches.

## What the bootstrap actually does

Two things Zitadel cannot be told to do declaratively.

`docker-compose.yml` sets `ZITADEL_FIRSTINSTANCE_*` variables, which is enough
for an instance, an organisation, a human admin, and a machine user whose
personal access token Zitadel writes to a shared volume. That is where
declarative provisioning stops: a **project** and an **application** have to be
created through the management API, and the client id and secret are *minted by
Zitadel* — neither can be chosen in advance, so neither can be written into a
compose file.

So `docker/bootstrap-zitadel.sh` runs once, using that PAT, and:

1. creates the project `research-team`, if it is not there;
2. creates a confidential OIDC web client named `console`, with
   `http://localhost:8000/auth/callback` as its redirect URI and
   `http://localhost:8000/` as its post-logout URI;
3. writes `AGENT_OIDC_CLIENT_ID` and `AGENT_OIDC_CLIENT_SECRET` into a second
   shared volume, which the app's entrypoint sources at start.

It is idempotent. Run again and it finds both, regenerates the client secret
(Zitadel returns a secret exactly once, so regenerating is the only way to get
a usable one back for an application that already exists) and rewrites the
file. That matters after a crash: without it, a second `up` would create a
*second* application, the app would keep the first one's credentials, and
sign-in would fail with `invalid_client`.

Two volumes rather than one, deliberately: the app has no business being able
to read an `IAM_OWNER` token.

## What the app asks for

Scopes: `openid profile email`. Nothing else.

Not `offline_access`: a refresh token would let this app act as you while you
are away from the browser, and nothing here has any use for that — every call
this system makes to a model or to the network is made as *itself*. The cost is
that a browser session outlives its access token and cannot be renewed, which
is fine because the app never uses the access token for anything. The signed
session cookie is the only credential it checks after the callback, and it
lasts twelve hours.

No project audience either. Adding `urn:zitadel:iam:org:project:id:…:aud` is
what makes Zitadel put role claims in the token, and roles belong to the
tenancy and RBAC workstream. Adding it now would ship a claim nothing reads.

The organisation id arrives as `urn:zitadel:iam:user:resourceowner:id` and is
stored as the user's `tenant_id`. Nothing uses it yet; it exists so the tenancy
work has something to key on rather than a backfill to run.

## Pinned to v3, on purpose

`ghcr.io/zitadel/zitadel:v3.4.15`, not `latest`.

From v4 onward Zitadel's login UI is a **separate container** that has to sit
behind a reverse proxy alongside the API — upstream's own compose example for
it is a Traefik deployment with two dozen routing labels. v3 still serves its
login pages from one container, which is the entire difference between a
four-service stack and a seven-service one for an IdP nobody is deploying.

Revisit when v3 leaves support, not before. The app itself is version-agnostic:
it discovers everything from `.well-known/openid-configuration` and would work
against v4 or against a Zitadel you do not run.

## What must not survive into anything real

Four things, each of which is correct here and dangerous elsewhere:

- **`devMode: true`** on the OIDC application. That is what allows a plain
  `http` redirect URI at all.
- **`ZITADEL_EXTERNALSECURE: false`** and `--tlsMode disabled`. Every token in
  this stack crosses the wire in the clear.
- **The masterkey** (`MasterkeyNeedsToHave32Characters`) and the Postgres
  password (`zitadel`), both literals in the compose file.
- **`AGENT_SESSION_SECRET: local-development-session-secret`**, which is the
  key this app's session cookies are signed with. A shared default signing key
  is the same as no signature: anyone who knows it can mint a cookie naming any
  subject. Unset, the app mints a random key per process instead — which signs
  everyone out on restart, and is the right failure.

## Starting over

```
docker compose down -v
docker compose up -d
```

`-v` drops Zitadel's database and both bootstrap volumes, so the next start is
a genuine first run. Everything in Zitadel is local development data; the only
thing you lose that you might want is any user you created by hand in its
console.

Note that `down -v` also drops the *app's* volumes — the event log and the
blobs. To reset only the identity side:

```
docker compose rm -sfv zitadel zitadel-db zitadel-bootstrap
docker volume rm <project>_zitadeldata <project>_machinekey <project>_bootstrap
docker compose up -d
```

`docker volume ls` gives the prefix, which is the directory name.
