# The interaction log

Capture what the user does in the console, durably and in its own store, so
that later work on friction and preemption is designed against a real corpus
rather than against imagination.

This document is the design. It is deliberately explicit about what is *not*
being built, because the value of the first version rests on refusing to guess
at consumers.

## Name

**The interaction log.** Not "telemetry" — that word is taken in this
repository and means something else. `check_telemetry.py`,
`check_telemetry_reader.py`, `application/check_telemetry_read.py` and
`infrastructure/telemetry.py` are all about *agent check outcomes* and
OpenTelemetry tracing. Nothing here touches those. The collision is worth
avoiding in code and in conversation: a reader who sees "telemetry" in this
repository should keep thinking about checks.

Module names follow: `research_team/interaction_log/` and
`frontend/src/**/interaction-log/`.

## Scope

**In:** a client-side emitter, a batched transport, an ingest endpoint, a second
event store, and one projection that makes the log queryable by hand.

**Out, explicitly:**

- No proactive agent. No suggestions, no push messages, no prefetch.
- No HTTP read route and no browser view of the log. This mirrors the
  deliberate choice recorded for check telemetry in `BACKLOG.md` B44 — the data
  is inspected with `sqlite3` until there is a reason for a route. A view is
  where scope creep enters, and there is no consumer to serve yet.
- No cross-store correlation. See "Boundaries".
- No multi-user support. The install id below is the seam where that would
  arrive, and it is called out so nobody mistakes it for one already.

The first version's success criterion is a single sentence: **after a week of
ordinary use, a developer can open the database and reconstruct what a session
looked like** — what was visited, in what order, for how long, and what was
repaired.

## Why a separate store

Interaction data is not domain history. It is high-volume relative to the
domain log, it is derived from a UI that will be rewritten, it carries content
that makes it privacy-shaped, and — the part that matters most — **it is
droppable.** No product state derives from it.

So: a second SQLite database at `~/.research-team/interactions.db`,
event-sourced with the same `eventsource` library and the same projection
machinery, wired in its own composition block.

The separation buys one asymmetry that is the whole point:

**The schema-evolution contract does not extend here.** `domain/events.py` opens
with a contract that events already written must stay readable, and
`tests/infrastructure/test_schema_evolution.py` enforces it. That contract is
correct for domain history and wrong for this log. When the vocabulary changes,
**we drop the database.** Pre-release, single-purpose, and the data's value is
in the recent past — a corpus that predates the current vocabulary is not worth
the cost of reading two shapes.

This must be written where someone will find it: a docstring at the top of the
event module saying that old payloads are *not* supported and the recovery is
`rm ~/.research-team/interactions.db`.

## Boundaries

Three, and the first is enforced by the library rather than by discipline.

**No projection spans both stores.** `eventsource` derives a store id from the
database string it was handed (`f"sqlite:{database}"`) and every position token
carries it, so ordering a position from one store against another raises
`PositionForeignError`. This repository has already been bitten by it — CLAUDE.md
records the incident and the `local_copy` tool written to work around it. The
consequence here is structural: a projection subscribes to one store, and any
correlation between an interaction and a domain fact happens at the application
layer or not at all.

**The dependency points one way.** Interaction events may carry `project_id` and
`session_id` as *context*, so the log is queryable by the work being done. But
nothing in the research domain reads this store. Deleting `interactions.db`
degrades no feature.

**`/rebuild` stays a domain-store operation.** No interaction event is ever
replayed to reconstruct product state, because no product state derives from
one.

### The correlation problem, stated now rather than discovered

The query this design makes awkward is the one someone will eventually want:
"which friction preceded which abandoned research run". That crosses stores, so
it is an application-layer join on `project_id`/`session_id` plus wall-clock
time — and **wall-clock across two logs is not an ordering.** Two events a
millisecond apart in different stores cannot be reliably sequenced, and client
clocks are involved on one side.

This is an accepted cost, not an oversight. The mitigation is design pressure:
the common signals (friction, prefix-prediction) are answerable *within* the
interaction log alone, and anything that needs the join must be honest in
whatever presents it about the ordering being approximate.

## The load-bearing rule

**Raw observation is not history. Only decisions are.**

When a signal is eventually acted on, the durable consequence — "this friction
point was detected", "this grant was proposed" — becomes a real domain event in
the domain store. The evidence behind it stays in the interaction log, cheap and
droppable.

This is `docs/direction.md` §3's rule ("record promotion as an event so folding
restores the gate") applied to a second store. It also means the interaction log
never needs to be durable *enough to justify a decision after the fact*, which
is what licenses dropping it.

### Inherited constraints from `direction.md` §3

§3 was written about proposing `FetchGrant`s from approval history, and its four
constraints are design law for anything that turns observed behaviour into a
suggestion. They are recorded here because the consumer will be built by someone
who may not read that section:

