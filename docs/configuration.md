# Configuration

Every setting is an environment variable. The README carries the handful a
first run needs; this file is all of them, plus the reasoning behind the ones
where the obvious choice is wrong.

The model is an OpenAI-compatible endpoint, configured entirely by environment
variable:

| Variable | Default | Meaning |
|---|---|---|
| `AGENT_MODEL` | `qwen3.6-27b-mtp` | model name sent to the endpoint |
| `AGENT_BASE_URL` | `http://localhost:8080/v1/` | OpenAI-compatible base URL |
| `AGENT_API_KEY` | `not-needed` | API key; local servers usually ignore it |
| `AGENT_DB` | `~/.research-team/sessions.db` | SQLite file holding all sessions |
| `AGENT_WEB_HOST` | `127.0.0.1` | interface the web UI binds to |
| `AGENT_WEB_PORT` | `8000` | port the web UI binds to |
| `AGENT_CONTEXT` | `full` | how this instance manages context: `full`, `elide`, `compact`, `delegate` |
| `AGENT_CONTEXT_TRIGGER` | `120000` | approximate tokens of live conversation before `compact` summarizes |
| `AGENT_CONTEXT_KEEP_MESSAGES` | `20` | recent messages `compact` leaves out of the summary |
| `AGENT_CONTEXT_KEEP_RESULTS` | `6` | recent tool results `elide` leaves whole |
| `AGENT_CONTEXT_CLEAR_OVER` | `2000` | tool results longer than this are cleared outright under `elide` |
| `AGENT_TRACING` | unset | set to `1` to export OpenTelemetry traces (needs the `tracing` extra) |
| `AGENT_OTLP_ENDPOINT` | `http://localhost:4318/v1/traces` | where traces are sent |
| `AGENT_SERVICE_NAME` | `research-team` | what this process calls itself in a trace |
| `AGENT_RESEARCH_RUN` | *(unset)* | set to `1` to expose the autonomous-run routes over HTTP; unset means they are absent |
| `AGENT_SEARXNG_URL` | *(unset)* | SearXNG base URL; unset means no search tool is registered |
| `AGENT_SEARXNG_RESULTS` | `5` | how many results reach the model |
| `AGENT_GRAPH_STORE` | `memory` | what backs the knowledge graph: `memory` or `neo4j` |
| `AGENT_KNOWLEDGE_DOMAIN` | `auto` | a redstring schema id, or `auto` to have a classifier choose |
| `AGENT_EXTRACTION_THINKING` | *(unset)* | set to `1` to let the extraction model reason before answering; off by default because extraction is measurably worse for it (slower, more false positives, same recall). Turn it on for a backend with no chat template — OpenAI's hosted API rejects the field with a 400 on the first extraction call |
| `AGENT_EXTRACTION_CONCURRENCY` | `8` | how many extraction calls may be in flight **per document**. Two documents ingested at once are two ceilings, so the real bound against the server is this times the number of overlapping ingests. Matches the slot count of the local server `AGENT_BASE_URL` points at; lower it for a hosted endpoint with a per-minute quota |
| `AGENT_EXTRACTION_CHUNK_SIZE` | `2000` | characters per extraction chunk, against redstring's own default of 3000. Smaller chunks extract more and are only affordable because the calls overlap — set both back to `1` and `3000` together to get the pre-0.8.0 pipeline exactly. Below roughly this size, extraction starts manufacturing duplicate identities rather than finding more. Raising extraction's yield also raises what consolidation pays: more mentions is more candidate pairs, and each cross-document duplicate costs an adjudicator call |
| `AGENT_CATALOG_SWEEP_CONCURRENCY` | `1` | how many candidates a catalog blurb or art sweep works on at once. The sweeps can run them in parallel; `1` because on this deployment it was measured to buy nothing — interleaved on 2026-08-24 with a latency probe bracketing every run, ceiling 8 came back 1.0% faster than ceiling 1 over the same 24 candidates (148.0s vs a 149.5s clean sequential baseline). This server serialises. Raise it for an endpoint that batches, and re-measure interleaved before you do — see `catalog_sweep_concurrency` in `config.py` for the table, for the row excluded because it straddled a change in load, and for the contended run that reads as a 1.85x slowdown and is not one |
| `AGENT_NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection URI, when `AGENT_GRAPH_STORE=neo4j` |
| `AGENT_NEO4J_USER` | `neo4j` | Neo4j username |
| `AGENT_NEO4J_PASSWORD` | *(unset)* | Neo4j password; required when `AGENT_GRAPH_STORE=neo4j`, no default |
| `AGENT_NEO4J_DATABASE` | *(unset)* | which database on the server; unset means the server's default |
| `AGENT_VECTOR_STORE` | `memory` | what holds entity embeddings: `none`, `memory` or `pgvector`. `none` switches embedding off; `memory` loses every vector when the process ends and cannot get them back — see "Durable backends" below |
| `AGENT_EMBEDDING_MODEL` | `nomic-embed-text` | the embedding model's name. **Not** `AGENT_MODEL`, which names a chat model. Set this and the dimension together |
| `AGENT_EMBEDDING_DIMENSION` | `768` | how wide that model's vectors are — `nomic-embed-text`'s width. A property of the model, not a preference |
| `AGENT_EMBEDDING_BASE_URL` | *(`AGENT_BASE_URL`)* | where embedding requests go, when that is not the chat endpoint. llama.cpp serves one model per process, so this is usually a second port |
| `AGENT_EMBEDDING_API_KEY` | *(`AGENT_API_KEY`)* | key for the embedding endpoint, when it differs |
| `AGENT_PGVECTOR_DSN` | *(unset)* | Postgres DSN; required when `AGENT_VECTOR_STORE=pgvector`, no default. Reached when the store is built, so a wrong one fails at startup rather than mid-ingest |
| `AGENT_CHUNK_STORE` | `memory` | what backs the document-chunk corpus that usage lookups search: `none`, `memory`, or `postgres` (listed as a real, unwired setting rather than a typo — see below) |
| `AGENT_CURATION_MODEL` | *(`AGENT_MODEL`)* | model the media-curation chain runs on: phrasing a search term, judging a pool of results |
| `AGENT_VISION_MODEL` | *(unset)* | model that describes frames and images; unset means no vision |
| `AGENT_TRANSCRIBER_MODEL` | *(unset)* | ASR model name, required once `AGENT_TRANSCRIBER_URL` is set |

### Durable backends

Both defaults keep everything in this process, and neither needs a container.
`docker-compose.yml` brings up the two servers that change that:

```
docker compose up -d
export AGENT_GRAPH_STORE=neo4j
export AGENT_NEO4J_PASSWORD=research
export AGENT_VECTOR_STORE=pgvector
export AGENT_PGVECTOR_DSN=postgresql://research:research@localhost:5432/research_team
```

The remaining Neo4j and embedding variables already default to what the compose
file serves. **Nothing needs to be run against the database first** — the
`vector` extension and the table are created on the first project open, by
`ensure_schema`. The image has to be `pgvector/pgvector` rather than `postgres`,
though: `vector` is a compiled extension and the stock image cannot create it.

**The two are not the same kind of durable, and the difference is worth
knowing before you choose:**

- **`AGENT_GRAPH_STORE`** changes where a *derived* store lives. Extraction is
  recorded in the event log as `DocumentExtracted`, and the graph is rebuilt
  from it at every project open — so `memory` costs a fold at startup and
  loses nothing. Switching to `neo4j` gives you a graph you can query with
  Cypher and a startup that does not re-fold; switching back loses nothing
  either.
- **`AGENT_VECTOR_STORE`** changes whether embeddings survive at all. This
  project does not append `EntitiesEmbedded`, so there is nothing in the log
  for a replay to fold, and `memory` means **every vector is lost when the
  process ends** — after a restart, consolidation silently drops to two
  features for every entity extracted before it, which is the scoring the
  default was turned off for. `pgvector` is currently the only setting under
  which an embedding outlives the process. Re-ingesting a document re-embeds
  it and repairs this; nothing else does.
- **`AGENT_CHUNK_STORE`** is the same shape as `AGENT_GRAPH_STORE`, not
  `AGENT_VECTOR_STORE`: the document-chunk corpus behind entity usage lookups
  is derived from `DocumentChunked`, so `memory` — the default — is the
  graph's "memory", rebuilt by folding the log at project open rather than
  lost with the process. What the default costs is that fold, proportional to
  corpus size, paid once per project open, not data loss. `postgres` is a real
  redstring adapter that this deployment refuses rather than ships untested —
  `build_chunk_store` raises naming it explicitly, so a deployment that sets
  it is told it picked a real, unwired setting rather than a typo. Nobody has
  asked for a chunk corpus that outlives the process yet.

  **A corpus stored before chunk indexing shipped has no `DocumentChunked` to
  fold, whatever this is set to.** The fold is the only thing that fills the
  chunk store, so such a project comes up with an empty one — and that is
  invisible: entity usage lookups simply return nothing and the entity panel
  says "No mentions of this entity were found", which is also what a correct
  answer looks like. `POST /api/projects/{project_id}/sources/reindex` is the
  repair. It re-chunks every stored document, makes no model call, and is safe
  to run at any time. `POST /api/corpus/rebuild` does *not* help: it rebuilds
  the corpus documents table, which is derived from the log, and these chunks
  are not.

`docker-compose.test.yml` is a separate file for `pytest -m integration`. It
binds the same two servers on different ports (7688, 55432) and keeps no data,
so an integration run cannot reach the database you are actually using. Both
can be up at once.

### Embeddings are on, and here is what they cost

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
  adjudicator call** — that is the running cost, and it scales with duplicates
  rather than with corpus size.

Indexing costs one embedding call per extracted entity, batched into a single
request per document. It is paid again on re-ingest: `build_graph` re-embeds
rather than suppressing a repeat, so the store absorbs it as an idempotent
rewrite and you pay the call. Embedding happens *after* extraction, inside the
same ingest — it is not deferred, and nothing is embedded for a document that
was never extracted.

**If your endpoint does not serve embeddings**, nothing breaks. The default
`AGENT_EMBEDDING_BASE_URL` is the chat endpoint, and llama.cpp serves one model
per process, so this is the expected misconfiguration rather than an exotic
one. On the first ingest the adapter probes the endpoint once; if the call
fails, or the width it returns disagrees with `AGENT_EMBEDDING_DIMENSION`, it
logs a warning and consolidates on `name` and `graph` for the rest of the
process. Ingests still complete — a document already fetched and extracted is
not thrown away over an optional scoring signal. Set `AGENT_VECTOR_STORE=none`
to skip the probe and say you meant it.

### `AGENT_CURATION_MODEL` defaults to the chat model, on purpose and loosely

Curation — deciding what a topic needs seen or heard, phrasing a search term,
judging a pool of results — is a distinct role from the chat model, the same
way embedding is. It differs from `AGENT_EMBEDDING_MODEL` in what happens when
you leave it unset: embedding has no reasonable default (a chat model refuses
or, worse, answers something vector-shaped and numerically meaningless), so
that variable is required once the vector store is on. Curation's replies are
read the way the agent's own JSON-shaped tool replies already are, so pointing
it at `AGENT_MODEL` is a reasonable place to start rather than a hazard, and
`AGENT_CURATION_MODEL` defaults to `model_name()` accordingly. That default is
a convenience, not a claim that the two roles are the same thing — set
`AGENT_CURATION_MODEL` once curation should run cheaper, faster, or on a
different endpoint, and the two stop moving together.

### `image_proxy` — a deployment setting the code cannot enforce

The media review pane renders thumbnails from whatever the search instance
returns in `thumbnail_src`. Measured on 2026-08-15 against a real SearXNG
instance: it returns **raw third-party thumbnail URLs**
(`https://tse1.mm.bing.net/...`), because `image_proxy` is off by default. With
it off, opening the pane makes the viewer's browser fetch each thumbnail
directly from whoever indexed the image — leaking that viewer's IP and
referrer to a third party, once per thumbnail rendered.

