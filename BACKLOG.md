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
  `settle_timeout=0.1`. **Measured properly since, after two wrong readings
  of it.** It was first recorded here as failing ~1 run in 3 on a quiet
  machine; that figure was taken while other suites were running and is not
  right. A controlled trial on the same code gives 10/10 passing on an idle
  box and 6/6 under one concurrent suite, with failures appearing only under
  heavy load (two or more suites, one of them another project's).

  Both wrong readings pointed the same way, which is the useful part: a
  0.1s timeout produces failures whose cause is invisible in the failure
  itself, so whoever meets it reaches for the nearest story. Once it cost an
  afternoon deciding whether a branch had broken the turn path; the branch
  was fine and the answer needed a same-code A/B against `main` under matched
  load to establish. That is far too much ceremony to attribute one test.

Both are wall-clock races against a loaded scheduler, not logic faults, and
both are testing something worth testing — a real socket and a real timeout
are the point. The fix is not a longer sleep: it is making the wait
condition-driven, or making the timeout injectable so the test names its own.

Neither is urgent on its failure rate. Both are urgent on their
*diagnosability*: a hardcoded port and a 0.1s deadline each fail in a way
that names nothing about the real cause, so each one costs an investigation
every time somebody new meets it. Make the port ephemeral and the timeout
injectable, and both become tests that either pass or say why.

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

### B22. `self_review_separation` is called a harness invariant and bound like an option

`research_team/application/checks.py` describes it as an invariant -- a critic
must not be the generator whose work it screens, because self-screening yields
near-100% pass rates and the failure is invisible in the output. Every preset
then binds it only at Tyler's screen stages, and not at the other stages that
have both a generator and a critic. Consistent across `hybrid.py`, `ubd.py` and
`addie.py`, so it is a pattern rather than a slip.

Nothing is currently wrong: the stages it guards are the ones where the
model's authority is most concentrated. But an invariant that each preset
author has to remember to bind is not an invariant, it is a convention with a
strong docstring, and the next preset written by someone who has not read that
docstring will not have it anywhere.

**The fix is probably not more bindings.** If it is genuinely an invariant,
`stage_exit` should assert it for every stage that declares both a generator
and a critic, whether or not the preset asked -- the same way the corpus layer
prevents a lost document structurally rather than by asking authors to
remember. That turns a per-preset obligation into a property of the engine,
and it removes the failure mode where the check is absent exactly where nobody
thought to look.

Found in review of the check library and deferred because it changes the
contract between presets and the engine, which is a decision worth making
deliberately rather than inside a review round.
## Topics and autonomous research

Added alongside the topic tracker and auto-research mode
(`docs/superpowers/specs/2026-08-06-topic-tracker-and-auto-research-design.md`).
Each is a thing that feature deliberately did *not* build, recorded so the
reasoning does not have to be rediscovered.

### B23. Contradiction detection is a human gate, not a check

`topic.contested` tracks contradictions somebody already recorded. Nothing
*detects* them: deciding that two sources disagree on substance is semantic, and
a model asked "does my corpus contradict itself?" as a boolean answers no
fluently.

The shape when it is picked up: a critic prompt behind a gate whose output is a
*proposed* `TopicContested` entry -- a candidate for a human, not a verdict. The
registry already has the slot for it (`Trigger(run=None)` reports a standing
human gate rather than a silent pass), so the work is the prompt and the gate,
not the plumbing.

### B24. An auto-research run cannot fetch

By design, and worth writing down so it is not "fixed" by accident. `fetch`
floors at `ask`; an unattended loop that reaches an approval either deadlocks on
a future nobody will resolve or is auto-rejected outright. So a run is read-only
over the corpus and graph the project already holds.

The honest way to lift it is a **scoped, counted, run-expiring** pre-authorization
-- a domain allowlist with a fetch budget, granted as an event and dead when the
run ends. Not a blanket "N auto-approvals", which is `auto` with a counter: the
count is not what makes an approval meaningful, the scope is. And not the loop
lowering `TOOL_FLOORS` itself, ever -- a loop that can edit its own permissions
makes the floors advisory for everything else too.

### B25. A run's rounds are not narrated to a browser

**Mostly done.** Both front ends can start a run: `/research [n]` in the REPL,
and `POST /api/projects/{id}/auto-research` (plus its status and cancel
routes) over HTTP. The authentication objection that held the endpoint back is
answered the way `web_search` answers it -- the routes are wired only when
`AGENT_AUTO_RESEARCH` is set, so an install that has not opted in has no route
rather than a route that refuses.

**What is left is narration, and it is the same gap `/turns` already has.** A
run's events reach the live feed like any others, so a browser watching the
project sees each round land -- but a round *is* a turn, and a turn is atomic,
so nothing arrives while one is running. The web UI can therefore show a run's
history and its counters and cannot show the round in flight. Closing that
needs the second channel `on_activity` already gives the REPL, which is the
work described at the end of "What the live feed can and cannot show" rather
than anything about runs specifically.

There is also no listing of a project's past runs. `GET .../auto-research`
answers about the run in flight only, because "every run this project has ever
done" is a projection nobody has built and a stream scan there would be the
read that quietly gets slower for a year.

### B26. Two registries share a type; the bindings are still separate

**Half done.** `topic_attention.py` now produces `findings.Finding` -- one type,
not two that agree until they quietly stop -- and its triggers return
`(message, cites, suggested_edit)` the way `CheckFn` does, so severity is the
registry's to stamp rather than something a trigger can contradict. The join
renamed `Finding.affected_artifact_ids` to `cites`, because a trigger cites
source ids and sub-question keys and neither is an artifact.

**What is deliberately not done, and why.** The two `run` signatures stay
separate. A check reads a `CheckContext` of artifacts, links and matrices; a
trigger reads folded topic state and a corpus snapshot. They share a contract
and an output, not an input, and forcing one signature would hand every check
arguments it does not use to make a table look tidy.

**What is left, and is real.** Presets cannot bind topic triggers. `checks.py`
has a parameter model per check, `problems()` validation, and a binding syntax
preset authors already use; the topic registry has a plain `params: dict` and
`Trigger.bind(**params)`. So a preset can say a stage wants `coverage` at three
and cannot say a project wants `topic.low_coverage` at three. Closing that means
giving triggers pydantic parameter models and a binding site in the preset
schema -- worth doing when a second project wants different thresholds, and not
before, since today there is exactly one caller and it takes the defaults.

### B27. Staleness is per-corpus, not global

Every position in the topic feature is one project's *corpus version*
(`corpus_position`), because a projection handler is given an event rather than
its envelope, so the global feed position is not in reach where these are
written. That is the right scale for the questions being asked -- "did anything
arrive in this corpus since I last looked" -- but it means a topic cannot be
stale with respect to anything outside its own project's corpus.

If topics ever need to notice work in *another* project, this is the thing that
has to change first, and it is a wider change than it looks: the positions are
persisted in `TopicInvestigated.at_position` and in every acknowledgement's
expiry, so redefining the scale invalidates both.

## Interactive components

What v1 of the markdown component system knowingly left out. The design is in
`docs/research/course-design/markdown-components.md` §3.10, which phases it;
`widget-horizons.md` beside it ranks the types not yet registered.

B28, B29 and B31 are **closed**. What remains open is B30, which is not a
defect of this subsystem at all -- see its entry.

### B32. A rewritten item leaves a learner's history ambiguous

Closing B28 surfaced the question B28 said was the hard part, in a smaller and
more answerable form. `LearnerProgress` keys an item by `(path, component_id)`
and stamps every attempt with the sha256 of the body it was answered against.
That means a rewrite is *visible* -- the digest changes under a learner -- and
nothing acts on it.

Deliberate, and the reason is that the right action is not a domain rule. A
fixed typo should not reset anyone; a reworded distractor probably should; a
question rewritten to ask something else definitely should. Only the first is
mechanically detectable, and the aggregate has no basis for the other two.

What it wants is not a rule but a *report*: an author-facing view of which
items changed under which learners, with the two digests, so the call is made
by someone who can read both versions. That belongs beside `alignment_map` in
`widget-horizons.md` -- both are reports that make an authoring decision
visible rather than making it automatically.

Worth noticing: this is only answerable because the digest is in the log. If
the attempt had stored the verdict alone, the question could not be asked at
all afterwards.

### B33. Progress is per session, which is where authentication will bite

`LearnerProgress` shares its session's UUID, because a session is the only
identity in this codebase that means "one person working through this
material". That is correct today and is exactly what breaks first when B18 is
picked up: two learners cannot share a course without sharing a session, and a
session is also the thing the *author* takes turns in.

Recorded separately from B18 so the coupling is not rediscovered. The shape
when it is picked up: progress keys on a principal, and the session id becomes
the principal for the single-operator case rather than the definition of one.
Nothing else in the aggregate assumes a session -- `decide` and `evolve` never
name one -- so the change is the repository's key and the routes, not the
rules.

### B30. Answer-withholding is real projection and still not a boundary

The learner projection removes the answer key structurally before serialisation
and grading happens on the server, so the browser genuinely cannot mark an
answer. That is worth having and it is not a control: the same file is readable
in full at `GET /api/sessions/{id}/files?path=`, the source toggle shows it, and
the agent's prose discusses the answers while authoring them.

This is B18 restated at one surface rather than a separate problem, and B18's
last line is the rule this implementation follows: it is a presentation
affordance and is described as one, in the module docstring, in the README, and
in the UI's own tooltip on the "answers withheld" badge. Anyone tempted to
describe it otherwise should read B18 first.

**Not independently fixable, and it was reviewed for closure and deliberately
left open.** There is no action here that is not B18 -- the fix needs
authentication and a separate deny-by-default delivery reader, which is B18's
whole content. It stays as the marker that this surface follows the rule rather
than bending it, and it closes when B18 closes.

### ~~B28. An attempt is graded and then forgotten~~ (done)

`LearnerProgress` (`domain/learner.py`) is the record: one stream per session,
sharing its UUID, keyed `(path, component_id)`, with `answered` and `completed`
as its event names for the xAPI reason §3.6 gives.

Three things went differently from what this entry anticipated:

- **`attempted` is not emitted.** The entry named three xAPI verbs. No surface
  produces the first -- nothing tells the server that a learner opened an item
  and did not submit -- so emitting one would have been inventing a fact to
  fill out a vocabulary.
- **Identity was the hard part, as predicted, and is not resolved so much as
  made answerable.** Every attempt carries the digest of the body it was
  answered against, so a rewrite under a learner is recorded. What to do about
  it is now B32.
- **`persist: true` is honoured rather than assumed.** A checklist that did not
  ask to be remembered is refused with a 400 rather than quietly accumulating
  state the author never opted into.

The state holds counts, scores and flags and no response text, for the reason
`corpus.py` holds no document text: snapshots fold the state, and a growing
list of every answer ever given would go into each one. The sequence of
attempts -- the object this entry called the pedagogically interesting one --
is a projection over the stream, and the stream has everything it needs.

### ~~B31. A subagent sent to write assessment items will write prose~~ (done)

Took the second of the two options this entry laid out: the stage prompt tells
the model to put the component requirement in the task it writes. The entry
called that one "probably right" and said nobody should make the change without
watching a real delegated authoring turn first. That caveat was aimed at the
*first* option; what settled it without a live turn is that `delegation.py`
already steers subagents toward investigation and away from constructive work,
and already tells the caller "give it everything it needs; it cannot see this
conversation". Deriving guidance into the delegation prompt would have argued
with both.

Part of the component block rather than a new always-on paragraph, so a stage
with no component-bearing output is still told nothing.

### ~~B29. The parse is not cached, though the cache key is exact~~ (done, differently)

Measured, as this entry asked, and the measurement found something better than
a cache. `yaml.safe_load` binds PyYAML's *pure-Python* scanner even when the
libyaml extension is installed -- which it is here -- and the C loader parses
the same component body about nine times faster. A 24-component lesson went
from 83ms to 16ms on a loaded machine.

So there is still no cache, and now there is much less reason for one: the win
is larger than a cache over the slow loader would have been, and it costs no
invalidation story. `CSafeLoader`, not `CLoader` -- the unsafe loader is also
faster and would let a lesson written by a model construct arbitrary Python.

The cache key this entry recorded is still exact and still unused, including
the asymmetry it flagged: `at=None` means HEAD, which moves, so a cache keyed
on it would need the resolved event index. Left here rather than deleted,
because that is the note whoever measures next will want.

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
affordance and must not be described as security. One now exists -- the
learner projection in `application/components.py` -- and B30 records that it
follows this rule rather than bending it.

**B33 is the other half, and it is the one that will bite first.**
`LearnerProgress` is keyed by session, because a session is the only identity
this codebase has. So there is not merely no boundary between author and
learner -- there is no way for two learners to be *distinct* without being two
sessions, and a session is also the thing the author takes turns in. Whoever
picks this up should read B33 before designing the principal, because progress
is the first thing that needs one.

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
