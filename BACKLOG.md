# Backlog

Deferred work. Every deficiency found and not fixed on the spot lands here,
with enough detail that picking it up does not require rediscovering it.

The `B` numbers are stable handles, not a taxonomy. Closed entries are deleted;
if tracked code cites one by name, say where its reasoning went before deleting.

## Code quality

### B1. `Project`'s class docstring says little that its module does not

`research_team/domain/project.py`. The class docstring is near-verbatim from
`CodingSession`'s — "the imperative shell, holds no rules, delegates all
three" — and the `Project`-specific reasoning it might add is already in the
module docstring above it. Not wrong, just thin: a reader who came for the
difference between the two aggregates does not find it here.

Found in the Task 1 review of the projects/redstring work and deferred as
Minor, because the docstring convention is satisfied and nothing is
misleading.

### B3. No type checking

`mypy` is not configured and has never run against this codebase. The CI gate
added alongside the projects/redstring work covers `ruff check`, `ruff format`
and the test suites, and deliberately stops there.

Deferred on measurement rather than principle: ~40 modules have never been
type-checked, so `mypy --strict` is an open-ended migration whose size is
unknown until it is run, and starting one in the middle of a feature was the
wrong trade. The sibling project (`redstring`) gates on `mypy --strict` and is
the model to copy when this is picked up.

Do not add mypy in permissive mode as a stepping stone. A gate that starts
permissive tends to stay permissive, and it costs the honesty of saying
plainly, as this entry does, that there is no type checking today.

### B4. Two tests flake under machine load

Both surfaced during the projects/redstring work, each failing once and passing
on an isolated re-run, on a machine running several other projects' containers:

- `tests/interfaces/test_web.py::test_stream_reaches_a_real_browser_over_a_real_socket`
  — waits up to 10s on a real socket for an SSE frame, on **hardcoded port
  8749**. The load sensitivity is real, but the sharper cause found since is
  the fixed port: any two concurrent runs of that file collide deterministically,
  and the second one fails with a `CancelledError` out of httpx that names
  nothing about ports. It cost a regression hunt during the corpus work before
  `ss -ltnp` showed a sibling pytest holding the port. Binding port 0 and
  reading back the assigned port would remove the whole class.
- A cancel-settle test in `tests/application/test_turn_supervisor.py` with
  `settle_timeout=0.1`. **Measured since, and worse than this entry first
  said:** it failed roughly one run in three on an otherwise quiet machine
  during the workflow-engine work, in a branch that touches neither the
  supervisor nor its test. 0.1s is not a margin, it is a coin toss with a
  bias, and "passes reliably when unloaded" below is simply not true of this
  one.

Both are wall-clock races against a loaded scheduler, not logic faults, and
both are testing something worth testing — a real socket and a real timeout
are the point. The fix is not a longer sleep: it is making the wait
condition-driven, or making the timeout injectable so the test names its own.

The socket test does pass reliably once nothing else holds its port. The
cancel-settle test does not, and on the measurement above it is the more
urgent of the two: a suite that fails a third of the time on one test trains
people to re-run rather than read, which is how a real failure gets waved
through.

### B5. An unclosed `SQLiteEventStore` blocks interpreter shutdown

**This entry was wrong when first filed and has been corrected.** It originally
blamed `SQLiteSnapshotStore` for lacking a `close()`. That store is innocent: it
opens a connection per operation via `async with aiosqlite.connect(...)` and
leaves no threads behind, so having no `close()` is right for it. The original
diagnosis was a hypothesis that fit the symptom and was never tested against the
alternative.

What actually happens, measured:

- `SQLiteEventStore` holds one long-lived aiosqlite connection, and aiosqlite's
  connection worker thread is **non-daemon**.
- Call `close()` and the thread goes; the process exits clean.
- Forget `close()` and the thread outlives the loop. The process then parks in
  `threading._shutdown` waiting for a thread that will never finish, and on the
  way out aiosqlite raises `RuntimeError: Event loop is closed` from
  `call_soon_threadsafe` — neither of which names the store that was not closed.

