# In-Memory Event-Sourced Coding Agent — Design

**Date:** 2026-08-01
**Status:** Approved

## Purpose

Build a coding agent whose entire session — conversation, tool calls, and virtual
filesystem — is a single event stream. The stream is the source of truth. State is
derived by folding it. This gives us three things at once:

1. **Replay & time-travel** — rebuild any point in the session, rewind, fork.
2. **Audit** — a total, ordered record of what the agent did and when.
3. **Versioned virtual filesystem** — per-file history, diffs, and provenance.

Everything lives in memory. Nothing touches the real disk, and the agent has no
shell. This is deliberate: with no side effects escaping the process, replay is
*pure* — refolding the log reproduces the exact workspace, every time.

## Non-Goals

- No persistence adapter (Postgres/SQLite). `InMemoryEventStore` only.
- No shell/exec tool. No `SandboxBackendProtocol`.
- No HTTP surface, no web UI.
- No subagents, no multi-tenancy, no outbox, no event bus.

## Architecture

```
              ┌──────────── REPL (research_team.repl) ────────────┐
              │  you type → run_turn() → meta-commands            │
              └──────────────────┬───────────────────────────────┘
                                 ▼
     ┌──────────────── CodingSession aggregate ────────────────┐
     │  stream: CodingSession-<uuid>                           │
     │  one stream: conversation AND filesystem                │
     └──────────────────┬──────────────────────────────────────┘
        fold            │                    fold
        ▼               │                    ▼
   messages.py          │            SessionState.files
   list[BaseMessage]    │            dict[path, FileEntry]
        │               │                    │
        └──► create_deep_agent(              ◄── EventSourcedBackend
                model=ChatOpenAI(...),           (BackendProtocol impl)
                backend=EventSourcedBackend,
                checkpointer=None)
```

### Why one stream

Files and conversation share the session stream so ordering between "assistant said
X" and "file Y changed" is **total**. Two streams would need a merge rule to answer
"what did the workspace look like when the model said that?" — one stream answers it
by construction. The filesystem view and the transcript view are two folds over the
same log.

### Why the event log owns conversation state

`create_deep_agent(checkpointer=None)` makes LangGraph stateless per invocation — it
does not retain messages between calls. That removes the usual conflict: there is no
second source of truth to reconcile. Each turn we fold the stream into
`list[BaseMessage]`, pass it in as the input state, and append whatever comes back as
new events. Rewind is then just "fold fewer events."

Long sessions refolding from zero is the only cost, so we attach
`InMemorySnapshotStore` with `snapshot_threshold=50`, `snapshot_mode="sync"`.
`SessionState` is a Pydantic model, so it snapshots without custom serialization.

## Components

### `research_team/events.py`

All events subclass `eventsource.DomainEvent` (frozen Pydantic, `extra="forbid"`) and
are decorated with `@register_event`. Every event sets
`aggregate_type: str = "CodingSession"`.

**Conversation events**

| Event | Fields |
|---|---|
| `SessionStarted` | `system_prompt: str`, `model_name: str` |
| `UserMessageSent` | `message: dict[str, Any]` |
| `AssistantMessageAdded` | `message: dict[str, Any]` |
| `ToolResultRecorded` | `message: dict[str, Any]`, `is_error: bool = False` |
| `TurnCompleted` | `turn_index: int` |

Each message-bearing event carries `message` as the output of
`langchain_core.messages.message_to_dict` — the library's canonical, lossless
serialization, including `tool_calls` on `AIMessage` and `tool_call_id` on
`ToolMessage`. We do not define our own message schema. Folding is
`messages_from_dict`.

Keeping three *named* events rather than one generic `MessageAppended` preserves the
audit granularity: `/log` and per-turn queries stay readable, and a projection can
filter on event type without inspecting payloads. The payload shape is the library's;
only the envelope is ours.

**Filesystem events**

| Event | Fields |
|---|---|
| `FileWritten` | `path: str`, `content: str` |
| `FileEdited` | `path: str`, `content: str`, `old_string: str`, `new_string: str`, `replace_all: bool` |
| `FileDeleted` | `path: str` |

`FileEdited` carries the resulting full `content` as well as the edit intent. The
content makes the fold trivial and O(1) per event; the `old_string`/`new_string` pair
preserves *why* the file changed, which is the audit value. Storing only the diff
would make folding cost O(history) per file.

**Design constraint:** every event is self-contained. Folding never requires
consulting state outside the stream.

### `research_team/session.py`

