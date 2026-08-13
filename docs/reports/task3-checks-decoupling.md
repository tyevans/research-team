# Task 3: `checks.py` knows no domain, enforceably

Commit `2e119f7` on `worktree-defects-and-decisions`.

## What changed

Three files, staged by explicit path.

**`research_team/application/checks.py`**

- `CriterionDocAuthoredParams` grows `documents: TypeFilter`, defaulting to
  `TypeFilter.model_validate("CriterionDocument")`. The string shorthand rather
  than `TypeFilter(artifact_type=ArtifactType.CRITERION_DOCUMENT)` — the point
  is that the enum member is named by presets, so naming it in the default
  would have kept the coupling while moving it five lines.
- `_criterion_doc_authored` selects `params.documents` instead of constructing
  its own filter.
- The "no CriterionDocument named ... is present" message now renders
  `params.documents.describe()`. Byte-identical under the default, since
  `ArtifactType` is a `StrEnum` and `describe()` returns `"CriterionDocument"`.
  Without this, a binding that scoped the check to another type would be told
  its artifacts were missing under a name it never used — a latent defect my
  own change would have introduced.

**`research_team/workflows/hybrid.py`** — the one live binding passes
`"documents": "CriterionDocument"` explicitly, so the default is unreachable
from shipped content.

**`tests/test_architecture.py`** — new
`test_the_shared_check_library_names_no_artifact_type`.

## What the plan got wrong

The plan and the design doc both specify the test as: `ArtifactType` appears in
`checks.py` **only inside string literals**, on the basis that "`ArtifactType`
appears five times ... three of those are inside error strings".

That count is wrong and the test as worded cannot pass on any correct version
of the file. The AST-level non-string references are:

```
import 95     from research_team.domain.workflow import ArtifactType
Name   155    Artifact.artifact_type: ArtifactType
Name   219    TypeFilter.artifact_type: ArtifactType | None
Name   1862   TypeFilter(artifact_type=ArtifactType.CRITERION_DOCUMENT)   <- the coupling
```

95, 155 and 219 are legitimate. They name the *type* as an annotation; they
commit to no methodology, and forbidding them would leave the check library
unable to describe the filter it is handed. Only 1862 reaches into the enum for
a *member*, which is a vocabulary choice belonging to the binding.

So the honest property — the one that is actually true after the fix and
actually false before it — is: **`checks.py` names no member of
`ArtifactType`.** That is what the test asserts. I did not weaken the intent;
the intent ("shared checks know no domain") is unchanged and now enforced. Only
the plan's mechanical wording was unsatisfiable.

The test parses rather than greps, which the plan correctly demanded. It closes
attribute access (`ArtifactType.X`), subscript (`ArtifactType["X"]`) and call
(`ArtifactType("X")`). Only the attribute form has ever appeared; the other two
cost three lines and are the obvious detours. Because it is AST-based, a
commented-out occurrence produces no node — but so does a genuinely absent one,
and a commented-out occurrence is not live coupling. A *grep* would have failed
the plan's own bar here, matching the docstring prose `"is not
ArtifactType.field"` and being unable to tell it from real coupling.

## Red-then-green evidence

The architecture test was written first and run against unmodified code:

```
$ uv run pytest tests/test_architecture.py -k artifact_type
>       assert not offenders, (
            f"checks.py names domain vocabulary: {offenders}; "
            "take the type through a TypeFilter on the check's params, so the "
            "binding that knows the methodology is the thing that states it"
        )
E       AssertionError: checks.py names domain vocabulary: ['line 1862: ArtifactType.CRITERION_DOCUMENT']; take the type through a TypeFilter on the check's params, so the binding that knows the methodology is the thing that states it
E       assert not ['line 1862: ArtifactType.CRITERION_DOCUMENT']

tests/test_architecture.py:195: AssertionError
=========================== short test summary item ============================
FAILED tests/test_architecture.py::test_the_shared_check_library_names_no_artifact_type
====================== 1 failed, 142 deselected in 0.56s =======================
```

It failed for the right reason and named the exact line the design doc names.

## The four cited tests were not edited

`tests/application/test_checks.py:1206`, `:1230`, `:1249`, `:1260` pass
unchanged. Confirmed mechanically, not by inspection:

```
$ git diff --stat -- tests/application/test_checks.py
(no output — the file is untouched)
```

That is what makes the change behaviour-preserving by demonstration rather than
by argument. I never needed to reconsider the design.

## Tests run

Only the five files named in the task. Never the full suite; never vitest.

```
tests/application/test_checks.py
tests/application/test_stage_exit.py
tests/domain/test_workflow.py
tests/application/test_preset_gates.py
tests/test_architecture.py

352 passed in 2.26s
```

## Ruff

- `uv run ruff format --check .` — **passes**, 211 files already formatted.
- `uv run ruff check .` — **fails on one error that is not mine**, in
  `research_team/infrastructure/agent/search.py:99`, which is Task 1's file and
  was in flight concurrently:

  ```
  B039 Do not use mutable data structures for `ContextVar` defaults
     --> research_team/infrastructure/agent/search.py:99:54
   99 |             f"search_attempts_{id(self):x}", default=_Counter()
  help: Replace with `None`; initialize with `.set()`
  ```

  My three files pass in isolation:
  `uv run ruff check research_team/application/checks.py
  research_team/workflows/hybrid.py tests/test_architecture.py` → *All checks
  passed!*

Worth flagging to whoever holds Task 1: ruff's suggested fix (`default=None`)
is in direct tension with that task's load-bearing requirement that the
ContextVar hold a *mutable object*. The resolution is a lazy default (`None`,
with the tool installing a `_Counter()` when it finds one absent) or a
`# noqa: B039` carrying the reason — not switching to an immutable default.
Whichever they choose, this gate blocks the integrator until it is resolved.

## Scope

B22 and B38 both live in the files I touched. Neither was touched.