Where it bites here: most tests construct a `SQLiteEventStore` and never close
it. Usually harmless; once, it turned a passing test into an apparent infinite
hang, and only a `faulthandler` dump distinguished "hung" from "finished, then
could not exit". See the upstream notes for the changes that would make this
self-diagnosing rather than a day's detective work.

**It also flakes the suite, which is how it will actually reach you.** In
`tests/infrastructure/test_knowledge_rebuild.py`, two tests build an adapter and
never close the event store, so their worker threads are still live when a later
test in the same file runs — and under full-suite load that test intermittently
fails. It was first reported as "the same class as B4"; it is not. B4 is a socket
test and a timing test racing the scheduler. This is threads outliving their test
and contending, which is a different and more tractable problem: close the stores.

*(Original title, for anyone following a link: "`SQLiteSnapshotStore` cannot be
closed, and its thread outlives the process".)*

**Update, eventsource 0.12: the original title became true, and the correction
became wrong.** ADR 0053 gave `SQLiteSnapshotStore` one connection for its
lifetime and a `close()` to match, so it is no longer innocent -- it now leaks
exactly the way `SQLiteEventStore` does, and for exactly the same reason. The
upgrade closed every site: `EventStoreSessionRepository.close()` closes its
snapshot store; `build_aggregate_repository` no longer builds one it cannot
hand back (it now requires one, since a store built there is returned to nobody
and so can never be closed); and the test fixtures own and close theirs.

Two unrelated leaks surfaced during the same audit and are also closed:
`SessionSummaryRunner` and `CorpusRunner` each built a SQLAlchemy async engine
in `start()` and never disposed it, so a pooled aiosqlite connection and its
thread survived `stop()`. That one predates 0.12 and was never anything to do
with snapshots.

The suite went from 14 thread-exception warnings to 2. What remains of this
entry is the *diagnosis* problem, not any known leak: the symptom still names
no store, which is why finding these took a hand audit of every construction
site. That half is now filed upstream (eventsource-py BACKLOG, "An unclosed
connection-owning adapter is undiagnosable"), which is the only place it can
actually be fixed.

### B6. `undo_merge` always reports `reason=None`

`RedstringKnowledge.undo_merge` builds its `MergeRecord` from
`ConsolidationReport.reason`, and `Consolidator.undo` documents that field as
`None` for an undo — the reason belongs to the merge, not to its reversal. So
the `reason` on an undo's record is always empty, and a caller reading it sees
nothing rather than the reason the original merge was made.

Nothing is wrong today: `unmerge`'s tool output does not print it. It becomes a
papercut the moment something wants to say "this merge, made because X, was
reversed". The fix is either to say so in the docstring and leave it, or to read
the original `EntitiesMerged` off the consolidation stream and carry its reason
through. Deferred rather than guessed at, because which one is right depends on
whether any caller ever wants that string.

### B7. One weak assertion in the knowledge-tools tests

`tests/infrastructure/test_knowledge_tools.py::test_remember_reports_counts_and_confidence`
asserts `"7" in result and "4" in result` — bare digits, which could appear
incidentally inside a UUID or another number in the same output. It should
assert the whole informative phrase instead.

It came from the plan's own test code, and the surrounding assertions (the
domain name, the confidence disambiguation) make a false pass unlikely in
practice — which is why it was not worth a fix round on its own. Worth
correcting the next time that file is touched.

### B8. One accessor reaches through a private attribute

`Application.turns_tools()` in `research_team/composition.py` reads
`self.service._executor`, so a test can inspect which tools are bound.

**This entry has shrunk twice, and both reductions were the rule working.** It
originally covered two reaches. The REPL's `_project_repository` is gone —
`SessionService` grew `projects` and `list_projects`, so the interface asks
rather than reaches. And the `._tools` half is gone — the executor now has a
public `tools` property, added when Task 14 needed to swap tools at runtime
anyway. What survives is the `._executor` hop itself.

The remaining fix is a `tools` accessor on `SessionService`, or accepting that a
composition root may know its own executor. Left as-is because the case for the
latter is real and nobody has needed to decide.

**The rule that produced those reductions still stands: if a third reach
appears, fix the pattern rather than adding to it** — at that point it is the
codebase's convention whether anyone chose it or not.

### B10. `Application.close()` can skip `detach_project`

`research_team/composition.py`. `detach_project()` is the last statement after
`turns.cancel_all()`, `summaries.stop()` and `service.close()`. If any of those
raises, a Neo4j driver is left open at process exit.

Shutdown-path only, and only for the Neo4j backend, so nothing leaks in the
default in-memory configuration. The fix is a `finally` or a small ordered
teardown that runs every step regardless — worth doing the next time that
function is touched, not on its own.

### B11. The web UI's "last join wins" swaps tools under an open tab

`research_team/interfaces/web/app.py`, the join route. The web app serves every
session from one process with one executor, so a second browser tab joining
project B rebinds the executor's tools while tab A's session prompt still
describes project A's graph.

Chosen deliberately: this is a local single-user tool, and a per-session
attachment map would add isolation nothing currently needs. The route's
docstring says so. There is no corruption risk in flight — `set_tools` rebinds
rather than mutates, and a running turn keeps the list it started with.

It becomes worth fixing the moment two people, or two projects, use one server
at once. The shape is a per-session attachment keyed the way `TurnActivity`
already keys its buffers.

### B9. A silent no-op release hides one failure it cannot distinguish

`SessionService.release_project` returns early when the caller is not the
project's active holder. That is deliberate: releasing something you do not hold
should be nothing rather than an error, and it is what keeps the REPL's `finally`
from raising and skipping `service.close()`.

The cost is that two situations look identical — a session that correctly is not
the holder, and a session that *should* be the holder but lost `active_session_id`
through some logic error. Both no-op silently. A real bug of the second kind would
surface only as a later "held by nobody in particular", not as a loud failure.

Accepted as the better trade for now: the alternative reopens a `finally` that can
raise. If it needs closing, the cheap version is a logged warning when a session
carrying a `project_id` releases and finds itself not the holder — enough to leave
a trace without turning a shutdown path into a failure path.

### B17. The browser offers only approve and reject, though `edit` works end to end

`research_team/interfaces/web/static/app.js`, `renderApproval`. `ApprovalPort`
accepts an `edit` decision, `DeepAgentTurnExecutor._apply` records it and
translates it into langchain's `edited_action`, and the HTTP route takes it —
but the only buttons rendered are Approve and Reject, so the one decision that
lets a person correct a tool call instead of refusing it is unreachable from
the UI.

Found while surveying the approval surface for course-design gate review. Not
fixed on the spot because the gate work will rewrite this renderer anyway, and
adding a third button now would be written twice.

### B21. `list_projects` scans the whole `Project` category on every call

`research_team/infrastructure/persistence/event_store.py`. Filtering deleted
projects out of the listing needs the set of deleted ids, and the set is built
by reading the entire `Project` category each time the list is asked for. The
result is correct and the cost is invisible at present scale -- a handful of
projects, each with a handful of events.

It is recorded rather than fixed because the fix is a read model, not a tweak,
and adding a third projection to carry a list that currently fits in memory
would be paying the projection's whole price (a runner, a table, a rebuild
path, an eventual-consistency surface) to avoid a scan nobody can feel yet.