```python
class FileEntry(BaseModel):
    content: str
    version: int          # bumped per write/edit
    created_at: datetime
    updated_at: datetime

class SessionState(BaseModel):
    session_id: UUID
    system_prompt: str = ""
    model_name: str = ""
    files: dict[str, FileEntry] = {}
    messages: list[dict[str, Any]] = []   # raw langchain message payloads
    turn_index: int = 0

class CodingSession(DeclarativeAggregate[SessionState]):
    aggregate_type = "CodingSession"
    requires_creation_event = True
    schema_version = 1
```

Command methods (`start`, `send_user_message`, `record_assistant_message`,
`record_tool_result`, `complete_turn`, `write_file`, `edit_file`, `delete_file`)
validate invariants and call `self.create_event(...)`. Reducers are
`@handles`-decorated and do nothing but update `self._state`.

Invariants enforced by commands:
- `start` only when version == 0; every other command requires a started session.
- `edit_file` / `delete_file` require the path to exist.
- `record_tool_result` requires a matching outstanding `tool_call_id` among the
  `tool_calls` of the most recent `AIMessage`.

Note the aggregate does *not* re-validate `old_string` occurrence counts — the
deepagents superclass owns that check and has already run it (see `backend.py`).
Duplicating it here would mean two definitions of correct that can drift.

`unregistered_event_handling` is left at the default `"error"`.

### `research_team/backend.py`

`EventSourcedBackend(StateBackend)` — **subclass, do not reimplement.**

Every file operation in `deepagents.backends.state.StateBackend` funnels through
exactly two private seams:

- `_read_files() -> dict[str, Any]`
- `_send_files_update(update: dict[str, Any]) -> None`

`ls`, `read`, `write`, `edit`, `delete`, `grep`, `glob`, `upload_files`, and
`download_files` are all implemented in terms of those two. So we override the seams
and inherit every tool's semantics — line numbering, read windowing, `old_string`
ambiguity checks, glob/grep matching, truncation, error strings — byte-identical to
stock deepagents, for free.

```python
class EventSourcedBackend(StateBackend):
    def __init__(self, aggregate: CodingSession) -> None:
        self._aggregate = aggregate

    def _read_files(self) -> dict[str, Any]:
        return {p: e.to_file_data() for p, e in self._aggregate.state.files.items()}

    def _send_files_update(self, update: dict[str, Any]) -> None:
        for path, file_data in update.items():
            if file_data is None:
                self._aggregate.delete_file(path)
            else:
                self._aggregate.write_file(path, file_data_to_string(file_data))
```

This also removes the dependency on LangGraph's `CONFIG_KEY_READ`/`CONFIG_KEY_SEND` —
the inherited `_get_config()` is never reached, so the backend works outside a graph
context and is directly unit-testable.

**One override beyond the seams.** `_send_files_update` cannot distinguish a write
from an edit — both arrive as `{path: file_data}`. To record `FileEdited` with its
`old_string`/`new_string` intent, `edit()` is overridden to stash the edit intent on
the instance, delegate to `super().edit()`, and clear it:

```python
def edit(self, file_path, old_string, new_string, replace_all=False):
    self._edit_intent = (old_string, new_string, replace_all)
    try:
        return super().edit(file_path, old_string, new_string, replace_all=replace_all)
    finally:
        self._edit_intent = None
```

`_send_files_update` checks `self._edit_intent` to decide `FileEdited` vs
`FileWritten`. The superclass still performs all validation and the actual string
replacement; we only observe.

Async variants (`als`, `aread`, …) are inherited — the base delegates to the sync
methods, and everything here is in-memory, so there is nothing to await.

`FileEntry.to_file_data()` produces deepagents' `FileData` shape via the library's own
`create_file_data` / `update_file_data` helpers rather than hand-built dicts.

**Aggregate invariants vs. backend validation.** The aggregate still enforces its own
invariants (path exists, session started) because it must be correct independent of
who calls it — a replay or a test can drive it directly. But it never duplicates
deepagents' *user-facing* validation: by the time `_send_files_update` fires, the
superclass has already produced the correct error result for the model. The aggregate
commands are reached only on the success path.

### `research_team/messages.py`

Thin, pure, no I/O. It is deliberately small because
`langchain_core.messages.message_to_dict` / `messages_from_dict` do the actual work.

- `to_langchain(state) -> list[BaseMessage]` — `messages_from_dict(state.messages)`,
  prepended with the `SystemMessage` built from `state.system_prompt`.
- `classify(message) -> type[DomainEvent]` — maps a `BaseMessage` to the matching
  event class (`HumanMessage`→`UserMessageSent`, `AIMessage`→`AssistantMessageAdded`,
  `ToolMessage`→`ToolResultRecorded`).
