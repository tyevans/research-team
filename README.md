# research-team

An event-sourced coding agent with an in-memory workspace. The whole session — every
user message, every model reply, every tool call, and every file the agent writes — is
a single ordered event stream, and all state is derived by folding that stream.

The agent's filesystem is purely virtual and it has no shell, so nothing it
*writes* escapes the process. Network egress is a real, documented exception:
a web search tool exists, gated per-tool, and absent unless configured. With
no `AGENT_SEARXNG_URL` set, no search tool is registered at all --
`tests/integration/test_no_network.py` pins that. Replay stays pure even with
search in the picture, because a search result is recorded as an ordinary
tool-result event: refolding the log replays the results the agent actually
saw rather than fetching new ones, so a session refolded years later
reproduces exactly, even if the SearXNG instance is long gone. The log itself
is stored in SQLite, so sessions outlive the process and can be listed and
resumed.

That buys four things: time travel (rewind and fork to any point), a total audit
trail of what the agent did and in what order, a virtual filesystem with per-file
history and provenance, and resumable sessions.

## Quickstart

Two front ends over the same log — a terminal REPL:

```bash
uv run main.py
```

and a web UI, which is where time travel actually becomes visible:

```bash
uv run web.py        # http://127.0.0.1:8000
```

The web UI is built around the event log rather than the chat: a timeline you
can scrub to any point (the workspace refolds to that moment — no fork, no
write), per-file provenance with real diffs of each recorded edit, and the fork
lineage as a tree. New events reach every open browser over SSE. Both front ends share one
SQLite database, so a session started in the terminal opens in the browser.

From the REPL you get a prompt. Type anything to send it to the agent as a turn; type a
`/`-command to inspect or manipulate the event log.

The default endpoint is `http://localhost:8080/v1/`. If your model server lives
somewhere else, point at it:

```bash
export AGENT_BASE_URL=http://your-host:8080/v1/
```

## Configuration

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
| `AGENT_SEARXNG_URL` | *(unset)* | SearXNG base URL; unset means no search tool is registered |
| `AGENT_SEARXNG_RESULTS` | `5` | how many results reach the model |

## REPL commands

| Command | Effect |
|---|---|
| `/files` | files in the workspace, with revision counts |
| `/cat <path>` | current contents of a file |
| `/history <path>` | every event that touched a path |
| `/diff <path>` | each recorded edit to a path, old → new |
| `/log [n]` | last `n` events (default 20), with timestamps |
| `/state` | session id, event count, turn count, file count |
| `/health` | whether the session list's projection is healthy |
| `/rebuild` | derive the session list from the log again; safe at any time |
| `/rewind <n>` | continue from a fork at event `n` |
| `/fork <n>` | fork at event `n` and switch to it |
| `/sessions` | every stored session, newest first; current one marked `*` |
| `/resume <n\|id>` | switch to a stored session by list position or id prefix |
| `/new` | start a fresh session |
| `/autonomy` | current autonomy level for each gated tool |
| `/autonomy <tool> <level>` | set a gated tool's level: `auto`, `ask`, or `deny` |
| `/help` | the command list |
| `/quit` | exit |

Anything not starting with `/` is sent to the agent as a turn.

## Autonomy and approvals

Four tools are gated: `web_search`, `write_file`, `edit_file`, `delete_file`.
Read-only file tools (`read_file`, `ls`, `glob`, `grep`) are deliberately not
gated -- there is nothing to approve about a read. Each gated tool has one of
three levels: `auto` runs it, `ask` interrupts the turn for a human to approve
or deny, and `deny` refuses without asking. Every tool starts at `auto`, so
behaviour is unchanged until someone asks for a gate.

Set a level from the REPL with `/autonomy <tool> <level>`, or from the web UI.
A change takes effect on the *next tool call* -- including one made partway
through a turn already running -- not at the next session. A pending `ask`
approval can be answered from either front end.

Search runs against a self-hosted SearXNG instance. Most instances ship with
their JSON API disabled; without `formats: [json]` under `search:` in the
instance's `settings.yml`, the tool cannot read its response and the failure
is otherwise mystifying.

## How it works