The trigger to revisit is projects accumulating events rather than projects
accumulating: the scan is O(events in the category), not O(projects), so a
long-lived project makes every listing slower even if there is only one.

Found in review of the corpus-layer work; the scan predates it.

## Knowledge and corpus

Found while researching course-design workflows
(`docs/research/course-design/research-intake.md`). Five entries originally,
all the same shape: the graph path is well built and correctly bounded, and
the gap was *beneath* it — there was no corpus layer under the graph.

Three of them (retained source text, span-addressable offsets, and the unset
citation fields) are closed by the corpus layer: documents are now stored on
a `Corpus` stream before extraction, spans are derived deterministically from
the retained text rather than depending on offsets redstring discards, and
`uri`/`title`/`published_at` are populated. What remains below are the two
that the corpus layer does not answer.

### B15. Consolidation can silently merge contradictory claims

Two sources disagreeing about the same thing — one SME saying the escalation
threshold is 24 hours, another saying 48 — are likely to be consolidated into a
single entity, because both mention the same concept and the adjudicator is
looking for the same concept. The contradiction disappears rather than
surfacing.

`unmerge` exists and reverses it, but only if the agent notices, and the whole
failure mode is that nothing looks wrong. In procedural domains an apparent
contradiction is usually an *unstated conditional* — the two experts are each
right under conditions neither stated — so the interesting output is not "which
is correct" but "what were the two of them each assuming".

