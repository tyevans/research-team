# Configuration

This system has one registry of settings and five layers that can answer for
them. `research_team/domain/settings.py` declares 41 settings. The provider
catalogue adds 20 more, one per provider credential. Each declaration carries
the key, the environment variable, the type, the default, the validation and
the scopes that may set it. Nothing in this file is written twice: the tables
below are the same declarations, read out.

The environment used to be the only layer. It is now the fourth of five.

## The five layers

A value is resolved by walking the layers in this order and taking the first
answer:

```
project  →  user  →  tenant  →  environment  →  built-in default
```

`RESOLUTION_ORDER` in `research_team/domain/settings.py` fixes the first three.
The last two are not scopes and never appear in a scope picker.

The first three layers are stored in the `setting_overrides` table of the
`AGENT_DB` database. You write them over HTTP. The fourth layer is the
process environment. The fifth is the constant in the declaration.

A caller cannot invert the order. The resolver re-sorts whatever chain it is
given and drops any scope that was not named, so a client that lists `tenant`
before `project` still gets `project` first.

### What each layer costs you

The environment layer is the deployment layer. One process reads one
environment, so a value set there applies to every project, every user and
every tenant that process serves. That is the right layer for a database path
or a bind address. It is the wrong layer for a model choice that two projects
should be able to disagree about.

The three scoped layers cost a database read per request and give you that
disagreement. They also have **no authorization on them yet** — see the
warning below.

## What the layers do not yet reach

**An override written at project, user or tenant scope does not change what
the running agent does.** This is the most important thing to know before you
use the settings API, and it is easy to miss, because a write succeeds, the
value reads back correctly, and the resolved view reports the right layer.

`research_team/infrastructure/config.py` is what the agent, the extractor, the
curator and the embedder actually read. Its own docstring says what it
resolves: "the environment, then the built-in default, and nothing else. It
has no scope to resolve for -- a process has no project and no user." Verified
on 2026-08-29 by grep: `SettingsResolver` has no caller outside the settings
modules themselves.

So today the settings store is a working, tested surface with no consumer
below it. Model profiles are the same: `PUT /api/profiles/.../roles/extraction`
stores the selection and `GET /api/profiles` reports it, but no client is
built from it. What ships is the registry, the catalogue, the encrypted store
and the contract. The wiring is the next slice.

**To change what this process does, set the environment variable.** Every
setting has one, including every provider credential.

## The seven environment-only settings

Seven variables are excluded from the registry, because no scope can answer
for them. The reasons below are the ones in `ENVIRONMENT_ONLY`, quoted:

| Variable | Why it cannot be scoped |
|---|---|
| `AGENT_DB` | "Where the settings store itself lives. A setting whose value decides which database holds the settings cannot be read from that database." |
| `AGENT_INTERACTION_DB` | "A second database path, resolved before any store opens. AGENT_DB's circularity." |
| `AGENT_BLOB_ROOT` | "A filesystem path the process must own before a request exists, and the hook `tests/conftest.py` uses to keep uploads out of a developer's home." |
| `AGENT_PERCEPTION_ROOT` | "A filesystem path, for AGENT_BLOB_ROOT's reason." |
| `AGENT_WEB_HOST` | "Bound before the first request, so no request's scope can supply it." |
| `AGENT_WEB_PORT` | "Bound before the first request, for AGENT_WEB_HOST's reason." |
| `AGENT_SETTINGS_KEY` | "The key secrets are encrypted with. Storing it beside the ciphertext would make the encryption decorative." |

Their defaults:

| Variable | Default |
|---|---|
| `AGENT_DB` | `~/.research-team/sessions.db` |
| `AGENT_INTERACTION_DB` | `~/.research-team/interactions.db` |
| `AGENT_BLOB_ROOT` | `~/.research-team/blobs` |
| `AGENT_PERCEPTION_ROOT` | `~/.research-team/perception` |
| `AGENT_WEB_HOST` | `127.0.0.1` |
| `AGENT_WEB_PORT` | `8000` |
| `AGENT_SETTINGS_KEY` | *(unset)* |

`AGENT_SETTINGS_KEY` is the only one of the seven that changes behaviour when
you leave it unset rather than merely picking a path. Unset is a supported
state. Non-secret settings read and write normally. A write to a *secret*
setting is refused:

