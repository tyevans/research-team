# Check telemetry, Task 4: the projection and the read model

## What changed

Two new files, nothing else touched.

- `research_team/infrastructure/persistence/check_telemetry.py` —
  `CHECK_TELEMETRY_NAMESPACE`, `CheckOutcomeRow` (`__table_name__ =
  "check_outcomes"`, `row_id(review_id, check)`), `CheckTelemetryProjection`,
  `CheckTelemetryStore` (`open` / `outcomes` / `truncate` / `close`), and
  `CheckTelemetryRunner` (`start` / `stop` / `rebuild` / `failures` /
  `caught_up` / `projection_name` / `outcomes`).
- `tests/infrastructure/test_check_telemetry.py` — 18 tests.

Both plan-mandated divergences from `CorpusRunner` are in: `caught_up` follows
`SessionSummaryRunner`'s `FeedReadOptions(aggregate_type=...)` form, and the
store applies its DDL through `apply_schema` rather than `executescript`.

`CheckTelemetryStore.outcomes(project_id)` was added beyond the plan's list for
the store (it names it only on the runner). The runner delegates rather than
reaching into the repository, matching `CorpusRunner.list`.

## The unresolved question the plan flagged: `check` as a column name

**Resolved, and worse than the plan expected.** The plan asked whether `check`
needs quoting *in the index DDL*. It cannot be a column at all.

`CHECK` is a SQLite keyword and `generate_full_schema` does not quote
identifiers, so a `ReadModel` with a `check: str` field produces a `CREATE
TABLE` that will not parse — before any index is reached:

```
CREATE TABLE IF NOT EXISTS check_outcomes (
    ...
    check TEXT NOT NULL,
    ...
);
sqlite3.OperationalError: near "TEXT": syntax error
```

Quoting the index name does not help, because the table never gets created.
Measured rather than reasoned: a throwaway `ReadModel` with that field was
built and opened against SQLite, and again after the rename.

**The column is therefore `check_name`.** With the rename, the table creates,
the index works both quoted and unquoted (unquoted is used, matching the
neighbours), and `Filter(field="check_name", ...)` finds rows. The reasoning is
in `CheckOutcomeRow`'s docstring so nobody renames it back.

**This is a hand-off for Task 5.** The event payload, the spec and the CLI all
say `check`; only the row column is `check_name`. The adapter in
`check_telemetry_reader.py` maps `row.check_name` onto `CheckOutcome.check`.

## Where the plan's sketch was wrong

**`Filter` values must be the UUID, not `str(uuid)`.** The plan's sketch has
`value=str(event.review_id)`, copied from `topics.py`. That is correct against
SQLite — ids are stored as TEXT — and matches *nothing* against
`InMemoryReadModelRepository`, which compares the field's real value. Since the
plan also says to use the in-memory repository for the projection tests, the
sketch as written produces a projection whose fold silently never fires in
every test that exercises it. Verified both directions:

```
memory UUID 1     memory str 0
sqlite UUID 1     sqlite str 1
```

Passing the UUID is correct for both, and is what the code does, with a comment
saying why `topics.py` gets away with the other spelling.

**The idempotence test cannot fail the way the plan says.** The plan's docstring
for `test_replaying_a_review_twice_leaves_one_row_per_check` says it "fails with
a uniqueness error or a doubled count if someone inserts." It does not: `save`
is an upsert on the row id in *both* repository implementations, so a blind
`CheckOutcomeRow(id=row_id, **fields)` leaves one row and even increments
`version`. Confirmed by running the test against a deliberately blind-inserting
handler — it passed.

Rather than ship a test whose docstring is false, its docstring now says it is
weak and what it actually constrains (the derived row id), and a second test was
added that does constrain the handler:
`test_redelivering_a_review_alone_does_not_erase_its_decision`. The real cost of
a blind insert is that redelivering the review event *alone* — a retry after a
transient failure, or a checkpoint written mid-review — writes the review's
facts back with `decision` at its default and erases an answer already recorded.
A full-stream replay hides this, because the decision is re-applied afterwards.

**Two tests were added beyond the sketch**, both pinning something a plausible
implementation gets wrong: `test_a_decision_only_fills_the_review_it_names` (a
projection filtering on the session rather than the review would attribute every
later decision to every earlier gate) and
`test_caught_up_returns_with_other_aggregate_types_in_the_store` (the divergence
the plan calls load-bearing, made into a failing test rather than a comment).

**One sketched test was re-argued rather than dropped.**
`test_a_decision_replayed_after_its_review_is_rewritten_is_still_applied` is
kept, but the sketch's framing ("order within a rebuild is stream order") makes
it pass trivially; its docstring now states that the replay rewrites the rows
*after* the decision filled them, which is the part worth pinning.

## Red, then green

### Step 2 — the whole file, before the module existed