1. **Only human decisions are evidence.** An automated or granted-by-policy
   decision tells you nothing about what a person wanted.
2. **Volume is the weakest signal.** A long streak of approvals is
   click-through. The strong signal is *repair* — approve-after-edit, retry,
   undo. The vocabulary below is shaped by this: repair has its own event kinds.
3. **Count distinct sessions and days, never raw events.** One frustrated
   afternoon is one data point.
4. **Never auto-apply.** Whatever the consumer proposes, a human confirms.

## Identity and context

Every event carries three kinds of key.

**`install_id`** — a UUID persisted in `localStorage`, surviving restarts. Its
only job is to let a count say "on nine separate days" rather than "in nine
separate tabs". It is a pseudonymous identifier, and it is the exact thing that
becomes real identity if this product ever grows past one user. Flagged here so
that growth is a decision and not an accident.

**`browser_session_id`** — a UUID minted fresh per page load. This is the
aggregate id: the event store's stream is a browser session, which makes
ordered-prefix reads (what preemption needs) a stream read rather than a query.

**Domain context** — `project_id` and `session_id` where they are in scope,
nullable. This is what the interaction was *about*.

There is no user identity beyond `install_id`, and the design claims nothing
about cross-user aggregation because there are no other users.

## Event shape

`aggregate_type = "browser_session"`, `aggregate_id = browser_session_id`.

Envelope on every event:

| field | source | why |
|---|---|---|
| `event_id` | client UUID | idempotency; `sendBeacon` can double-deliver |
| `install_id` | client | distinct-days counting |
| `browser_session_id` | client | the stream |
| `seq` | client, monotonic per session | **the ordering authority** |
| `occurred_at` | client clock | human-readable time |
| `received_at` | server, at ingest | cross-check against clock skew |
| `view` | client | where the user was |
| `project_id`, `session_id` | client, nullable | domain context |

**`seq` is the ordering truth, not `occurred_at` and not arrival order.**
Batching means arrival order is meaningless, and a client clock can be skewed or
moved mid-session. `seq` is a counter, so it survives both. `occurred_at` is
kept for reading and for computing intervals; `received_at` is kept so that a
batch whose client clock disagrees wildly with its arrival can be *flagged as
suspect* rather than silently trusted or discarded.

Durations are **not** computed from `occurred_at`. See "Dwell".

### The vocabulary

Deliberately small and enumerable. Adding a kind is a schema change with a
reason attached, and since the database is droppable that is cheap.

**Attention and navigation**

- `ViewEntered` — `view`, `params` (ids only)
- `ViewExited` — `view`, `dwell_ms`, `hidden_ms`
- `AttentionLost` / `AttentionRegained` — from `visibilitychange`

`AttentionLost`/`Regained` exist so that dwell is not inflated by a backgrounded
tab. Without them, "stalled on this view for four minutes" — the archetypal
friction signal — is indistinguishable from "went to lunch", and the whole
attention half of the log is worthless.

**Semantic actions**, emitted from application-layer seams:

- `EntityOpened` — `entity_id`, `source` (`graph|search|timeline|link`)
- `ProjectSwitched` — `from_project_id`, `to_project_id`
- `ExtractionQueued`, `ExtractionCancelled`
- `DispatchRequested`
- `SearchPerformed` — `query_text`, `result_count`
- `AskSubmitted` — `query_text`
- `ApprovalDecided` — `decision`, `latency_ms`, `expanded_details`

`ApprovalDecided` deliberately duplicates *nothing* from the domain's
`ToolCallDecided`. What it adds is UI-only and is exactly what §3's second
constraint demands: **how long the human took, and whether they opened the
details.** A decision in 400ms without expanding is click-through; a decision
after twelve seconds with the details open is deliberation. The domain event
cannot tell these apart and the distinction is the difference between a usable
signal and a misleading one.

**Repair** — the strong signal, given first-class kinds so it is never inferred:

- `ActionUndone` — `action_kind`, `target_id`
- `ActionRetried` — `action_kind`, `attempt_number`
- `EmptyResultEncountered` — `where`, `query_length`

### Content: a closed allowlist

Most events carry structure only — ids, view names, counts, durations. Free text
is normally recorded as shape (`query_length`, `result_count`), which is enough
to detect a zero-result search without knowing what was searched.

**Two fields carry text, and they are the whole allowlist:**

- `SearchPerformed.query_text`
- `AskSubmitted.query_text`

The justification is narrow and specific: the strongest friction signal is
"they did nearly the same thing again, slightly differently", and *nearly the
same* requires the thing itself. Lengths cannot express it. A retried search
with a small edit is the clearest evidence in the whole log that the product
failed to answer someone.

