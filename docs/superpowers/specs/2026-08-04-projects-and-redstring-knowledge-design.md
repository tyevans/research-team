# Projects and a redstring knowledge graph

## The problem

The agent researches, and then forgets. A session's filesystem and its findings
die with the session, so session 40 cannot use what session 3 learned. Web
search makes this sharper rather than better: the agent can now reach outside
the process, but everything it reaches stays flat text in one conversation log.

redstring turns documents into a queryable graph of entities and relationships,
and it is built on the same substrate as this project — `eventsource-py`, a
store that is a projection of a log rather than a second source of truth. The
two fit together well enough that the integration is mostly a question of
choosing boundaries carefully.

This spec covers the foundation: a **project** that scopes shared state across
sessions, a **knowledge port** with a redstring adapter behind it, and an
**ingest path** the agent drives, plus one recall tool to prove the read side.

research-team is redstring's first consumer. Five gaps that finding surfaced
are recorded in [Upstream dependencies](#upstream-dependencies); this spec is
designed to ship against redstring as it is today, and to unwind cleanly when
they land.

## Scope

In scope:

- `Project` — a collection of sessions sharing a virtual filesystem, sequential.
- `KnowledgePort` — the application-side seam, naming no redstring types.
- `RedstringKnowledge` — the adapter, and the only module importing redstring.
- `remember` — extraction and consolidation, driven by the agent.
- `unmerge` — reversing a consolidation the agent judges wrong.
- `graph_search` — one recall tool, pulled forward so the port's read side is
  exercised rather than guessed.

Out of scope, each with its own later spec:

- **Vector search of any kind**, and the embedding step it needs. See R1: the
  library cannot populate a `VectorStore` today, so a slice that configured one
  would configure a store guaranteed to stay empty.
- The rest of recall: `neighbors`, temporal slicing.
- A `fetch` tool, and distillation strategies over what it retrieves.
- The event log as a content source — folding session events into documents.
- Web and CLI surfaces for the graph.
- Forked concurrency within a project, and the merge mechanics it needs.

## Decisions

### A project is a sequential collection of sessions

Sessions in a project run one at a time. Each inherits the project's current
filesystem, works, and leaves its file events as the project's new tip. A
second concurrent session is rejected, naming the session that holds the
project, rather than merged.

This reuses the fork machinery rather than adding a parallel one: inheriting a
project tip is the same operation as `SessionForkedFrom`, with a different
reason. The alternative — a project aggregate owning the file stream, so
concurrent sessions share a live filesystem — was rejected because it costs the
property the system leads with. If files are the project's events rather than
the session's, scrubbing a session's timeline no longer refolds its filesystem.
That trade is only worth making for genuine concurrent collaboration, which is
not yet wanted.

Forked concurrency is the expected next step, and nothing here forecloses it.

### The graph is scoped to a project

The project id **is** redstring's `tenant_id`, which means `project_id` must be
a `UUID` — redstring's `TenantId` is `UUID`, not a string.

This is why the project concept comes first: a shared graph without a boundary
has no natural tenant, and a session-scoped graph is a research memory that
forgets.

### redstring's own streams live in the same event store

Not a stream of our naming. redstring derives its stream ids and does not
accept a caller-supplied one:

- `DocumentExtracted` → `StreamId(uuid5(tenant_id, source_id), "Document")` —
  one stream per document.
- `EntitiesMerged` / `MergeUndone` → `StreamId(tenant_id, "Consolidation")` —
  one per project.

Both events bake `aggregate_type` in, and the services write through their own
repositories. So the adapter passes research-team's `SQLiteEventStore` and
`SQLiteSnapshotStore` into redstring rather than routing redstring's events
somewhere of its own choosing.

An earlier draft of this spec invented a single `StreamId(project_id,
"knowledge")` stream. That is recorded here because the reason it fails is
worth keeping: parking these events on a foreign stream is mechanically legal —
the SQLite adapter writes the stream's category and ignores the event's — but
it forfeits `Document`'s per-`model_version` idempotency, the merge guards, and
`unmerge` entirely, because `undo` rehydrates `ConsolidationLog` by replaying
the `Consolidation` stream and would raise `UnknownMergeError` against events it
cannot see.

Everything that framing was reaching for survives without it. One SQLite file
holds the session streams and redstring's, so there is one place to look for
provenance and one thing to back up, and the graph is still a projection that
can be rebuilt.

**Replay purity is the constraint every part of this obeys.** Extraction is a
model call. If it runs at fold time, a refolded session stops reproducing what
the agent actually saw, and a session refolded years later depends on a live
endpoint. So extraction results are recorded as events and never recomputed on
replay — the same reason a search result is recorded rather than re-fetched.

### Sharing a store with redstring has two consumer-side costs

Both are ours, not redstring's, and both must be paid or reads break:

- **The event registry must be complete.** redstring registers its event types
  by `@register_event` at *import* time, and research-team constructs
  `SQLiteEventStore` against the default registry. A read that touches
  redstring rows without redstring imported raises `EventTypeNotFoundError` —
  which would hit exactly the "no project, no store" path. So composition
  imports `redstring.events` unconditionally. It is cheap and touches no
  network.
- **`read_since` must be filtered.** `EventStoreSessionRepository.read_since`
  reads the whole store and builds `FeedEntry(session_id=event.aggregate_id)`.
  Unfiltered, the live feed and session list would show entries attributed to
  documents that are not sessions. It filters to the `CodingSession` category.

### Knowledge-first ordering

An ingest writes to redstring's streams before returning a tool result to the
session. A crash between the two leaves an orphan extraction — the graph
learned something the session log does not mention — rather than a phantom one,
where the log claims an extraction that never landed. The graph is the thing
that must not lie.

### Consolidation is automatic, adjudicated, and reversible

`Consolidator.resolve()` runs over the entities from each extraction. Skipping
consolidation produces one node per *mention*, which looks like a knowledge
graph and answers every question wrong, because an entity's edges are split
across its aliases.

Three things about how redstring actually does this shape the adapter:

- **`resolve` is per-entity.** It takes an `Entity` and returns a
  `ConsolidationReport | None`, where `None` means nothing worth merging. So an
  ingest loops over the extraction's entities.
- **`resolve` appends and folds its own merge event.** The adapter must *not*
  append `EntitiesMerged` itself; doing so would double-apply the merge.
- **Without an `Adjudicator`, the middle similarity band is rejected rather
  than merged.** So the adapter passes one, built over the same LLM provider as
  extraction. `Adjudicator` is exported. Without it, consolidation would be
  name-and-structure-only, which is materially weaker than this decision
  promises — and weaker still here, because there are no embeddings to
  contribute a signal (R1).

Merges are reversible: the agent gets `unmerge`. `undo` is durable rather than
session-only *only if* the `Consolidator` is constructed with both `event_store`
and `snapshot_store`; omitting them silently substitutes an in-memory store. The
adapter passes both, and a test asserts `remembers_merges_across_restarts` —
that property exists to be asserted.

### Repairing an interrupted ingest is our bookkeeping, not a sweep

An earlier draft proposed a `resolve` sweep over "unconsolidated entities" at
project open. There is no such API and no way to identify one — `Entity` carries
no consolidation state, so the only approximation is paging every entity in the
tenant and re-resolving it, which is O(all entities) per open and redoes settled
work.

Instead the ingest records the `source_id` on the session side before
consolidating. If consolidation is interrupted, repair re-resolves the entities
of *that* extraction only: bounded, cheap, and needing no library support. R2
would let this be simpler, and this is the code it replaces.

### Stores are in-memory by default, and swappable

`InMemoryGraphStore`, rebuilt at project open. No servers, `uv run main.py`
keeps working. Store construction sits behind config, so moving to Neo4j is
wiring rather than redesign — and the rebuild-from-log path that move needs is
the same path used at every startup, so it is continuously exercised rather than
written under duress during a migration.

Two qualifications:

- **"No extras" covers the stores, not the model provider.**
  `LangChainLlmProvider` needs `redstring[llm]`. `FakeLlmProvider` is in the
  base install, so the adapter tests still need nothing.
- **Rebuilding scopes by `tenant_filter`, not by stream.** `project()` folds the
  *global* feed with no stream or category argument, so in a shared store it
  reads every session event too. Passing `tenant_filter=project_id` to
  `GraphProjection` is the supported scoping; research-team's own events carry
  no tenant and are filtered out. This is a workaround for R3 and should be
  revisited when that lands.
- **Project open refuses on a failed replay.** `ReplayReport.failed` is a count,
  not a raise — poison events are swallowed. Startup checks it and refuses,
  because a half-populated graph that answers queries is worse than one that
  does not start. Workaround for R4.

## Architecture

```
remember(text, source_id)
  -> build_graph(...)               # extract, fold into GraphStore
  -> append report.event            # DocumentExtracted -> Document stream
  -> for each entity:
       Consolidator.resolve(entity) # appends EntitiesMerged AND folds, itself
  -> tool result on the session stream
```

`build_graph` rather than driving `ExtractionPipeline` by hand: it folds into
the store *and* returns `report.event` unappended for precisely this purpose,
and it yields `domain` and `domain_confidence`, which the manual path loses —
recovering them would mean a dotted import of the internal `ContentClassifier`.
The cost is one redundant fold, which is idempotent by upsert. Chunking is not
omitted; `ExtractionPipeline` defaults to `SlidingWindowChunker`.

Every redstring call happens inside `async with tenant_scope(project_id)` —
`TenantAwareRepository` raises `TenantContextNotSetError` outside one, and the
extraction path does not open its own.

Three seams:

**`Project`** (`domain/project.py`) — a decider aggregate holding membership and
the filesystem lineage pointer. Events: `ProjectCreated`,
`SessionJoinedProject`, `ProjectTipAdvanced`. Mirrors `session.py`: `decide`,
`evolve`, pure. It must declare `aggregate_type = "Project"` — the default was
removed in eventsource 0.9.0 and its absence raises `AggregateTypeNotSetError`.

**`KnowledgePort`** (`application/knowledge.py`) — a Protocol in the style of
the existing ports:

- `ingest(source: SourceRef) -> IngestReport`
- `search(query: str) -> list[Match]`
- `undo_merge(merge_id: UUID) -> MergeRecord`

`SourceRef`, `IngestReport`, `Match` and `MergeRecord` are research-team's own
DTOs. No redstring type appears in this module. The tenant is not a parameter;
the adapter supplies it from the project.

**`RedstringKnowledge`** (`infrastructure/knowledge/redstring_adapter.py`) — the
only module that imports redstring. Owns tenant scoping, the projection, store
construction, and the `LlmProvider` built via `LangChainLlmProvider` over the
endpoint already configured by `AGENT_BASE_URL`.

### Modules

| Module | Responsibility |
|---|---|
| `domain/project.py` | The `Project` aggregate and its events |
| `application/knowledge.py` | `KnowledgePort` and its DTOs |
| `infrastructure/knowledge/redstring_adapter.py` | The one redstring importer |
| `infrastructure/knowledge/stores.py` | Store construction behind config |
| `infrastructure/agent/knowledge_tools.py` | The three tools, shaped like `search.py` |

### Dependencies

- `redstring[llm]` — the base install plus `langchain-openai`.
- `eventsource-py[sqlite]>=0.10.0` — already pinned. The floor must not drop:
  redstring's projections forward `retry_policy`, `tracer` and `tenant_filter`,
  which 0.9.x rejects with `TypeError`. See R5.

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `AGENT_GRAPH_STORE` | `memory` | `memory` or `neo4j` |
| `AGENT_KNOWLEDGE_DOMAIN` | `auto` | A redstring schema name, or `auto` |

Projects are not configured by environment variable. They are created and
selected through the session-management surface that already exists — a
`/project` REPL command and the web UI's session list — because a project is
data, not deployment configuration.

A session that belongs to no project gets no knowledge tools and opens no
store, the same posture `web_search` has without `AGENT_SEARXNG_URL`. The
variables above only decide what backs the store once a project exists.

### Tools

- **`remember(text, source_id, note?)`** — extract and consolidate. Returns
  entity and relationship counts, the extraction's domain and confidence, and
  the merges performed, so the agent can see what was joined and object.
  `source_id` must be non-blank; redstring raises on an empty one.
- **`graph_search(query)`** — entities matching a query, each with its type and
  a count of its relationships, capped and flattened the way search results
  are. Traversal from a known entity is `neighbors`, which is deliberately in
  the next spec; this tool finds entry points, it does not walk the graph.
- **`unmerge(merge_id)`** — reverses a consolidation. The id is the `event_id`
  of the `EntitiesMerged`, surfaced by `remember`'s result.

`remember` and `unmerge` are writes and join the gated set alongside the file
tools. `graph_search` is a read and defaults to `auto` like the file reads.
`AutonomyPolicy` gains the three names, and a `KNOWLEDGE_PROMPT` alongside
`SEARCH_PROMPT` describes when committing something to the graph is worth it
against merely reading.

## Error handling

| Situation | Behaviour |
|---|---|
| Extraction fails — endpoint down, timeout, malformed response | Nothing is appended. The tool returns a plain-language failure, as `search.py` does for a disabled JSON API. |
| Crash between the redstring append and the session tool result | An orphan extraction. Recoverable, and the reason for knowledge-first ordering. |
| Consolidation fails after extraction succeeded | The extraction stands, the merges so far stand, and the report says so. Repair re-resolves that `source_id`'s entities only. |
| Replay reports failures at project open | Refuse to start, naming the count. `ReplayReport.failed` is otherwise silent (R4). |
| Store unreachable at startup | Fail at composition, before any session opens. Never degrade silently to in-memory. |
| `domain=AUTO` falls back | `AUTO` never raises; it falls back to `encyclopedia_wiki` with confidence `0.0` on four paths. A fallback is indistinguishable from a confident choice by the domain alone, so `IngestReport` carries `domain_confidence` and the tool result prints it. `None` means no classifier ran; `0.0` means it gave up. |
| `unmerge` with an unknown id | `UnknownMergeError` covers never-happened, already-undone and wrong-consolidator indistinguishably. The tool reports it as "no such merge in this project". |
| Oversized input | Capped before extraction. Chunking multiplies model calls rather than capping them, so the cap is still ours to impose. |
| A second concurrent session in a project | Rejected by the decider, naming the session that holds it. |

## Testing

- **Decider tests** for `Project`, mirroring the existing `session.py` tests.
  Pure, no I/O.
- **Adapter tests against redstring's `FakeLlmProvider`** — no server, no store
  extras, runnable in CI.
- **Projection determinism** — rebuild twice from the same store, assert
  identical graphs.
- **Replay purity** — refold a session with a provider stub that raises on
  call, asserting no extraction happens at fold time. This is the property most
  worth pinning, because it is the one that dies silently.
- **Durable undo** — assert `remembers_merges_across_restarts`, and that a
  merge survives reopening the store.
- **Feed isolation** — with redstring events in the store, `read_since` yields
  only session entries.
- **Registry completeness** — reading a store containing redstring events
  succeeds from a cold import of research-team alone.
- **A no-network sibling** to `tests/integration/test_no_network.py`: a session
  with no project registers no knowledge tools and opens no store.
- Existing mutation testing covers the new decider and the report formatting.

## Upstream dependencies

Gaps in redstring that research-team, as its first consumer, surfaced. None
blocks this spec; each has a workaround named above, and each workaround is
written to be deleted.

Status is against **redstring 0.2.0**, which closed two of the five.

| | Gap | Status | What it costs here |
|---|---|---|---|
| **R1** | **No `EmbeddingProvider` port.** `VectorProjection` folds only `EntitiesEmbedded`, whose sole producer takes caller-supplied vectors. Nothing in the library can populate a `VectorStore`. | **Closed in 0.2.0.** `EmbeddingProvider`, `FakeEmbeddingProvider` and `EmbeddingProviderError` are exported; `build_graph` takes `embedding_provider` and `vector_store` together and refuses a mismatched or half-supplied pair. `LangChainEmbeddingProvider` is reached by path, so `import redstring` still pulls in no LangChain. | Nothing now. Vector search is unblocked but **not built** — no `AGENT_VECTOR_STORE`, no recall path. That is a feature to spec, not a workaround to delete. |
| **R2** | **No way to identify unconsolidated entities.** `Entity` carries no consolidation state. | Open. 0.2.0's `Entity` still has no such field, and its docstring records the omission as deliberate. | Repair bookkeeping stays on our side, keyed by `source_id`. |
| **R3** | **`project()` cannot scope to a stream, category or tenant** — global feed only. | Open, and cheaper to close than first recorded: `GlobalEventFeed.read_all` already accepts `FeedReadOptions(tenant_id=...)`, which the eventsource SQLite adapter pushes into the `WHERE` clause. `project()` calls `read_all(from_position)` and never passes options, so filtering the query could do happens in Python instead. | Rebuild uses `tenant_filter` and still reads the whole log per project open. |
| **R4** | **`ReplayReport.failed` is a count, not a raise.** No strict mode. | Open, and worse than "no strict mode": the handler is a bare `except Exception` that **discards the exception**, so no caller can learn which event failed or why. | Project open checks the count and refuses — safely, and with a message nobody can act on. |
| **R5** | **eventsource floor understated** — `>=0.9.1`, but projections forward keywords added in 0.10.0. | **Closed in 0.2.0.** Floor is now `>=0.10.0,<0.12`, tested against 0.11.0. | None, and none before: our floor was already 0.10.0. |

When a redstring release closes these, the workarounds are the change list.

Two further asks that no longer fit the table, because they are additions
rather than gaps this spec worked around:

- **A progress callback on `build_graph`.** `remember` is one opaque `await`
  that chunks, extracts per chunk and consolidates per entity — the slowest
  thing in a turn and the least legible. The web UI's activity channel shows
  the tool call and the final report with nothing in between, and cannot show
  more until redstring emits something to show. Closing this also needs work
  here: `build_knowledge_tools` takes no `ActivityReporter`, so a tool has
  nowhere to send progress even if it had some.
- **An alias for the `project` verb.** redstring exports it bare, and any
  consumer with its own project noun collides. Ours does; `rebuild.py` imports
  it as `fold_into` for exactly this reason.

## What comes next

In order: the rest of recall (`neighbors`, temporal slicing); vector search,
once R1 lands; a `fetch` tool with distillation strategies, which is what gives
`remember` substantial content instead of search snippets; web and CLI surfaces
for the graph; and last, folding the session event log itself into documents —
the most speculative piece, and the one that benefits most from the others
existing first.
