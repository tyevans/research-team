# Backlog

Deferred work. Every deficiency found and not fixed on the spot lands here,
with enough detail that picking it up does not require rediscovering it.

The `B` numbers are stable handles, not a taxonomy. Closed entries are deleted;
if tracked code cites one by name, say where its reasoning went before deleting.

## Code quality

### B1. `Project`'s class docstring says little that its module does not

`research_team/domain/project.py`. The class docstring is near-verbatim from
`Session`'s — "the imperative shell, holds no rules, delegates all
three" — and the `Project`-specific reasoning it might add is already in the
module docstring above it. Not wrong, just thin: a reader who came for the
difference between the two aggregates does not find it here.

Found in the Task 1 review of the projects/redstring work and deferred as
Minor, because the docstring convention is satisfied and nothing is
misleading.

### B54. Three components set a border width with no `border-solid`, so it draws nothing

This build imports no Tailwind preflight, so an element's border style
defaults to `none` unless a utility sets it. A width alone on a side whose
style is `none` draws nothing — the inverse of the `border-0` trap recorded
in `CLAUDE.md`. Three call sites carry a directional border-width utility
with no `border-solid`, each sitting beside a padding utility (`pl-2`/`pl-3`)
that only makes sense next to a visible rule, which is the tell that a line
was intended:

- `frontend/src/presentation/session/GateReview.tsx:135` —
  `border-l-2 border-line-strong pl-2`
- `frontend/src/presentation/shell/DecisionBar.tsx:44` —
  `border-b border-k-tool`
- `frontend/src/presentation/course/AutonomyAllowAll.tsx:78` and `:95` —
  `border-l border-line-soft pl-3`

Found while reviewing the ask-page redesign branch, which fixed the same
class of defect within its own files (see that branch's story and the
`border-0` entry in `CLAUDE.md`). Not fixed there because it is a pre-existing
defect on `main`, outside that branch's scope, and each site needs a
judgement call this can't make blind: whether the missing rule is what these
three intended, or whether the surrounding padding should shrink instead. That
wants eyes on the rendered result in Storybook, not a sed pass adding
`border-solid` everywhere a directional border-width utility appears.

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

  **Fixed, and this entry was wrong about it three times.** The
  `settle_timeout=0.1` was never the problem. The precondition was: the test
  slept 0.3s and assumed the turn had reached the model call, and the cancel's
  answer depends entirely on where the turn is when it arrives --

  | Turn's position | Result |
  |---|---|
  | not yet registered | `cancelled=False, settled=True` |
  | registered, not yet in the model call | `cancelled=True, settled=True` |
  | wedged in `StubbornModel` | `cancelled=True, settled=False` |

  Only the third is under test. Under CI load the turn was slower to *start*,
  so 0.3s left it in the second row and the cancel settled promptly -- correct
  behaviour, failing as `assert True is False`. Note the direction, which is
  what kept this misfiled: load makes things slower, so a "will not settle"
  test failing under load reads as impossible, and the failure was repeatedly
  waved through as "the flaky one" on the strength of this entry. It was
  reproduced deliberately by dropping the sleep to zero (first row) and
  confirmed by proving the fixed test red with the wedge removed.

  `StubbornModel` now sets an `asyncio.Event` as the call begins and the test
  waits on that, with a 5s ceiling that means "the turn never started" rather
  than naming a deadline. The two other `sleep(0.3)` sites in that file have
  the same shape and are not yet converted; they have not been observed
  failing, which is not the same as being right.

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

**The evidence now exists: `/checks` reports how often this check runs, fires
and is overridden, per stage it is bound at.** That answers "whether its absence
costs anything" with numbers instead of argument. Deciding what to do about them
— more bindings, or an engine-level assertion — is still entirely open, and the
telemetry round deliberately did not touch it.

### B38. Four `matrix_density` bindings still have no axes, so they still report

