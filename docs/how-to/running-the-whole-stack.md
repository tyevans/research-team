# Running the whole stack

One command brings up the durable backends, a search engine, an identity
provider, and the app itself:

```
docker compose up -d
```

The first run builds the app image, which includes `npm ci` and a Vite build,
so expect a few minutes. After that:

| Service | Where | What it is |
| --- | --- | --- |
| the app | <http://localhost:8000> | the console and the API |
| Zitadel | <http://localhost:8081> | the identity provider |
| SearXNG | <http://localhost:8888> | search, for the `fetch` tool |
| Mailpit | <http://localhost:8025> | every mail Zitadel sends, caught rather than delivered |
| Postgres | `localhost:5432` | pgvector, for entity embeddings |
| Neo4j | <http://localhost:7474> | the knowledge graph |

Sign in at <http://localhost:8000> with the credentials in
[the local Zitadel how-to](running-zitadel-locally.md).

## Just the durable backends

The previous behaviour of this compose file — Postgres and Neo4j, nothing else,
with the app run on the host — is still one command:

```
docker compose up -d postgres neo4j
uv run web.py
```

Naming the services is what selects them; compose starts their dependencies
and nothing else. Nothing is profiled, so `up -d` with no arguments starts
everything and `up -d <names>` starts exactly what you asked for.

Then export the variables in the README's "Durable backends" table. This is
the arrangement to use on macOS and Windows — see "Why the app uses host
networking" below.

## What each service costs you

**Postgres and Neo4j keep their data.** `docker compose down` leaves the named
volumes alone; `down -v` is how you deliberately lose them. That is the whole
point of running them at all.

**Zitadel has a database of its own** (`zitadel-db`), separate from the
project's Postgres. Zitadel runs its own migrations and expects to own the
database it is given, and putting a foreign migration history in the middle of
the project's data is not worth saving a container.

**The app's event log lives on a volume too** (`appdata`, mounted at
`/root/.research-team`). A host run and a container run therefore have
*different* databases — a project created in one is invisible to the other.
That surprises people; it is not a bug, and the alternative (bind-mounting
your home directory into the container) means a container writing files your
user does not own.

## Why the app uses host networking

`network_mode: host`, which is Linux-only and is the one thing about this file
that does not port.

Two problems force it, and only host networking solves both:

1. **The model endpoint is on the host.** `AGENT_BASE_URL` defaults to
   `http://localhost:8080/v1/`, and a container with its own network namespace
   resolves that to itself. This is exactly what the old header of
   `docker-compose.yml` said, and it was right.
2. **The OIDC issuer has one name.** Zitadel builds its discovery document and
   every `iss` claim from `ZITADEL_EXTERNALDOMAIN`, and that has to be the
   name the *browser* uses — `localhost:8081`. The app validates `iss` for
   exact equality against the issuer it discovered, deliberately, so it has to
   reach Zitadel at the same URL the browser does.

`extra_hosts: ["host.docker.internal:host-gateway"]` fixes (1) and not (2):
the app could reach Zitadel through the gateway, but the discovery document it
got back would name an issuer it did not ask for, and `OidcClient` refuses
that as issuer confusion rather than shrugging.

What it costs, so you are not surprised:

- **macOS and Windows.** `network_mode: host` is a no-op under Docker Desktop,
  where the container still runs in a VM. Use the backends-only path above and
  run the app on the host.
- The app ignores `ports:` and binds `8000` on the host directly. A host
  process already on 8000 is a container that fails to start, not a port
  conflict compose reports nicely.
- Everything the app talks to, it reaches on `localhost` at its *published*
  port — not through compose DNS. That is why SearXNG publishes on **8888**
  rather than its usual 8080: 8080 is where the model endpoint lives, and a
  silent collision there would look like the model being down.

## Pointing the app at a LAN model endpoint

The default is the host's own `localhost:8080`. For an endpoint elsewhere on
the network:

```
AGENT_BASE_URL=http://192.168.1.14:8080/v1/ docker compose up -d app
```

Or edit the `AGENT_BASE_URL` line in `docker-compose.yml`. Host networking
means there is nothing else to change — the container's view of the LAN is the
host's view.

## Turning identity off

The app service sets `AGENT_AUTH=on`, which is the only place in the
repository it is on. To run the whole stack without a sign-in wall:

```
AGENT_AUTH=off docker compose up -d app
```

Everything else is unaffected. With auth off, `/api/*` answers exactly as it
did before identity existed — that is what the flag is for, and
`tests/interfaces/test_auth_gate.py` holds both states.

## When something does not come up

`docker compose ps -a` first: a container that exited is a different problem
from one that never started.

- **`app` exits immediately with an address-in-use error.** Something on the
  host already has port 8000. Host networking means compose cannot remap it.
- **`zitadel` exits 1 with `setup failed`.** Read four lines further up in
  `docker compose logs zitadel`; the real error is usually buried in migration
  output. A permission error writing `/machine/pat.txt` means the `user: "0"`
  line has been removed.
- **`zitadel-bootstrap` waits and then gives up on `/machine/pat.txt`.**
  Zitadel writes that file only during first-instance setup, so a Zitadel that
  came up against a database it had already initialised will never write it.
  `docker compose down -v` and start again — this is local development data.
- **Sign-in fails with `invalid_client`.** The app is using a client id or
  secret that no longer matches. `docker compose up zitadel-bootstrap` rewrites
  them (it regenerates the secret when the application already exists), then
  `docker compose restart app`.

## This is not `docker-compose.test.yml`

That file is for `pytest -m integration`. It binds the same servers on
*different* ports (7688, 55432) and its Neo4j is wiped per test, because an
integration run deletes its tenant's rows. Both files can be up at once, and
nothing here changes that one.
