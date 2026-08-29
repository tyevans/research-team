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

## Where the activation email goes

Registration ends with Zitadel emailing an activation link, so a stack with no
SMTP provider leaves every new account stuck one step short. It does not look
like a failure: Zitadel accepts the registration, logs the send failure into
its own output, and returns the browser to a screen that says to check your
mail.

`docker-compose.yml` runs [Mailpit](https://mailpit.axllent.org/) for that.
Open **<http://localhost:8025>** and the activation mail is the first thing in
the list; click the link inside it exactly as a real user would. Nothing leaves
the machine, and nothing is kept — the mailbox is in memory, so a restart of
the container empties it.

Mailpit rather than MailHog, which is the name most people know. MailHog has
had no functional commit since 2022; Mailpit is its drop-in successor on the
same ports (1025 for SMTP, 8025 for the UI). Checked 2026-08-29.

One detail in `docker-compose.yml` looks like a typo and is the whole thing
working: the SMTP **user is empty and the password is not**. Two different
parts of Zitadel read those two fields, and neither does what its name
suggests.

- The notifier refuses to build an email channel when the stored password is
  NULL — it returns `QUERY-Wrs3gw Errors.SMTPConfig.NotFound` before looking
  at anything else, and Zitadel stores an empty password as NULL. So a
  provider with no password is invisible to the only component that sends
  mail, while `GET /admin/v1/smtp` cheerfully reports it
  `SMTP_CONFIG_ACTIVE`. The value is never checked; it only has to exist.
- Whether Zitadel offers `AUTH` at all is `user != "" && password != ""`.
  Leaving the user empty is what stops it issuing an AUTH command, which
  Mailpit does not implement — set a user and delivery fails with
  `Errors.SMTP.CouldNotAuth Parent=(502 Command not implemented)` and you are
  one plausible step from turning AUTH on at the catcher to fix a problem you
  created.

Measured on 2026-08-29 against a throwaway first-run stack: with those values
and a Mailpit with no environment at all, the mail arrives.

**The trap, and it will bite an existing stack.** Zitadel reads
`ZITADEL_DEFAULTINSTANCE_SMTPCONFIGURATION_*` when it *creates* the instance
and never again. A stack that was brought up before this was added has an
instance with no mail provider, and pulling the new compose file changes
nothing about it — no error, no log line, the same silent dead end. Start over
(below), or add the provider by hand in Zitadel's console under **Settings →
Notification providers**.

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

## What the first sign-in actually looks like

Walked end to end on 2026-08-29 against this stack, so this is what happens
rather than what should:

1. `http://localhost:8000` shows the sign-in screen.
2. **Sign in** goes to Zitadel's login. Enter the login name, then the password.
3. **Zitadel asks you to set up 2-factor authentication.** Press **Skip**. It
   asks once per account and is not something this project configures; there is
   no way to pre-skip it from `FirstInstance`.
4. You land back on `http://localhost:8000` with the console and your name in
   the top right.

Signing out returns you to Zitadel's "Logged Out" page rather than to the app,
because the app hands off to the issuer's `end_session_endpoint`. That is
deliberate — without it, signing out and clicking sign-in again goes straight
back in with no password prompt, because only the app's cookie was cleared.

## Things that go wrong, and what they actually look like

All four were hit while building this, and none of them says what it means.

**Zitadel exits 1 with `setup failed`, and the container never becomes
healthy.** The real error is several lines up in `docker compose logs zitadel`,
buried in migration output: `open /machine/pat.txt: permission denied`. The
image runs as an unprivileged user and a fresh named volume is owned by root,
so it cannot write the bootstrap PAT — and it fails *inside a migration*, which
is why the message is nowhere near the top. `user: "0"` on the service is the
fix and is already there; this is what its removal would look like.

**`zitadel-bootstrap` waits two minutes and gives up on `/machine/pat.txt`.**
Zitadel writes that file only during first-instance setup, so a Zitadel that
came up against a database it had already initialised never writes it. Start
over (below) — this is local development data.

**Sign-in fails with `invalid_client`.** The app is using a client id or secret
that no longer matches. Run `docker compose up zitadel-bootstrap` to rewrite
them, then `docker compose restart app`.

**A 404 from the management API while editing the bootstrap script.** Two
different mistakes produce the identical `{"code":5,"message":"Not Found"}`:
the regenerate-secret path is `_generate_client_secret`, *not*
`_regenerate_clientsecret` as the `RegenerateOIDCClientSecret` RPC name
suggests; and it takes the **app id**, not the client id. Zitadel returns both
and they are different numbers of the same shape. The path came from
`proto/zitadel/management.proto` at the pinned tag rather than from guessing.

**Sign-in succeeds and the account menu shows a long number.** That is a thin
profile: the ID token carried `sub` and nothing else. `OidcClient` falls back to
the userinfo endpoint for display claims, so this should not happen against
this stack — if it does, the userinfo request is failing, and the app
deliberately treats that as cosmetic rather than as a failed sign-in.

**Registration says to check your mail and nothing arrives at
<http://localhost:8025>.** `docker compose logs zitadel | grep -i smtp` tells
you which of four it is, and none of them says so on the browser:

| In the log | What it is |
| --- | --- |
| `QUERY-Wrs3gw Errors.SMTPConfig.NotFound` | No provider, or a provider whose password is empty. If the instance predates this section, it has none — see above. |
| `Errors.SMTP.CouldNotAuth Parent=(502 Command not implemented)` | The provider has a non-empty user, so Zitadel is offering AUTH. Clear the user rather than enabling AUTH on Mailpit. |
| a dial or connection error | Mailpit is down, or the host lost its port — it must be `mailpit:1025`. A bare hostname is refused *inside a migration*, so a fresh stack exits 1 on `setup failed` with `INST-mruNY Errors.Invalid.Argument` and nothing naming SMTP. |
| nothing at all | The mail was sent and the mailbox was emptied. Mailpit keeps nothing across a restart. |

**`tenant_id` is empty.** The `urn:zitadel:iam:user:resourceowner` scope is what
carries the organisation id, and it is in the default scope set. If
`AGENT_OIDC_SCOPES` has been set, it *replaces* that default — add the scope
back or W-B's tenancy work has nothing to key on.

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