`stage_exit.course_matrices` builds the matrix a `matrix_density` binding is
about, from `rows` and `columns` filters on the binding. Only
`ubd.pure`'s `intent_x_evidence` names them, because that is the one this round
was scoped to. The other four bindings -- `addie.pure`'s `objective_x_module`
and `intent_x_evidence`, and `hybrid.default`'s `behaviour_x_content` and
`thread_x_thread` -- still answer "no matrix was built for this stage" on every
run of every course, which is the defect this round fixed for one of the five.

Two of the four are ordinary and one is not:

- `objective_x_module`, `intent_x_evidence` and `thread_x_thread` are
  relational, and each needs its axis pair chosen and a course fixture written
  against it. `thread_x_thread` additionally carries `min_contact_points`,
  which `matrix_density_check` raises on rather than implements -- so it has a
  second problem underneath the first.
- `behaviour_x_content` is Tyler's **intrinsic** grid. Its axes are attribute
  values, not artifact types, and `course_matrices` deliberately does not build
  one: a grid whose rows are the behaviours somebody happened to write has no
  empty rows by construction, which is the exact way `coverage.py` says the
  diagnostic goes vacuous. It needs *declared* axes from somewhere -- most
  likely the preset -- and that is a design decision, not a wiring one.

Not fixed here because each needs a course written the way its methodology's
prompts (which for ADDIE and Tyler do not exist yet) would write one, and a
matrix bound to axes nobody has validated against real output is the same
always-reports defect with a different message.

**`/checks` now counts it: these four should show a fire rate at or near 100%
with an override rate to match, which is the shape this entry asserts and could
not previously demonstrate.** The numbers make the case; wiring the axes is
still the open work and nothing about it was fixed.

### B44. Check telemetry has no HTTP route and no browser view, deliberately

`/checks` in the REPL is the only way to read the `check_outcomes` table.
`create_app` gained no parameter and `tests/interfaces/test_web_entrypoint.py`
passes untouched, which is the intended state rather than an omission.

The reasoning, from
`docs/superpowers/specs/2026-08-12-check-telemetry-design.md`: these numbers are
a maintainer's instrument for deciding which checks earn their place — a
decision made once in a while, by the person who can change `checks.py` — and
not a per-project surface a course author needs. A JSON route with no UI behind
it is a route nobody calls, and building the UI is a frontend round that ought
to be justified by somebody actually wanting it. `CorpusRunner` and
`TopicRunner` already set the precedent of a projection whose `rebuild()` has no
HTTP surface.

**The trigger to revisit: someone wanting these numbers who is not editing
`checks.py`.** Recorded because a deferral without a trigger is a
rationalisation — it reads as a decision and behaves as a default, and nothing
ever overturns it.

The work if that trigger fires is a route over
`ProjectCheckTelemetryReader.stats()` plus the view, and the honesty constraints
travel with it: the null median on the tool path and the separated policy
approvals are guards in `summarise`, not notes in a docstring, so any surface
reading through that function inherits them. A surface that recomputed the
statistics from rows would not.

### B45. `test_advisory_findings_do_not_fail_the_condition` passes for the wrong reason

`tests/application/test_stage_runner.py:324` binds
`Check(check="shared.orphan", params={"artifact_type": "Intent"})`.
`OrphanParams` declares `type` and `must_link_to` and nothing else, and `Params`
is `extra="forbid"` — deliberately, so that a misspelled parameter is loud. So
the binding raises `MalformedCheck`, `review_stage` turns that into one
**blocking** finding, and the advisory finding the test's name promises is never
produced.

It still passes, because `review.blocked` is `bool(invariant_failures)` and a
blocking finding is not an invariant failure. That is the correct behaviour and
worth pinning — but the test as written pins it against a crashed check rather
than against an advisory one, so the case in its docstring is untested and the
name misdescribes what runs.

Made visible by the telemetry round: `StageReview.evaluated` now reports
`severity='blocking'` for that binding, which is what exposed the mismatch. Left
alone there because it is a different task's file and the fix is a judgement
about what the test should assert, not a rename. The binding that would exercise
the intended case is `params={"type": "EvidenceSpec", "must_link_to": "Intent"}`
— which runs over an empty domain and finds nothing, so whoever fixes this needs
a course that produces an actual advisory finding, not just a corrected
parameter dict.

