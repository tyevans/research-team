"""Tests for truncate, table migration, and extraction status projection
in the corpus read model.
"""

from uuid import uuid4

import pytest
from eventsource.adapters.memory.readmodels import InMemoryReadModelRepository
from redstring import DocumentExtracted

from research_team.domain.research.corpus import (
    Corpus,
    CorpusMediaStored,
    StoreSourceDocument,
)
from research_team.infrastructure.persistence.read_models import (
    CorpusDocumentRow,
    CorpusMediaRow,
    CorpusProjection,
    CorpusStore,
)


def _events(corpus_id, *commands):
    """Drive the aggregate rather than hand-building events.

    The projection has to agree with the fold, so the events it sees here are
    the ones `decide` actually produces -- including the digest it computes.
    """
    corpus = Corpus(corpus_id)
    for command in commands:
        corpus.execute(command)
    return list(corpus.uncommitted_events)


@pytest.fixture
def rows() -> InMemoryReadModelRepository:
    return InMemoryReadModelRepository(CorpusDocumentRow)


@pytest.fixture
def media_rows() -> InMemoryReadModelRepository:
    return InMemoryReadModelRepository(CorpusMediaRow)


@pytest.fixture
def projection(rows, media_rows) -> CorpusProjection:
    return CorpusProjection(rows, media_rows)


def _media_stored(project_id, source_id: str, **overrides) -> CorpusMediaStored:
    """A `CorpusMediaStored` with sane defaults, for tests that don't care
    about a specific field -- mirrors `_extracted`'s role below for
    `DocumentExtracted`.
    """
    fields = {
        "aggregate_id": project_id,
        "source_id": source_id,
        "sha256": "c" * 64,
        "media_type": "video/mp4",
        "byte_count": 123,
    }
    fields.update(overrides)
    return CorpusMediaStored(**fields)


async def test_truncate_empties_both_tables(db_path):
    """`truncate` must clear `corpus_media`, not only `corpus_documents`.

    Not an end-to-end rebuild test, deliberately -- one was tried first and
    rejected because it doesn't actually exercise the bug this guards
    against. `CorpusMediaRow.row_id` is a pure function of
    `(project_id, source_id)`, and `_on_media_stored` writes by
    load-and-mutate onto that same id. So a rebuild that replays the same
    events onto a media table `truncate` never cleared still converges to
    the identical final row through the ordinary overwrite path -- there is
    no revision or ordering of `CorpusMediaStored` events whose *result*
    would differ depending on whether `truncate` actually ran a `DELETE`
    against `corpus_media` first. Proved by trying it: with `truncate`'s
    second `DELETE` temporarily removed, a rebuild test built the same way
    as `test_a_rebuild_reproduces_the_table_from_the_log` still passed.

    So this asserts on `truncate`'s own effect instead of on a downstream
    replay that cannot distinguish it from a no-op. It does not exercise
    `rebuild()`'s wiring -- `test_a_rebuild_reproduces_the_table_from_the_log`
    already covers that a rebuild reaches `truncate` at all, and this is the
    other half: that `truncate`, once reached, is not a single `DELETE`.
    """
    store = await CorpusStore.open(db_path)
    try:
        project_id = uuid4()
        for event in _events(
            project_id, StoreSourceDocument(corpus_id=project_id, source_id="s1", text="body")
        ):
            await store.projection.handle(event)
        await store.projection.handle(_media_stored(project_id, "v1"))

        assert await store.get(project_id, "s1") is not None
        assert await store.get_media(project_id, "v1") is not None

        await store.truncate()

        assert await store.get(project_id, "s1") is None
        assert await store.get_media(project_id, "v1") is None
        assert await store.list_all(project_id, include_dropped=True) == []
    finally:
        await store.close()


async def test_a_corpus_database_written_before_a_field_existed_gains_its_column(db_path):
    """`CorpusStore.open` must reconcile the table, not only create it.

    It called `executescript` directly, which is `CREATE TABLE IF NOT EXISTS`
    and so does nothing to a table that already exists -- a field added to
    `CorpusDocumentRow` would never reach a database anybody already had, and
    every read of it would fail. That is the same defect
    `test_a_database_written_before_a_field_existed_gains_its_column` in
    `test_summary_store.py` records for `/sessions`, one store over, and this
    is that test against `CorpusStore`.

    Simulated by dropping `uri` back off, which is the shape of the problem: a
    table one field behind the model.
    """
    import aiosqlite

    store = await CorpusStore.open(db_path)
    await store.close()

    async with aiosqlite.connect(db_path) as connection:
        await connection.execute(
            f"ALTER TABLE {CorpusDocumentRow.table_name()} DROP COLUMN uri"
        )
        await connection.commit()

    reopened = await CorpusStore.open(db_path)
    try:
        columns = await reopened._connection.execute(
            f"PRAGMA table_info({CorpusDocumentRow.table_name()})"
        )
        assert "uri" in {row[1] for row in await columns.fetchall()}
        # And it still answers, which is the failure a schema check alone misses.
        assert await reopened.list_all(uuid4()) == []
    finally:
        await reopened.close()


