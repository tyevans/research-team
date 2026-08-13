# Check telemetry, Task 1: the event, the command, and the join key

## What changed

- `research_team/domain/events.py` — new `StageChecksEvaluated` (registered,
  `aggregate_type="CodingSession"`), `ToolCallDecided.review_id: UUID | None = None`
  added after `edited_args`, `StageChecksEvaluated` appended to `SESSION_EVENTS`.
  `UUID` and `Any` were already imported; verified, nothing added.
- `research_team/domain/commands.py` — new `RecordStageReview`,
  `RecordToolDecision.review_id: UUID | None = None`, and `RecordStageReview` added
  to the `SessionCommand` union. The plan did not mention the union; it is the
  written-down surface of what a session accepts, and leaving the new command out
  of it would have made that statement false.
- `research_team/domain/session.py` — imports for both new names; the supervision
  comment rewritten from "Both of these" to the three-case version; the
  `RecordToolDecision` case now destructures and forwards `review_id`; a new
  `RecordStageReview` case returning one `StageChecksEvaluated`. `evolve` is
  untouched, deliberately.
- `research_team/domain/__init__.py` — `RecordStageReview` and
  `StageChecksEvaluated` added to both the imports and `__all__`, alphabetically,
  matching what it does for `RecordToolDecision` and `ToolCallDecided`.
- `tests/domain/test_decider.py` — three new tests (see the deviation below).
- `tests/infrastructure/test_schema_evolution.py` — one new case.

## Where the plan was wrong, and what I did instead

**The domain tests belong in `test_decider.py`, not `test_session.py`.** The plan
names `tests/domain/test_session.py` for all three tests, but that file's own
docstring says: *"Anything here needs an aggregate or a store; anything that does
not belongs next door."* All three tests are pure `decide` calls with no aggregate,
so they went into `tests/domain/test_decider.py`, appended to its
`---------------- supervision ----------------` section beside
`test_a_tool_decision_produces_an_audit_event`. I ran both files.

**`initial_state()` is the wrong state to decide against.** The plan's sketch calls
`decide(..., initial_state())`. `test_decider.py` has a `started()` helper for
exactly this and every supervision test there uses it; a command against a state
with no `session_id` would produce an event with `aggregate_id=None`. Used
`started()`.

**The sketch's first assertion is not an assertion.**
`assert event.aggregate_id == session_id or event.aggregate_id is not None` cannot
fail as written (and `session_id` is never bound in the sketch). Replaced with
`assert event.aggregate_id == state.session_id`, which is the real claim.

Likewise `assert evolve(state, event) is state or evolve(state, event) == state`
was reduced to `assert evolve(state, event) == state` — `evolve` returns the same
object for an unhandled event, but equality is the claim that survives someone
making it return a copy, and the `or` made the whole line unfailable.

**The schema-evolution fixture is `started`, not `session_id`.** The plan sketches
`(repository, session_id, db_path)`. Every case in that file takes `started` — the
fixture that writes `SessionStarted` through the ordinary path, which is what
creates the `events` table and makes `version=2` the correct next version. Followed
the file. The payload also needs the `aggregate_id` / `aggregate_type` /
`aggregate_version` keys that every other case in that file supplies; the sketch
omitted them.

## Red, then green

### Step 2 — the three domain tests, before the change

```
$ uv run pytest tests/domain/test_decider.py -k "stage_review or names_the_review or answers_no_review" -v
collecting ... collected 0 items / 1 error

==================================== ERRORS ====================================
________________ ERROR collecting tests/domain/test_decider.py _________________
ImportError while importing test module '/home/ty/workspace/research-team/.claude/worktrees/check-telemetry/tests/domain/test_decider.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/home/ty/.local/share/uv/python/cpython-3.13.5-linux-x86_64-gnu/lib/python3.13/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/domain/test_decider.py:20: in <module>
    from research_team.domain import (
E   ImportError: cannot import name 'RecordStageReview' from 'research_team.domain' (/home/ty/workspace/research-team/.claude/worktrees/check-telemetry/research_team/domain/__init__.py)
=========================== short test summary info ============================
ERROR tests/domain/test_decider.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.27s ===============================
```

### Step 5 — after the change

```
$ uv run pytest tests/domain/test_decider.py tests/domain/test_session.py -q
..........................................                               [100%]
42 passed in 0.17s
```

### Step 6 — the schema-evolution case, proved load-bearing

Made `ToolCallDecided.review_id` required (dropped `= None`) and ran it. This is
the temporary mutation the plan asks for, not a state anything was committed in:

```
$ uv run pytest tests/infrastructure/test_schema_evolution.py -k review_ids -v
    def _deserialize_event(self, event_type: str, payload: str) -> DomainEvent:
        event_class = self._event_registry.get(event_type)
        data = json_loads(payload)
>       return event_class.model_validate(data)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       pydantic_core._pydantic_core.ValidationError: 1 validation error for ToolCallDecided
E       review_id
E         Field required [type=missing, input_value={'aggregate_id': 'db890d4...ype': 'ToolCallDecided'}, input_type=dict]
E           For further information visit https://errors.pydantic.dev/2.13/v/missing

.venv/lib/python3.13/site-packages/eventsource/adapters/sqlite/store.py:486: ValidationError
=========================== short test summary info ============================
FAILED tests/infrastructure/test_schema_evolution.py::test_a_decision_written_before_review_ids_still_loads
======================= 1 failed, 13 deselected in 0.27s =======================
```

Default restored, then:

```
$ uv run pytest tests/domain/test_decider.py tests/domain/test_session.py tests/infrastructure/test_schema_evolution.py -q
........................................................                 [100%]
56 passed in 1.05s
```

## Ruff, repository-wide

```
$ uv run ruff check .
All checks passed!
check exit=0
$ uv run ruff format --check .
211 files already formatted
format exit=0
```

The first run of these caught one E501 and one formatting difference in the new
test (a 99-column dict literal on an `assert`); both fixed before this.

## Flagged rather than fixed

- **`StageChecksEvaluated` has no schema-evolution case, and should not.** The file
  exists to prove *old* payloads still load; there are no old payloads of an event
  that has never been written. The next change to its shape is what needs a case.
- **`SESSION_EVENTS` order.** Appended `StageChecksEvaluated` after
  `ToolCallDecided` and before `AutonomyChanged`, matching the declaration order in
  the module rather than sorting. Nothing appears to depend on the order; noting it
  in case something later does.
- **Not run:** the full pytest suite, vitest, `npm run verify`, per instruction.
  Nothing under `research_team/application/stage_exit.py` or
  `tests/application/test_stage_exit.py` was read or touched.
