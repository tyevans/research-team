"""The definition cache: generated text and the citations backing it.

Nothing here folds an event -- unlike the corpus and session tables, there is
definition-generated event for this store to project. `DefinitionService`
writes through this store's `put`, and `EntityDefinitionProjection` marks
rows through `mark_stale`/`delete`; the store itself reads no events.

These tests only exercise the store: a value
round-trips through SQLite exactly, and a database that predates this table
gains it without a query ever raising.
"""

import json
from uuid import uuid4

import aiosqlite

from research_team.infrastructure.persistence.read_models import (
    CorpusStore,
    EntityDefinitionRow,
    EntityDefinitionStore,
)


def _row(project_id, entity_id, **overrides) -> EntityDefinitionRow:
    fields = {
        "id": EntityDefinitionRow.row_id(project_id, entity_id),
        "project_id": project_id,
        "entity_id": entity_id,
        "text": "A protein that folds RNA.",
        "citations": json.dumps([{"source_id": "doc-1", "start": 0, "end": 26}]),
        "model": "test-model",
        "generated_at": "2026-08-14T00:00:00+00:00",
        "stale": False,
    }
    fields.update(overrides)
    return EntityDefinitionRow(**fields)


async def test_a_definition_round_trips_with_its_citations(db_path):
    project_id, entity_id = uuid4(), uuid4()
    store = await EntityDefinitionStore.open(db_path)
    try:
        await store.put(_row(project_id, entity_id))
        got = await store.get(project_id, entity_id)
        assert got.text == "A protein that folds RNA."
        assert json.loads(got.citations)[0]["source_id"] == "doc-1"
        assert got.model == "test-model"
    finally:
        await store.close()


async def test_an_unknown_entity_answers_none_not_a_raise(db_path):
    store = await EntityDefinitionStore.open(db_path)
    try:
        assert await store.get(uuid4(), uuid4()) is None
    finally:
        await store.close()


async def test_stale_round_trips_as_a_real_bool_not_an_integer(db_path):
    """`stale` is stored as SQLite's 0/1. `model_validate` on the way back out
    is what turns that into an actual `bool` -- if a repository ever bypassed
    validation (`model_construct`, a raw cursor read), this would start
    returning `1`, which is truthy in Python and wrong in JSON, and nothing
    else here would catch it. `is True`/`is False` is the assertion that
    would fail on either -- `== True` would not, since `1 == True`.
    """
    project_id, entity_id = uuid4(), uuid4()
    store = await EntityDefinitionStore.open(db_path)
    try:
        await store.put(_row(project_id, entity_id, stale=True))
        got = await store.get(project_id, entity_id)
        assert got.stale is True

        other_entity = uuid4()
        await store.put(_row(project_id, other_entity, stale=False))
        got_other = await store.get(project_id, other_entity)
        assert got_other.stale is False
    finally:
        await store.close()


async def test_one_projects_definition_is_not_returned_for_another(db_path):
    entity_id = uuid4()
    project_a, project_b = uuid4(), uuid4()
    store = await EntityDefinitionStore.open(db_path)
    try:
        await store.put(_row(project_a, entity_id))
        assert await store.get(project_b, entity_id) is None
    finally:
        await store.close()


async def test_marking_stale_leaves_the_text_and_citations_untouched(db_path):
    project_id, entity_id = uuid4(), uuid4()
    store = await EntityDefinitionStore.open(db_path)
    try:
        await store.put(_row(project_id, entity_id))
        await store.mark_stale(project_id, entity_id)
        got = await store.get(project_id, entity_id)
        assert got.stale is True
        assert got.text == "A protein that folds RNA."
    finally:
        await store.close()


async def test_marking_an_unknown_entity_stale_is_a_noop_not_an_error(db_path):
    """Task 8's invalidation projection reacts to graph events, not to
    whether a definition happens to have been generated yet -- an entity
    with no cached definition is the ordinary case, not drift, so this must
    not raise the way `CorpusProjection._require` does for a genuine
    aggregate invariant.
    """
    store = await EntityDefinitionStore.open(db_path)
    try:
        await store.mark_stale(uuid4(), uuid4())  # does not raise
    finally:
        await store.close()


async def test_deleting_removes_the_row(db_path):
    project_id, entity_id = uuid4(), uuid4()
    store = await EntityDefinitionStore.open(db_path)
    try:
        await store.put(_row(project_id, entity_id))
        await store.delete(project_id, entity_id)
        assert await store.get(project_id, entity_id) is None
    finally:
        await store.close()


async def test_deleting_an_unknown_entity_is_a_noop_not_an_error(db_path):
    store = await EntityDefinitionStore.open(db_path)
    try:
        await store.delete(uuid4(), uuid4())  # does not raise
    finally:
        await store.close()