```
$ uv run pytest tests/infrastructure/test_check_telemetry.py -v
ImportError while importing test module '.../tests/infrastructure/test_check_telemetry.py'.
Traceback:
tests/infrastructure/test_check_telemetry.py:27: in <module>
    from research_team.infrastructure.persistence.check_telemetry import (
E   ModuleNotFoundError: No module named 'research_team.infrastructure.persistence.check_telemetry'
=========================== short test summary info ============================
ERROR tests/infrastructure/test_check_telemetry.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
```

### The unimplemented status, proved load-bearing

Temporarily stored unimplemented bindings with `status="ran"`:

```
$ uv run pytest tests/infrastructure/test_check_telemetry.py -k unimplemented_binding_is_stored -v
>       assert by_name["shared.no_such_check"].status == "unimplemented"
E       AssertionError: assert 'ran' == 'unimplemented'
E         - unimplemented
E         + ran
=========================== short test summary info ============================
FAILED tests/infrastructure/test_check_telemetry.py::test_an_unimplemented_binding_is_stored_as_unimplemented
================== 1 failed, 2 passed, 14 deselected in 0.24s ==================
```

### The blind insert, proved load-bearing

Temporarily replaced `_upsert`'s load-then-mutate with
`await self._rows.save(CheckOutcomeRow(id=row_id, **fields))`:

```
$ uv run pytest tests/infrastructure/test_check_telemetry.py -k redelivering -v
>       assert {row.decision for row in stored} == {"reject"}
E       AssertionError: assert {None} == {'reject'}
E         Extra items in the left set:
E         None
E         Extra items in the right set:
E         'reject'
=========================== short test summary info ============================
FAILED tests/infrastructure/test_check_telemetry.py::test_redelivering_a_review_alone_does_not_erase_its_decision
======================= 1 failed, 17 deselected in 1.99s =======================
```

In the same run, `test_replaying_a_review_twice_leaves_one_row_per_check`
**passed** against the blind insert. That is the evidence behind the plan
correction above.

### The `caught_up` divergence, proved load-bearing

Temporarily replaced `caught_up` with `CorpusRunner`'s global-position form:

```
$ uv run pytest tests/infrastructure/test_check_telemetry.py -k caught_up -v
>       raise TimeoutError(f"did not reach {target} within {timeout}s")
E       TimeoutError: did not reach Position(store_id='sqlite:/tmp/pytest-of-ty/pytest-1088/
E       test_caught_up_returns_with_ot0/test.db', key=(3,)) within 2.0s

research_team/infrastructure/persistence/check_telemetry.py:412: TimeoutError
=========================== short test summary info ============================
FAILED tests/infrastructure/test_check_telemetry.py::test_caught_up_returns_with_other_aggregate_types_in_the_store
======================= 1 failed, 16 deselected in 2.39s =======================
```

Exactly the symptom the plan named: a timeout whose message says nothing about
the cause. The test uses `timeout=2.0` so a regression costs two seconds rather
than ten.

### Step 6 — green

```
$ uv run pytest tests/infrastructure/test_check_telemetry.py -q
..................                                                       [100%]
18 passed in 3.02s
```

### Step 7 — the neighbouring read-model tests

```
$ uv run pytest tests/infrastructure/test_read_model.py \
      tests/infrastructure/test_corpus_read_model.py \
      tests/infrastructure/test_topic_read_model.py -q
.............................................                            [100%]
45 passed in 4.25s
```

## Ruff, repository-wide

First run caught one E501 and the matching format difference in the new module
(a 96-column `_upsert` call); both fixed, then:

```
$ uv run ruff check .
All checks passed!
check exit=0
$ uv run ruff format --check .
213 files already formatted
format exit=0
```

## The old-database test

`test_a_database_written_before_check_outcomes_existed_gains_the_table` creates
a database containing an unrelated table, closes it, then opens
`CheckTelemetryStore` against it and writes and reads a row.

Stated plainly rather than overclaimed: **this test passes against the current
code and would also pass with `executescript` in place of `apply_schema`,**
because this change *adds* a table and `CREATE TABLE IF NOT EXISTS` handles
that case correctly on its own. What `apply_schema` buys is the next change —
a field added to `CheckOutcomeRow` against a database that already has the
table, which is precisely the `SessionSummaryRow` incident. The test cannot
exercise that today because there is no earlier version of this row to have
been written by. It is here so the path is the reconciling one before anyone
needs it, and so the next person adding a field has a place to extend.

## Flagged rather than fixed

- **`check_name` is a hand-off, not a local detail.** Task 5's adapter and any
  future SQL against this table must use it. Repeated here because the spec,
  the event and the CLI all say `check`.
- **No composition wiring.** `CheckTelemetryRunner` is constructed by nothing;
  that is Task 5 Step 6. Nothing starts or stops it yet, so no existing test
  could notice if it were broken at startup.
- **`read_models.py`'s `CorpusStore.open` still uses raw `executescript`.** Out
  of scope here and untouched. It is the same latent bug `apply_schema` exists
  to prevent, one file over.
- **Not run:** the full pytest suite, vitest, `npm run verify`, per instruction.
  None of the files another agent is editing were read or touched.
