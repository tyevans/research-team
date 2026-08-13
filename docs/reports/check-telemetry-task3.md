# Check telemetry, Task 3: emitting at both gates

Plan: `docs/superpowers/plans/2026-08-12-check-telemetry.md`, Task 3.
Spec: `docs/superpowers/specs/2026-08-12-check-telemetry-design.md`, "Where the
events are emitted".

## What changed

`research_team/application/session_service.py`

- `record_stage_review(session_id, review_id, project_id, stage, preset,
  preset_version, evaluated, unimplemented, posed_by)`, mirroring
  `record_tool_decision` and appending immediately for the same reason plus one
  of its own: the decision that answers the review is appended separately, and
  the gap between the two `occurred_at` values is the only measurement of how
  long a reviewer took.
- It takes `EvaluatedCheck`s and flattens them to the event's dicts here, so
  the payload shape is decided in one place. `domain` cannot name
  `EvaluatedCheck`, which is why the event carries dicts at all.
- `record_tool_decision` gained `review_id: UUID | None = None`, forwarded into
  `RecordToolDecision`.
- New import `from research_team.application.stage_exit import EvaluatedCheck`.
  No cycle: `stage_exit` imports only `artifacts`, `checks`, `coverage`,
  `findings` and `domain.workflow`.

`research_team/application/stage_runner.py`

- `_gate_and_advance` gained a leading `project_id: UUID` parameter; `_work`,
  its only caller, already had it in scope. See the deviation below.
- `review_id = uuid4()` and a `record_stage_review` call immediately after the
  findings-file write, with a comment saying why it is here and not in
  `review_stage` (`course_progress` reviews a stage on every course view) and
  why it is above the `deny` branch (a check that fired at a gate nobody was
  allowed to open still ran).
- Both `record_tool_decision` calls -- the `deny` branch and the main one --
  now pass `review_id=review_id`.

`research_team/application/ports.py`

- `GateReview.review_id: UUID | None = None`, with the docstring the plan
  specifies.

`research_team/composition.py`

- `gate_review` binds `project_id` off `running_workflow` instead of discarding
  it as `_`, executes `RecordStageReview` beside the existing `WriteFile` with
  `posed_by="tool"`, and returns the `review_id` on the `GateReview`.
- New imports: `uuid4`, and `RecordStageReview` from `domain.commands`.

`research_team/infrastructure/agent/deep_agent.py`

- `_decide` binds `review_id = gate.review_id if gate is not None else None`
  immediately after `_review_gate`, and passes it into the harness-refusal
  `RecordToolDecision`, the `ApprovalRefused` one, and through to `_apply`.
  The two decisions recorded *before* `_review_gate` runs (the `deny` /
  no-approvals-port branch) get no `review_id`, deliberately: no review ran.
- `_apply` gained `review_id: UUID | None = None` and passes it into both of
  its `RecordToolDecision`s. Its docstring says why the id is a parameter
  rather than obtained by re-running the reviewer -- a second `_review_gate`
  call would emit a second `StageChecksEvaluated` that nobody was asked about
  and halve every fire rate. New `from uuid import UUID`.

`tests/application/test_stage_runner.py` -- six new tests under a
`# --- check telemetry ---` section, plus two helpers (`_checked_project`,
`_reviews`, `_gate_decisions`) and a one-word widening of the existing
`_preset` helper (`preset_id: str = "test.runner"`, default unchanged).

`tests/integration/test_advance_stage_gate.py` -- one new test covering the
tool path end to end, through a scripted model, a real interrupt and a real
`ApprovalPort`.

## The two things the plan left open

**1. `StageWorkflow` has no `project_id`, and it should not grow one.** The
plan says to add a read-only property to the port and its adapter "rather than
threading a new parameter through `_gate_and_advance`", on the grounds that
"the runner already holds the workflow and the id is a property of it". The
premise is wrong in a way that changes the answer: the runner holds the
*project id* too. `_work(project_id, session_id, workflow, ...)` is
`_gate_and_advance`'s only caller and already has it, so "threading through" is
one argument at one call site.

The property is the more expensive option. `StageWorkflow` is a `Protocol`
restated in `application/` precisely so `application` need not import
`infrastructure`, and it is satisfied structurally by `ProjectWorkflow` and by
whatever `workflow_tools.py` declares. A new member widens the shape every
implementer and every test double must satisfy, in order to re-supply a value
the caller is already holding. The alternative reading -- calling
`await workflow.project_state()` -- adds an aggregate load per gate for a field
already in a local variable.

