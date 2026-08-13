# Task 2 — the denominator: `StageReview.evaluated`

Plan: `docs/superpowers/plans/2026-08-12-check-telemetry.md`, Task 2.
Spec: `docs/superpowers/specs/2026-08-12-check-telemetry-design.md`, "`StageReview.evaluated`, the denominator".

## What changed

`research_team/application/stage_exit.py`

- New frozen dataclass `EvaluatedCheck(check, severity: FindingSeverity, findings: int)`,
  added to `__all__`. `FindingSeverity` is now imported from
  `research_team.application.findings` — it was not previously imported here.
- `StageReview` gained two defaulted fields, both `tuple[EvaluatedCheck, ...] = ()`:
  `evaluated` (every binding that ran) and `unimplemented_bindings` (the bindings
  naming no registered check, carrying the severity the binding declared).
  `StageReview.unimplemented: tuple[str, ...]` is untouched, as the plan requires —
  `render_review` and `gate_context` both read it and it reaches a browser as a
  list of names.
- `review_stage`'s loop restructured: `run_check`'s result is bound to `produced`
  in every branch instead of being extended inline, so the per-binding count is
  available. `findings.extend(produced)` happens once, after the `try`. The
  `UnknownCheck` branch still `continue`s without contributing to `findings`; the
  `MalformedCheck` and bare-`Exception` branches still yield exactly one blocking
  finding each.
- Severity on an `EvaluatedCheck` is read off `produced[0].severity`, falling back
  to `binding.severity` when the check produced nothing. Not recomputed as
  `spec.fixed_severity or binding.severity`: that rule lives in `run_check` and a
  second copy here would drift the first time it changes. The fallback is not a
  compromise — a check that passed carried a severity nowhere, and the binding's
  own word is the only one there is.

`tests/application/test_stage_exit.py` — four new tests under a new
`# --- the denominator ---` section, placed after
`test_the_review_counts_what_it_looked_at` and before the invariants section.

All four reuse the file's existing helpers: `specify`, `preset_of`,
`artifact_file`, `file`, and `break_check` (which already monkeypatches a single
`REGISTRY` entry with a `run` that raises, and is restored by `monkeypatch`). No
new harness was introduced.

Two substitutions from the plan's sketch, both because the plan left the fixture
as `...`:

- The plan named a nonexistent-check binding `shared.no_such_check`. The file
  already has a convention here and a comment explaining it — the existing
  `test_a_binding_naming_no_registered_check_is_reported_not_ignored` uses
  `addie.no_such_check`, deliberately a name that is not and will not be
  registered. I followed that rather than introducing a second spelling.
- The plan's crash test used `shared.coverage` with a `_files_that_make_coverage_raise()`
  helper that does not exist. There is no course that makes a correct check raise;
  the existing mechanism is `break_check`, so the test monkeypatches
  `shared.provenance` (what the neighbouring crash test breaks) and asserts the
  same two things the plan asked for: `findings == 1` and `severity == "blocking"`.

## Red, then green

### Red — all four, verbatim

`uv run pytest tests/application/test_stage_exit.py -k "passed_as_well or severity_the_finding or not_reported_as_having_passed or raises_is_recorded" -v`

```
               ^^^^^^^^^^^^^^^^
E       AttributeError: 'StageReview' object has no attribute 'evaluated'

tests/application/test_stage_exit.py:404: AttributeError
_____________ test_a_check_that_raises_is_recorded_as_having_fired _____________

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x764e633ae8b0>

    def test_a_check_that_raises_is_recorded_as_having_fired(monkeypatch):
        """From the gate's point of view a crashed check is a check that blocked.

        A fire rate that excluded crashes would under-report the cost of a broken
        check, which is the thing most worth surfacing. The message says it
        crashed; the count says it fired.
        """
        break_check(monkeypatch, "shared.provenance")
        stage = specify("s.one", Check(check="shared.provenance"))
        review = review_stage(preset_of(stage), stage, {})

>       entry = next(e for e in review.evaluated if e.check == "shared.provenance")
                                ^^^^^^^^^^^^^^^^
E       AttributeError: 'StageReview' object has no attribute 'evaluated'

tests/application/test_stage_exit.py:421: AttributeError
=========================== short test summary info ============================
FAILED tests/application/test_stage_exit.py::test_a_review_reports_the_checks_that_passed_as_well_as_those_that_fired
FAILED tests/application/test_stage_exit.py::test_an_evaluated_check_carries_the_severity_the_finding_would_have
FAILED tests/application/test_stage_exit.py::test_an_unimplemented_binding_is_not_reported_as_having_passed
FAILED tests/application/test_stage_exit.py::test_a_check_that_raises_is_recorded_as_having_fired
======================= 4 failed, 45 deselected in 0.64s =======================
```

