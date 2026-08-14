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
| `AGENT_EXTRACTION_CHUNK_SIZE` | `2000` | characters per extraction chunk, against redstring's own default of 3000. Smaller chunks extract more and are only affordable because the calls overlap — set both back to `1` and `3000` together to get the pre-0.8.0 pipeline exactly. Below roughly this size, extraction starts manufacturing duplicate identities rather than finding more |
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