- `new_messages(before, after) -> list[BaseMessage]` — the suffix of `after` not
  present in `before`, matched on message `id`.

`state.messages` is `list[dict]` — the raw langchain payloads, stored exactly as the
events carried them. No intermediate `RecordedMessage` model. This keeps the
aggregate free of any LangChain import at fold time (dicts in, dicts out) while
guaranteeing fidelity, since we never re-derive a message ourselves.

### `research_team/runtime.py`

Wiring plus the turn loop.

```python
@dataclass
class AgentRuntime:
    store: InMemoryEventStore
    repo: AggregateRepository[CodingSession]
    session_id: UUID
    model: BaseChatModel
```

- `build_runtime(...)` constructs the store, `InMemorySnapshotStore`, repository
  (`snapshot_threshold=50`, `snapshot_mode="sync"`), and the model.
- `async def run_turn(rt, user_input: str) -> str`:
  1. Load aggregate; append `UserMessageSent`.
  2. Fold messages; build agent with an `EventSourcedBackend` bound to this aggregate.
  3. `await agent.ainvoke({"messages": folded})`.
  4. Diff via `new_messages(before, after)`; append one event per new message using
     `classify` + `message_to_dict`; append `TurnCompleted`.
  5. `await repo.save(aggregate)` — one append, one optimistic-lock check per turn.
  6. Return the final assistant text.
- `async def history(rt) -> list[DomainEvent]` — reads the raw stream.
- `async def rewind(rt, n: int) -> None` — truncate to the first `n` events by
  replaying them into a **fresh** stream and repointing `session_id`. We never delete
  events; the old stream stays intact and inspectable. This is also exactly what fork
  does.
- `async def fork(rt, at: int) -> UUID` — same mechanism, returns the new id without
  repointing.

### `research_team/repl.py`

`asyncio`-driven `input()` loop. Anything not starting with `/` is a turn.

| Command | Effect |
|---|---|
| `/log [n]` | last `n` events, one line each: `#idx  EventType  summary` |
| `/files` | file list with version and size |
| `/cat <path>` | current content |
| `/history <path>` | every event touching that path, with turn index |
| `/rewind <n>` | truncate session to `n` events |
| `/fork <n>` | fork at event `n`, switch to the fork |
| `/state` | session id, event count, turn count, file count |
| `/help`, `/quit` | |

### Model configuration

`ChatOpenAI` against an OpenAI-compatible endpoint:

```python
ChatOpenAI(
    model=os.getenv("AGENT_MODEL", "qwen3.6-27b-mtp"),
    base_url=os.getenv("AGENT_BASE_URL", "http://192.168.1.14:8080/v1/"),
    api_key=os.getenv("AGENT_API_KEY", "not-needed"),
    temperature=0,
)
```

All four are env-overridable. The defaults point at the local endpoint so the REPL
runs with no configuration.

## Library Leverage

A standing constraint on this build: **we own the event-sourcing decisions and
nothing else.** Every other concern is delegated. Before writing any helper, check
whether one of the two libraries already provides it.

| Concern | Owned by | We write |
|---|---|---|
| File tool semantics (ls/read/edit/grep/glob, error strings, line numbers, truncation) | `deepagents.backends.state.StateBackend` | two seam overrides |
| `FileData` construction/update | `deepagents.backends.utils.create_file_data`, `update_file_data` | nothing |
| Path normalization | `deepagents.backends.utils.to_posix_path`, `validate_path` | nothing |
| Message serialization | `langchain_core.messages.message_to_dict` / `messages_from_dict` | nothing |
| Agent loop, tool dispatch, prompt assembly | `deepagents.create_deep_agent` | config only |
| Event base, registry, validation | `eventsource.DomainEvent`, `@register_event` | subclasses only |
| Fold/reduce dispatch | `eventsource.DeclarativeAggregate`, `@handles` | reducers only |
| Load/save/optimistic locking | `eventsource.AggregateRepository` | wiring only |
| Snapshotting | `InMemorySnapshotStore` + repo `snapshot_threshold` | wiring only |
| Storage | `InMemoryEventStore` | nothing |
| Test scaffolding | `eventsource.testing` (harness, assertions, builder) | test bodies only |

**Where duplication is accepted, and why.** Two places, both deliberate:

1. *Aggregate invariants that overlap deepagents validation* — the aggregate checks
   "path exists" for `delete_file` even though the backend superclass also checks it.
   The aggregate must be correct when driven directly (by replay, or by a test), so
   it cannot rely on a caller having validated. This is a genuine second consumer,
   not a copy.
