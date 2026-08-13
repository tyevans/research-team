# Check telemetry, Task 5: the read surface

Plan: `docs/superpowers/plans/2026-08-12-check-telemetry.md`, Task 5.
Spec: `docs/superpowers/specs/2026-08-12-check-telemetry-design.md`, "The read
surface" and "Honesty constraints".

## What changed

**Created `research_team/application/check_telemetry_read.py`.** A Protocol, two
frozen dataclasses, an exception and one pure function. It imports
`dataclasses`, `datetime`, `statistics`, `typing` and
`research_team.application.checks` -- no infrastructure, no `aiosqlite`, no
`sqlalchemy`.

- `CheckOutcome` -- the arithmetic's input. It mirrors only the eight row
  columns `summarise` reads; `severity`, `stage`, `preset` and the ids stay in
  storage. A wider mirror would grow a field every time the row did.
- `CheckStat` -- the spec's shape, exactly, plus `standing_gate`.
- `CheckTelemetryReadPort` -- `async def stats(self) -> list[CheckStat]`, no
  project argument, for `CorpusReadPort`'s reason.
- `CheckTelemetryReadError`.
- `summarise(outcomes) -> list[CheckStat]`, ordered by fire rate descending,
  ties on the check name. Each honesty constraint is one filter with the
  comment its test docstring states in shorter form.

**Created `research_team/infrastructure/persistence/check_telemetry_reader.py`.**
`ProjectCheckTelemetryReader(runner, project_id)`, following `corpus_reader.py`:
project bound at construction, `RuntimeError` from an unstarted runner
translated into `CheckTelemetryReadError`. Its `_outcome` is the single place
`row.check_name` becomes `CheckOutcome.check` -- Task 4's hand-off, and the only
place below the CLI that has to know the column is spelled differently.

**`research_team/composition.py`** -- `CheckTelemetryRunner` constructed beside
`corpus` and `topics`; two `Application` fields (`check_telemetry`,
`check_telemetry_readers`); started in `start()`, stopped in `close()`; a
`check_telemetry_caught_up()` delegator; a `check_telemetry_reader` factory
built the way `topic_reader` is.

**`research_team/interfaces/cli/repl.py`** -- `/checks` in the help text under
"Event log", an optional `check_telemetry_readers` factory on `Repl` and on
`Repl.start`, `_handle_checks`, the dispatch branch beside `/health`, and a
fourth parameter on `run()`. **Not** added to `_WITHOUT_A_SESSION`: it needs a
project and finds one through the current session.

**`research_team/interfaces/cli/formatters.py`** -- `format_checks`, an aligned
table (check, ran, fired, fire%, over, refus, auto, med s) with a
`bound but not registered:` line and a `*` footnote for standing gates.

**`main.py`** -- passes `application.check_telemetry_readers` into `run`. The
plan says `research_team/main.py`; the file is at the repository root.

**Tests** -- `tests/application/test_check_telemetry_read.py` (10, new file) and
eight appended to `tests/interfaces/test_repl.py`.

## Red, then green

### Step 2 -- the aggregation tests, before the module existed

```
$ uv run pytest tests/application/test_check_telemetry_read.py -v
ImportError while importing test module '.../tests/application/test_check_telemetry_read.py'.
Traceback:
tests/application/test_check_telemetry_read.py:16: in <module>
    from research_team.application.check_telemetry_read import CheckOutcome, summarise
E   ModuleNotFoundError: No module named 'research_team.application.check_telemetry_read'
=========================== short test summary info ============================
ERROR tests/application/test_check_telemetry_read.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

A module-not-found is a weak red -- it proves the tests run, not that any of
them constrains an implementation choice. So each honesty constraint was then
proved against the *plausible wrong implementation* rather than against nothing.
All five mutations were made to the finished module, run, and reverted.

### The tool path contributing null, not zero

The plan calls this the one most worth pinning, because the wrong version reads
as correct. Dropped the `posed_by` filter from `durations`, so the delta is
computed unconditionally:

```
$ uv run pytest tests/application/test_check_telemetry_read.py -k "tool_path or median_is_taken" -v
>       assert stat.median_seconds_to_decision == 20.0
E       AssertionError: assert 10.0 == 20.0
E        +  where 10.0 = CheckStat(check='shared.coverage', evaluated=3, fired=0, findings=0,
E            unimplemented=0, decided=3, overridden=0, refused=0, auto_approved=0,
E            standing_gate=False, median_seconds_to_decision=10.0).median_seconds_to_decision
=========================== short test summary info ============================
FAILED tests/application/test_check_telemetry_read.py::test_the_tool_path_contributes_no_duration
FAILED tests/application/test_check_telemetry_read.py::test_a_median_is_taken_over_the_runner_rows_that_remain
======================= 2 failed, 8 deselected in 0.21s ========================
```

Both halves fire: the tool-only case reports a number where it should report
nothing, and the mixed case is dragged from 20s to 10s by a three-millisecond
row. The second test exists precisely so the failure is a wrong number rather
than a missing one -- a project with a handful of tool-path gates would
otherwise still produce a plausible-looking median.

### A policy approval counted as an override

`overridden = list(opened)`:

```
$ uv run pytest tests/application/test_check_telemetry_read.py -k policy_approval -v
        assert stat.auto_approved == 1
