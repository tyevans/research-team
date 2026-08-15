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

### B54. Premise withdrawn — the three components below draw their borders

**Withdrawn on 2026-08-14, on the same evidence that withdrew [[B55]] a day
earlier.** This entry and B55 were filed independently on one premise — that a
directional width with no `border-style` leaves the side's style at the browser
default `none` and so draws nothing. B55 was retracted on 2026-08-13 by reading
the built stylesheet this repository commits: Tailwind v4 emits the style
longhand *with* the width and registers `--tw-border-style` with
`initial-value: solid`, `border-style:none` occurs zero times in the whole
sheet, and `frontend/src/styles/border-style-default.browser.test.tsx:53-71`
asserts that `border-b border-line` alone computes to `solid` / `1px`. B54 was
never updated in that commit, so it outlived its own premise by a day. **All
three call sites below draw. Nothing is owed.**

**The inverse trap is real and is not withdrawn here.** `border-solid` *without*
`border-0` is the shorthand for all four sides, so three sides get a style and
no explicit width and fall back to the UA's `medium` (~3px) — a rule meant for
one edge draws a box. That is `CLAUDE.md`'s first half, it is correct, and
`border-style-default.browser.test.tsx:73` measures it. None of the three sites
below is an instance of it.

The original entry follows unedited except for its line citations, which had
gone stale independently of the premise and are corrected in place
(`GateReview.tsx:135`→`:143`, `AutonomyAllowAll.tsx:78,95`→`:101,:118`;
`DecisionBar.tsx:44` was already right). A wrong belief that two entries were
filed on is worth keeping legible, and it is the reason this is marked rather
than deleted.

This build imports no Tailwind preflight, so an element's border style
defaults to `none` unless a utility sets it. A width alone on a side whose
style is `none` draws nothing — the inverse of the `border-0` trap recorded
in `CLAUDE.md`. Three call sites carry a directional border-width utility
with no `border-solid`, each sitting beside a padding utility (`pl-2`/`pl-3`)
that only makes sense next to a visible rule, which is the tell that a line
was intended:

- `frontend/src/presentation/session/GateReview.tsx:143` —
  `border-l-2 border-line-strong pl-2`
- `frontend/src/presentation/shell/DecisionBar.tsx:44` —
  `border-b border-k-tool`
- `frontend/src/presentation/course/AutonomyAllowAll.tsx:101` and `:118` —
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

  | Turn's position                       | Result                          |
  | ------------------------------------- | ------------------------------- |
  | not yet registered                    | `cancelled=False, settled=True` |
  | registered, not yet in the model call | `cancelled=True, settled=True`  |
  | wedged in `StubbornModel`             | `cancelled=True, settled=False` |

  Only the third is under test. Under CI load the turn was slower to _start_,
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
_diagnosability_: a hardcoded port and a 0.1s deadline each fail in a way
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