One `CodingSession` aggregate owns one event stream carrying both the conversation
and the filesystem, so the ordering between "the model said X" and "file Y changed"
is total. The session is written as a **decider**: `decide(command, state)` says
which requests are legal and what facts they produce, `evolve(state, event)` says
what each fact does, and `CodingSession` is a thin `DeciderAggregate` shell that
connects those two pure functions to replay, snapshots, and the repository. The
rules therefore test as rules -- `tests/domain/test_decider.py` folds commands
through plain function calls with no aggregate, store, or event loop in sight --
and `decide` doubles as the inventory of every legal transition.

Messages are stored as langchain's own `message_to_dict` payloads, so there is
no message schema of our own to maintain. File tools come from deepagents'
`StateBackend`: `EventSourcedBackend` overrides only its two private state seams
(`_read_files` / `_send_files_update`) plus `edit()` for intent capture, which means
line numbering, edit-ambiguity checks, glob/grep, and error strings are all
inherited rather than reimplemented. `create_deep_agent` is built with
`checkpointer=None` so LangGraph stays stateless and the event log is the sole
source of truth.

The "no shell" guarantee is worth being precise about, because it is not that
the tool is absent. deepagents offers an `execute` tool regardless; it refuses
here because `EventSourcedBackend` does not implement the sandbox protocol that
would give it somewhere to run, so an attempt returns an ordinary error and is
recorded like any other tool result. That is a subtle invariant to rest a
safety claim on, so `tests/integration/test_no_shell.py` pins it: a command
that tries to write outside the process must leave nothing behind. A turn is atomic: all of its events append at the end, or none do —
so an interrupted or failed turn leaves the log at the last completed turn rather
than half-applied.

The log lives in SQLite. Listing sessions reads a projection -- a
`session_summary_rows` table kept up to date event by event by a `SubscriptionManager`,
which replays from a persisted checkpoint on startup and then follows the live bus.
It used to be a fold over `read_category` on every request, which was the clearest
possible statement of what a summary is and got linearly slower forever; the fold
itself still lives in `summaries.py` as the definition, and a test feeds identical
events through both to keep them honest.

That trade buys speed and costs a failure mode a fold does not have. A fold is
recomputed every time, so it cannot be stale and a fixed bug is retroactive. A
projection is written down once: if a handler throws, the subscription carries on
(one bad event must not stop the rest), the checkpoint advances past it, and the
row it would have updated is wrong permanently -- a restart does not help, because
catch-up resumes after the event that was never applied. So failures go to a
dead-letter queue rather than only a log line, `/api/health` and the REPL's
`/health` report the count, the web UI shows a badge when it is non-zero, and
`/rebuild` (or `POST /api/summaries/rebuild`) drops the rows and the checkpoint
together so the whole table is derived again from the log. Rebuilding is
idempotent and safe to reach for on a hunch, which is the point: the log is the
only source of truth, so anything computed from it can be thrown away.

Turns are streamed with `stream_mode="values"`, which
gives both live tool-by-tool progress and the final message list in one pass.
That progress goes to whoever started the turn, through `on_activity` — it is
not in the log, so it does not reach a watching browser (see the live feed's
limits below).

## Layout

Four layers, and imports only ever point inward:

```
research_team/
  domain/          commands.py, events.py, session.py
                   The requests a session accepts, the facts it records, and
                   the decider relating them. Knows nothing about langchain,
                   deepagents, SQLite, or the environment.
  application/     ports.py, session_service.py, summaries.py, live_feed.py,
                   turn_supervisor.py
                   The use cases -- run a turn, cancel it, fork, scrub, list
                   sessions -- plus the ports (SessionRepository, TurnExecutor,
                   EventFeed, SessionSummaries) they need the outside world
                   to satisfy.
  infrastructure/  persistence/  the event store implementing SessionRepository,
                                 and the `/sessions` read model and the
                                 projection that keeps it current
                   agent/        deepagents + langchain, implementing TurnExecutor
                   telemetry.py  tracer setup; a no-op unless AGENT_TRACING is on;
                                 one tracer is shared by the turn, the store, and
                                 the /sessions projection, so a slow list and a
                                 slow turn are read off the same trace
                   config.py     the only module that reads the environment
  interfaces/      cli/          the REPL: parsing, dispatch, formatting
                   web/          FastAPI routes + presenters, and the SPA
  composition.py   the one place that picks concrete adapters and wires them
```

