"""The definition cache: generated text and the citations backing it.

Nothing here folds an event -- unlike the corpus and session tables, there is
no `DefinitionGenerated` for this store to project, because Task 8 owns that
projection and writes through this store's `put`/`mark_stale`/`delete` rather
than reading events itself. These tests only exercise the store: a value
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