_(Original title, for anyone following a link: "`SQLiteSnapshotStore` cannot be
closed, and its thread outlives the process".)_

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
entry is the _diagnosis_ problem, not any known leak: the symptom still names
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
the holder, and a session that _should_ be the holder but lost `active_session_id`
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
  diagnostic goes vacuous. It needs _declared_ axes from somewhere -- most
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
Each is a thing that feature deliberately did _not_ build, recorded so the
reasoning does not have to be rediscovered.

### B23. Contradiction detection is a human gate, not a check

`topic.contested` tracks contradictions somebody already recorded. Nothing
_detects_ them: deciding that two sources disagree on substance is semantic, and
a model asked "does my corpus contradict itself?" as a boolean answers no
fluently.

The shape when it is picked up: a critic prompt behind a gate whose output is a
_proposed_ `TopicContested` entry -- a candidate for a human, not a verdict. The
registry already has the slot for it (`Trigger(run=None)` reports a standing
human gate rather than a silent pass), so the work is the prompt and the gate,
not the plumbing.

### B36. A stage gate is decided against evidence that is not durable or visible

**Closed for the runner path; still open, unchanged, for the tool path.**

`StageRunner` poses the gate _between_ turns, after `_save_turn` has committed.
On that path both halves of this item evaporate structurally rather than being
worked around: the artifacts and the `check-findings` report are in the store
while the reviewer decides, so `GET /api/sessions/{id}/files` answers, and
nothing about `run_turn` changed. `test_the_artifacts_are_in_the_store_when_
the_gate_is_posed` is what fails if that stops being true.

The visibility half that was genuinely worth having landed too, in the smaller
form the diagnosis implies once durability is not the problem: `gate_context`
carries `artifact_paths` -- the _list_ of files this stage produced, so a
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
change the other half: the approval is still posed _before_ the tool runs, and
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

_Visibility_ is what the gate actually needs, and it does not require touching
durability. `ApprovalRequest.context` already carries the findings inline over
SSE -- that is why the gate is not blind today. Extending `gate_context` to
carry the stage's artifact paths and contents would put the evidence in front
of the reviewer with no change to when anything is written. Bounded work, no
new invariant.

_Durability_ -- committing pending events before raising the interrupt -- is
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
  mid-turn save that _loses_ its lock has no retry story at all.
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
project sees each round land -- but a round _is_ a turn, and a turn is atomic,
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

Every position in the topic feature is one project's _corpus version_
(`corpus_position`), because a projection handler is given an event rather than
its envelope, so the global feed position is not in reach where these are
written. That is the right scale for the questions being asked -- "did anything
arrive in this corpus since I last looked" -- but it means a topic cannot be
stale with respect to anything outside its own project's corpus.

If topics ever need to notice work in _another_ project, this is the thing that
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
operator who is already sitting in a session that _holds the project_, which a
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

The reason it is recorded anyway is that a queued dispatch is a _user
intention_ rather than a running process, and losing an intention silently is
worse than losing a process. The UI does not currently say "these were
dropped" -- the chips simply stop being there on reload, which is
indistinguishable from never having pressed the button.

The fix is not a bigger buffer. It is the `TopicDispatch` aggregate
`docs/design/topic-dispatch.md` §7 rejects for now, and §7's argument for
rejecting it is the thing to re-read before building it: four events in the
permanent vocabulary, and a decision about what a `DispatchStarted` with no
terminal event means when the process died. **Do not build it until someone has
actually lost work to this.** The trigger to watch for is the first request for
dispatch _history_ -- "what have we ever asked about this topic" -- which the
log genuinely cannot answer today.

### B39. Topics already stored with an implicit subject cannot be restated

A question opened before self-containment was required reads "typical physical
traits" -- correct only against the project it was opened in. The prompt fix
stops new ones being written that way and the dispatch briefing names the
project so a _dispatched agent_ can still act on an old one, but the stored
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
That means a rewrite is _visible_ -- the digest changes under a learner -- and
nothing acts on it.

Deliberate, and the reason is that the right action is not a domain rule. A
fixed typo should not reset anyone; a reworded distractor probably should; a
question rewritten to ask something else definitely should. Only the first is
mechanically detectable, and the aggregate has no basis for the other two.

What it wants is not a rule but a _report_: an author-facing view of which
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
session is also the thing the _author_ takes turns in.

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
_first_ option; what settled it without a live turn is that `delegation.py`
already steers subagents toward investigation and away from constructive work,
and already tells the caller "give it everything it needs; it cannot see this
conversation". Deriving guidance into the delegation prompt would have argued
with both.

Part of the component block rather than a new always-on paragraph, so a stage
with no component-bearing output is still told nothing.

### ~~B29. The parse is not cached, though the cache key is exact~~ (done, differently)

Measured, as this entry asked, and the measurement found something better than
a cache. `yaml.safe_load` binds PyYAML's _pure-Python_ scanner even when the
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
the gap was _beneath_ it — there was no corpus layer under the graph.

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
contradiction is usually an _unstated conditional_ — the two experts are each
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
The adjudicator is shown only the _subject's_ `entity_type`
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

What is _not_ a barrier, and is worth knowing: `entity_type` is an unvalidated
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

### B62. A queued extraction is an intention, and a restart loses it

`ExtractionQueue` (`research_team/interfaces/web/extraction_queue.py`) is
provisional in the same way `DispatchQueue` is: queued / running / done is not
a fact the log records. Press "extract all" against forty documents, restart
the process a minute later, and thirty-nine of them are simply gone -- the
catch-up route answers with an empty queue, and nothing anywhere says work was
ever asked for.

This is worse here than it is for dispatch, and the reason is worth keeping.
`DispatchQueue`'s docstring already argues that losing a queued *intention* is
worse than losing a running *process*, because nobody chose the process.
"Extract all" is the largest single intention this UI can express -- one press
standing for an entire corpus -- and it is the one most likely to be left
running unattended, which is exactly when a restart is not noticed.

The partial mitigation that already exists: extraction is idempotent in effect
and `extracted_at` is durable, so pressing the button again after a restart
re-queues precisely what was lost and nothing else. That is why this is filed
rather than fixed -- the recovery is one press, and it is discoverable because
the rows still read as unextracted.

The fix, when it is worth it, is not a queue aggregate. It is noticing that
"which documents lack a graph" is already a durable query
(`DocumentExtractor.unextracted`), so a queue that rebuilt itself from the
corpus on start would restore the intention without inventing four events and
a decision about what an `ExtractionStarted` with no terminal event means. The
trigger is somebody actually losing a long bulk run.

### B63. The extraction queue cannot push, so a second tab goes stale

The queue deliberately publishes no frames and has no SSE pump: `ExtractionActivity`
already streams the running document's stages, and a second channel saying
"this is running" beside one already saying `extracting, chunk 3 of 40` would
be two accounts of one thing that can disagree. The client refreshes the
catch-up route when a terminal extraction frame arrives.

What that leaves: **a queue change with no extraction frame behind it is not
pushed anywhere.** Queue six documents in one tab and a second tab's rows do
not move until something else refreshes them. Enqueueing produces no frame at
all, so the staleness starts at the press and lasts until the first document
finishes.

Single-user, second-tab-only, in a local tool -- which is the whole reason it
was accepted. The fix is a frame type, a pump, a `decodeFrame` case and a
client store, and it should not be bought until somebody is genuinely running
two tabs against one project. If it is ever bought, the thing to preserve is
that the *running* item keeps exactly one account of itself: the new frames
should carry queue membership only, not progress.

### B16. Premise superseded -- one ingest reports, and the forty-document case is now a queue

This said `build_graph` takes no progress callback and `build_knowledge_tools`
takes no `ActivityReporter`, so forty documents sat behind a single opaque
`await` in a UI that streams token-level deltas for everything else.

The second clause is now simply false: `build_knowledge_tools`
(`research_team/infrastructure/agent/knowledge_tools.py:78-84`) takes
`report: ExtractionReporter | None`, `ExtractionActivity` buffers those notes
per project, and `ExtractionNote` carries `index` / `total` / `model_calls`,
so a chunked extraction reports where it has got to. Verified against the
signature on 2026-08-14, not reasoned.

The first clause was never really about `build_graph`: what "forty documents"
described was a bulk operation with no per-document account. That case now
exists for real -- "extract all" on the Documents page -- and it is answered by
`ExtractionQueue` plus its catch-up route rather than by a callback. What it
inherits instead are B62 (a restart loses the queue) and B63 (the queue cannot
push), which is where the remaining work on this actually lives.

Left as a corrected entry rather than deleted, following B55: an entry the
repository acted on for months is worth more as a record of what changed than
as an absence.

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
_selection_ survives; their work does not. It is the same effect "Reset view"
has, applied by something they did not do.

Not fixed with the streaming change because the merge that would preserve
pruning has an unanswered question in it: once consolidation has merged a
removed node into one that is still on the canvas, "this node was pruned" no
longer names anything the new graph contains. Any rule here is a guess until
somebody decides what the reader meant. Worth deciding -- the pane's whole
pruning feature exists because browsing accumulates -- but it is a design
question, not an implementation gap.

### B68. The timeline reads the tenant twice per open

`ProjectTimelineReader.timeline` makes two linear passes over the tenant: one
`TemporalQuery.timeline` for the ordered dated entities, and one
`find_entities` for the `undated_count` denominator. The second exists only
because `TemporalQuery.timeline` returns dated entities and therefore cannot
supply the count of the ones it left out.

This is the same *order* as `ProjectGraphReader.whole`, which already pages the
store on every graph open, so it is not a new class of cost. It is double a
single read, and it is paid on a tab a reader may return to repeatedly.

Deliberately uncached, and this entry is the record of that being a decision
rather than an oversight. A cache needs an invalidation; the knowledge log
already emits `graph` frames that would have to drive one; and building that
before a measurement says which of the two passes actually hurts would be
guessing at which half to fix. **Not measured against a real corpus** -- the
figure to get first is the wall time of each pass on the largest project
available, because if the `find_entities` pass is the cheap one there is
nothing here worth doing.

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
learner -- there is no way for two learners to be _distinct_ without being two
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
  store) are right for _corpus_ documents and wrong for _authored files_,
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

### B54. The 122px hole cannot be reproduced, so nothing holds the keying

`itemKey` in `frontend/src/presentation/tree/ProjectRows.tsx` records a real
incident: when the projects query answered and every row shifted down by a
heading, a project row's measured 155px stayed cached against the 33px heading
that took its index, leaving 122px of nothing in the middle of the landing list.
Identity keys fixed it, and the fix is still right.