Wants a first-class contradiction record with a "both true in different
contexts" resolution state, and an escalation rather than an auto-resolve.

### B16. Bulk ingest reports no progress

`build_graph` takes no progress callback, and `build_knowledge_tools`
(`research_team/infrastructure/agent/knowledge_tools.py`) takes no
`ActivityReporter`. One document is tolerable. Forty documents behind a single
opaque `await`, in a UI that streams token-level deltas for everything else, is
not.

Blocking for corpus construction at any real scale, which is the only reason it
is not filed as a nicety.

## Security and multi-tenancy

Found while researching course-design workflows
(`docs/research/course-design/exposure-and-redaction.md`). Deferred as a group
because there is no user system and no RBAC: with a single local operator there
is no principal to withhold anything from, so all of this is long-term
importance rather than present risk. Recorded now because one item (B19) closes
a door permanently.

### B18. There is no authentication, so there is no author/learner boundary

There is no authentication anywhere in `research_team/interfaces/web/app.py` —
no user, no session identity, no authorization check on any of the routes. Every
surface is fully open to anyone who can reach the port.

That is fine for a local single-user tool and becomes the blocking issue the
moment anything is shared with a learner. Recorded here mainly so the surface
list does not have to be rediscovered — content reaches a browser through the
file route, scrub-to-event-N, `/files/history` (which ignores the scrub point),
diffs, the session view, and the SSE stream, whose approval and activity
channels bypass the presenter layer entirely (`app.py:592-593`) and can be
replayed via `Last-Event-ID`.

**Filtering these is not the fix, and this is the part worth not rediscovering.**
The agent's prose reasoning carries whatever the files carry — it discusses
answers and rationales while authoring them — and it is served in full by
`session_view` (`presenters.py:156`). Filtering that is a semantic
classification problem in which every false negative is permanent and public.
Allow-by-default is the wrong posture regardless of how well it is implemented.

The shape when it is picked up: two surfaces, not one filtered surface. The
console stays maximally transparent; learner delivery is a separate
deny-by-default reader over an explicit publication allowlist with pinned
revisions, whose stored bytes have never contained a withheld field at any
event index. A cosmetic "presenter mode" for screen-shares is fine if it is
labelled cosmetic and leaves the API untouched.

Until then, any answer-withholding in the renderer is a presentation
affordance and must not be described as security.

### B19. Nothing in the event log can be erased

The event store has no delete operation at all. Snapshots hold folded plaintext
every 50 events, `SessionSummaryRow.first_message` caches a copy, and
redstring's `Document` and `Consolidation` streams live in the same SQLite
file. So once sensitive source material — an SME transcript naming individuals
and judging their performance, a confidential internal document, a ticket
carrying customer data — is ingested, there is no supported way to remove it.

Of the four standard remedies, none is free here:

- **Crypto-shredding is disqualified specifically by this design.** `FileEdited`
  is delta-encoded (`domain/events.py:160-164`), so a shredded revision leaves
  every later revision of that path undefined. Time travel breaks, not just the
  shredded event.
- **Forgettable payloads** (log holds a reference, bytes live in a deletable
  store) are right for *corpus* documents and wrong for *authored files*,
  because applying them to files would replace the log-as-sole-truth property
  the whole system rests on.
- **Stream rewriting** is the only coherent remedy and must rewrite in place,
  because `SessionForkedFrom.at_event` is positional.
- **Tombstones** record intent and erase nothing.

**So the control belongs at intake**, where a human gate already exists and
where the exclusion record already has somewhere to say what was withheld and
why.

**The one part with a deadline:** pseudonymize identifiers at intake and keep
the mapping in a sidecar outside the event store. It costs a convention, it
survives contact with redstring's entity extraction and consolidation —
deleting one sidecar line erases a person from the graph without touching an
event — and it is the only item on this list that becomes impossible the moment
the first real transcript is ingested.

