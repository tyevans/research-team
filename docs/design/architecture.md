# Architecture

How the pieces fit, and why the layering is asserted rather than described.

## The session aggregate

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
                   web/          FastAPI routes + presenters, and the built console
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

## Scrubbing, and the rule that is asserted

Scrubbing is the payoff of taking event sourcing seriously: `state_at(session, n)`
folds the first `n` events and returns the aggregate, so viewing any past moment
writes nothing and forks nothing. The live view is the same idea in the other
direction — `EventFeed` exposes the store's global cursor, and `LiveFeed` turns
"everything after this position" into a stream the browser subscribes to.

The dependency rule is asserted, not just documented: `tests/test_architecture.py`
parses every module and fails if a layer imports outward, if the domain or
application layer names a framework, or if anything but the entrypoint imports the
composition root.