```
{"detail":"AGENT_SETTINGS_KEY is not set, so secrets cannot be stored"}
```

The refusal is the point. A key stored in the clear beside the ciphertext is
worse than a key you were told you could not store. Generate one with
`openssl rand -base64 32`.

## Scope, in the tables below

The **Scope** column says which of the three scoped layers may set a value:

- **any** — project, user or tenant.
- **tenant** — tenant only. These are deployment facts. Two projects in one
  process cannot use two graph databases, so letting a project set
  `AGENT_GRAPH_STORE` would promise something the process cannot keep.

### Models

| Variable | Default | Scope | Meaning |
|---|---|---|---|
| `AGENT_MODEL` | `qwen3.6-27b-mtp` | any | The model the research agent talks to |
| `AGENT_BASE_URL` | `http://localhost:8080/v1/` | any | An OpenAI-compatible endpoint |
| `AGENT_API_KEY` | `not-needed` | any | Credential for the chat endpoint. **Secret.** Local servers usually ignore it |
| `AGENT_CURATION_MODEL` | *(unset)* | any | Runs the media-curation chain. Falls back to the chat model |
| `AGENT_EXTRACTION_MODEL` | *(unset)* | any | Runs knowledge extraction. Falls back to the chat model. Set it to point extraction at something cheap **without** repointing the research agent |
| `AGENT_VISION_MODEL` | *(unset)* | any | Describes frames and images. Unset means no vision at all |

### Embeddings

| Variable | Default | Scope | Meaning |
|---|---|---|---|
| `AGENT_EMBEDDING_MODEL` | `nomic-embed-text` | any | Turns text into vectors. **Not** `AGENT_MODEL`, which names a chat model |
| `AGENT_EMBEDDING_DIMENSION` | `768` | any | That model's vector width. A property of the model, not a preference |
| `AGENT_EMBEDDING_BASE_URL` | *(the chat endpoint)* | any | Where embedding requests go. llama.cpp serves one model per process, so this is usually a second port |
| `AGENT_EMBEDDING_API_KEY` | *(the chat key)* | any | Credential for the embedding endpoint. **Secret** |

### Perception

| Variable | Default | Scope | Meaning |
|---|---|---|---|
| `AGENT_TRANSCRIBER_URL` | *(unset)* | any | A whisper.cpp server. Unset means audio is perceived without speech |
| `AGENT_TRANSCRIBER_MODEL` | *(unset)* | any | The ASR revision. Required once the transcriber URL is set. It is part of the capability fingerprint, so it has no default |
| `AGENT_PERCEPTION_MAX_CHARS` | `500000` | any | Characters of derived text. Equal to the document cap, deliberately |

### Context

| Variable | Default | Scope | Meaning |
|---|---|---|---|
| `AGENT_CONTEXT` | `full` | any | How a conversation that outgrows the window is managed: `full`, `elide`, `compact` or `delegate` |
| `AGENT_CONTEXT_TRIGGER` | `120000` | any | Approximate tokens `compact` tolerates before it summarizes |
| `AGENT_CONTEXT_KEEP_MESSAGES` | `20` | any | Recent messages `compact` leaves out of the summary |
| `AGENT_CONTEXT_KEEP_RESULTS` | `6` | any | Recent tool results `elide` leaves whole |
| `AGENT_CONTEXT_CLEAR_OVER` | `2000` | any | Older tool results longer than this are cleared outright under `elide` |
| `AGENT_AUTHORING_ROUNDS` | `6` | any | Model calls a course-authoring turn may make before its graph, corpus and web tools are withdrawn. `0` turns the bound off. See below |

### Extraction

| Variable | Default | Scope | Meaning |
|---|---|---|---|
| `AGENT_KNOWLEDGE_DOMAIN` | `research_corpus` | any | A redstring schema id, or `auto` to classify per document |
| `AGENT_EXTRACTION_CONCURRENCY` | `8` | any | Extraction calls in flight **per document**. See below |
| `AGENT_EXTRACTION_CHUNK_SIZE` | `2000` | any | Characters per chunk. See below |
| `AGENT_EXTRACTION_THINKING` | `false` | any | Let the extraction model reason before answering. Off by default: measured worse precision and about five times slower. Turn it on for a backend with no chat template. OpenAI's hosted API rejects the field with a 400 on the first extraction call |
| `AGENT_CONSOLIDATION_BATCH` | `25` | any | Entities decided together in one consolidation pass |
| `AGENT_CATALOG_SWEEP_CONCURRENCY` | `1` | any | Candidates a catalog blurb or art sweep works on at once. See below |