The cost is stated plainly: **`AskSubmitted.query_text` is the most sensitive
field in this system.** It is a research prompt — a transcript of what someone
was thinking about. It is included because the retry signal is worth it on a
local single-user tool, and because the kill switch below is one environment
variable.

The rule that keeps this auditable: **any event kind carrying text declares it
in the module, and the set is small enough to read in one screen.** Adding to
the allowlist is a deliberate change, not a judgement call at a call site.

## Client emission

### Where it is called from

The **application layer**, at the existing seams — the zustand stores and query
hooks (`use-dispatch`, `use-extraction-queue`, `ask-store`, `graph-store`,
`session-store`). These already *are* the semantic vocabulary: they know "an
extraction was queued" in the terms the log wants.

Rejected alternatives, with reasons:

- **Presentation-layer handlers** (`onClick` also calls `track`). Scatters
  instrumentation across every component, puts an infrastructure concern in the
  layer that should be dumb, and adds a stub to every component test. The
  failure mode that kills these systems is *forgetting to instrument*, and this
  gives you ~200 sites nobody can enumerate instead of ~20 you can.
- **A state-diff subscriber** that derives events from store transitions. Nearly
  zero instrumentation and impossible to forget — but the events then mean
  "state changed in a way I interpreted as X" rather than what they say, and a
  refactor of state shape silently changes the log. This subsystem's entire
  value rests on events meaning what they claim.

Route and dwell observation is the exception and belongs near the router — one
place, not scattered.

### Layering

Following the existing hexagonal structure:

- `application/ports/interaction-log.ts` — the port
- `application/interaction-log/emitter.ts` — the buffer (below)
- `infrastructure/http/interaction-log-repository.ts` — over the existing
  `HttpClient`
- registered in `app/container.ts` alongside the other repositories

The port is what application code calls. Nothing imports the repository
directly.

### Transport: buffer, batch, flush

Buffered client-side, flushed on a timer and on page-hide.

There is **no library for this**, and that finding is worth recording because it
contradicts the reasonable instinct to reach for one. The batch-and-beacon
machinery exists only *inside* full analytics SDKs — PostHog, Snowplow,
Rudderstack — each of which brings its own event ontology and a server half we
are not using. Adopting one means either bending this vocabulary to fit theirs,
or carrying a large dependency against a CI bundle budget to use a few percent
of it. The standalone prior art is written up as *patterns* over
`navigator.sendBeacon` and `pagehide`, not as packages.

So it is written here, in one file, and browser-tested:

- Buffer in memory. Flush every 5s if non-empty, immediately at 50 events.
- Flush on `visibilitychange → hidden` and on `pagehide`, via
  `navigator.sendBeacon`, because a batch dropped at tab close removes the *end*
  of every session — which is precisely where friction lives.
- **No durable client-side spill** (no `localStorage` queue). This was
  considered and rejected: it spends real complexity protecting data we have
  already agreed is droppable, and it makes *late arrival* a permanent property
  of the log that every future reader must reason about. A crash loses the last
  few seconds. That is acceptable.
- `sendBeacon` cannot report success, and per MDN it "is not reliably fired,
  especially on mobile". No library fixes this; the design absorbs it.

### Dwell

Computed from `performance.now()`, not from `Date.now()` and not from
`occurred_at`. `performance.now()` is monotonic, so a system clock change
mid-session cannot produce a negative or absurd duration.

`hidden_ms` accumulates across `visibilitychange` while a view is current, and
`ViewExited.dwell_ms` is wall-time-in-view with `hidden_ms` reported alongside
rather than subtracted — the consumer decides which it wants, and the raw
figures stay inspectable.

`ViewExited` is emitted on route change and on the page-hide flush, so a session
that ends by closing the tab still gets a terminal dwell.

## Ingest

`POST /api/interactions`, following the existing pattern in
`interfaces/web/app.py` — a module-level pydantic body model, a route closure in
`create_app`, `ValueError` → `HTTPException(400)`.

Body: `{"events": [...]}`. Limits: 200 events per batch, and a body-size cap.
Response: `202` with `{"accepted": n, "rejected": n}`.

**Partial acceptance is deliberate.** A malformed event does not reject the
batch — the valid 199 are written and the count of rejects is returned. The
alternative loses good data to one bad event, and since the client cannot
observe a `sendBeacon` response anyway, a whole-batch rejection would be silent.

**Idempotency** by `(browser_session_id, seq)`, deduplicated at the projection.
`sendBeacon` can double-deliver and a timer flush can race a page-hide flush, so
duplicates are expected rather than exceptional.

### Kill switch

`INTERACTION_LOG=0` disables collection, and it does so the way this repository
already does feature flags: **the dependency is `None` at the entrypoint and the
route answers 503.** `config.py` states the reasoning and it is better than the
alternative — "unset means the route is not there is a stronger promise than any
check inside a route that exists".