Worth checking the neighbours at the same time: one wrong parameter spelling in
a test file is rarely alone, and nothing fails when a check quietly stops
running.

### B46. No test drives a real gate through to a rendered `/checks` table

The path from a gate to a number is covered in three overlapping pieces and
nowhere as a whole: `tests/application/test_stage_runner.py` proves both gate
paths emit, `tests/infrastructure/test_check_telemetry.py` proves the projection
folds a review and its decision, and
`test_an_application_wires_a_reader_that_is_actually_following` proves the
runner is started and reachable through a real `Application`. No single test
walks from a stage review to a rendered row.

The gap is not hypothetical. The seam the three pieces do not cover between them
is the projection subscribing to a real store in a real composition and keeping
up with it — and Task 4 measured that a wrong `caught_up` there fails as a bare
`TimeoutError` naming nothing about the cause. `check_telemetry_caught_up()`
exists and has no caller, so nothing currently exercises it either.

Deferred rather than skipped: building it means driving `StageRunner` to a gate
inside a built `Application`, and `tests/application/test_stage_runner.py` uses
its own harness instead. That is a new fixture rather than a reuse, which is why
it did not belong in a task scoped to the read surface. It belongs beside
`tests/integration/test_advance_stage_gate.py`, which already drives the tool
path through a real application.

### B47. The only branch of `apply_schema` that drops a table has no test naming it

`research_team/infrastructure/persistence/read_models.py`. When
`generate_additive_migration` refuses -- a required column with no default --
`apply_schema` checks for a row, re-raises if it finds one, and otherwise
`DROP TABLE`s and recreates. The re-raise is pinned by
`test_a_refused_reconcile_leaves_the_table_untouched`. The drop is not pinned by
anything: it is reached only incidentally, by
`test_a_database_written_before_a_field_existed_gains_its_column`, which is
about `project_id` arriving in an old database and passes for that reason rather
than for this one.

That asymmetry is the reason this is filed rather than shrugged at. Every other
path here widens; this is the one that destroys a table, and it is guarded by a
single `SELECT 1 ... LIMIT 1` whose sense could invert in an edit with no test
turning red. A test that named the recreate would also record the argument for
it -- an empty read-model table holds nothing that is not re-derivable from the
log -- which is currently only in a docstring.

Worth writing when someone next touches that function, and it needs two cases,
not one: an empty table taking the recreate, and the same model against a table
with one row taking the raise. Flagged by the task that introduced the branch
(`docs/reports/adopt-0140-task2.md`) rather than found later.

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

### B36. A stage gate is decided against evidence that is not durable or visible

**Closed for the runner path; still open, unchanged, for the tool path.**

`StageRunner` poses the gate *between* turns, after `_save_turn` has committed.
On that path both halves of this item evaporate structurally rather than being
worked around: the artifacts and the `check-findings` report are in the store
while the reviewer decides, so `GET /api/sessions/{id}/files` answers, and
nothing about `run_turn` changed. `test_the_artifacts_are_in_the_store_when_
the_gate_is_posed` is what fails if that stops being true.

The visibility half that was genuinely worth having landed too, in the smaller
form the diagnosis implies once durability is not the problem: `gate_context`
carries `artifact_paths` -- the *list* of files this stage produced, so a
reviewer does not have to know where a stage writes -- and not their contents,
because the viewer can already open them.

**What is left is the tool path, and it is left deliberately.** A model calling
`advance_stage` still raises the interrupt before the tool body runs, and at
that instant nothing the turn produced has reached the store; that is what
`test_nothing_the_turn_wrote_is_durable_when_the_reviewer_is_asked` pins and it
is still true. `gate_context` passes no `artifact_paths` there, because on that
path the files genuinely are not there yet and listing paths that answer 404
would be worse than listing none. The durability analysis below is why nobody
should fix that by committing mid-turn; the fix is to use the runner, or to
accept that a hand-driven advance is reviewed against the findings and the
model's rationale, which is what it has always been.