This is a different axis from the project's usual "nothing escapes" property.
That property is about the *agent process* — no shell, network gated by
default, pinned by `test_no_network.py` and `test_no_shell.py`. This is the
*browser*, which the agent process does not mediate and this project's code
cannot reach into. The pane renders whatever `thumbnail_src` holds; the fix has
to happen where that field is produced.

Set it on the SearXNG instance's `settings.yml`:

```yaml
server:
  image_proxy: true
```

With it set, SearXNG rewrites `thumbnail_src` to an instance-relative proxied
URL before the pane ever sees it, and the browser never talks to a third
party. Nothing in this codebase changes; the fix is entirely in the instance
you point `AGENT_SEARXNG_URL` at.

**The rejected alternative** was a proxy endpoint of our own — the server
fetching model-supplied thumbnail URLs on a browser's behalf. That solves the
leak but adds an SSRF surface (our server, told to fetch an attacker-chosen
URL) for a feature that does not need one, since SearXNG already does this
job when asked to.

One more thing the same measurement turned up: `thumbnail_src` was absent on
46 of 262 captured image results (`thumbnail` was frequently present but
empty). The pane falls back to a typed placeholder rather than the full-size
asset in that case — falling back to the full asset would put a grid of
full-resolution images on the page for the results that happened to lack a
thumbnail, which is not the same failure mode as a missing thumbnail should
produce.

This was one instance, one afternoon, 262 image results captured in one
session. What generalises is the shape — an unproxied instance leaks, a
proxied one doesn't, thumbnails are sometimes absent — not the exact ratio;
a different instance or a differently-indexed query set will not reproduce
46/262.