`main.py` and `web.py` build the application and hand it to a front end, so
nothing below an entrypoint chooses its own database or model. Building is
synchronous and `start()` is not: the `/sessions` projection opens its own
aiosqlite connection, and aiosqlite binds a connection to the loop that created
it, so it has to be opened inside the loop that will use it -- under uvicorn's
lifespan for the web UI, inside `asyncio.run` for the REPL.

**No current session.** The application layer is session-addressed: every use
case names the session it acts on, and the service holds no cursor. "The
session I'm looking at" is a property of whoever is driving — one terminal has
exactly one, a browser has one per tab — so the REPL owns a `Repl` cursor and
the web layer takes the id from the URL. That is what lets both front ends, and
any number of browsers, share a single wired application safely.

The seam that matters is `TurnExecutor`. A turn's file writes land on the
aggregate as they happen -- the agent's filesystem *is* the aggregate -- while
conversation messages come back as `RecordedMessage` values for the use case to
append. That is what keeps a turn all-or-nothing: the service decides whether
the turn is committed at all, and a turn that raises is discarded whole.

**Turns are supervised.** `TurnSupervisor` owns the in-flight turn for each
session, which buys two things. A second turn on a busy session is refused
immediately rather than after a minute in the model (and then losing a version
check anyway). And a turn can be *cancelled*: the events it had accumulated are
discarded whole, `turn_index` does not advance, and a single `TurnFailed` marker
records the attempt, flagged `cancelled` so the audit trail can tell "someone
stopped this" from "this broke" — an abandoned turn is visible in the log rather
than silently absent. Recording that marker is shielded, because the usual reason to
be recording it is cancellation, and a cancelled coroutine's next await would be
cancelled too. The wait for a turn to unwind is bounded, so a cancel request
never hangs behind a slow model — it answers `settled: false` instead.

A turn also reports *where it landed*: `TurnOutcome` carries the inclusive event
span it wrote, which the REPL prints as `[turn 3 · events #14-21]` and the web
UI uses to jump straight to them. An aggregate's version is its event count, so
this is exact rather than inferred.

**Concurrency, and its one limit.** The store serialises every statement
through a single lock on a single connection, and `AggregateRepository.save()`
appends with an expected version. So two turns posted to one session resolve as
one success and one `OptimisticLockError` — mapped to HTTP 409 — with the
loser's events discarded whole, leaving exactly one turn in the log. Turns on
different sessions run concurrently, and reads during a write are safe.

That safety is **single-process**: it rests on one in-process lock over one
connection. Running the web UI under multiple workers (`uvicorn --workers N`)
would give each process its own lock and reintroduce the race, where SQLite's
own locking would surface it as a busy error rather than a clean 409. Serve it
from one process.

**What the live feed can and cannot show.** A turn's events all arrive at the
same instant — the moment it commits — because the feed reads the store and a
turn is atomic. That is the all-or-nothing guarantee seen from the outside, and
it is the correct behaviour, but it means SSE cannot narrate a turn *while* it
runs: a browser watching a sixty-second turn sees nothing, then sees all of it.
The REPL does show tool-by-tool progress, because the executor reports activity
to it directly through `on_activity` rather than through the log. Giving the web
UI the same would need a second channel that is not the event stream.

What the feed *does* guarantee is that nothing is missed. Each SSE frame carries
its feed position as the event id, and `EventSource` replays that in
`Last-Event-ID` when it reconnects, so a browser that drops resumes from where it
left off instead of silently skipping whatever landed while it was away. An id the
store cannot place -- stale, or from a database since replaced -- falls back to the
live end rather than replaying the whole log. Delivery itself is still a read of
the store, never of the bus: the bus only says "something landed", and ordering and
completeness stay the log's business. That signal is what lets the feed skip its
poll interval, which is now a ceiling on latency rather than the latency itself.

## Context management

Every turn re-sends the conversation, so a session's cost grows with its
length and eventually hits the window. Four modes, chosen per instance with
`AGENT_CONTEXT`, differ in what they do about it:

| Mode | What it does | Costs | Best when |
|---|---|---|---|
| `full` | sends everything | nothing | short sessions; the default |
| `elide` | shortens older tool results, keeping the recent ones whole | nothing — pure and deterministic | the context is mostly file reads |
| `compact` | summarizes the older conversation, recording the summary as an event | one model call per compaction | the context is mostly prose |
| `delegate` | gives the agent a `worker` subagent so bulky work happens in a fresh context | more model calls, less parent context | work that would fill the log with tool output |