### Stores

Every setting here is tenant-scoped only.

| Variable | Default | Scope | Meaning |
|---|---|---|---|
| `AGENT_GRAPH_STORE` | `memory` | tenant | What backs the knowledge graph: `memory` or `neo4j` |
| `AGENT_VECTOR_STORE` | `memory` | tenant | What backs entity embeddings: `none`, `memory` or `pgvector` |
| `AGENT_CHUNK_STORE` | `memory` | tenant | What backs the document-chunk corpus: `none`, `memory` or `postgres` |
| `AGENT_PGVECTOR_DSN` | *(unset)* | tenant | Postgres DSN. **Secret.** Required when the vector store is `pgvector`. No default: a silent localhost connection writes somebody's vectors somewhere they did not choose |
| `AGENT_NEO4J_URI` | `bolt://localhost:7687` | tenant | The bolt endpoint |
| `AGENT_NEO4J_USER` | `neo4j` | tenant | The account to connect as |
| `AGENT_NEO4J_PASSWORD` | *(unset)* | tenant | **Secret.** Required when the graph store is `neo4j`. No default: a store that comes up on `neo4j/neo4j` connects to somebody else's |
| `AGENT_NEO4J_DATABASE` | *(unset)* | tenant | Which database on the server. Unset means the server's default |

### Search

| Variable | Default | Scope | Meaning |
|---|---|---|---|
| `AGENT_SEARXNG_URL` | *(unset)* | any | SearXNG base URL. Unset means the agent gets no network search tool at all |
| `AGENT_SEARXNG_RESULTS` | `5` | any | How many results reach the model. Capped because context is the cost |

### Media

| Variable | Default | Scope | Meaning |
|---|---|---|---|
| `AGENT_MEDIA_RECONCILE_INTERVAL` | `300.0` | tenant | Seconds between sweeps for proposals stuck at `accepted` |
| `AGENT_BLOB_SWEEP_GRACE` | `86400.0` | tenant | How long an unreferenced blob must sit before the sweep may delete it |

### Observability

| Variable | Default | Scope | Meaning |
|---|---|---|---|
| `AGENT_TRACING` | `false` | tenant | Export OpenTelemetry traces. Needs the `tracing` extra |
| `AGENT_OTLP_ENDPOINT` | `http://localhost:4318/v1/traces` | tenant | Where traces are sent |
| `AGENT_SERVICE_NAME` | `research-team` | tenant | What this process calls itself in a trace |
| `AGENT_INTERACTION_LOG` | `true` | tenant | Record what the console user did. The one default-on switch here. `README.md` says what it collects and how to turn it off |

### Provider credentials

Twenty more settings are synthesised from the provider catalogue, one per
credential. They are not listed one by one here, because the catalogue is the
list. The key is `provider_key.<provider>[.<credential>]` and the variable is
`AGENT_PROVIDER_KEY_<PROVIDER>_<CREDENTIAL>`:

```bash
export AGENT_PROVIDER_KEY_GROQ_API_KEY=gsk_...
export AGENT_PROVIDER_KEY_BEDROCK_REGION=us-east-1
```

[`docs/how-to/bringing-your-own-model.md`](how-to/bringing-your-own-model.md)
walks through picking a provider and testing a key.
[`docs/reference/settings-api.md`](reference/settings-api.md) is the HTTP
contract.

## Types, and how a value is parsed

- A **boolean** accepts `1`, `true`, `yes` or `on`, and `0`, `false`, `no` or
  `off`. Case does not matter.
- An **enum** is stripped and lowercased before it is checked against its
  choices.
- An **empty variable reads as unset**, everywhere. `AGENT_TRACING=` clears
  the setting rather than asking for the empty string.
- Minimum and maximum bounds are inclusive. A value outside them is refused
  with a 422 rather than clamped.

## Secrets