The original item, kept because its diagnosis is the reason the runner is
shaped as it is:

`EndTurnOnStageAdvance` made a successful `advance_stage` end its turn, so a
crossed boundary is durable before anything is built on it. It did **not**
change the other half: the approval is still posed *before* the tool runs, and
at that instant nothing the turn produced has reached the store.

The ordering, verified rather than assumed:

- `SessionService._save_turn` is the only thing that appends a turn's events,
  and it runs after the executor returns. `DeepAgentTurnExecutor` is
  constructed with no repository, so it could not commit early if it wanted to.
- `advance_stage` floors at `ask`, so the interrupt fires before the tool body.
- `GET /api/sessions/{id}/files` loads the aggregate from the store. So the
  stage's artifacts, and the `check-findings` report `gate_review` writes, are
  invisible to the reviewer's file viewer until the turn they are judging has
  already finished.

`test_nothing_the_turn_wrote_is_durable_when_the_reviewer_is_asked` pins this,
and a comment in `gate_review` asserted the opposite for some time.

**Two different fixes, and the cheap one is probably the right one.**

*Visibility* is what the gate actually needs, and it does not require touching
durability. `ApprovalRequest.context` already carries the findings inline over
SSE -- that is why the gate is not blind today. Extending `gate_context` to
carry the stage's artifact paths and contents would put the evidence in front
of the reviewer with no change to when anything is written. Bounded work, no
new invariant.

*Durability* -- committing pending events before raising the interrupt -- is
the larger and riskier change, and was rejected here rather than deferred by
oversight:

- It breaks the invariant `run_turn`'s docstring states and its `except`
  clause enforces: "all events append atomically at the end, or not at all". A
  crash after a mid-turn commit leaves a committed partial turn with no
  `CompleteTurn` and a failure marker appended beside it, which is precisely
  the half-applied turn the current design refuses to produce.
- It interacts with the retry added in #69. `_save_turn` computes
  `base_version` from the aggregate and `_refuse_unrebasable` allows a rebase
  only over `AutonomyChanged`; a mid-turn save moves that baseline, and a
  mid-turn save that *loses* its lock has no retry story at all.
- It needs a new seam. The commit would have to happen inside
  `DeepAgentTurnExecutor._decide`, which is infrastructure and deliberately
  holds a `Session` rather than a repository.

Worth noting what a denied approval would then mean, since it is not obviously
wrong: the artifacts would be committed and the stage not advanced, which is an
accurate record -- the work was done, the boundary was not crossed. The problem
is not that arm; it is the atomicity guarantee and the retry.

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
`AGENT_RESEARCH_RUN` is set, so an install that has not opted in has no route
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

### B36. Topic dispatch is web-only, and the REPL is a second composition site

`docs/design/topic-dispatch.md` §9 asks for a deliberate answer rather than a
silent absence, so here it is: **dispatch is wired in `web.py` and not in
`main.py`.** The REPL has no `/dispatch`, and `TopicDispatcher` is reachable
there only as `application.dispatcher`.

That is a choice, not an oversight. `DispatchQueue` is the whole point of the
feature -- one at a time per project, the rest waiting -- and a REPL has no
way to show a queue draining, no place to put a per-topic status chip, and one
operator who is already sitting in a session that *holds the project*, which a
dispatch would then be refused from joining. `/research` works in the REPL
because a run is a single thing with a single status line; a queue over forty
topics is not.

What must not happen is the failure `tests/interfaces/test_web_entrypoint.py`
exists to catch, arriving at the other composition site. That guard reads
`inspect.signature(create_app)` and does not cover `main.py` at all, so a REPL
dependency added and not wired is still invisible. **Extending the guard to
`main.py` is the work here**, and it is worth doing while the reasoning is
fresh -- not adding `/dispatch`.

### B37. A dispatch's queue does not survive a restart