**Where the intervention happens matters more than which one you pick.** It
happens at the *fold* — the log always holds every message, and a strategy
decides which of them, and in what form, the model is shown next turn.

That is not a stylistic choice. Measured against this codebase, langchain's
`SummarizationMiddleware` rewrites the running message list via
`RemoveMessage(REMOVE_ALL_MESSAGES)`, and doing so silently breaks how a turn
is recorded: we identify what a turn produced by slicing the agent's returned
list at the length we sent, and rewritten history makes that slice meaningless.
Turns then land in the log missing their assistant messages and tool results —
`UserMessageSent → FileWritten → TurnCompleted`, a log claiming the agent wrote
a file with no reply and no tool call. It does not even fail loudly. Middleware
that only rewraps the outbound request is safe by the same reasoning:
`ContextEditingMiddleware` hooks `wrap_model_call`, leaves state alone, and is
what `elide` is modelled on.

`compact` records its decision as a `ConversationCompacted` event rather than
recomputing a summary each turn. So it costs one model call rather than one per
turn, two replays of a log produce the same context, and folding to a point
before the compaction shows the conversation as it was. The messages it
summarizes are never removed — only hidden from the model.

`delegate` is the odd one out: it does not transform anything. Subagents share
the backend, so a subagent's file writes are recorded on the same stream, while
its reads and reasoning never enter the parent's context. Measured here, a
delegated turn left four messages in the parent — the request, the `task` call,
the subagent's report, and the reply.

**Delegation is the mode with two-sided evidence, and it is worth knowing which
side you are on.** Anthropic reports a large quality win for a research system
of one lead plus subagents — and also that token spend alone explained most of
the performance variance, at three to ten times the tokens. Much of the win is
paying more, not organising better. Cognition argues the opposite for
*constructive* work: subagents each producing part of an artifact make
conflicting implicit decisions that the parent then has to reconcile.

That second warning applies here, because our subagents write to a shared
filesystem later turns build on. So `delegate` steers towards investigation —
reading, searching, surveying — where a subagent returns a conclusion rather
than a piece of something that has to fit with other pieces. It is the right
mode for "which of these forty files mentions X", and the wrong one for
splitting a refactor three ways.

Three choices are worth explaining, because the obvious alternative is wrong in
each case:

**Keep the `compact` trigger well above the size of one turn.** If a turn costs
a meaningful fraction of the trigger, the conversation re-crosses it almost
immediately and you pay a summarizer call every turn. The default leaves a wide
margin; a trigger set near per-turn size will thrash. A compaction that would
not actually shrink the context is refused outright — a four-section summary of
very little is bigger than the little it replaced, and recording it would
burden every later turn permanently.

**The trigger counts tool call arguments, not just message content.** A
`write_file` carries the whole file in its arguments and answers with one line
of confirmation, so counting content alone saw 224 tokens where the real
payload was nearer 2,600 — the trigger would have fired long after it should
have, or never.

**The `compact` trigger is high** (≈120k tokens). Anthropic's server-side
compaction defaults to 150k input tokens and refuses to be configured below
50k; its tool-result clearing triggers at 100k. A trigger an order of magnitude
lower costs a summarizer call on nearly every turn and discards detail that
would have fit comfortably.

**`compact` never cuts between a tool call and its result.** A result whose
call was summarized away is a malformed request — an answer to a question the
model cannot see itself having asked. The boundary snaps backwards until the
first kept message is not a tool result, which summarizes strictly more and is
therefore always safe.

**`elide` offers no way to retrieve what it cleared, on purpose.** The obvious
improvement is a handle back to the original, which the log still holds. It
would be wrong here. Every tool the agent has -- `read_file`, `ls`, `glob`,
`grep` -- is a cheap, deterministic read of an in-memory filesystem, so
re-running one costs almost nothing and returns the file as it is *now*. A
recalled result is a snapshot from an earlier turn, which may since have been
edited: it would be slower to reach for and sometimes wrong. The advice to keep
a retrievable handle comes from systems whose cleared output was expensive or
impossible to reproduce; ours is neither.

