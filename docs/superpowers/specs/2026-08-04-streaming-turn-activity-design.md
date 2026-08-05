# Streaming Turn Activity to the Web UI — Design

**Date:** 2026-08-04
**Status:** Approved

## Purpose

Make the web UI show what a turn is doing *while* it is doing it. Today the
pane sits empty for the length of a turn — a minute or more against a local
model — and then everything appears at once.

This is not a bug. It falls out of a property the system deliberately holds:
a turn is atomic. `SessionService._run_turn` accumulates every event on the
aggregate and calls `repository.save()` exactly once, at the end, so a turn
that fails is discarded whole. The live feed reads the durable log, so until
that single append lands there is genuinely nothing to read.

`app.js` says so in a comment at the point where narration would otherwise go:

> *No narration here on purpose: a turn's frames all arrive together when it
> commits, so per-event progress would be a burst at the end, not progress.*

The fix is therefore **not** to make the log incremental. It is to add a
second, explicitly non-durable channel carrying provisional content, and to
keep the timeline a faithful rendering of the log.

## What this does not change

- **Turn atomicity survives.** No event is appended mid-turn. `_run_turn` still
  saves once. A failed turn still records nothing but a `TurnFailed` marker.
- **The durable record is still produced by the code that produces it today.**
  Token deltas never feed `new_messages()`. A stream and a log cannot disagree,
  because the stream is not an input to the log.
- **The timeline still renders the log and nothing else.** Provisional content
  is visually distinct and is *replaced*, not merged, on commit.
- **REPL output stays byte-identical.**

## Non-Goals

- **No durable record of a discarded stream.** What streamed during a failed or
  cancelled turn is readable immediately afterwards and gone on reload. Making
  it durable would mean either an event carrying the abandoned messages — which
  contradicts "a failed turn records nothing" — or a second store outside the
  log. Neither is worth it.
- **No token deltas for tool call arguments.** Partial JSON renders as garbage
  and would have to be buffered to whole anyway. Tool calls and results arrive
  whole.
- **No replacement of the approvals channel.** Approvals keep their existing
  frames and catch-up route. This channel sits beside them.
- **No new persistence, no schema change, no new event types.**

## Architecture

```
  DeepAgentTurnExecutor._invoke
       │  astream(stream_mode=["values", "messages"])
       │
       ├── "values"  ─► final / reported / new_messages()   ── the durable record
       │                (unchanged; this is today's code)
       │
       └── "messages" ─► AIMessageChunk, main agent, no tool_calls
                              │
                              ▼
                      ActivityReporter(note)          ── ports.py
                              │
                              ▼
                        TurnActivity                  ── interfaces/web/activity.py
                        ├── buffers the running turn, per session
                        ├── broadcasts to SSE listeners
                        └── on fail/cancel: buffer ─► discarded slot
                              │
              ┌───────────────┴────────────────┐
              ▼                                ▼
     /api/stream  (frames, no id)     /turns/current/activity  (catch-up)
```

The channel carries no positions, so `Last-Event-ID` cannot resume it. That is
the same situation approvals are in, and it is solved the same way: a
server-side buffer plus a catch-up route. `_sse`'s docstring already explains
the reasoning for approvals, and it applies here unchanged.

The buffer is not an optimisation. SSE connections drop routinely — sleep/wake,
network change, a proxy closing an idle connection — which is why the stream
sends keepalives and honours `Last-Event-ID` at all. Log events already survive
a reconnect. Without a buffer, provisional frames would not, and a lossy
reconnect would be indistinguishable from a slow model: both look like a frozen
pane.

### 1. The port — `research_team/application/ports.py`

`ActivityReporter` is `Callable[[str], None]` today, which cannot carry
structure. It becomes:

```python
@dataclass(frozen=True)
class ActivityMessage:
    """A whole message the agent produced, provisionally."""
    message_id: str
    kind: MessageKind          # "assistant" | "tool"
    payload: dict
    is_error: bool = False

@dataclass(frozen=True)
class ActivityDelta:
    """A chunk of assistant prose, to append to `message_id`."""
    message_id: str
    text: str

ActivityNote = ActivityMessage | ActivityDelta
ActivityReporter = Callable[[ActivityNote], None]
```