What #49 could not do is test it. `ProjectRows.browser.test.tsx` was written for
exactly this, in a real engine because jsdom provably cannot hold a stale
measurement — it lays nothing out, so `VirtualList`'s `|| estimate` fallback
fires for every row and the cache never holds a measured height at all. Then
inverting the fix to the index keying the incident blames, and reading the gaps
between rows synchronously in the same statement as the render that inserts the
headings, gave `[0,0,0,0,0,0,0]`. No gap, at the earliest moment one could be
observed. The virtualizer re-measures through the `ResizeObserver` that
`measureElement` installs, and the correction lands first.

So the gap assertion was deleted rather than kept green against broken keying,
which would have been worse than nothing. What is left is an assertion on the
keys themselves, which holds the invariant but not the symptom.

Two candidate explanations, neither established. The library may have gained the
observer correction after the incident — in which case this is closed by writing
that down and the keying is belt-and-braces. Or the incident had a contributing
cause the harness does not reproduce, and the obvious candidate is scrolling: a
row scrolled out of the rendered window is never re-measured, so its stale entry
survives in a way an on-screen row's does not. Trying that is the next step, and
it is cheap — scroll the list before inserting the headings, then assert.

Worth doing because the alternative is a defect that shipped once, has a fix
nobody can break loudly, and a docstring that will read as folklore in a year.

### B57. Closed 2026-08-14 — all three bands measured, one shipped defect found in each

**Closed by the slice
`docs/superpowers/plans/2026-08-14-below-the-narrow-breakpoint.md`, which
measured the band the previous slice left open.** Kept as a stub rather than
deleted, because `docs/increment-c-plan.md` §8 and four reports cite this number.

Three bands, three defects, all three fixed:

- **≥1181** — the fr shares were 337/506/337 and MATERIAL's five-tab strip is
  351px wide and neither wraps nor scrolls, so the Graph tab painted past the
  pane's right edge: present and unclickable. `PROJECT_TRACKS` floors are now
  **344/342/352**, measured, replacing the session view's 280/320/280 adopted
  without measurement. 1440 is pixel-identical before and after.
- **821–1180** — the band had no layout at all: `Split` writes no inline template
  below `--bp-wide` and the only middle-band rule was scoped to
  `[data-split='session']`, so three regions resolved to one grid column and
  MATERIAL measured **148px** with no scroller. The project view now declares its
  own two-column arrangement in `responsive.css`.
- **below 821** — **the surface never scrolled, and never had.**
  `scrollHeight == clientHeight == 856` at every width from 820 down to 375: the
  split stayed pinned, so every pane shrank below its content to share one screen
  and MATERIAL got **112px**. `overflow: auto` had nothing to scroll. It is the
  same defect `layout.css` already records and fixes for `page` mode fifty lines
  above — the below-narrow half of `auto` was given the overflow and not the
  release. **Fixed with one declaration**, `flex: 0 0 auto` on `.lay-split`;
  after, the surface is 1128/856 and the panes 578/401/148.

**The candidate defect that was refuted, so nobody re-derives it.** The 60vh cap
on `.lay-pane-body` is unqualified where the `page`-mode rule excludes
`[data-scroll='regions']`, and a cap on an `overflow: hidden` box looks like a
clip with no way to reach what it cut. Measured: it does not clip. Every region
inside a `regions` body is `flex: 1 1 0%; min-height: 0` with its own scroller,
so a capped body hands the shortfall down — HOLDER's body at 362.9 under a 540
cap, both its regions scrolling 88px each, composer on screen. Adding the
`:not()` would have been a change justified by nothing.