**`elide` clears a result rather than truncating it.** A cut-off head reads as
a whole result, so the model trusts it — and a half-read file or half-finished
command output is exactly how an agent concludes something succeeded when it
did not. The marker says how much was removed and that it is *not* the result.
The tool call itself is untouched, so the model can still see what it asked and
ask again, which is what Anthropic's `clear_tool_uses` does and why.

Scrubbing is the payoff of taking event sourcing seriously: `state_at(session, n)`
folds the first `n` events and returns the aggregate, so viewing any past moment
writes nothing and forks nothing. The live view is the same idea in the other
direction — `EventFeed` exposes the store's global cursor, and `LiveFeed` turns
"everything after this position" into a stream the browser subscribes to.

The dependency rule is asserted, not just documented: `tests/test_architecture.py`
parses every module and fails if a layer imports outward, if the domain or
application layer names a framework, or if anything but the entrypoint imports the
composition root.

Full design: `docs/superpowers/specs/2026-08-01-event-sourced-coding-agent-design.md`.

## Tests

```bash
uv run pytest
```

338 tests, no network. `tests/` mirrors the source layout -- `tests/domain`,
`tests/application`, `tests/infrastructure`, `tests/interfaces`, plus
`tests/integration` for the cross-layer ones.

The live smoke test in `tests/integration/test_live.py` is marked `live` and
deselected by default; run it explicitly with:

```bash
uv run pytest tests/integration/test_live.py -m live -v
```

## Status

Working, and exercised against a real model rather than only against fakes.

On 2026-08-01, against a local `qwen3.6-27b-mtp` server, a two-turn session was
driven end to end: turn one
asked for `/fizzbuzz.py` and the model emitted a well-formed `write_file` tool call;
turn two asked for a docstring and it used `edit_file`, producing a `FileEdited`
event carrying both the new content and the `old_string`/`new_string` intent.
`/history /fizzbuzz.py` then showed the two revisions, and a cold refold of the
stream through a fresh repository with no snapshot cache reproduced the live state
exactly. Rewind was verified separately: rewinding past the second write restored
the earlier file content while leaving the original stream intact and readable.

On 2026-08-02, after moving the log to SQLite, persistence was verified across two
**separate OS processes**: the first created `/greet.py` and exited; the second
started fresh, resumed the session by id, saw the file already present, and
continued the conversation — the model read the file back and edited it with full
prior context. `/diff /greet.py` then showed the docstring being added, and
`/sessions` listed the session with its turn and file counts.

No malformed tool calls were observed. Local models of this size are slow relative
to the fake-model suite — allow a minute per live turn, which is why turns now
report each tool call as it happens instead of sitting silent.

On 2026-08-02 the web UI was driven in a real browser against a seeded database:
the fork tree rendered three generations of lineage with the event index each
branch came from; scrubbing to event 3 of 19 refolded the workspace to one file
at revision 1 and truncated the conversation to the single message sent by then,
writing nothing; per-file history rendered the recorded `old_string`/`new_string`
as a red/green diff; and a turn sent from the browser wrote a file into the
event-sourced workspace, with the new events arriving live over SSE. Two turns
posted concurrently to one session resolve as one 200 and one 409, leaving
exactly one turn in the log.

**An audit of the claim "is it fully event sourced?" found three gaps, now closed**
(`0955c78`..): `is_error` was declared on `ToolResultRecorded` but never set, so
every failed tool call was recorded as a success — it now comes from the
`ToolMessage.status` field deepagents already sets. Forking replayed events onto a
new stream without recording *that a fork happened*, so a branched session was
indistinguishable from a coincidence — there is now a `SessionForkedFrom` event, and
`/sessions` and `/state` show lineage. And a crashed turn left no trace at all; a
`TurnFailed` marker is now appended on its own, after the failed turn's events are
discarded, so the log gains the attempt without the turn ceasing to be atomic.

**An earlier bug was found the same way and fixed** (`e97020b`): `to_langchain` prepended a
`SystemMessage` while `create_deep_agent` was also given `system_prompt`, so the
prompt had two owners. Because LangGraph echoes back every message it is handed,
that extra leading message shifted the new-message suffix by one and each turn
recorded a spurious `AssistantMessageAdded` containing the user's own text. The
unit suite missed it because it asserted which event *types* appeared rather than
how many; reading the actual event log from a live run is what surfaced it. The
regression tests now pin the exact per-turn event sequence.