I took the parameter. Flagged here rather than substituted silently.

**2. `_apply` can receive the `review_id` as a parameter, and does.** `_apply`
is called from exactly one place, `_decide`'s last line, where `gate` is in
scope. No reviewer is re-run and no second review event is emitted; the
tool-path test below asserts exactly one `StageChecksEvaluated` per turn, which
is what fails if anyone changes that.

## Red, then green

Red was produced by copying the five implementation files aside, running
`git checkout --` on them, running the tests, and copying them back. The tests
themselves were never reverted.

### The five runner tests, before the change

```
$ uv run pytest tests/application/test_stage_runner.py -k "checks_were_asked or names_the_review or rejected_gate_still or nobody_was_asked or denied_gate_records" -v
E       ValueError: not enough values to unpack (expected 1, got 0)
E       ValueError: not enough values to unpack (expected 1, got 0)
E       ValueError: not enough values to unpack (expected 1, got 0)
E       ValueError: not enough values to unpack (expected 1, got 0)
E       ValueError: not enough values to unpack (expected 1, got 0)
=========================== short test summary info ============================
FAILED tests/application/test_stage_runner.py::test_the_gate_records_what_the_checks_were_asked
FAILED tests/application/test_stage_runner.py::test_the_decision_names_the_review_it_answered
FAILED tests/application/test_stage_runner.py::test_a_rejected_gate_still_records_both
FAILED tests/application/test_stage_runner.py::test_a_gate_nobody_was_asked_to_open_is_recorded_as_policy
FAILED tests/application/test_stage_runner.py::test_a_denied_gate_records_the_review_it_refused
======================= 5 failed, 31 deselected in 2.99s =======================
```

The unpack is `[review] = await _reviews(...)` against an empty history, which
is the plan's predicted "no `StageChecksEvaluated` in the history".

### The course-view test, before the change

Its own guard fires first, which is the point of having one:

```
        before = await _reviews(service, session_id)
>       assert before, "the gate recorded nothing, so this would prove nothing about a view"
E       AssertionError: the gate recorded nothing, so this would prove nothing about a view
E       assert []

tests/application/test_stage_runner.py:1175: AssertionError
```

### The tool-path test, before the change

```
$ uv run pytest tests/integration/test_advance_stage_gate.py -k tool_path_records -v
        history = await application.service.history(session_id)
>       [review] = [event for event in history if isinstance(event, StageChecksEvaluated)]
        ^^^^^^^^
E       ValueError: not enough values to unpack (expected 1, got 0)

tests/integration/test_advance_stage_gate.py:437: ValueError
=========================== short test summary info ============================
FAILED tests/integration/test_advance_stage_gate.py::test_the_tool_path_records_the_review_and_the_decision_that_answered_it
======================= 1 failed, 15 deselected in 1.46s =======================
```

### Green

```
$ uv run pytest tests/application/test_stage_runner.py -q
.....................................                                    [100%]
37 passed in 12.57s

$ uv run pytest tests/integration/test_advance_stage_gate.py tests/application/test_course.py tests/infrastructure/test_deep_agent.py tests/infrastructure/test_advance_ends_turn.py -q
..............................................................           [100%]
62 passed in 8.22s

$ uv run pytest tests/application/test_stage_exit.py tests/application/test_session_service.py tests/test_architecture.py -q
........................................................................ [ 33%]
........................................................................ [ 66%]
........................................................................ [100%]
216 passed in 8.56s
```

`test_advance_ends_turn.py` is not in the plan's list and was run because it
constructs a `GateReview` directly; a new field with a default does not break
it, and now that is measured rather than assumed. `test_architecture.py` was
run because this task added a cross-layer import
(`session_service` -> `stage_exit`, both in `application`) and a new
`infrastructure` -> `application` one.

## Ruff

```
$ uv run ruff check .
E501 Line too long (98 > 95)
   --> research_team/infrastructure/persistence/check_telemetry.py:153:96
Found 1 error.
```

**That file is Task 4's and is being written concurrently; I did not touch it.**
Scoped to this task's seven files both gates are clean:

```
$ uv run ruff format --check research_team/application/ports.py \
    research_team/application/session_service.py \
    research_team/application/stage_runner.py research_team/composition.py \
    research_team/infrastructure/agent/deep_agent.py \
    tests/application/test_stage_runner.py \
    tests/integration/test_advance_stage_gate.py
7 files already formatted
```

Before the concurrent file appeared, a full-repository run was clean:
`uv run ruff check .` -> "All checks passed!", `uv run ruff format --check .`
-> "213 files already formatted".

**One thing to know:** I ran `uv run ruff format .` (not `--check`)
repository-wide once, which reformats every file including Task 4's two
untracked ones. Nothing was lost -- the Task 4 agent has written over both
since, which is why the E501 above is present again -- but the run could have
collided with a concurrent write, and it was avoidable. Formatting runs during
parallel work should be scoped to the files the task owns.

## Where the plan was wrong

1. **`StageWorkflow.project_id` was the wrong fallback.** See above. The plan
   made this call without knowing `_work` already holds the id.

2. **`test_course.py` cannot host the "viewing a course records no telemetry"
   test.** `course_progress(preset, state, files)` is a pure function and
   `test_course.py` builds no session and no service, so a test living there
   could only assert that a function with nothing to emit onto emitted nothing
   -- true before this change, true after, and true of any implementation. The
   test went into `test_stage_runner.py`, where a real session with a real gate
   already recorded on it makes "and three course views added nothing" a claim.
   Its docstring says so. Its first assertion is a guard that the gate recorded
   something, so the test cannot pass vacuously.

3. **The plan's sketch fills `record_stage_review`'s dict comprehensions at the
   call sites.** Both call sites would then own the payload shape. The runner
   path's copy went into `SessionService.record_stage_review`; the tool path
   executes the command directly on the aggregate and has no service to put it
   behind, so that one is still inline in `composition.py`. Two spellings of
   the same flattening remain, one per path -- see "flagged" below.

4. **The plan's Step 1 sketch names `bound_check_names` and elides every
   fixture.** As Task 2 found, the sketches' helper names are guesses. The real
   fixtures reused here are `_Approvals`, `_Turns`, `_runner`, `_advances`,
   `_specify`, `_no_outputs`, `_preset` and `_artifact`, all already in the
   file; the only new ones are `_checked_project`, `_reviews` and
   `_gate_decisions`, and they exist because `TWO_STAGES` binds no checks at
   all and a telemetry test against it would hold vacuously.

## Flagged rather than fixed

- **The dict flattening exists twice**, once in
  `SessionService.record_stage_review` and once in `composition.gate_review`.
  The obvious repair -- a module-level `_payload(evaluated)` in `stage_exit.py`
  -- was not made because the two paths disagree about which is authoritative
  and Task 4 is concurrently deciding what reads these dicts. If Task 4's
  projection ends up asserting the shape, that assertion plus one helper is the
  right follow-up. Named here so it is a decision rather than an oversight.

- **An existing test in `test_stage_runner.py` is misnamed and I left it
  alone.** `test_advisory_findings_do_not_fail_the_condition` binds
  `Check(check="shared.orphan", params={"artifact_type": "Intent"})`, but
  `OrphanParams` has no `artifact_type` field and `Params` is
  `extra="forbid"`, so that binding raises `MalformedCheck` and produces one
  **blocking** finding, not the advisory one the name promises. The test still
  passes, because `blocked` is about invariants rather than about blocking
  findings -- so it passes for a reason unrelated to its docstring. Task 2's
  `EvaluatedCheck` is what made this visible: the review now reports
  `severity='blocking'` for that binding. Out of scope here; worth a one-line
  fix (`params={"type": "Intent", "must_link_to": ...}`) by whoever owns that
  test next.

  It cost me one wrong iteration: my own new binding copied the same spelling
  and recorded `findings=1` where the test expected a check that passed. The
  correct spelling is `params={"type": "EvidenceSpec", "must_link_to":
  "Intent"}`, which runs over an empty domain and finds nothing -- which is the
  case the whole denominator exists for.

- **Nothing reads these events yet.** Task 4's projection is the consumer. Both
  gates now write `StageChecksEvaluated` and a joined `ToolCallDecided` on
  every run, which is a permanent addition to every session's stream; the
  event's docstring already argues why it carries counts rather than prose.

- **Not run:** the full pytest suite, vitest, `npm run verify`, per the
  dispatch. No frontend code was touched.