>       assert stat.overridden == 1
E       AssertionError: assert 2 == 1
=========================== short test summary info ============================
FAILED tests/application/test_check_telemetry_read.py::test_a_policy_approval_is_not_an_override
======================= 1 failed, 9 deselected in 0.18s ========================
```

### An unimplemented binding counted as a run

`ran = list(rows)`:

```
$ uv run pytest tests/application/test_check_telemetry_read.py -k unimplemented_binding_is_not_a_run -v
        assert stat.unimplemented == 2
>       assert stat.evaluated == 1
E       AssertionError: assert 3 == 1
=========================== short test summary info ============================
FAILED tests/application/test_check_telemetry_read.py::test_an_unimplemented_binding_is_not_a_run
======================= 1 failed, 9 deselected in 0.19s ========================
```

### An override counted without requiring a finding

Counted `opened` and `refused` over every row rather than over the fired ones --
the spelling anyone writes who reads "overridden" as "approved":

```
$ uv run pytest tests/application/test_check_telemetry_read.py -k only_counted_when -v
>       assert stat.overridden == 0
E       AssertionError: assert 1 == 0
E        +  where 1 = CheckStat(check='shared.coverage', evaluated=2, fired=0, findings=0,
E            unimplemented=0, decided=2, overridden=1, refused=1, auto_approved=0,
E            standing_gate=False, median_seconds_to_decision=0.0).overridden
=========================== short test summary info ============================
FAILED tests/application/test_check_telemetry_read.py::test_an_override_is_only_counted_when_the_check_actually_fired
======================= 1 failed, 9 deselected in 0.18s ========================
```

This test is not in the plan. It is the same class of error as the other three
and it is the one that inverts the table: the checks that never complain would
be reported as the most ignored.

### Standing gates read from a list rather than the registry

`_is_standing_gate` replaced with `return False`:

```
$ uv run pytest tests/application/test_check_telemetry_read.py -k standing_gate
>       assert stats["ubd.uncoverage"].standing_gate is True
E       AssertionError: assert False is True
=========================== short test summary info ============================
FAILED tests/application/test_check_telemetry_read.py::test_a_standing_gate_is_marked_as_one
======================= 1 failed, 9 deselected in 0.20s ========================
```

### Step 4 -- the aggregation tests, green

```
$ uv run pytest tests/application/test_check_telemetry_read.py -q
..........                                                               [100%]
10 passed in 0.17s
```

### The REPL tests, before the implementation

Produced the way Task 3 did it: the three implementation files copied aside,
`git checkout --` on them, the tests run, the files copied back. The tests were
never reverted. First, with all three reverted, collection fails:

```
$ uv run pytest tests/interfaces/test_repl.py -q
tests/interfaces/test_repl.py:10: in <module>
    from research_team.interfaces.cli.formatters import (
E   ImportError: cannot import name 'format_checks' from
    'research_team.interfaces.cli.formatters'
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

Then with `formatters.py` alone restored, so the remaining failures are
specific:

```
$ uv run pytest tests/interfaces/test_repl.py -q
>       assert "unavailable" in output
E       assert 'unavailable' in "unknown command '/checks' -- try /help"

>       stats = await application.check_telemetry_readers(uuid4()).stats()
E       AttributeError: 'Application' object has no attribute 'check_telemetry_readers'

=========================== short test summary info ============================
FAILED tests/interfaces/test_repl.py::test_checks_renders_what_the_reader_answers
FAILED tests/interfaces/test_repl.py::test_checks_says_so_when_no_telemetry_is_wired
FAILED tests/interfaces/test_repl.py::test_a_broken_instrument_does_not_read_as_an_empty_one
FAILED tests/interfaces/test_repl.py::test_an_application_wires_a_reader_that_is_actually_following
4 failed, 50 passed in 8.83s
```

The four formatter tests passed in that run, which is right -- they are about
`formatters.py` and it was restored. Their own red is below.

**`test_checks_needs_a_session_like_every_other_project_command` passed against
the reverted code**, and its docstring says so in substance: before `/checks`
exists, an unknown command hits the same `NO_SESSION` guard and returns the same
string. It constrains the future rather than the present -- it fails the day
somebody adds `/checks` to `_WITHOUT_A_SESSION` for symmetry with `/health`,
which is a plausible edit and a wrong one. Stated here rather than left as
reassurance.

### The renderer's half of the duration constraint

The aggregation can report `None` correctly and the renderer can still print a
zero. Mutated `format_checks` to `f"{stat.median_seconds_to_decision or 0:.1f}"`:

```
$ uv run pytest tests/interfaces/test_repl.py -k renders_as_no_measurement
E         - -
E         + 0.0
=========================== short test summary info ============================
FAILED tests/interfaces/test_repl.py::test_the_tool_path_renders_as_no_measurement_rather_than_zero
======================= 1 failed, 53 deselected in 0.18s =======================
```

### Step 8 -- green, with the two guard suites

```
$ uv run pytest tests/application/test_check_telemetry_read.py \
      tests/interfaces/test_repl.py tests/interfaces/test_web_entrypoint.py \
      tests/test_architecture.py -q
........................................................................ [ 33%]
........................................................................ [ 66%]
........................................................................ [100%]
216 passed in 10.94s
```

`tests/test_architecture.py` was run because this task adds one `application`
module and one `infrastructure` module; the layering rules hold.

### Step 7 -- the entrypoint guard

`tests/interfaces/test_web_entrypoint.py` passes untouched, which is what the
plan predicted. No parameter was added to `create_app` and no HTTP route was
added. Nothing to report there.

## Ruff, repository-wide

The first run found one `E501` in the new application module (a 96-column
`sorted(...)` call), its matching format difference, and three `I001` import
orderings in files I appended to. All fixed, then:

```
$ uv run ruff check .
All checks passed!
check exit=0
$ uv run ruff format --check .
216 files already formatted
format exit=0
```

## Where the plan was wrong

**1. `main.py` is at the repository root, not `research_team/main.py`.** Minor
and obvious once looked at; noted because the plan's file list is otherwise
accurate about paths.

**2. The spec and the plan disagree about `auto_approved`, and the plan is
right.** The spec's `CheckStat` comments it as "of `overridden`, how many by
`decided_by="policy"`" -- a subset. The plan's test says "counted in
`auto_approved` and *excluded* from `overridden`", and so does the spec's own
honesty constraint two sections later ("They are counted in `auto_approved` and
reported beside the rate, not inside it"). A subset would make `overridden`
include exactly what the constraint exists to keep out of it, so the spec's
inline comment is the stale half. Implemented as disjoint: `overridden` is the
human ones, `auto_approved` is the policy ones, and they sum to the fired gates
that opened.

**3. The plan's `_stats(rows)` in the duration sketch is not a real name.** The
recurring defect again, in its mildest form -- the sketch calls `_stats(rows)`
and indexes `[0]`. The function is `summarise`, and the tests here call it
directly.

**4. Nothing in the plan says what `decided` counts when a row is
unimplemented.** I count `decided` over every row of the check, `ran` or not:
each row is one check at one gate, and the gate was answered. This means a check
that has only ever been unimplemented can show `decided > 0` and `evaluated ==
0`, which is accurate rather than surprising once `evaluated` is understood as
runs. Flagged because it is a choice the plan left open and someone could
reasonably have made the other way.

## Choices worth arguing with

**Refusals are not split by `decided_by` the way approvals are.** A policy
`deny` is counted in `refused` alongside a human rejection. The asymmetry is
deliberate and the comment in `_summarise_one` states it: an unasked *approval*
overstates what a human ignored, which is the lie the honesty constraint names;
an unasked refusal overstates nothing, because the gate genuinely did not open.
Splitting it would add a column that answers no question anyone has.

**`CheckStat` carries counts, not rates.** The renderer divides. A reader given
only "100%" cannot tell 1-of-1 from 200-of-200, and those warrant opposite
conclusions about whether a check earns its place -- which is the only decision
this table is for.

**The `evaluated == 0` case sorts rather than crashes.** `_fire_rate` returns
0.0 for a check that has never run, and `format_checks` prints `-` rather than
`0%`. B38's four bindings are one rename away from being exactly this, and a
`ZeroDivisionError` in the read surface would be a strange way to find out.

## Flagged rather than fixed

- **Nothing renders the `findings` total or `decided`.** Both are on `CheckStat`
  and neither is a column in the CLI table, which is already eight columns wide.
  They are there because they are cheap to compute and impossible to recover
  later, and because the next reader of these numbers is as likely to be a
  script as a terminal.

- **`check_telemetry_caught_up()` has no caller.** Added because the plan asks
  for the delegator and because a test that drives a gate and then asks
  `/checks` needs it; unlike its three neighbours, nothing in a run reads these
  numbers back, so nothing in production races the projection. Its docstring
  says so rather than implying a symmetry that is not there.

- **No test drives a real gate through to a rendered `/checks` table.** The
  chain is covered in three overlapping pieces -- Task 3's tests prove both
  gates emit, Task 4's prove the projection folds them, and
  `test_an_application_wires_a_reader_that_is_actually_following` proves the
  runner is started and reachable through a real `Application` -- but no single
  test walks the whole path. Building one means driving `StageRunner` to a gate
  inside an application fixture, which `tests/application/test_stage_runner.py`
  does with its own harness rather than a built `Application`. Worth an
  integration test beside `tests/integration/test_advance_stage_gate.py`; not
  built here, because it is a new harness rather than a reuse and this task's
  brief was the read surface.

- **`Application` gained two fields and is a frozen dataclass with one
  defaulted field at the end.** Both new fields are non-default and were placed
  before `graphs`, so the ordering rule still holds. Nothing constructs
  `Application` positionally -- one call site, all keywords -- but a positional
  construction anywhere would now be wrong.

- **Not run:** the full pytest suite, vitest, `npm run verify`, per the
  dispatch. No frontend code was touched.