`DispatchQueue` is process-local, so a restart drops every pending dispatch and
the catch-up route answers with an empty queue. `dispatch.py`'s module
docstring states the trade and accepts it: it is the same trade every
supervisor here makes, and `workers.py` already argues that "a restart shows an
empty roster, which is the truth".

The reason it is recorded anyway is that a queued dispatch is a *user
intention* rather than a running process, and losing an intention silently is
worse than losing a process. The UI does not currently say "these were
dropped" -- the chips simply stop being there on reload, which is
indistinguishable from never having pressed the button.

The fix is not a bigger buffer. It is the `TopicDispatch` aggregate
`docs/design/topic-dispatch.md` §7 rejects for now, and §7's argument for
rejecting it is the thing to re-read before building it: four events in the
permanent vocabulary, and a decision about what a `DispatchStarted` with no
terminal event means when the process died. **Do not build it until someone has
actually lost work to this.** The trigger to watch for is the first request for
dispatch *history* -- "what have we ever asked about this topic" -- which the
log genuinely cannot answer today.

### B39. Topics already stored with an implicit subject cannot be restated

A question opened before self-containment was required reads "typical physical
traits" -- correct only against the project it was opened in. The prompt fix
stops new ones being written that way and the dispatch briefing names the
project so a *dispatched agent* can still act on an old one, but the stored
text is unchanged and shows up unrepaired everywhere else: `list_topics` output,
the topic list in the browser, and the `/topics/<nn>-<slug>/` directory names,
which are derived from the question at dispatch time.