## Waiting on redstring

**Closed by redstring 0.3.0 and eventsource 0.12.0.** Every ask in this section
landed upstream, and the workarounds they justified are deleted:

- **B20** — `Relationship.source_id` exists, defaulting to `None` and filled by
  `map_extraction` from the document being extracted. There is deliberately no
  `source_text` counterpart: `ExtractedRelationship` has no span field, so a
  value there could only be a paraphrase, and a paraphrase in a field named for
  a quotation reads as evidence. Span-level anchoring remains B13's problem.
- **R3** — the fold is scoped by `tenant_id`, pushed into the adapter's `WHERE`
  clause. Rebuilding one project is an indexed read rather than a full scan
  filtered in Python.
- **R4** — a replay's failures are named. `ReplayFailure` carries the position,
  event id, event type, rejecting projection and the exception object itself,
  and `strict=True` refuses at the first one. `rebuild.py` catches
  `ReplayFailedError` and re-raises the detail as `KnowledgeError`, so the
  refusal an operator sees now names the event that caused it.

The rebuild driver moved: redstring 0.3.0 deleted its own replay module in
favour of `eventsource.replay`, so `rebuild.py` imports from eventsource now.
R2 (identifying unconsolidated entities) is still open, which is why the repair
path is still keyed by `source_id`.

*(Entries below are kept for the reasoning; the asks themselves are closed.)*

### B20. `Relationship` carries no provenance at all

redstring 0.2.0's `Relationship` model has neither `source_id` nor
`source_text`, where `Entity` has both. Verified by introspection.

Instructional claims are overwhelmingly relational — this control mitigates
that risk, step B follows step A, this failure mode has that cause — so the
part of the graph carrying the most instructional content is the part carrying
the least provenance. Worth filing upstream alongside R3 and R4; our corpus
layer (B12) can carry document-level provenance regardless, but cannot
retroactively tell us which sentence produced a given edge.

### B2. Two workarounds to unwind when redstring closes R3 and R4

`research_team/infrastructure/knowledge/rebuild.py` carries two workarounds,
both commented in place, both recorded as R3 and R4 in
`docs/superpowers/specs/2026-08-04-projects-and-redstring-knowledge-design.md`:

- **R3** — `redstring.projections.project` folds the *global* feed with no
  stream or category argument, so rebuilding one project's graph reads every
  session event in the store too. Scoping is by `tenant_filter` on the
  projection instead. Correct, but the scan is O(whole log) per project open,
  and that is the first thing to hurt as a store grows.
- **R4** — `ReplayReport.failed` is a count rather than a raise, so a poison
  event is swallowed and the graph comes up quietly incomplete. Project open
  checks the count by hand and refuses. A strict mode upstream would replace
  that check.

Both still stand as of redstring **0.2.0**, and both are worth filing upstream
with the detail found while upgrading:

- **R3 is a small change, not a redesign.** `GlobalEventFeed.read_all` already
  takes `FeedReadOptions(tenant_id=...)`, and eventsource's SQLite adapter
  pushes it into the `WHERE` clause. `project()` just never passes it.
  Forwarding a `tenant_id` would turn our per-open full-log scan into an
  indexed read.
- **R4's real defect is lost information, not the missing raise.** The handler
  is a bare `except Exception` that discards the exception, so `failed` is an
  integer with no way back to the offending event. We can implement the raise
  ourselves — we do — but we cannot reconstruct what redstring threw away. Ask
  for `ReplayReport.failures` carrying position, event type and error; the
  strict mode is the lesser half.

Of the other three gaps recorded in the same spec section, **R1 (embedding
provider) and R5 (understated eventsource floor) are closed in 0.2.0**. R2
(identifying unconsolidated entities) is still open, and is why the repair path
is keyed by `source_id` here rather than asking the library what is
unconsolidated.

R1 closing means vector search is now *possible*, not present: there is still
no `AGENT_VECTOR_STORE` and no recall path. That is a feature to spec, not a
workaround to delete, and it does not belong in this section.
