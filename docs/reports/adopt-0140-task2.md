# Task 2: `apply_schema` takes the library's generator

## What changed

`research_team/infrastructure/persistence/read_models.py`

- Deleted `_column_definitions`, the regex over the generated DDL, and the
  `import re` that only it used.
- `apply_schema` now asks `generate_additive_migration(model, existing,
  dialect="sqlite")` for its statements. The reason it is not the library's
  `reconcile_read_model_schema` — a SQLAlchemy connection nothing here owns —
  is in a comment at the call site, so the next reader does not "upgrade" it.
- Added an empty-table recreate path. This is a deviation from the plan and is
  argued below; it is the only way the regression test survives the rewrite.
- `CorpusStore.open` calls `apply_schema(connection, CorpusDocumentRow)`
  instead of `executescript`. The hand-made project index stays, with a
  one-line comment saying `apply_schema` reconciles columns and not indexes.

Import paths, verified rather than trusted: `generate_additive_migration` comes
from `eventsource.adapters.sql.readmodel_schema` (also re-exported by
`eventsource.adapters.sql`), and `ReadModelSchemaMismatchError` from
`eventsource.ports.readmodels`. **Neither is exported at the `eventsource` top
level** — `hasattr(eventsource, "generate_additive_migration")` is `False`.

Tests added, both in files the plan named incorrectly (see below):

- `tests/infrastructure/test_summary_store.py`
  - `test_a_refused_reconcile_leaves_the_table_untouched`
  - `test_a_populated_table_gains_an_addable_column`
- `tests/infrastructure/test_corpus_read_model.py`
  - `test_a_corpus_database_written_before_a_field_existed_gains_its_column`

## Red, then green

### `test_a_refused_reconcile_leaves_the_table_untouched`

Red, against the loop it replaces:

```
>       assert "nickname" not in present, "the addable column landed before the refusal"
E       AssertionError: the addable column landed before the refusal
E       assert 'nickname' not in {'created_at', 'deleted_at', 'id', 'nickname', 'settled', 'updated_at', ...}

tests/infrastructure/test_summary_store.py:206: AssertionError
=========================== short test summary info ============================
FAILED tests/infrastructure/test_summary_store.py::test_a_refused_reconcile_leaves_the_table_untouched
======================= 1 failed, 5 deselected in 0.45s ========================
```

`owner` is absent and `nickname` is present: the table is half-widened, which
is the behaviour under test rather than a missing name.

**The first version of this test was a false red and is worth recording.** It
built the narrow table and reconciled immediately, with no rows in it — and
*both* columns arrived. SQLite accepts `NOT NULL` with no default on an empty
table. So the refusal the old comment called "the right refusal" only ever
happened on a database with data in it. The test now inserts a row first, and
says why in a comment.

### `test_a_corpus_database_written_before_a_field_existed_gains_its_column`

Red, against `CorpusStore.open`'s `executescript`:

```
>           assert "uri" in {row[1] for row in await columns.fetchall()}
E           AssertionError: assert 'uri' in {'char_count', 'created_at', 'deleted_at', 'dropped_reason', 'fetched_at', 'id', ...}

tests/infrastructure/test_corpus_read_model.py:446: AssertionError
=========================== short test summary info ============================
FAILED tests/infrastructure/test_corpus_read_model.py::test_a_corpus_database_written_before_a_field_existed_gains_its_column
1 failed, 24 deselected in 0.47s
```

### `test_a_populated_table_gains_an_addable_column`

No red: it passes against the previous implementation, and its docstring says
so. It exists because the refusal path now recreates an empty table, and every
other old-database test in the repository starts from a table with no rows —
nothing else would notice a branch that dropped data.

### Green

```
$ uv run pytest tests/infrastructure/test_corpus_read_model.py \
    tests/infrastructure/test_read_model.py \
    tests/infrastructure/test_topic_read_model.py \
    tests/infrastructure/test_check_telemetry.py \
    tests/infrastructure/test_summary_store.py -q
71 passed in 7.31s
```

`test_a_database_written_before_a_field_existed_gains_its_column` — the
regression surface named in `CLAUDE.md` — is in that run and passes.

## Ruff

```
$ uv run ruff check research_team/infrastructure/persistence/read_models.py \
    tests/infrastructure/test_summary_store.py tests/infrastructure/test_corpus_read_model.py
All checks passed!
$ uv run ruff format --check <same three>
3 files already formatted
```

Repo-wide, run immediately before committing:

```
$ uv run ruff check .
All checks passed!
$ uv run ruff format --check .
216 files already formatted
```

An earlier repo-wide run reported `I001` on
`research_team/domain/auto_research.py` and `research_team/domain/corpus.py`,
which Task 1 was editing at the time. Both are clean now.

## What the plan got wrong

1. **The file the tests go in.** The plan puts both new tests in
   `tests/infrastructure/test_read_model.py` and calls
   `test_a_database_written_before_a_field_existed_gains_its_column` its
   neighbour. That test is in `tests/infrastructure/test_summary_store.py`;
   `test_read_model.py` is about the projection and uses an in-memory
   repository, so nothing there touches a database file. The atomicity test
   went next to its actual neighbour.

2. **The rewrite as specified breaks the regression test.** This is the
   substantive one. The plan's `apply_schema` body was applied exactly as
   written and produced:

   ```
   E  eventsource.ports.readmodels.exceptions.ReadModelSchemaMismatchError:
      Cannot reconcile session_summary_rows: project_id is required and has no
      default, so it cannot be added to a table that may already have rows
   FAILED tests/infrastructure/test_summary_store.py::test_a_database_written_before_a_field_existed_gains_its_column
   ```

   `generate_additive_migration` refuses a required column with no default
   *categorically*; SQLite refuses it only when the table has rows. The two are
   not equivalent, and the gap is exactly the `SessionSummaryRow.project_id`
   incident the function exists to repair — a required column added to a table
   that is, in the case that matters, empty.

   The spec treats the difference as pure gain ("raises before returning any
   statement"). It is gain on a populated table and a straight loss of
   capability on an empty one.

   **What I did instead**, rather than leave the plan's version failing: on
   `ReadModelSchemaMismatchError`, check whether the table has a row. If it
   does, re-raise — the refusal is atomic, which is the gain the task is for.
   If it does not, `DROP TABLE` and recreate from `model_schema`. An empty read
   model table has nothing to lose, and it is derived data besides.

   This is a design decision beyond the plan and it is flagged here rather than
   buried: it widens `apply_schema` from "additive reconcile" to "additive
   reconcile, or recreate when the table is empty". The alternative was to give
   `project_id` a default, which would let a row exist without a project and is
   contradicted by the field's own docstring.

3. **`_column_definitions` was not at `read_models.py:245`** and `CorpusStore`
   not at `729` by the time this ran; line numbers in the plan and spec had
   already drifted. Nothing depended on them.

## Flagged, not fixed

- The empty-table recreate path has no test of its own beyond
  `test_a_database_written_before_a_field_existed_gains_its_column`, which
  reaches it incidentally (dropping `project_id` and reopening an empty
  database is exactly that path). A test naming the recreate directly would be
  better and belongs with whoever revisits this decision.
- `apply_schema` still issues its `ALTER`s one at a time without a transaction,
  so atomicity now rests on the generator refusing up front rather than on the
  database. Good enough while every statement is generated before any is run;
  worth knowing if a future path interleaves them.