`message_id` is the identity the frontend keys accumulation on. It comes from
the langchain message's own `id`, so a delta and the whole message that later
supersedes it agree without the executor inventing a correlation scheme.

### 2. The executor — `DeepAgentTurnExecutor._invoke`

Switch to `stream_mode=["values", "messages"]`. `astream` then yields
`(mode, chunk)` tuples and both streams come from one pass — no second call,
and no chance of the streamed content disagreeing with the recorded content.

- **`values`** — unchanged. Drives `final`, `reported`, and the existing
  `new_messages()` accounting. Emits `ActivityMessage` where today it emits a
  formatted string.
- **`messages`** — yields `(message_chunk, metadata)`. Emit `ActivityDelta`
  only when the chunk is an `AIMessageChunk`, carries text content, and has no
  `tool_calls`.

Subagent chunks arrive on the `messages` stream as well. They are filtered by
`metadata["langgraph_node"]` — without that, a subagent's internal prose would
render as the main agent's answer to the user.

The `reported` counter still deliberately survives the interrupt/resume loop,
for the reason its comment already gives.

### 3. The REPL — `research_team/interfaces/cli/repl.py`

`repl.py:306` passes `on_activity=print`, which no longer type-checks against a
structured note. It becomes a small formatter that renders an `ActivityNote` to
a line, reusing the logic in `describe_activity`. `describe_activity` stays
where it is and keeps its shape; it is now a presenter for the terminal rather
than the only representation available.

Deltas are dropped by the REPL formatter. The terminal already shows the reply
when the turn completes, and echoing prose token by token into a scrolling
transcript would be noise.

### 4. The buffer — `research_team/interfaces/web/activity.py`

New module, deliberately mirroring `approvals.py`: same `listen()` /
`stop_listening()` broadcast pattern, same per-session dict, same lifetime.

```python
class TurnActivity:
    def reporter(self, session_id: UUID) -> ActivityReporter: ...
    def current(self, session_id: UUID) -> list[dict]: ...     # catch-up
    def discarded(self, session_id: UUID) -> list[dict]: ...
    def settle(self, session_id: UUID, *, committed: bool) -> None: ...
    def listen(self) -> asyncio.Queue: ...
    def stop_listening(self, queue: asyncio.Queue) -> None: ...
```

Lifecycle:

- **Turn starts** — clear both slots for that session.
- **Note arrives** — append to the buffer (deltas coalesce onto their keyed
  message), broadcast to listeners.
- **Turn commits** — drop the buffer. The real events are arriving on the log
  channel and are authoritative.
- **Turn fails or is cancelled** — move the buffer to `discarded`, held until
  the next turn starts on that session.

State held is one turn's messages per running session — the same shape and
lifetime as `WebApprovals`' pending dict and `TurnSupervisor._started`.

### 5. HTTP surface — `research_team/interfaces/web/app.py`

- `POST /api/sessions/{id}/turns` passes `activity.reporter(session_id)` into
  `turns.run(...)`. `TurnSupervisor.run` already accepts `on_activity`; the web
  route simply never supplied one.
- `GET /api/sessions/{id}/turns/current/activity` — the in-flight buffer, plus
  the discarded set if there is one. Sits beside the existing `/turns/current`,
  which exists for exactly this reason: so a tab arriving mid-turn can say what
  is happening.
- `_sse` grows a third pump kind, `activity`, alongside `event` and `approval`.
  Activity frames carry **no `id`**, for the same reason approval frames do not.

`create_app` takes `activity: TurnActivity | None = None`, following the
`approvals` parameter's existing optional shape, so composition stays outside
and tests can build an app without it.

### 6. Frontend — `research_team/interfaces/web/static/app.js`

State:

```js
state.activity  = { order: [], byId: {} }   // provisional, current turn
state.discarded = {}                        // failed turn index -> messages
```