Four declared settings are secret — `AGENT_API_KEY`, `AGENT_EMBEDDING_API_KEY`,
`AGENT_PGVECTOR_DSN` and `AGENT_NEO4J_PASSWORD` — plus 16 of the 20 provider
credentials. Azure's `resource`, `deployment` and `api_version` and Bedrock's
`region` are not secret: they are addresses, and hiding them buys nothing.

**A stored secret is never read back.** The resolved view returns `value:
null` and a mask:

```json
{"key": "provider_key.groq.api_key", "value": null, "layer": "project",
 "secret": true,
 "masked": {"present": true, "last_four": "5678", "display": "set (…5678)"}}
```

That is measured, not described: the response above was taken from a running
server on 2026-08-29. The mask shows the *last* four characters. A prefix
would identify the vendor rather than the key.

Secrecy is structural rather than a rule each route remembers. `Resolved.value`
is `None` for any secret, always. Plaintext is reachable only through
`SettingsResolver.secret()`, which has no HTTP surface above it.

**What the encryption protects against, and what it does not.** Values are
sealed with AES-256-GCM under a key derived from `AGENT_SETTINGS_KEY`. That
protects a stolen database file and a careless backup. It does **not** protect
against anyone who can read this process's environment, because the key is in
it. A KMS adapter behind `SecretBoxPort` is the named upgrade path, and it is
not built.

If the key changes, a sealed value no longer opens. The resolver logs a
warning and stops the scope walk for that setting rather than falling through
to the environment. A shadowed environment value would be worse: you would get
a working system configured with something other than what you stored.

## There is no authorization on the settings API yet

Every route under `/api/settings`, `/api/profiles` and `/api/providers` takes
its scope and scope id as plain path or query parameters, and checks nothing.
Anyone who can reach the HTTP surface can write a tenant-scoped override or
read the whole schema. `AGENT_WEB_HOST` defaults to `127.0.0.1`, so a default
deployment is not exposed. **Do not bind this to a public interface.** The
authorization work is designed in
[`docs/design/tenancy-and-authorization.md`](design/tenancy-and-authorization.md)
and is not implemented.

There is also no audit trail. A write replaces the row. This is not
event-sourced, unlike the rest of the system, and that is deliberate rather
than an oversight — `infrastructure/settings/store.py` says why.

## Durable backends

Both store defaults keep everything in this process, and neither needs a
container. `docker-compose.yml` brings up the two servers that change that:

```bash
docker compose up -d
export AGENT_GRAPH_STORE=neo4j
export AGENT_NEO4J_PASSWORD=research
export AGENT_VECTOR_STORE=pgvector
export AGENT_PGVECTOR_DSN=postgresql://research:research@localhost:5432/research_team
```

The remaining Neo4j and embedding variables already default to what the
compose file serves. **Nothing needs to be run against the database first.**
The `vector` extension and the table are created on the first project open, by
`ensure_schema`. The image has to be `pgvector/pgvector` rather than
`postgres`: `vector` is a compiled extension and the stock image cannot create
it.

**The three stores are not the same kind of durable, and the difference is
worth knowing before you choose:**

- **`AGENT_GRAPH_STORE`** changes where a *derived* store lives. Extraction is
  recorded in the event log as `DocumentExtracted`, and the graph is rebuilt
  from it at every project open. So `memory` costs a fold at startup and loses
  nothing. `neo4j` gives you a graph you can query with Cypher and a startup
  that does not re-fold. Switching back loses nothing either.
- **`AGENT_VECTOR_STORE`** changes whether embeddings survive at all. Since
  2026-08-22 the vectors are on the event log, so a project folds them back at
  open. Before that they were not, and every vector this system computed was
  dropped when its process ended. A project older than that clusters on the
  graph alone until you press **Embed entities**.
- **`AGENT_CHUNK_STORE`** is the same shape as `AGENT_GRAPH_STORE`. The
  document-chunk corpus behind entity usage lookups is derived from
  `DocumentChunked`, so `memory` is rebuilt by folding the log at project
  open. What the default costs is that fold, proportional to corpus size, paid
  once per project open. It is not data loss. `postgres` is a real redstring
  adapter that this deployment refuses rather than ships untested:
  `build_chunk_store` raises and names it, so a deployment that sets it is
  told it picked a real, unwired setting rather than a typo.

  **A corpus stored before chunk indexing shipped has no `DocumentChunked` to
  fold, whatever this is set to.** Such a project comes up with an empty chunk
  store, and that is invisible: entity usage lookups return nothing and the
  entity panel says "No mentions of this entity were found", which is also
  what a correct answer looks like. `POST
  /api/projects/{project_id}/sources/reindex` is the repair. It re-chunks every
  stored document, makes no model call, and is safe to run at any time. `POST
  /api/corpus/rebuild` does **not** help: it rebuilds the corpus documents
  table, which is derived from the log, and these chunks are not.