An earlier draft of this section had the endpoint answer `202 {"accepted": 0}`
and drop the batch, to spare the client a branch. That was wrong on its own
terms: `sendBeacon` cannot observe a response at all, so a 503 costs the client
nothing that a fake 202 saves it, and the fake 202 gives up a real promise for
no gain. The emitter treats every transport failure identically — drop and carry
on — so a disabled route needs no client-side handling.

Default is **on**, unlike `AGENT_TRACING`: this is local, single-user, on the
user's own machine, and a log nobody collects is worth nothing. Turning it off
is one environment variable, and that is the answer to the
`AskSubmitted.query_text` objection.

## Persistence

One projection, following the existing trio convention in
`read_models.py` — `Row(ReadModel)` + `Projection(DeclarativeProjection)` +
`Store` + `Runner`, in `research_team/interaction_log/`.

`InteractionEventRow` is a flat table of every event: envelope columns, `kind`,
and a JSON payload column for kind-specific fields. Indexed on
`(browser_session_id, seq)` for stream reads and on `(kind, occurred_at)` for
aggregate reads. That one table satisfies the success criterion — a developer
can reconstruct a session — and nothing more is built.

A flat table with a JSON column is a deliberate choice over per-kind tables: the
vocabulary will churn, the database is droppable, and `sqlite3`'s JSON operators
are enough for hand queries. Per-kind tables would be the right call once a
consumer exists and its queries are known.

The runner is constructed and started in **one** composition block, in the
convention `composition.py` already states and explains — "a projection wired
somewhere else is a projection somebody forgets to start". Because this is a
second store, it gets its own block and its own `apply_schema` call rather than
joining the existing one.

## Testing

The gates are the four in CLAUDE.md, plus `npm run build` and a commit of
`web/static` for any frontend change, plus `npm run test:browser` for the
measurement code below.

**What each test must actually assert**, because this repository has been burned
by the alternatives:

- **The projection's tests assert that a row exists with the right values** —
  never that the request succeeded. `eventsource.replay` counts an event no
  projection handles as APPLIED, so an assertion that the POST returned 202
  passes with the projection removed entirely and is worthless. A test that
  fails when the runner is not constructed is the requirement.
- **A schema test against a database that predates the change.** Adding a column
  to a `ReadModel` does not add it to an existing database, and this has shipped
  once here. The test writes a database with the old shape, then opens it.
- **Dwell and visibility are browser tests** (`*.browser.test.tsx`), not jsdom.
  jsdom lays nothing out, and this is measurement code — CLAUDE.md's rule is
  that anything whose correctness is a computed style or a measurement belongs
  in the browser suite. Timer and buffer logic can stay in jsdom with fake
  timers; `visibilitychange`, `pagehide` and `performance.now()` behaviour
  cannot.
- **A partial-acceptance test** with one malformed event among valid ones,
  asserting the valid ones landed.
- **A duplicate-delivery test** — the same `(browser_session_id, seq)` twice,
  asserting one row.
- **A kill-switch test** asserting no row is written with `INTERACTION_LOG=0`.

Each test's docstring says what it would fail on. Anything that would pass with
the change reverted says so.

## Costs, accepted

- Two event stores: two `apply_schema` paths, two runners, and a second place
  the "verify against a database that predates the change" rule applies.
- Cross-store correlation is an application-layer join on approximate time.
- `AskSubmitted.query_text` makes the log sensitive; the mitigation is an env
  var and the fact that it never leaves the machine.
- ~20 emission sites in application code that a new feature can forget to add.
  This is the residual risk of the chosen approach and there is no gate for it.
- Bundle growth for the emitter. The `app` bucket is at 85.3 kB gzipped against
  a 96 kB limit, so there is ~10.7 kB of room and the emitter fits — but the
  budget is a CI gate and the measurement should be re-taken, not assumed.
- The frontend coverage thresholds are ratchets, and `src/application/**`
  requires 66% of lines. The emitter lands there, so it must be genuinely
  tested or `npm run verify` fails on coverage rather than on correctness.
  This is a feature, but it means "add the emitter, test it later" is not an
  available sequence.
- Every route added to `create_app` must also be wired in `web.py`, the single
  production call site. Three comments there record routes that shipped 503ing
  because someone added the parameter and forgot the argument;
  `tests/interfaces/test_web_entrypoint.py` exists to catch exactly that.

## Open, deliberately

- The consumer. Both plausible families — friction (aggregate, cross-session)
  and preemption (ordered prefix, within-session) — are answerable from this
  log, and neither is designed here.
- Whether `install_id` becomes real identity. That is a multi-user decision.
- Per-kind tables, once a consumer's queries are known.
