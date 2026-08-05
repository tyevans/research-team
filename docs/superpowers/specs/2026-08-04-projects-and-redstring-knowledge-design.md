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

- The rest of recall: `neighbors`, vector similarity, temporal slicing.
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

`tenant_id` is the project. This is why the project concept comes first: a
shared graph without a boundary has no natural tenant, and a session-scoped
graph is a research memory that forgets.

### Extraction events live on their own stream in the same store

`StreamId(project_id, "knowledge")`, alongside the session streams in the same
SQLite file. The session log records the ingest tool call and its result the
way it records a search. The knowledge stream holds redstring's
`DocumentExtracted` and `EntitiesMerged`, and the graph is
`redstring.projections.project` folded over it.

This keeps redstring's central claim intact — the store is derived, and
"re-extract everything with a better prompt" is a replay rather than a
migration — while keeping one file to back up and one place to look for
provenance. Interleaving redstring's events into the session stream was
rejected because it would make `CodingSession`'s decider know redstring's event
schema, and would make rebuilding the graph a fold over every session. A
separate database was rejected for the same reason a second source of truth is
always rejected here.

**Replay purity is the constraint every part of this obeys.** Extraction is a
model call. If it runs at fold time, a refolded session stops reproducing what
the agent actually saw, and a session refolded years later depends on a live
endpoint. So extraction results are recorded as events and never recomputed on
replay — the same reason a search result is recorded rather than re-fetched.

### Knowledge-first ordering

An ingest appends to the knowledge stream before returning a tool result to the
session. A crash between the two leaves an orphan extraction — the graph
learned something the session log does not mention — rather than a phantom one,
where the log claims an extraction that never landed. The graph is the thing
that must not lie.

### Consolidation is automatic, and the agent can reverse it

`Consolidator.resolve()` runs after each extraction. Skipping consolidation
produces one node per *mention*, which looks like a knowledge graph and answers
every question wrong, because an entity's edges are split across its aliases —
so a default that leaves the graph in that state is not an option.

But the agent has context the blocker does not: whether two identically-named
entities are one thing. So merges are recorded reversibly on the knowledge
stream and the agent gets `unmerge`. Because the merge history is on a stream
rather than in memory, `undo` is durable here rather than session-only.

### Stores are in-memory by default, and swappable

`InMemoryGraphStore` and the in-memory vector store, folded from the knowledge
stream when a project opens. No servers, no extras, `uv run main.py` keeps
working. Store construction sits behind config, so moving to Neo4j or pgvector
is wiring rather than redesign — and the rebuild-from-log path that move needs
is the same path used at every startup, so it is continuously exercised rather
than written under duress during a migration.

In-memory vector search over a few thousand entities is fine. It is the half
that pushes toward pgvector first as a project grows.

## Architecture

```
remember(text, source)
  -> extract (LLM)
  -> append DocumentExtracted   -\
  -> Consolidator.resolve         >- StreamId(project_id, "knowledge")
  -> append EntitiesMerged      -/
  -> fold into GraphStore + VectorStore
  -> tool result on the session stream
```

Three seams:

**`Project`** (`domain/project.py`) — a decider aggregate holding membership and
the filesystem lineage pointer. Events: `ProjectCreated`,
`SessionJoinedProject`, `ProjectTipAdvanced`. Sessions gain `project_id`.
Mirrors `session.py` in structure: `decide`, `evolve`, pure.

**`KnowledgePort`** (`application/knowledge.py`) — a Protocol in the style of
the existing ports:

- `ingest(source: SourceRef) -> IngestReport`
- `search(query: str) -> list[Match]`
- `undo_merge(merge_id: str) -> MergeRecord`

`SourceRef`, `IngestReport`, `Match` and `MergeRecord` are research-team's own
DTOs. No redstring type appears in this module.

**`RedstringKnowledge`** (`infrastructure/knowledge/redstring_adapter.py`) — the
only module that imports redstring. Owns the knowledge stream, the projection,
store construction, and the `LlmProvider` built via `LangChainLlmProvider` over
the endpoint already configured by `AGENT_BASE_URL`.

### Modules

| Module | Responsibility |
|---|---|
| `domain/project.py` | The `Project` aggregate and its events |
| `application/knowledge.py` | `KnowledgePort` and its DTOs |
| `infrastructure/knowledge/redstring_adapter.py` | The one redstring importer |
| `infrastructure/knowledge/stores.py` | Store construction behind config |
| `infrastructure/agent/knowledge_tools.py` | The three tools, shaped like `search.py` |

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `AGENT_GRAPH_STORE` | `memory` | `memory` or `neo4j` |
| `AGENT_VECTOR_STORE` | `memory` | `memory` or `pgvector` |
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
- **`graph_search(query)`** — entities matching a query, each with its type and
  a count of its relationships, capped and flattened the way search results
  are. Traversal from a known entity is `neighbors`, which is deliberately in
  the next spec; this tool finds entry points, it does not walk the graph.
- **`unmerge(merge_id)`** — reverses a consolidation.

`remember` and `unmerge` are writes and join the gated set alongside the file
tools. `graph_search` is a read and defaults to `auto` like the file reads.
`AutonomyPolicy` gains the three names, and a `KNOWLEDGE_PROMPT` alongside
`SEARCH_PROMPT` describes when committing something to the graph is worth it
against merely reading.

## Error handling

| Situation | Behaviour |
|---|---|
| Extraction fails — endpoint down, timeout, malformed response | Nothing is appended. The tool returns a plain-language failure, as `search.py` does for a disabled JSON API. |
| Crash between the knowledge append and the session tool result | An orphan extraction. Recoverable, and the reason for knowledge-first ordering. |
| Consolidation fails after extraction succeeded | The extraction stands, the merge does not, and the report says so. Project open runs a `resolve` sweep over unconsolidated entities, which is also the repair path for an interrupted ingest. |
| Store unreachable at startup | Fail at composition, before any session opens. Never degrade silently to in-memory: a half-populated graph that answers queries is worse than one that refuses. |
| `domain=AUTO` falls back | `AUTO` never raises; it falls back to `encyclopedia_wiki` on three paths, and a fallback is indistinguishable from a confident choice by the domain alone. `IngestReport` carries `domain_confidence` and the tool result prints it. |
| Oversized input | Capped before extraction, for the reason search results are capped: cheaper not to make the mess. |
| A second concurrent session in a project | Rejected by the decider, naming the session that holds it. |

## Testing

- **Decider tests** for `Project`, mirroring the existing `session.py` tests.
  Pure, no I/O.
- **Adapter tests against redstring's `FakeLlmProvider`** — no server, no
  extras, runnable in CI.
- **Projection determinism** — fold the knowledge stream twice, assert
  identical graphs.
- **Replay purity** — refold a session with a provider stub that raises on
  call, asserting no extraction happens at fold time. This is the property most
  worth pinning, because it is the one that dies silently.
- **A no-network sibling** to `tests/integration/test_no_network.py`: the
  default install registers no knowledge tools and opens no store.
- Existing mutation testing covers the new decider and the report formatting.

## What comes next

In order: the rest of recall (`neighbors`, vector similarity, temporal
slicing); a `fetch` tool with distillation strategies, which is what gives
`remember` substantial content instead of search snippets; web and CLI surfaces
for the graph; and last, folding the session event log itself into documents —
the most speculative piece, and the one that benefits most from the others
existing first.