2. *`FileEntry` alongside `FileData`* — `FileData` is deepagents' transport shape and
   has no version/history fields. `FileEntry` adds `version`, `created_at`,
   `updated_at`, which is exactly the event-sourcing value we are adding.
   `to_file_data()` converts, so the shapes never drift.

Anything else that looks like reimplementation is a bug in the implementation, not a
design choice — the reviewer should flag it.

## Data Flow — one turn

```
user types "create fizzbuzz.py"
  → UserMessageSent
  → fold stream → [SystemMessage, HumanMessage]
  → agent.ainvoke
      model emits tool_call write_file(fizzbuzz.py, ...)
      → EventSourcedBackend.write()
          → aggregate.write_file()  → FileWritten (pending)
      → ToolResultRecorded (the ToolMessage)
      model emits final text
  → AssistantMessageAdded (tool-call turn, then final text turn)
  → TurnCompleted(turn_index=1)
  → repo.save()  ← single atomic append of all pending events
```

Because the save is once per turn, a turn is all-or-nothing: a crash mid-turn leaves
the log at the last completed turn, never half-applied.

## Error Handling

- **Tool errors** (edit target missing, ambiguous `old_string`) — the command raises,
  the backend catches and returns deepagents' standard error result so the *model*
  sees it and can retry. `ToolCallCompleted(is_error=True)` is still recorded: failed
  attempts are part of the audit trail.
- **Model/transport errors** — propagate out of `run_turn`. The aggregate is not
  saved, so the failed turn leaves no partial events. The REPL prints the error and
  keeps the session alive.
- **`OptimisticLockError`** — cannot occur (single-threaded REPL, one writer), but is
  not suppressed. If it ever fires, a wiring assumption broke and we want to know.
- **Unknown event type on fold** — `DeclarativeAggregate` default raises
  `UnhandledEventError` rather than silently skipping.
- **REPL meta-command misuse** (bad index, missing path) — printed as a message, never
  a traceback.

## Testing

`pytest` + `pytest-asyncio`, using `eventsource.testing` helpers. **No test calls the
live model** — the model is stubbed with a scripted `FakeChatModel` so the suite is
deterministic and offline. One optional integration test, marked
`@pytest.mark.live` and skipped by default, exercises the real endpoint.

| File | Covers |
|---|---|
| `test_events.py` | every event registers, round-trips, rejects extra fields |
| `test_session.py` | each command emits the right event; each invariant rejects; fold correctness |
| `test_backend.py` | every op emits the right events; inherited semantics still hold (read windowing, edit ambiguity error, grep/glob) |
| `test_messages.py` | `message_to_dict`→event→fold→`messages_from_dict` round-trip preserves tool calls |
| `test_runtime.py` | full turn with `FakeChatModel`; rewind; fork divergence; snapshot threshold crossed |
| `test_replay.py` | **the load-bearing test**: run a scripted session, refold from event 0, assert workspace and messages are byte-identical |
| `test_repl.py` | meta-command parsing and output formatting |

`test_replay.py` is the one that proves the premise. If purity holds, it passes.

## Sequencing

1. `events.py` + `test_events.py`
2. `session.py` + `test_session.py` (depends on 1)
3. `messages.py` + `test_messages.py` (depends on 1)
4. `backend.py` + `test_backend.py` (depends on 2)
5. `runtime.py` + `test_runtime.py` + `test_replay.py` (depends on 2, 3, 4)
6. `repl.py` + `test_repl.py` (depends on 5)

Steps 3 and 4 are independent of each other and can be built in parallel.

## Open Risks

- **Tool-calling quality.** `qwen3.6-27b-mtp` via llama-swap must emit well-formed
  OpenAI tool calls for the file tools to work at all. If it does not, the event
  sourcing machinery is still correct and fully tested — only the live REPL
  experience degrades. Mitigation: the suite does not depend on the live model.
- **We subclass over private seams.** `_read_files` and `_send_files_update` are
  underscore-prefixed: deepagents makes no compatibility promise about them, and a
  0.8 release could restructure `StateBackend` and break us silently. This is a
  considered trade — reimplementing ~350 lines of file-tool semantics carries a
  higher and *continuous* correctness cost than pinning a version and fixing a break
  when it comes. Mitigations: `deepagents>=0.7.1,<0.8` in `pyproject.toml`, and
  `test_backend.py` asserts both seams still exist on `StateBackend` with the
  expected signatures, so an upgrade fails loudly at test time rather than
  mysteriously at runtime.
- **Tool-call id pairing.** `record_tool_result` matches against the preceding
  `AIMessage`'s `tool_calls`. If the model emits parallel tool calls resolved out of
  order, the check must be set-membership, not positional. Spec'd as set-membership;
  called out because it is easy to implement positionally by accident.