def _extracted(project_id, source_id: str) -> DocumentExtracted:
    """The event redstring appends when a document's graph is written.

    Hand-built rather than driven through redstring, unlike `_events` above.
    The reason the aggregate is driven there is that the projection must agree
    with the fold and the digest is computed inside it; nothing here folds
    anything, and standing up an extraction to obtain one event would put a
    model provider in the way of a test about a column.
    """
    return DocumentExtracted(
        aggregate_id=uuid4(),
        tenant_id=project_id,
        source_id=source_id,
        entities=[],
        relationships=[],
        model_version="test",
    )


async def test_a_document_reads_as_extracted_once_its_graph_is_written(projection, rows):
    """The whole point of the column, over the two streams that decide it.

    `CorpusDocumentStored` and `DocumentExtracted` come from different
    aggregates and different categories; this passes only because the corpus
    subscription is unfiltered and dispatch is by event type.
    """
    project_id = uuid4()
    for event in _events(
        project_id, StoreSourceDocument(corpus_id=project_id, source_id="s1", text="a body")
    ):
        await projection.handle(event)
    assert (await rows.get(CorpusDocumentRow.row_id(project_id, "s1"))).extracted_at is None

    await projection.handle(_extracted(project_id, "s1"))

    assert (
        await rows.get(CorpusDocumentRow.row_id(project_id, "s1"))
    ).extracted_at is not None


async def test_extracting_a_document_this_corpus_never_stored_is_ignored(projection, rows):
    """Not drift, and so not an error.

    `_on_dropped` raises on a missing row because the aggregate refuses to drop
    what it does not hold, so the event could not legitimately exist. Nothing
    makes that true of extraction: it is another aggregate entirely, and every
    `DocumentExtracted` written before this table existed names a row that is
    not here. Raising would fill the DLQ with ordinary history and report drift
    that is not there.
    """
    project_id = uuid4()

    await projection.handle(_extracted(project_id, "never-stored"))

    assert await rows.get(CorpusDocumentRow.row_id(project_id, "never-stored")) is None


async def test_restoring_a_document_with_new_bytes_clears_its_extraction(projection, rows):
    """A graph about text the document no longer has is not a graph of it.

    Reading as unextracted puts the document back in front of the person who
    can requeue it. Identical bytes never reach here -- `_store_document`
    swallows those without appending -- so a store event always means the text
    changed.
    """
    project_id = uuid4()
    row_id = CorpusDocumentRow.row_id(project_id, "s1")
    for event in _events(
        project_id, StoreSourceDocument(corpus_id=project_id, source_id="s1", text="first")
    ):
        await projection.handle(event)
    await projection.handle(_extracted(project_id, "s1"))
    assert (await rows.get(row_id)).extracted_at is not None

    for event in _events(
        project_id, StoreSourceDocument(corpus_id=project_id, source_id="s1", text="revised")
    ):
        await projection.handle(event)

    assert (await rows.get(row_id)).extracted_at is None


async def test_one_projects_extraction_does_not_mark_anothers_document(projection, rows):
    """`tenant_id` is the project, and the row id is keyed on the pair.

    Source ids are chosen per project and collide across them -- `"s1"` is the
    obvious one -- so an extraction addressed by source id alone would mark
    whichever project's row it found first.
    """
    mine, theirs = uuid4(), uuid4()
    for project_id in (mine, theirs):
        for event in _events(
            project_id, StoreSourceDocument(corpus_id=project_id, source_id="s1", text="body")
        ):
            await projection.handle(event)

    await projection.handle(_extracted(mine, "s1"))

    assert (await rows.get(CorpusDocumentRow.row_id(mine, "s1"))).extracted_at is not None
    assert (await rows.get(CorpusDocumentRow.row_id(theirs, "s1"))).extracted_at is None