async def test_a_database_written_before_definitions_existed_gains_the_table(db_path):
    """`CREATE TABLE IF NOT EXISTS` does nothing to a database that already
    exists, and every query against a missing table answers 500 while every
    test on a fresh database passes -- the incident `apply_schema` exists to
    prevent, recorded in `test_a_database_written_before_a_field_existed_gains_its_column`
    (`test_summary_store.py`) and its corpus sibling in
    `test_corpus_read_model.py`. This is that test for `entity_definitions`.

    A fresh database proves nothing here, because a fresh one already has
    every table `apply_schema` knows about. `CorpusStore.open` is used to
    build the "old" database precisely because it does NOT create
    `entity_definitions` -- that is what makes this database genuinely
    predate the table, not a stand-in for one.
    """
    old = await CorpusStore.open(db_path)
    await old.close()

    async with aiosqlite.connect(db_path) as connection:
        tables = {
            row[0]
            for row in await (
                await connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
    assert "entity_definitions" not in tables

    store = await EntityDefinitionStore.open(db_path)
    try:
        assert await store.get(uuid4(), uuid4()) is None  # not a raise
    finally:
        await store.close()


async def test_staling_keeps_the_repository_bookkeeping_a_save_would_have_done(db_path):
    """B74 replaced `mark_stale`'s read-modify-write with a hand-written
    `UPDATE`, and this is the bill for that: `save` maintains `updated_at` and
    `version` and skips soft-deleted rows, and a statement written by hand can
    silently stop doing any of the three. A row staled through this path has to
    be indistinguishable from one staled through `save`, or optimistic locking
    quietly stops counting.

    **This is not a test of the lost update B74 is about, and no test here is.**
    That property -- a `put` landing between the old code's read and its write
    keeping its text -- needs two writers inside one call, and every way of
    forcing that in this harness measures the harness: re-entering the store's
    own `aiosqlite.Connection` deadlocks its worker thread, and a second
    connection meets `database is locked` under *both* implementations, because
    the competing write is injected mid-statement either way. Tried both on
    2026-08-29 and rejected both. What is left is the reasoning -- an `UPDATE`
    naming one column cannot revert a column it does not name -- plus this test
    of the part that is observable.
    """
    project_id, entity_id = uuid4(), uuid4()
    store = await EntityDefinitionStore.open(db_path)
    await store.put(_row(project_id, entity_id, text="first"))

    before = await _bookkeeping(store, project_id, entity_id)
    await store.mark_stale(project_id, entity_id)
    after = await _bookkeeping(store, project_id, entity_id)

    row = await store.get(project_id, entity_id)
    assert row is not None
    assert row.stale is True
    assert row.text == "first", "staling must not touch a column it was not asked about"
    assert after["version"] == before["version"] + 1
    assert after["updated_at"] > before["updated_at"]
    await store.close()


async def test_staling_an_entity_nobody_has_a_definition_for_is_a_no_op(db_path):
    """The ordinary case, and the one the invalidation projection is in most of
    the time -- most entities have never had a definition generated. It has to
    not raise, or routine graph activity lands in the DLQ.

    Would pass with the change reverted: the old read-modify-write returned
    early on a missing row. Kept because the `UPDATE` reaches the same answer a
    different way -- zero rows matched -- and nothing else asserts it.
    """
    store = await EntityDefinitionStore.open(db_path)
    await store.mark_stale(uuid4(), uuid4())
    await store.close()


async def test_staling_under_the_wrong_project_leaves_the_row_alone(db_path):
    """`project_id` is in the `WHERE` as well as inside the row id.

    **It would pass with that clause deleted**, and saying so is the point.
    The pair is baked into `row_id`, so a call under the wrong project computes
    an id that matches no row and stales nothing whether or not `project_id` is
    in the `WHERE`. There is no input reachable through this class that
    separates the two. The clause is defence against a caller that reaches the
    table by some other route -- `get` carries the identical check for the
    identical unreachable reason -- and this test records the behaviour rather
    than proving the clause earns its keep.
    """
    project_id, entity_id = uuid4(), uuid4()
    store = await EntityDefinitionStore.open(db_path)
    await store.put(_row(project_id, entity_id))

    await store.mark_stale(uuid4(), entity_id)

    row = await store.get(project_id, entity_id)
    assert row is not None
    assert row.stale is False
    await store.close()


async def _bookkeeping(store, project_id, entity_id) -> dict:
    """`version` and `updated_at` are the repository's own columns; the model
    does not carry them, so they are read straight out of the table."""
    cursor = await store._connection.execute(
        f"SELECT version, updated_at FROM {EntityDefinitionRow.table_name()} WHERE id = ?",
        (str(EntityDefinitionRow.row_id(project_id, entity_id)),),
    )
    try:
        version, updated_at = await cursor.fetchone()
        return {"version": version, "updated_at": updated_at}
    finally:
        await cursor.close()