**Fixed versus only recorded, and the difference matters.** Fixed: the three
defects above. **Recorded and deliberately not fixed** — the project view's first
horizontal clips, at **350px** (MATERIAL's `.tabs`, which needs 351) and **343px**
(QUEUE's seeding form). Both are phone widths, below the ~561 that slice treats
as worth effort on a console with one user on one machine; and `.tabs` is the
class on both `Choices` and `TabList`, so a `flex-wrap` there changes every tab
row in the console — cheap to type, not cheap to justify from one measurement in
one view. `workspace.css:130-133` is the whole change if it is ever wanted.

**And what was never swept at all: the session view below 700.** Only 821, 1000
and 700 were rendered there. Unmeasured rather than measured and fine. The
research view below 821 was written here as unmeasured too — that was [[B63]],
and its premise was wrong: there is no research view left to render. What was
actually open, and is now measured, is in that entry.

What survives this closure and is re-filed rather than dropped: [[B65]] — the
wrapped row's 46vh cap is still inherited rather than derived, and the 1/1.5/1
weights are still reasoned rather than observed.

Numbers and red proofs: `docs/reports/measured-task-a.md`,
`measured-task-b.md`, `stacked-task-a.md`, `stacked-task-b.md`.

The original entry follows, because the reason it was filed is worth keeping:
the measurement was nobody's acceptance criterion for four slices running, and
it took two dedicated slices to discharge.

`PROJECT_TRACKS` sets the QUEUE / HOLDER / MATERIAL widths, and the numbers have
never been measured against a rendered page. Increment C slice 1 chose them,
slice 2 said slice 3 was "the honest place" for the measurement because it
wanted a page with the graph on it, slice 3a said the same of 3b, and **slice 3b
built the graph and still did not do it.**

Filed here rather than deferred a fifth time. Four slices of "the next one will
measure it" is a prediction the record no longer supports, and the reason is
visible in each report: the measurement is nobody's acceptance criterion, so it
loses to whatever else the slice owes. An entry here at least makes it findable.

What it needs: the three regions rendered at each of the three responsive
layouts with real content in all of them — the graph is the widest thing the
page has and is the reason the wait was justified — and the widths chosen
against what is actually legible rather than against a guess. `npm run
test:browser` is where the assertion belongs, since a width is a measurement and
jsdom lays nothing out.

Related and equally unmeasured: **nothing on this page has been rendered below
`--bp-wide` in any of the four slices.**

### B56. Settled 2026-08-14 — the three utilities are deleted, not repaired

**Closed.** Left in place rather than deleted, against this file's "closed
entries are deleted" convention, because two pieces of tracked code cite B56 by
name — `TruncatedText.tsx:134` and `TruncatedText.browser.test.tsx:87` — and
deleting the entry would point both at nothing. This heading is where their
reasoning went.

**Measured in Chromium on 2026-08-14**, on a genuinely clipped `EntityRef` label
at 200px, with the three utilities still on the span:

```
outlineStyle  'solid'
outlineWidth  '2px'
outlineOffset '1px'     <- the utility asks for 2px
```

and with them deleted: **identical**. The offset is the tell — the width and
colour agree only because the global rule already gives what the utilities asked
for.

**Deleted rather than made to work.** The house fix for a real override is a
named class in a stylesheet (`.lay-ring-inward` is the precedent), and here that
would buy one pixel more offset on every truncated label and detail in the
console — a visual change to a shared primitive, made to honour a declaration
nobody wrote deliberately. This entry asked for that call to be made by someone
looking at it; the ring the console gives every other focus stop is the right
ring for this one. `clsx` went with them, having no other use in the file. The
argument is preserved as a comment where the utilities were, so the absence reads
as a decision rather than an omission.

The test holding the measurement **would have passed before the deletion too.**
That is the point of it — it is why the deletion is safe, not why the test is
weak — and its docstring says so.

The original entry follows.

`presentation/common/TruncatedText.tsx:127` writes
`focus-visible:outline-offset-2` (with `outline-2` and `outline-accent`). All
three utilities are in `@layer utilities` and lose to `tokens.css`'s unlayered
`:focus-visible`, so the declaration does nothing and the element draws the
global ring — see the entry `CLAUDE.md` now carries.

**Cosmetic, not a defect, and that is why it is here rather than fixed.** The
offset it asks for is *positive*, so nothing is clipped and there is no visible
symptom; the width and colour it asks for are what the global rule already
gives. What is wrong is that three utilities claim to be doing something and are
not, which is exactly the state that made the inward-ring bug invisible for a
slice.

Found by increment C slice 3b's sweep of every `focus-visible:outline-offset`
site in `src/`, and deliberately not swept up with the other three: the other
three were broken, this one is inert, and "fixing" it changes the ring from 1px
to 2px of offset on every truncated label and detail in the console — a visual
change made blind, in a shared primitive, in a slice that owns neither. Do it
when someone can look at it, and decide then whether the intent was 2px or
whether the utilities should simply go.

### B55. Premise withdrawn — a directional width alone draws, and the two remaining entries are not defects

**Withdrawn on 2026-08-13, by reading the built stylesheet this repository
commits.** This entry was filed on the second half of `CLAUDE.md`'s single-side
border rule: that a directional width with no `border-style` anywhere leaves
every side's style at the browser default `none` and so draws nothing. **That
half of the rule is wrong for this build, and `CLAUDE.md` has been corrected in
the same commit.** Tailwind v4 does not emit a bare width longhand. From
`research_team/interfaces/web/static/assets/index.css`:

```
.border-b{border-bottom-style:var(--tw-border-style);border-bottom-width:1px}
.border{border-style:var(--tw-border-style);border-width:1px}
@property --tw-border-style{syntax:"*";inherits:false;initial-value:solid}
```

The registered property's `initial-value` is `solid`, Tailwind emits a second
`--tw-border-style:solid` on `*,::before,::after` inside its Safari `@supports`
block, and **`border-style:none` occurs zero times in the whole built sheet**. So
`border-b` alone resolves to `border-bottom-style: solid; border-bottom-width:
1px` and draws. No `border-solid` is required.

The repository already contained the measurement and nobody read it:
`Drawer.tsx:162` writes `border-l border-line` with no `border-solid`, `.drawer`
gets no border rule from any stylesheet (`responsive.css:95-99` sets only
widths), and `shell-reached-dressing.browser.test.tsx:157-158` asserts
`borderLeftWidth === '1px'` **and** `borderLeftStyle === 'solid'` on that same
element. If this entry's premise held, that assertion would be red.

**So `Drawer.tsx:163` and `DecisionBar.tsx:44` are not defects and no sweep is
owed.** The `border-0 border-b border-solid border-line` form in `AskHead.tsx:27`,
`AskComposer.tsx:43` and `AskTurn.tsx:36` is correct but redundant under v4;
`border-b` alone is equivalent. Nothing needs changing either way.

**One recorded reason was wrong and is corrected here rather than quietly
dropped.** This entry, and commit `162dff5`'s message, both claimed the four
`QueueHeader` cards "have been drawing no border at all since slice 1". **They
were drawing.** The edit that commit made was a no-op in pixels, so nothing
regressed and nothing needs reverting — but the reason given for making it was
false, and the two `QueueHeader` entries struck through above were struck for a
defect that did not exist.

**The inverse rule is the real one, and it is what survives into
`check-tailwind.mjs`.** `.border-solid{--tw-border-style:solid;border-style:solid}`
is the shorthand, all four sides — so `border-solid` paired with one directional
width and *no* `border-0` leaves three sides styled with no explicit width,
falling back to the UA's `medium` (~3px), and a rule meant for one edge draws a
box. That is `CLAUDE.md`'s *first* half, it is correct, and it is the one this
repository has actually drawn. A sweep of every string literal in
`frontend/src/**/*.{ts,tsx}` with comments stripped finds **zero live
instances**, so a check for it is a ratchet rather than a fix.

**And it cannot be an emission check, which this entry also got wrong.**
`findSilentUtilities` (`check-tailwind.mjs:143-156`) asks one question — does a
selector for this class name appear in the built `index.css`? `border-b` **does**
emit a rule, so the check as built would never have caught any instance here,
including under this entry's own premise. The defect described was a *missing
companion class*, not a missing rule. What is cheap is a **co-occurrence pass**
over the token set `check-tailwind.mjs:93-113` already builds (every string
literal, comments stripped, line numbers preserved) — about fifteen lines, and it
could also catch two hazards nothing enforces today: two utilities setting the
same property in one class string (the coin-toss `primitives.tsx:44-48`
documents), and a variant prefix that is not a declared breakpoint or known state
(`theme.css:49-54` declares no `--breakpoint-*`, so every `sm:`/`md:`/`lg:`
compiles to nothing — zero uses in `presentation/` today, so latent, one
`md:flex` away from live).

**What is still owed, and it is the honest gap.** `CLAUDE.md` says the border
defect was "caught by eye in Storybook, twice, in both directions", and only one
direction is explained by the current build. The other observation has not been
re-taken. `frontend/src/styles/border-style-default.browser.test.tsx` is written
to settle it and **has not been run** — a benchmark held the machine. If it
fails, the reading above is wrong and this entry should be reinstated.

### B58. The roster's run worker carries no rounds and no start time, so the picker chip says less than it used to

`research_team/application/workers.py:296-303` builds the roster's `run` worker
with `detail="autonomous run"` and `started_at=None`. Neither is wrong for the
agent dock, which lists what is working; both are why increment C slice 4's
landing-page chip draws `run running` where it used to draw `run · round N`,
and appends no `· elapsed` either. The rounds and the start time exist — the
project page reads them from the run's own aggregate — they simply do not reach
`Worker`.

**This is a backend change, and that is the whole reason it is here rather
than done.** Increment C's §4 is titled "the one backend change"; taking this
spends that title on buying a number back. Slice 4's §2 weighed it and answered
(a) — accept the degradation — deliberately, before any code was written, so
that nobody later reads the chip as a bug that slipped through. The plan asked
for the entry rather than a silent drop.

What a reader loses in the meantime: the round count, which is still one click
away on the project page, and an elapsed time the chip never promised anywhere
else. What they keep is the chip's actual job — "something is happening here" —
unchanged, and now sourced from one request instead of `2N`.

**Not simply "add a `rounds` field".** `Worker.detail` documents itself as
already composed, precisely so two front ends cannot disagree about how to say
the same thing, so the honest shape is to compose `round N` into `detail` where
the roster is folded and to pass the run's real start time through as
`started_at`. A `rounds` integer beside a composed `detail` would give the
front end a second way to say it, which is the arrangement that docstring
exists to prevent.

### B59. A running turn is invisible to every roster a frame refreshes, and there are now three of them

`run_turn`'s contract (`application/session_service.py:859`) is that all events
of a turn "append atomically at the end, or not at all". So a turn emits **no
feed entry for its entire duration**, and the browser's `log` frame is a session
event (`sse/event-stream.ts:222-236`) — there are none until the turn commits.

A `turn` worker is in the roster for exactly that interval:
`turn_supervisor.py:140-142` records it at task creation and the `finally` at
`:157-159` removes it. The two intervals are complementary, so anything that
re-reads the roster only on frames sees it **only at moments when the turn is
already gone**. The worker is not late; it is never visible.

Extraction has the same hole by a different route: `Extraction` frames "carry no
feed position" and are routed to `kind: 'extraction'`
(`event-stream.ts:167-174`), never `log`, and `remember` runs *inside* a turn —
so an extraction lasting minutes produces no `log` frame either.

**Three consumers, two of them affected.**

| Consumer | Refresh | State |
|---|---|---|
| `useRunningAgents` (the dock, every route) | `log`/`dispatch` frames, no poll | understates turn and extraction liveness |
| `useProjectActivity` (the picker chip) | `useTreeRefresh`, `log` frames only | same blindness — **pre-existing, not introduced by slice 4** |
| `Workers.tsx` (the course/queue roster) | 2000ms poll | correct, and this is why the poll survived slice 4 |

Slice 4 re-sourced the picker chip from the per-project roster to the global
one. Both keys sit under the `allWorkers()` prefix `App.tsx:173` invalidates on
a `log` frame, so the refresh path is byte-identical before and after: **the
swap is neutral on freshness and this entry is not a regression it caused.** It
is recorded here because the swap gave the defect a third consumer's worth of
visibility and nobody had written it down.

**The fix is not a wider frame filter on the client.** There is no frame to
filter for — the information does not leave the server. It is a frame emitted
when the roster changes (turn begin/end, extraction begin/end), which is backend
work. That is the same budget [[B58]] wants and the same one increment C's §4
titles "the one backend change", so whoever takes either should look at both: a
roster-changed frame would make `Workers.tsx`'s poll deletable as well, which is
the third thing this buys.

Until then the honest summary is that a turn shows up in the roster **only where
something polls**, and the two places a reader is most likely to be looking are
the two that do not.

### B60. Closed 2026-08-14 — the combined rule is ported, red-proved at 966px

**Fixed.** `responsive.css` now carries, after the two single-collapse rules so
it wins on source order exactly as the project block does:

```css
.lay-split[data-split='session']:has([data-pane='timeline'].is-collapsed):has(
    [data-pane='workspace'].is-collapsed
  ) {
  grid-template-columns: var(--rail-w) var(--rail-w);
}
```

**Proved red against the block as it shipped**, at 1000x900, before the CSS was
touched:

```
× rails both session flanks when both are folded
  → AssertionError: expected 966 to be close to 34, received difference is 932,
    but expected 0.5
```

**966px where a rail is 34**, under a rotated title — measured in the session
view rather than carried over from the project view's identical number, which is
the same 1000 − 34 arithmetic and not a coincidence. The claim asserts the two
rectangles rather than the template string (reading the template back would agree
with whichever rule won) and re-reads the first pane *after* the second fold,
since the defect is the second collapse undoing the first pane's track.

The paragraph below about whoever merges the two blocks "owing the session view
this rule" is now false and the project block's comment has been rewritten:
**the two blocks differ only in their floors** — 344/320 against 280/300.

`docs/reports/stacked-task-b.md` §1. Kept as a stub rather than deleted because
`docs/increment-c-plan.md` §8 cites it. The original entry follows.

`responsive.css:40-45`. In the 821–1180px band the session split declares its own
arrangement, and two of its rules —
`:has([data-pane='timeline'].is-collapsed)` and the `workspace` equivalent — have
**identical specificity and each write the whole `grid-template-columns`**. So
when both match, the later one wins outright: the earlier pane keeps a full-width
track while `Pane.tsx:126` still draws it in its rail form, rotated title and
all. A 34px affordance stretched across two thirds of the viewport.

**It is reachable in two clicks.** `toggleCollapsed` (`split-tracks.ts:98`)
refuses only when *every* pane would close, so with three tracks the second fold
is allowed.

**Pre-existing — not introduced by the 2026-08-14 slice.** That slice hit the
identical bug in the new `[data-split='project']` block, fixed it there with a
combined `:has(...):has(...)` rule placed after the two single rules so it wins
on source order, and **deliberately did not touch the session one**, because
editing it would have meant changing the session view inside a slice that owned
only the project view. The fix is written out one block away and its red proof is
in `docs/reports/measured-task-a.md` (fix round 1) — a folded QUEUE measured
966px where a rail is 34.

**The reason this is worth a number rather than a comment:** the two blocks in
`responsive.css` now look like duplication and are not. They carry a real
difference, and whoever merges them into one primitive owes the session view this
rule. A merge done on the assumption that the blocks are the same shape would
silently keep the bug.

### B61. The graph canvas keeps its old width for a few frames after a resize

**An observation, filed rather than fixed, and deliberately not called a
defect.** `GraphCanvas` sizes its `<canvas>` from a `ResizeObserver`, and an
observer fires *after* the layout it observed. Measured on 2026-08-14:
immediately after narrowing to 1181, the graph container's border box is already
352 while the canvas inside it is still the **411** it was handed at 1440 — seven
boxes reporting `411 in 352`, all of them the canvas or an ancestor. It settles
within a few frames. What a reader sees is a stale canvas for a frame or two
while dragging a window edge, which is what every observer-sized canvas does.

**The part worth having written down is what it does to tests.** It is why
`project-tracks.browser.test.tsx`'s overflow claim **polls** rather than reading
once. A single read immediately after a viewport change fails there **against
correct code** — which is precisely the failure `CLAUDE.md` warns ends up filed
as flakiness, and it would fail in a direction load cannot explain. Anyone
measuring this page after a resize needs `expect.poll`, not a bare read.

**The shared resize helper does not discharge this, and the pointer is
re-aimed rather than removed** ([[B64]], closed 2026-08-14).
`src/test/browser-viewport.ts` waits for React and for the browser's own
re-layout of the split — which is *exactly* the moment a `ResizeObserver` has
not yet run, because an observer fires after the layout it observed. So
`resizeViewport` returning is not permission to read inside the graph. The
helper's docstring says so, and `project-tracks`' claim 1 keeps its own
`expect.poll` on top of it; anyone deleting that poll as redundant would be
reintroducing this.

If it is ever picked up as a defect rather than an observation, the fix is on the
observer side (size from the container's own measurement synchronously on the
frame the layout changes), not on the test side.

### B62. Which width wins on the drawer below 820 — CLOSED, measured 2026-08-14

**A question, not a defect, and the distinction is the entry.** `Drawer.tsx:164`
sets the panel's width three ways in Tailwind utilities — `w-[42vw]
max-w-[640px] min-w-[360px]` — while `responsive.css:217-221` sets
`.drawer { width: 100%; max-width: none; min-width: 0 }` below 820px. Both
selectors are 0-1-0. Nobody has watched the result at a narrow width.

The two outcomes, and they are opposite:

- **The stylesheet wins.** The drawer is full width below 820, which is what
  the rule was written for and what `Drawer.tsx:155-163`'s comment claims.
- **Tailwind wins.** `w-[42vw]` and `min-w-[360px]` survive, and the drawer is a
  360px strip pinned to the right of an 819px viewport — a *narrower* panel on a
  narrower screen, the exact inverse of the rule's intent, on the one screen
  size it was written to serve.

**One correction to make before anyone measures: source order is not what
decides this.** The obvious reading — `index.css:24` imports `responsive.css`,
so whichever comes later wins — is the wrong mechanism. `theme.css:85` imports
Tailwind's utilities as `layer(utilities)`, and `responsive.css` contains no
`@layer` at all, so the comparison is unlayered-versus-layered, and **an
unlayered normal declaration beats a layered one regardless of specificity or
order** (the rule `CLAUDE.md` records under the inward focus ring, and
`theme.css:78-79` states in the same words). On that reading the stylesheet wins
and the drawer is correct. It is still reasoning, not a measurement, and this
project has shipped a defect off exactly that substitution once.

**jsdom cannot answer it.** `getComputedStyle` there returns only what an inline
style said, so a jsdom assertion that the drawer is full width would pass
whichever rule is actually in force. It needs `npm run test:browser` — open a
drawer at 800×900 and read `getBoundingClientRect().width` against the
viewport — or an eye on a real page.

---

**Measured in Chromium on 2026-08-14, and the prediction held.** The document
reader opened on the project page at 800x900:

```
drawer left 0, right 800, width 800        (viewport 800)
computed  width 800px, max-width none, min-width 0px
```

The stylesheet wins. The drawer is full width below 820 and
`Drawer.tsx:155-163`'s comment is correct as written.

**The losing outcome is not hypothetical, and that is why this closes with a
test rather than with a sentence.** Rename `.drawer` to anything else in
`responsive.css`'s below-820 block and the same probe reports

```
AssertionError: expected 360 to be 800
```

— `min-w-[360px]` beating `w-[42vw]`'s 336, a 360px strip pinned to the right of
an 800px screen. B62's second outcome, reproduced on demand. So the correct
behaviour rests entirely on one unlayered rule keeping its selector, and nothing
above the stylesheet says so.

**What is left behind:** `project-narrow-research.browser.test.tsx` claim 1,
which asserts the box *and* the three computed longhands — moving `.drawer`
into a `@layer`, deleting it, or adding a `!` to the utilities each turns one
line red with the real number. It would pass against unfixed code, because there
was nothing to fix; it is a regression guard, not a proof, and its docstring
says so.

**One thing this did not measure**, said rather than left implied: the boundary
itself. 800 is inside the media query, not on its edge, so `max-width: 820px`
being the right number for this rule is still unmeasured — a different question
from which rule wins inside it.

### B63. Research content below 821 — CLOSED, on a corrected premise, 2026-08-14

**This entry was filed on a fact that was not true, and the correction is kept
rather than the entry deleted, because a wrong premise that got corrected tells
the next reader more than a missing entry does.**

**What it said.** That the 2026-08-14 narrow-band slice fixed the below-821
surface with one declaration on the shared primitive — `flex: 0 0 auto` on
`.lay-split`, inside `layout.css`'s `@media not all and (min-width: 821px)`
block — that this therefore reaches **three** views mounting a `Split`, and that
two of the three were measured:

- **Project** — `project-stacked.browser.test.tsx`. Surface 856/856 before,
  1128/856 after.
- **Session** — `session-responsive.browser.test.tsx` claim 3 at 700x900. Same
  defect, red-proved by removing the declaration
  (`expected 856 to be greater than 856`); after, surface 1063/856, panes
  126/215/683.

**— and that the research view was the unmeasured third.**

**The correction.** There is no third view. Grepped on 2026-08-14 and verified
again while closing this: `<Split` appears in exactly **two** view files,
`ProjectView.tsx:277` and `SessionView.tsx:122`. Every other match is the
primitive's own definition, a story, or a unit test. The route merge folded
research into the project view's MATERIAL pane, where it is two tabs — `doc`
(`DocumentList`) and `entity` (`GraphPane`) — inside the split
`project-stacked` already measures. The entry outlived the change that made it
false, which is the ordinary way this happens: it was written against a
repository that had a research view, and the merge did not come back for it.

**What was genuinely open, once the premise was fixed**, and it is narrower than
what the entry claimed but not nothing. `project-stacked` measures this band
with `selection={null}`, which leaves MATERIAL on the `artifact` tab — a plain
`overflow-auto` panel. The `doc` tab is not that: `DocumentList` renders a
**virtualizer**, which owns a scroll container of its own, and
`ProjectView.tsx:499` deliberately gives that panel no `overflow-auto` for
exactly that reason. An inner scroller that swallows the height it is offered is
the same shape as the defect the below-821 rule was written for, one level
further in — and nothing had looked.

**Measured at 700x900 on 2026-08-14: it does not happen.** With the corpus in
MATERIAL, surface **1558/856**, split 1558.36, panes **578.5 / 401.4 / 578.5**,
all full width in one column, nothing clipping.

**The number that moved, and why it is not a discrepancy.** The sibling records
1128/856 with panes 578.5 / 401.4 / **148.0**. QUEUE and HOLDER are identical to
the pixel; MATERIAL is 578.5 instead of 148, because the corpus takes its
content's height where the empty artifact list took its head's, and that 430px
*is* the whole 1558-vs-1128 gap. The behaviour is the same; the number is the
fixture's. A claim asserting 1128 here would have been asserting the sibling's
fixture rather than this one's.

**What is left behind:** `project-narrow-research.browser.test.tsx` claim 2,
proved red under the same `layout.css` mutation the sibling records, with a
byte-identical failure (`expected 856 to be greater than 856`) — which is the
point of keeping it beside a file that looks like its duplicate: it pins that
research content is not a separate surface with a separate answer.

**Still open, and deliberately not folded in here** — the `entity` tab. The
graph is the other half of what "research content" means, it is `React.lazy`
over a canvas, and `GraphCanvas` sizes from a `ResizeObserver` that fires after
the layout it observed ([[B61]]). That makes it a slower and differently-shaped
measurement than the corpus, and it belongs to whoever picks up B61 rather than
being smuggled into this closure.

### B64. Three resize helpers, three versions of one bug — DONE 2026-08-14

**The finding is the repetition, not any one instance.** Every browser test file
that changes viewport width has written its own resize helper, and each has
independently shipped a variant of one defect: **the helper's readiness condition
is already satisfied at the width it starts from, so it resolves on the first
tick and the probe measures the old layout.**

Three instances, all on record:

1. `project-responsive.browser.test.tsx:158`'s `widen()` polls
   `split().style.gridTemplateColumns === ''`. That is already true at 1000px, so
   a 1000 → 700 resize resolves **without waiting for `matchMedia` to flip, for
   `stacked` to become true, or for React to commit**. It works only crossing
   `--bp-wide`, and only because the `afterEach` leaves the viewport at 1440.
2. Task B's first helper polled `data-collapse-to === 'rail'` — which is what the
   attribute says at 1440, the width every test starts from. A 1440 → 821 resize
   satisfied it instantly and the probe read the **1440** layout: a
   `280px 320px 280px` template, `Split`'s inline three-track style still on the
   element, and a conversation **880px wide inside an 821px viewport**. The
   documented trap was `widen()` crossing *down* past 1181; this is the same trap
   from the other side, because `'rail'` is the value on both sides of 1181.
3. Task A wrote a third helper to avoid both, per the plan's §2 warning.

So the plan for that slice had to spend two paragraphs warning about helper (1),
and helper (2) reinvented the bug anyway a task later. **A warning in a plan does
not survive into the next file; a shared helper would.**

**What it wants:** one resize helper, in a shared browser-test module, that polls
a React-written attribute **and** the resolved geometry (either alone is
insufficient — the attribute can be stale-correct, the geometry waits on the
browser rather than on React), with the failed readings above in its docstring as
the reason it does both. It should be red-proved the way any other claim here is:
mutate it back to a single poll and watch a probe read the wrong viewport.

**Cheap to state, not cheap to do**, which is why it is filed rather than done.
The three files' fixtures differ (two wrap the view in a bare flex column, the
two new ones mount a real `Shell` — see [[B63]]), so unifying the helper means
deciding whether the fixture unifies too, and that is a bigger change than any
one of them wanted. One extra constraint any shared version inherits:
`check-deleted.mjs` forbids the identifier `gridTemplateColumns` anywhere under
the session view, so the poll has to read
`getComputedStyle(...).getPropertyValue('grid-template-columns')`. Task B hit
that and spelled around it rather than loosening the rule; a shared helper should
be written that way from the start.

---

**Done.** `frontend/src/test/browser-viewport.ts` — `resizeViewport`,
`restoreViewport`, `DEFAULT_VIEWPORT`. All four local helpers are deleted and
all five callers migrated; `grep -rn 'page.viewport' frontend/src` returns the
module and two prose mentions. **No file keeps a private resize helper.** No
assertion was edited and no number moved: `Test Files 25 passed / Tests 82
passed`. The `check-deleted.mjs` rule was not loosened — the module reads
`getPropertyValue('grid-template-columns')` throughout.

**Four polls, and what each is decisive for.** Two React-written signals
(`Split`'s inline template, present iff `width >= 1181`; `data-collapse-to`,
`'strip'` iff `width < 821`), each *constant across the other's boundary* —
which is precisely the hole in failed readings 1 and 2. Then the split's own box
width, the only signal that moves for a resize **inside** a band. Then the
resolved tracks fitting `clientWidth`, which is what refuses a stale template on
a correctly-sized box.

**Red-proved, with numbers.** A probe resized 1440 → 821 and polled a single
signal at `{ interval: 1 }`. Attribute-only and geometry-only both returned with
the page reading `grid-template-columns: 344px 342px 352px` — three tracks
summing 1038 — and a MATERIAL pane **1038px wide inside an 821px viewport**.
Failed reading 2, reproduced. The full poll set returns at `344px 476.984px`,
MATERIAL 821.

**The honest caveat, because it changes what this was worth.** The stale window
is **one animation frame**. Run without `{ interval: 1 }`, both single-poll
mutants read the correct numbers every time — `expect.poll`'s 50ms default lands
after the frame. So a single poll is not *reliably* wrong today; it is
unguarded, and what stands between it and the 1038 reading is scheduling. Both
recorded historical failures were found by a person noticing a number, not by a
test going red, which is what an unguarded window looks like from outside. A
reader who tries to reproduce this and cannot should not conclude the helper is
pointless.

**What it cost, paid deliberately.** Poll 4 is the one poll a *broken*
stylesheet can make permanently unsatisfiable rather than merely slow: an
overflowing template never fits, so the helper times out and the caller's own
assertion never runs. Measured — `session-responsive` claim 2's recorded
`minmax(600px, 1fr)` mutation, whose proof used to read
`expected 300 to be greater than or equal to 320`, became
`expected 'pending' not to be 'pending'`. The claim still failed; the diagnosis
did not survive. Fixed by making the give-up value carry the measurement:

```
Received: "at 821px the tracks overflow the split: "600px 300px" = 900px in a clientWidth of 821px"
```

Poll 4 was kept — refusing failed reading 2 is its whole job — and the timeout
itself is still there. A file whose stylesheet overflows waits it out and fails
at the helper rather than at its own line. Only the message improved.

**The fixture question the entry called "not cheap" was measured, not
performed**, and is [[B67]].

**What this does not discharge:** [[B61]]. `resizeViewport` returns exactly when
a `ResizeObserver` has not yet run, so anything measuring inside the graph still
needs its own `expect.poll`.

### B65. What survives B57: the 46vh cap is inherited, and the weights are reasoned

**Re-filed from [[B57]] rather than dropped when it closed.** B57's headline —
the three responsive bands are unmeasured — is discharged; these two are the
residue, and they are small enough that they would have been lost inside a closed
entry.

- **The 46vh cap on the wrapped MATERIAL row is inherited from the session view's
  rule, not derived.** Nobody chose 46. The assertion guarding it is vacuous
  against a fixture whose MATERIAL is empty, and its own comment says so.
- **The `1 / 1.5 / 1` weights remain reasoned rather than observed.** The floors
  now say where a region *breaks* — they were measured, and finding them found a
  shipped defect. They say nothing about where a region is *good*, and no test
  written so far can tell the difference. A smaller gap than the one it replaced,
  and still a gap.

Neither is a defect. Both are numbers with no measurement behind them in a file
where the neighbouring numbers now have one, which is exactly the asymmetry that
makes the next reader trust them more than they have earned.

### B66. `.node-actions` looks dead, on a grep and nothing else

**Suspected dead, not confirmed dead, and the entry exists for that distinction.**

`tree.css:103-112` — five declarations, `display: flex`, `align-items`, `gap`,
`flex-wrap` and a `margin-top`. Grepped across every `.tsx`, `.ts`, `.css`,
`.mjs`, `.js`, `.html`, `.json` and `.md` under `frontend/` on 2026-08-14:
nothing carries the class. The only hits are **`node-actions-gap`**
(`ProjectList.tsx:354`, `ProjectCard.stories.tsx:173`), which is a distinct
single token with its own live rule immediately below it — it is not
`.node-actions` with a modifier, and the two rules are unrelated.

**Why this is filed rather than deleted, which is the whole point.** The
`.view-head` family in the same file was deleted in the same sitting, and the
deletions are not the same claim:

- `.view-head` rested on a **recorded cause**. `QueueHeader.tsx:84` names the
  commit that removed its last inbound link, and the stylesheet's own comment
  said it dressed "the head shared by the course and research views, which is
  all that still uses it" — and both those views are gone. The grep confirmed a
  story the repository already told.
- `.node-actions` rests on **the grep alone**. Nothing anywhere records it being
  orphaned, and its comment describes a live purpose (row buttons that were "raw
  inline-block elements with no gap and no wrap behaviour" before it).

**A deletion justified by "I could not find a reference" is a weaker claim than
one justified by a record of the reference being removed**, and this repository
has a rule shaped like exactly that difference. A grep is a search of the
spellings you thought of; a recorded cause is evidence.

**What upgrades this to a deletion:** find the commit that orphaned it —
`git log -S 'node-actions'` over the deleted views is the obvious place — or a
reviewer's second look confirming the grep. Either turns it into the same kind of
claim `.view-head` had. It is five declarations in one file; the work is the
justification, not the edit.

**And a note on what will not catch this, because it explains why `.view-head`
lasted as long as it did.** `scripts/check-deleted.mjs` guards two things and
neither reaches here. Its 35 `RULES` forbid named patterns from *coming back*,
and none names this class. Its `STYLESHEETS` list freezes **the set of files, not
their contents** — its own docstring says so and calls the hole out explicitly —
so `tree.css` surviving means every rule that dies inside it is invisible to the
check. **Rot inside a living file is a class of decay no gate here sees.** That
is a description of the guard's coverage, not a request to change it: the
existing rules forbid names specific enough that a re-add is always the mistake,
and a rule anchored on a name this generic would make a legitimate future use a
build failure.

### B67. Two browser files measure a fixture's accident, and one number says so

**Filed off a measurement rather than a suspicion**, taken while closing
[[B64]] on 2026-08-14. Two of the five browser files that resize —
`project-responsive` and `project-tracks` — wrap `ProjectView` in a **bare 900px
flex column**. The other three mount a real `Shell` inside `height: 100vh`. The
plan for that slice ruled the `Shell` fixture correct and the bare column not,
but also ruled that **migrating a fixture changes what a test measures**, so the
migration was measured and deliberately not performed.

**What the measurement found: every *width* is byte-identical between the two
fixtures**, at 1440, 1181, 1180, 1000 and 821, in both collapse states.

| width | tracks | queue | holder | material |
| --- | --- | --- | --- | --- |
| 1440 | `411.422px 617.141px 411.422px` | 411.42 | 617.14 | 411.42 |
| 1181 | `344px 485px 352px` | 344 | 485 | 352 |
| 1180 | `491.656px 688.344px` | 491.66 | 688.34 | 1180 |
| 1000 | `416.656px 583.344px` | 416.66 | 583.34 | 1000 |
| 821 | `344px 476.984px` | 344 | 476.98 | 820.98 |

`tabs.scrollWidth` inside MATERIAL matches too. **Only heights and tops move,
and by exactly the chrome's 44px** — pane `top` 0 against 44, pane height 900
against 856 above 1180 and 750.97 against 706.97 below it.

**So `project-tracks` migrates for free**: every claim in it is a width or a
`scrollWidth`.

**`project-responsive` does not, and this is the entry.** Its claim 2 computes

```ts
const topRow = 900 - 0.46 * 900   // 486
expect(box('queue').height).toBeGreaterThanOrEqual(topRow)
```

That `900` is the **viewport** height standing in for the **pane column's**
height, and the two are equal only because the bare wrapper is itself 900px
tall. Under a `Shell` the column is 856, so the honest floor is
`856 - 0.46 * 856 = 462.24`. The measured height is 706.97, which clears both —
**so migrating the fixture without rederiving that constant leaves a floor 44px
too high, passing for the wrong reason, with nothing failing.** That is the
plan's "a number that moves is a finding, not an edit", except that this number
does not move: it goes on being asserted while its derivation stops being true.

(MATERIAL's cap is `46vh`, which is the viewport either way, so `0.46 * 900` is
correct *there* and would stay correct. The two uses of the same arithmetic
differ, which is most of why this is easy to get wrong.)

Claims 1, 3, 5 and 6 of that file assert relative geometry or widths only and
are unaffected.

**The follow-up, whole:** move `project-responsive` and `project-tracks` onto
the `Shell`/`100vh` fixture, rederive claim 2's `topRow` from the split's own
height rather than from a literal 900, and re-prove claim 2 red. Small, and
worth doing before anyone reads 486 as a measured floor.

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

`open_topic` was in the read-only tool set until review found that it _creates_
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

_(Entries below are kept for the reasoning; the asks themselves are closed.)_

### B48. Nothing notices if `infer_relations` starts emitting a new relation

`_DRAWN_RELATIONS` in `graph_reader.py` is `{CONTAINS, OVERLAPS, EQUALS}`, and
its comment calls that _complete_ rather than a subset: `infer_relations`
canonicalises every dated pair to one edge, folding `AFTER` into its target's
`BEFORE` and `DURING` into its target's `CONTAINS`, so only four of
`TemporalRelation`'s six members can ever arrive. That is true of redstring
0.2.0 and it is the reason the set needs no `AFTER`/`DURING` entry.

It is also the one claim in that comment which is a _promise by another
package_ rather than arithmetic this repository can check. If redstring ever
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

- **R3** — `redstring.projections.project` folds the _global_ feed with no
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

R1 closing means vector search is now _possible_, not present: there is still
no `AGENT_VECTOR_STORE` and no recall path. That is a feature to spec, not a
workaround to delete, and it does not belong in this section.
