# research-team

An event-sourced coding agent with an in-memory workspace. The whole session — every
user message, every model reply, every tool call, and every file the agent writes — is
a single ordered event stream, and all state is derived by folding that stream.

The agent's filesystem is purely virtual and it has no shell, so nothing it does
escapes the process and replay is pure: refolding the log reproduces the exact
workspace, every time. The log itself is stored in SQLite, so sessions outlive the
process and can be listed and resumed.

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

## REPL commands

| Command | Effect |
|---|---|
| `/files` | files in the workspace, with revision counts |
| `/cat <path>` | current contents of a file |
| `/history <path>` | every event that touched a path |
| `/diff <path>` | each recorded edit to a path, old → new |
| `/log [n]` | last `n` events (default 20), with timestamps |
| `/state` | session id, event count, turn count, file count |
| `/rewind <n>` | continue from a fork at event `n` |
| `/fork <n>` | fork at event `n` and switch to it |
| `/sessions` | every stored session, newest first; current one marked `*` |
| `/resume <n\|id>` | switch to a stored session by list position or id prefix |
| `/new` | start a fresh session |
| `/help` | the command list |
| `/quit` | exit |

Anything not starting with `/` is sent to the agent as a turn.

## How it works

One `CodingSession` aggregate owns one event stream carrying both the conversation
and the filesystem, so the ordering between "the model said X" and "file Y changed"
is total. Messages are stored as langchain's own `message_to_dict` payloads, so
there is no message schema of our own to maintain. File tools come from deepagents'
`StateBackend`: `EventSourcedBackend` overrides only its two private state seams
(`_read_files` / `_send_files_update`) plus `edit()` for intent capture, which means
line numbering, edit-ambiguity checks, glob/grep, and error strings are all
inherited rather than reimplemented. `create_deep_agent` is built with
`checkpointer=None` so LangGraph stays stateless and the event log is the sole
source of truth. A turn is atomic: all of its events append at the end, or none do —
so an interrupted or failed turn leaves the log at the last completed turn rather
than half-applied.

The log lives in SQLite. Listing sessions is a fold over `read_category`, not a
separate table we maintain. Turns are streamed with `stream_mode="values"`, which
gives both live tool-by-tool progress and the final message list in one pass.
That progress goes to whoever started the turn, through `on_activity` — it is
not in the log, so it does not reach a watching browser (see the live feed's
limits below).

## Layout

Four layers, and imports only ever point inward:

```
research_team/
  domain/          events.py, session.py
                   The aggregate and the events it folds. Knows nothing
                   about langchain, deepagents, SQLite, or the environment.
  application/     ports.py, session_service.py, summaries.py, live_feed.py,
                   turn_supervisor.py
                   The use cases -- run a turn, cancel it, fork, scrub, list
                   sessions -- plus the ports (SessionRepository, TurnExecutor,
                   EventFeed) they need the outside world to satisfy.
  infrastructure/  persistence/  the event store, implementing SessionRepository
                   agent/        deepagents + langchain, implementing TurnExecutor
                   config.py     the only module that reads the environment
  interfaces/      cli/          the REPL: parsing, dispatch, formatting
                   web/          FastAPI routes + presenters, and the SPA
  composition.py   the one place that picks concrete adapters and wires them
```

`main.py` and `web.py` build the application and hand it to a front end, so
nothing below an entrypoint chooses its own database or model.

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

274 tests, no network. `tests/` mirrors the source layout -- `tests/domain`,
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