- `onStreamEvent` routes `type === 'TurnActivity'` to `onActivityFrame`, before
  the index handling — like approval frames, these are not log entries and must
  not be treated as one. `TurnActivity` is deliberately *not* a domain event
  type and must never become one; it names a transport frame, and the log has
  no such entry.
- A whole message inserts or replaces `byId[message_id]`. A delta appends to the
  keyed bubble's text, creating it if this is the first chunk.
- Provisional bubbles render below the timeline while `state.turnRunning`,
  visually distinct from committed events.
- **`TurnCompleted`** — clear `state.activity` and render from the real events
  that arrived on the log channel. A replace, not a merge.
- **`TurnFailed`** — move the set to `state.discarded[index]`, rendered behind a
  disclosure on that timeline row, labelled *discarded — not recorded*.
- On session load, fetch `/turns/current/activity` for catch-up — the same shape
  as the existing mid-approval refetch at `app.js:645`.

The stale comment at `app.js:1946` is replaced with one explaining the split
between the two channels.

## Error handling

- **Reporter raises** — must never fail a turn. The executor's call site guards
  it: a broken progress channel is not a reason to discard a minute of model
  work. Logged, not propagated.
- **`stream_mode` list unsupported** — see *Open question* below; the fallback
  is `values`-only, which yields whole messages without prose deltas.
- **Buffer growth** — bounded by one turn. A turn that produces pathological
  output is already bounded by the model's own limits, and the buffer is dropped
  on settle either way.
- **No listeners** — broadcasting to nobody is normal (the REPL drives turns
  with no browser attached) and is not an error.
- **Missing `message_id`** — if a chunk carries no `id`, the delta is dropped
  rather than guessed at. Guessing would splice two messages together.

## Testing

- **Regression guard: turn atomicity.** Assert no events are appended to the log
  mid-turn while activity is streaming. This is the invariant most at risk from
  this change and it gets an explicit test.
- **The durable record is unaffected.** A turn run with a reporter and one run
  without produce identical events.
- Reporter emits deltas only for main-agent prose: no deltas for tool args, none
  for subagent chunks.
- A whole message supersedes its accumulated deltas under the same
  `message_id`.
- SSE emits activity frames with no `id`, and log frames still carry theirs.
- Catch-up route returns the in-flight buffer mid-turn, and the discarded set
  after a failure.
- `settle(committed=True)` drops the buffer; `settle(committed=False)` moves it
  to discarded.
- A reporter that raises does not fail the turn.
- REPL output is unchanged for the same sequence of messages.

## Open question to resolve first in implementation

**Does `create_deep_agent`'s compiled graph accept `stream_mode` as a list?**

`create_deep_agent` returns a compiled langgraph graph, and langgraph 1.2.10
supports multi-mode streaming with `(mode, chunk)` tuples — but this is the one
assumption the whole design rests on, and it spans deepagents 0.7.1 as well.

Verify it before building anything else. If it does not hold, the fallback is
`values`-only: whole messages stream, prose deltas do not. Everything else in
this design is unaffected, because deltas were always additive to it.

## Alternatives considered

**A. Append events incrementally as the agent produces them.** The most direct
reading of "stream as events are found" — and rejected. It would end turn
atomicity, which is what lets a failed turn be discarded whole, and would put
partial turns in the log permanently. The log would gain rollback semantics it
does not have.

**B. Fire-and-forget frames, no buffer.** Cheapest, and self-healing at turn
end. Rejected because every SSE reconnect would silently lose whatever streamed
while disconnected, in a system whose stream already goes to lengths to survive
exactly that. It would also reproduce the reported complaint — a pane that looks
idle mid-turn — for any tab that joined late.

**C. Progress notes only, no content.** Wire the existing one-line
`describe_activity` notes to the browser. An afternoon's work, and it does
convey liveness. Rejected because the assistant's prose — the thing being waited
for — is what `describe_activity` drops on the floor.

**D. Token deltas for everything, tool arguments included.** Rejected: partial
JSON is unreadable, so it would have to be buffered to whole before rendering,
which is what option (b) already does — with extra steps.