`docker-compose.test.yml` is a separate file for `pytest -m integration`. It
binds the same two servers on different ports (7688, 55432) and keeps no data,
so an integration run cannot reach the database you are actually using. Both
can be up at once.

## Embeddings are on, and here is what they cost

Consolidation scores a candidate pair on `name`, `graph` and `embedding`. With
the third feature absent, an entity named identically in two documents that
describe different neighbourhoods scores **0.7143** — below redstring's
`LOW_SIMILARITY` of 0.75, so it is dropped before anything is asked about it.
That is the bug behind the same dog breed appearing twice on one canvas. With
the third feature it scores **0.8000**, clears 0.75 on its own evidence, and is
adjudicated.

Two things it does **not** do, stated because both are easy to assume:

- **It does not improve discrimination.** redstring embeds the entity *name*
  and nothing else, so the embedding feature is a blurrier second measurement
  of the string the name feature already measured. Under a real model an exact
  duplicate and `University of York` / `University of Cork` land about 0.011
  apart, and both are adjudicated.
- **It does not enable auto-merge across documents.** A perfect name and a
  perfect embedding cap at 0.8 against a graph feature of 0.0, below
  `HIGH_SIMILARITY` of 0.92. So **every cross-document duplicate costs one
  adjudicator call.** That is the running cost, and it scales with duplicates
  rather than with corpus size.

Indexing costs one embedding call per extracted entity, batched into a single
request per document. It is paid again on re-ingest: `build_graph` re-embeds
rather than suppressing a repeat, so the store absorbs it as an idempotent
rewrite and you pay the call. Embedding happens *after* extraction, inside the
same ingest. It is not deferred, and nothing is embedded for a document that
was never extracted.

**If your endpoint does not serve embeddings**, nothing breaks. The default
`AGENT_EMBEDDING_BASE_URL` is the chat endpoint, and llama.cpp serves one model
per process, so this is the expected misconfiguration rather than an exotic
one. On the first ingest the adapter probes the endpoint once. If the call
fails, or the width it returns disagrees with `AGENT_EMBEDDING_DIMENSION`, it
logs a warning and consolidates on `name` and `graph` for the rest of the
process. Ingests still complete: a document already fetched and extracted is
not thrown away over an optional scoring signal. Set `AGENT_VECTOR_STORE=none`
to skip the probe and say you meant it.

## `AGENT_EXTRACTION_CONCURRENCY` and `AGENT_EXTRACTION_CHUNK_SIZE`

`AGENT_EXTRACTION_CONCURRENCY` bounds calls in flight **per document**. Two
documents ingested at once are two ceilings, so the real bound against the
server is this times the number of overlapping ingests. The default of 8
matches the slot count of the local server `AGENT_BASE_URL` points at. Lower it
for a hosted endpoint with a per-minute quota.

`AGENT_EXTRACTION_CHUNK_SIZE` defaults to 2000, against redstring's own default
of 3000. Smaller chunks extract more and are only affordable because the calls
overlap. Set both back to `1` and `3000` together to get the pre-0.8.0 pipeline
exactly. Below roughly 2000 characters, extraction starts manufacturing
duplicate identities rather than finding more. Raising extraction's yield also
raises what consolidation pays: more mentions is more candidate pairs, and each
cross-document duplicate costs an adjudicator call.

## `AGENT_CATALOG_SWEEP_CONCURRENCY` defaults to 1, and that was measured

The sweeps can run candidates in parallel. The default is `1` because on this
deployment parallelism was measured to buy nothing. Interleaved on 2026-08-24
with a latency probe bracketing every run, ceiling 8 came back 1.0% faster than
ceiling 1 over the same 24 candidates — 148.0s against a 149.5s clean
sequential baseline. This server serialises.