All four fail on `AttributeError: 'StageReview' object has no attribute 'evaluated'`,
which is the failure the plan predicted.

### Green

`uv run pytest tests/application/test_stage_exit.py -q`

```
.................................................                        [100%]
49 passed in 0.53s
```

The 45 pre-existing tests are the regression surface for the loop restructuring
and all of them still pass.

`uv run pytest tests/application/test_stage_runner.py tests/application/test_course.py -q`

```
...................................................                      [100%]
51 passed in 9.73s
```

(`tests/application/test_course.py` is the file covering `application/course.py`;
the plan's guess at the name was right.)

## Ruff

`uv run ruff check .` and `uv run ruff format --check .` both report failures, and
**neither is in a file this task touched.** Both are in files another agent is
concurrently editing for Task 1:

- `research_team/domain/__init__.py:23,50` — `F401` on `RecordStageReview` and
  `StageChecksEvaluated` imported but not added to `__all__`.
- `tests/domain/test_decider.py:515` — `E501` (99 > 95) and a corresponding
  `ruff format` diff on the same line.

Scoped to this task's files, both gates are clean:

```
$ uv run ruff check tests/application/test_stage_exit.py research_team/application/stage_exit.py
All checks passed!
$ uv run ruff format --check tests/application/test_stage_exit.py research_team/application/stage_exit.py
2 files already formatted
```

One `E501` of my own was found and fixed before committing (a `params={...}` dict
on one line in the first new test).

## What the plan got wrong

Three things, all minor and all in Task 2's Step 1 sketch:

1. **`_preset_with_checks`, `_files_that_satisfy_orphan_only()`,
   `_files_with_an_uncited_verdict()` and `_files_that_make_coverage_raise()` do
   not exist** and are not close to anything that does. The plan flagged the `...`
   placeholders as the worker's to fill, but it also wrote helper *names* that read
   as if they were real. The actual helpers are `specify(stage_id, *checks)` +
   `preset_of(*stages)` for the preset, `artifact_file(**frontmatter)` / `file(content)`
   for the course, and `break_check(monkeypatch, name)` for the crash. Substitutions
   are listed above.

2. **`shared.no_such_check` contradicts an existing test's stated convention.**
   See above; I used `addie.no_such_check`.

3. **`Check.severity` is `Severity = Literal["blocking", "advisory"]`, while
   `EvaluatedCheck.severity` is `FindingSeverity`**, which is the wider
   `Literal["invariant", "blocking", "advisory", "human_gate", "critic_gate"]`.
   The plan specifies `FindingSeverity` and that is right — it has to hold an
   `invariant` resolved from a spec's `fixed_severity`. The narrowing direction is
   safe (every `Severity` is a `FindingSeverity`) so the `binding.severity`
   fallback type-checks, but the plan did not note that the two fields have
   different types, and a reader comparing them would reasonably wonder.

Nothing in the plan's design is wrong. The denominator argument holds and the
"read severity off the produced findings" instruction is the right call — the
alternative genuinely would have been a second copy of `run_check:350`.

## Flagged rather than fixed

- **The two ruff failures in `research_team/domain/__init__.py` and
  `tests/domain/test_decider.py`.** Task 1's territory, explicitly off-limits per
  the dispatch. They will need to be clean before either task's work passes CI.
- **`test_a_review_reports_the_checks_that_passed_as_well_as_those_that_fired`
  depends on `shared.orphan` passing on an empty domain.** That is the documented
  rule (`_INSTRUMENT_RULE` in `checks.py`: a universal over an empty domain
  passes), so it is a stable dependency rather than an accident, but it is a
  dependency on another module's stated behaviour and worth knowing about if that
  rule is ever revisited.
- **Nothing consumes the new fields yet.** Task 3 wires them into the two gates.
  Until then `evaluated` and `unimplemented_bindings` are written and never read,
  which is expected at this point in the plan and is why both fields default to `()`.