**They are not repairable today, and the reason is that there is no command for
it.** `domain/topic.py` has `SetTopicStatus`, `RecordFinding`, `LinkSource` and
nine others; nothing restates a question. Repairing an existing topic therefore
means a new event -- `TopicQuestionRestated`, say -- in the permanent
vocabulary. That is the same cost `topic_dispatch.py`'s module docstring is
proud of not paying ("a feature that adds no vocabulary to the log cannot break
anyone's stored history"), so it is not a change to make casually.

Rewriting `TopicOpened.question` in place was considered and rejected outright:
events already written are not rewritten, and a migration that edited stored
payloads would make the log disagree with every snapshot folded from it.

If it is built, it should be a **human** action rather than an agent one, for
the reason `TopicPort` gives about `close_topic`: deciding what a question was
really asking is a judgement, and an agent that could restate its own topics
could quietly redefine the work it failed to do. A restatement event also
answers something the log cannot today -- what a topic was originally opened
as, versus what it is now understood to be -- which is worth more than the
repair on its own.

The cheap interim, if a live project is unusable: open replacement topics with
self-contained questions and set the old ones to `superseded`, which is exactly
the status that exists for "another topic now covers this ground". That loses
the findings attached to the originals, which is why it is an interim and not
the answer.

### B42. A malformed URL a human approves crashes the turn

`fetch.py`'s `urlsplit(url)` is unguarded. `urlsplit("https://[::1/x")` raises
`ValueError: Invalid IPv6 URL`, and the tool's outer `try` has only a `finally`
and handlers for `httpx` and `UnicodeError` — so the `ValueError` escapes,
which is the thing tools here are written not to do ("a tool that raises turns
an outage into a broken turn").

`grants.py` guards the identical call for exactly this reason and returns "not
covered"; `fetch.py` never gained the same guard. So the gate refuses a
malformed URL — `_in_scope` fails closed and interrupts — and reaching the
crash needs a person to approve one. That is why it has not been seen: the
approval path is the only way in.

Found by the scope-fix re-review of the fetch pre-authorization branch and
deliberately not fixed there. That branch produced three Criticals in three
attempts at one mechanism, and adding an unrelated pre-existing fix to it was
the obvious way to produce a fourth. It is three lines: parse once, guard the
`ValueError`, return the same refusal string the scheme check already returns.

### B43. A page that renders in the browser cannot be read, and that is decided

`fetch.py`'s `UNREADABLE` path is a dead end for any JS-rendered page: an app
shell extracts to nothing, and asking again produces the same nothing.
`FETCH_PROMPT` already tells the model so. A headless browser is the only thing
that would lift the ceiling, and it is **refused** rather than deferred.

The reasoning, so that nobody has to reconstruct it from a frustrating
afternoon:

- The dependency is not a package. It is a browser binary, a download step in
  CI, and a resource profile unlike anything else this process runs.
- It buys a new class of failure on the path to a citation — render timeouts,
  anti-bot challenges, and pages slow enough to change what a turn costs.
  Today an app shell fails one way, immediately, and says which way. A
  rendered fetch that works most of the time produces something worse than a
  gap, which is an intermittent one, and the coverage machinery has no way to
  represent that.
- The honest answer already exists and is already wired: the model can
  `record_gap`, which is exactly what the coverage layer wants from a source
  nobody could reach.

**The trigger to revisit is a corpus this project actually wants being behind
an app shell.** Not a page; a body of sources. Until that exists the argument
above holds, and the entry is a decision. Without the trigger it would be a
rationalisation, which is the failure mode this entry is written to avoid — a
default and a decision look identical in a diff and fail very differently in
a year.

Recorded during the defects round that closed B41, because the two sit one
constant apart in the same file and only one of them was ever chosen.

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

Note B40 before designing that record as a graph node: consolidation would be
just as likely to eat it.

### B40. A node that is not a claim cannot safely live in the graph

Established while designing `record_gap`
(`docs/superpowers/specs/2026-08-10-representable-absence-design.md`), which
started as an "open question" entity type and became a topic event instead.
Recorded because the reasoning is not visible from the code, and the next
person to want a question node, a contradiction record (B15) or an assumption
node will reach for the same design.

**Consolidation would eat it, and the loss would be silent.** A node named for
the entity it concerns blocks with that entity on both the `p:` prefix key and
the `s:` soundex key (`redstring/domain/blocking.py:115-124`), scores name
similarity 1.0, and lands in the middle band, so it reaches the adjudicator.
The adjudicator is shown only the *subject's* `entity_type`
(`redstring/consolidation/policy.py:188-196`) and asked whether two mentions
"refer to the same real-world thing". `entity_type` is neither a scoring
feature nor a filter (`redstring/consolidation/candidates.py:126-153`), and
there is no per-entity opt-out anywhere on `Entity` or `CandidateFinder`. A
merged-away node then disappears from the browser
(`infrastructure/knowledge/graph_reader.py:54-84`), so the node does not show
as a duplicate — it vanishes.

**It would have to masquerade as an extraction.** `DocumentExtracted`'s
validator requires every entity's `source_id` to equal the event's
(`redstring/events/document.py:118-124`), so a node with no document behind it
needs a synthetic document identity.

**The browser could not show its state.** Entity types are distinguished only
by a hashed colour (`frontend/src/presentation/research/entity-colors.ts:21-48`);
there is no shape, border, or node-state notion. Open-versus-answered would be
new surface across `GraphEntity`, `GraphReadPort`, the presenter and the
canvas.

What is *not* a barrier, and is worth knowing: `entity_type` is an unvalidated
free string end to end, domain schemas prompt but do not constrain (ADR 0011),
`ExtractionMethod.MANUAL` already exists, and
`Document.record_extraction(entities=...)` accepts caller-supplied entities and
asks no model — so a non-extraction write path is reachable today without a
redstring change. The obstacle is consolidation and rendering, not the write.

If this is picked up, the redstring-side asks are: a deterministic public id
helper (`entity_id_for` is behind a dotted path and therefore internal), an
`EntityAsserted`-shaped event with a `GraphProjection` handler so a node need
not be attributed to a document, and a per-entity consolidation opt-out. Note
`rebuild.py` replays `strict=True` with one projection, so a new event type
without a handler fails project open rather than degrading.

### B16. Bulk ingest reports no progress

`build_graph` takes no progress callback, and `build_knowledge_tools`
(`research_team/infrastructure/agent/knowledge_tools.py`) takes no
`ActivityReporter`. One document is tolerable. Forty documents behind a single
opaque `await`, in a UI that streams token-level deltas for everything else, is
not.

Blocking for corpus construction at any real scale, which is the only reason it
is not filed as a nicety.

### B34. The live feed reads whole extractions to say "something happened"

`EventStoreSessionRepository.read_since` admits redstring's `Document` and
`Consolidation` categories so the graph pane can redraw without a reload. That
means every poll deserialises `DocumentExtracted` payloads -- every entity and
relationship an extraction found -- to emit a frame carrying a project id and
an event class name, and nothing else. The waste is the whole payload.

The fix, when it is worth it: a projection following those two categories that
appends a small `GraphChanged` of our own, on a stream this feed already reads.
The wire format does not change, because the frame already carries no entities;
only `read_since` and the projection's own start/health/rebuild wiring do. It
was not taken now because it adds a moving part -- another follower to start,
catch up, rebuild and report health for -- and a second lag between an
extraction landing and a browser hearing about it, in exchange for a cost that
has never been measured.

The trigger to act is a measurement, not a feeling: time one poll against a
project whose corpus is a few hundred documents. Until someone has that number,
this is speculation about a cost, which is the reason it is filed rather than
fixed.

### B35. A graph refresh discards what a reader pruned

`GraphPane` redraws by calling `loadAll` when a graph frame arrives, and
`loadWhole` replaces the view -- so an extraction that lands while a reader has
pruned their way down to six interesting nodes puts the whole graph back. Their
*selection* survives; their work does not. It is the same effect "Reset view"
has, applied by something they did not do.

Not fixed with the streaming change because the merge that would preserve
pruning has an unanswered question in it: once consolidation has merged a
removed node into one that is still on the canvas, "this node was pruned" no
longer names anything the new graph contains. Any rule here is a guess until
somebody decides what the reader meant. Worth deciding -- the pane's whole
pruning feature exists because browsing accumulates -- but it is a design
question, not an implementation gap.

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

## The ask page

Everything here was named in
`docs/superpowers/specs/2026-08-12-project-ask-page-design.md` as deliberately
not built. The page is a parallel path beside `SessionService`, and each entry
below is a reason to revisit whether that was right: a session already has
persistence, forking, a place to steer work from, and a supervisor that can fan
out. Picking up any one of these on the parallel path means rebuilding a piece
of the session machinery, and picking up two or three means the ask page should
have been a session after all.

### B48. An ask is not persisted, so there is no history and no resumption

The conversation lives in a `ConversationRegistry` in server memory, keyed by a
browser-minted chat id, and is dropped on `forget` or on restart. Nothing
records that a question was ever asked. A reader who found an answer useful
cannot come back to it, cannot link to it, and cannot see what anyone else
asked.

Picking it up means choosing where it lands. Events are the obvious home and
the one the design refused: appending them moves the project's tip, which is
what "ephemeral" was bought with, and
`tests/integration/test_ask_writes_nothing.py` fails the moment anything on
that path appends. A separate store answers that, and then owes an answer for
why the project's own log is not the record of what was asked of it.

### B49. No forking and no time travel over an ask

A session can be scrubbed to any point and forked from it; an ask cannot. There
is no way to take a conversation five turns in, branch it, and try a different
question from the same context, and no way to look at what the transcript held
before the last answer replaced it.

This one is downstream of B48 — there is nothing to travel over until there is
something stored — but it is the sharper reason to reopen the session
question, because scrub and fork are exactly what the session machinery already
does and what a bespoke store would have to reimplement.

### B50. The chat cannot steer the project it is asking about

The tool set is a read-only allowlist, so a reader who notices a gap while
asking — an unexamined topic, a claim with one source — has no way to act on
it from the page. Seeding a topic or dispatching a research run means leaving,
finding the Research page, and restating by hand what the chat already knows.

The obstacle is not the tools, it is the hold: writing to a project means
joining it, and joining forks the previous holder's filesystem and takes
exclusive hold. An asking surface that could also dispatch would need either
that hold or a narrow write path that does not fork — and a design for the
second is the actual work here.

### B51. One agent answers wide questions that want fan-out

"What did we find across every source?" runs as a single agent reading one
document at a time. The supervisor's subagent fan-out is not available on this
path, so breadth costs latency linearly and a long question can exhaust the
context that a set of parallel readers would each have had to spare.

Worth measuring before building: it is unknown how wide a question has to be
before this hurts, and the fix is substantial (a second executor shape,
per-subagent activity frames on the stream, citations merged across children).

### B52. No admitted tool reads one identified topic, so topics are not citable

`open_topic` was in the read-only tool set until review found that it *creates*
topics — `RepositoryTopics.open_topic` executes an `OpenTopic` command, so
naming a topic that does not exist brings it into being, and the page would
have written to the project by asking about it. Removing it was correct.

The cost is recorded in `domain/ask/conversation.ts` and in the server's
`Citation`: no admitted tool opens one identified topic, so nothing can emit a
topic citation, and `Citation.kind` is `Literal["source"]` rather than a union.
A genuine read-only topic reader — one that returns a topic or reports its
absence, and never opens one — is how topics become citable again, and it is a
small addition to `RepositoryTopics` rather than a redesign.

### B53. Minors deferred across the ask page's reviews

Each was found in review, reproduced, and judged not worth holding the task
for. None is a correctness bug on the happy path.

- **Task 1** — `dict(files)` is a shallow copy, so nested per-file dicts stay
  shared and a caller mutating one in place leaks through `_read_files()`.
  Worst case is a stale read, not a write.
- **Task 3** — abandonment after the executor has already failed skips the
  cancel branch and never retrieves the exception, so asyncio logs noise; and
  `suppress(CancelledError)` around `await running` can swallow a cancellation
  aimed at the consumer's own task.
- **Task 6** — purity is asserted through output values only. No test proves
  the input transcript and its turns are left unmutated by reference, though
  the implementation is immutable.
- **Task 7** — the SSE reader has no `try/finally reader.cancel()`, so an
  `onEvent` that throws leaves the body locked until GC; a 200 with an absent
  body throws `ApiError` with status 200, collapsing two distinct failures;
  frame delimiter and `data:` matching are `\n`-only, not CRLF and not
  space-less; and there is no final zero-arg `decoder.decode()` flush.
- **Task 9** — `AskThread`'s open-fold set is keyed by turn index and survives
  "New chat", so a reopened page can show a fold open on an unrelated turn;
  `reset()` is not guarded by `asking`, so "New chat" during an in-flight
  question is possible; the scroll column is unasserted and would need a
  browser test; and nothing manages focus after send.

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

### B48. Nothing notices if `infer_relations` starts emitting a new relation

`_DRAWN_RELATIONS` in `graph_reader.py` is `{CONTAINS, OVERLAPS, EQUALS}`, and
its comment calls that *complete* rather than a subset: `infer_relations`
canonicalises every dated pair to one edge, folding `AFTER` into its target's
`BEFORE` and `DURING` into its target's `CONTAINS`, so only four of
`TemporalRelation`'s six members can ever arrive. That is true of redstring
0.2.0 and it is the reason the set needs no `AFTER`/`DURING` entry.

It is also the one claim in that comment which is a *promise by another
package* rather than arithmetic this repository can check. If redstring ever
stopped canonicalising — or added a seventh relation — `_DRAWN_RELATIONS`
would silently exclude it, and the drawing would quietly lose a kind of edge
with nothing failing anywhere. Every other quantity in that comment is
verifiable here; this one is not.

Deliberately not tested, because the test would assert redstring's behaviour
rather than this adapter's, and a library's canonicalisation is not ours to
pin. The honest mitigation is to re-read it at the next redstring bump, which
is what this entry is for: the dependency pins already force that upgrade to
be a deliberate act (see `pyproject.toml`), so this is a line on the checklist
when it happens, not standing work.

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