Raise it for an endpoint that batches, and re-measure interleaved before you
do. See `catalog_sweep_concurrency` in `config.py` for the table, for the row
excluded because it straddled a change in load, and for the contended run that
reads as a 1.85x slowdown and is not one.

## `AGENT_AUTHORING_ROUNDS` defaults to 6, and that was measured too

A course-authoring parent turn may make 6 model calls before its graph, corpus
and web tools are withdrawn. The turn continues; it just cannot research any
more, so the next thing it can do is write.

The bound exists because without it the parent researched instead of writing.
**18 of 22 authoring runs never reached the write.** A budget of 16, derived
from the log, was inert — it was above what any run reached. Three live runs
fixed the working figure at 6.

Set `0` to turn the bound off. Raise it if your model needs more reading before
it can write, and expect the spiral back if you raise it far.

## `AGENT_CURATION_MODEL` defaults to the chat model, on purpose and loosely

Curation — deciding what a topic needs seen or heard, phrasing a search term,
judging a pool of results — is a distinct role from the chat model, the same
way embedding is. It differs from `AGENT_EMBEDDING_MODEL` in what happens when
you leave it unset. Embedding has no reasonable default: a chat model refuses
or, worse, answers something vector-shaped and numerically meaningless, so that
variable is required once the vector store is on. Curation's replies are read
the way the agent's own JSON-shaped tool replies already are, so pointing it at
`AGENT_MODEL` is a reasonable place to start rather than a hazard.

That default is a convenience, not a claim that the two roles are the same
thing. Set `AGENT_CURATION_MODEL` once curation should run cheaper, faster, or
on a different endpoint, and the two stop moving together.

## `image_proxy` — a deployment setting the code cannot enforce

The media review pane renders thumbnails from whatever the search instance
returns in `thumbnail_src`. Measured on 2026-08-15 against a real SearXNG
instance: it returns **raw third-party thumbnail URLs**
(`https://tse1.mm.bing.net/...`), because `image_proxy` is off by default. With
it off, opening the pane makes the viewer's browser fetch each thumbnail
directly from whoever indexed the image. That leaks the viewer's IP and
referrer to a third party, once per thumbnail rendered.

This is a different axis from the project's usual "nothing escapes" property.
That property is about the *agent process*: no shell, network gated by default,
pinned by `test_no_network.py` and `test_no_shell.py`. This is the *browser*,
which the agent process does not mediate and this project's code cannot reach
into. The pane renders whatever `thumbnail_src` holds. The fix has to happen
where that field is produced.

Set it on the SearXNG instance's `settings.yml`:

```yaml
server:
  image_proxy: true
```

With it set, SearXNG rewrites `thumbnail_src` to an instance-relative proxied
URL before the pane ever sees it, and the browser never talks to a third
party. Nothing in this codebase changes.

**The rejected alternative** was a proxy endpoint of our own — the server
fetching model-supplied thumbnail URLs on a browser's behalf. That solves the
leak but adds an SSRF surface, our server told to fetch an attacker-chosen URL,
for a feature that does not need one. SearXNG already does this job when asked
to.

One more thing the same measurement turned up: `thumbnail_src` was absent on 46
of 262 captured image results (`thumbnail` was frequently present but empty).
The pane falls back to a typed placeholder rather than the full-size asset in
that case. Falling back to the full asset would put a grid of full-resolution
images on the page for the results that happened to lack a thumbnail, which is
not the same failure mode as a missing thumbnail should produce.

This was one instance, one afternoon, 262 image results captured in one
session. What generalises is the shape — an unproxied instance leaks, a proxied
one does not, thumbnails are sometimes absent — not the exact ratio. A
different instance or a differently-indexed query set will not reproduce
46/262.

## Where to read more

| | |
|---|---|
| [`docs/how-to/bringing-your-own-model.md`](how-to/bringing-your-own-model.md) | pick a provider, store a key, test it, select it for a role |
| [`docs/reference/settings-api.md`](reference/settings-api.md) | the HTTP contract for settings, providers and profiles |
| [`docs/design/settings-page.md`](design/settings-page.md) | the console surface these routes were designed for, not yet built |
| [`docs/design/tenancy-and-authorization.md`](design/tenancy-and-authorization.md) | who may write which scope, designed and not implemented |
