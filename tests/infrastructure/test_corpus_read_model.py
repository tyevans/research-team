"""The corpus read model: the half of the corpus layer that can be read.

The aggregate deliberately holds no text, so these tests are the ones that say
retrieval works at all. The tightest of them is the round-trip: every span
offset downstream is computed against the text this table hands back, so if the
table is lossy in any byte, every citation in every course artifact is wrong
and nothing else in the system would notice.
"""

from uuid import uuid4

import pytest
from eventsource.adapters.memory.readmodels import InMemoryReadModelRepository

from research_team.domain.corpus import (
    Corpus,
    DocumentRecord,
    DropSourceDocument,
    StoreSourceDocument,
)
from research_team.infrastructure.persistence.event_store import build_corpus_repository
from research_team.infrastructure.persistence.read_models import (
    CorpusDocumentRow,
    CorpusProjection,
    CorpusRunner,
    CorpusStore,
)

ADVERSARIAL_TEXTS = [
    pytest.param("plain ascii", id="ascii"),
    pytest.param("line one\nline two\n", id="newlines"),
    pytest.param("windows\r\nline\r\nendings\r\n", id="crlf"),
    pytest.param("trailing whitespace   \n\n\n", id="trailing-whitespace"),
    pytest.param("café naïve 你好 مرحبا", id="non-ascii"),
    pytest.param("emoji \U0001f9ea\U0001f4da and ZWJ \U0001f469‍\U0001f4bb", id="emoji"),
    pytest.param("nul-adjacent \x01\x02 control bytes", id="control-chars"),
    pytest.param("quote ' and \" and backslash \\ and %s and ?", id="sql-metacharacters"),
    pytest.param("x" * 200_000, id="very-long"),
    pytest.param("", id="empty"),
]
"""Chosen rather than generated.

`hypothesis` is a dev dependency and this is a natural property, but a `@given`
over a function-scoped SQLite fixture is an error in hypothesis and working
around it means one database shared across examples, which trades the thing
being tested (a real round-trip through a real connection) for the generator.
These cases name the actual hazards -- encoding, line endings, SQL
metacharacters, size -- and a failure points at which one.
"""


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
def projection(rows) -> CorpusProjection:
    return CorpusProjection(rows)


async def _project(projection, events) -> None:
    for event in events:
        await projection.handle(event)


async def test_a_stored_document_is_retrievable_by_project_and_source(projection, rows):
    project_id = uuid4()
    await _project(
        projection,
        _events(
            project_id,
            StoreSourceDocument(
                corpus_id=project_id,
                source_id="s1",
                text="the body",
                uri="https://x/1",
                title="One",
            ),
        ),
    )

    row = await rows.get(CorpusDocumentRow.row_id(project_id, "s1"))
    assert row is not None
    assert (row.project_id, row.source_id) == (project_id, "s1")
    assert row.text == "the body"
    assert row.uri == "https://x/1"
    assert row.title == "One"


async def test_the_row_id_separates_the_same_source_id_in_different_projects(projection, rows):
    """Source ids are chosen per project and will collide across them.

    A row key that is only the source id would let one project's re-ingest
    overwrite another's document, silently.
    """
    first, second = uuid4(), uuid4()
    await _project(
        projection,
        _events(first, StoreSourceDocument(corpus_id=first, source_id="s1", text="mine")),
    )
    await _project(
        projection,
        _events(second, StoreSourceDocument(corpus_id=second, source_id="s1", text="yours")),
    )

    assert (await rows.get(CorpusDocumentRow.row_id(first, "s1"))).text == "mine"
    assert (await rows.get(CorpusDocumentRow.row_id(second, "s1"))).text == "yours"


async def test_superseding_a_source_leaves_exactly_one_row(projection, rows):
    """Supersession is an update, not an append.

    The aggregate treats a re-store as a revision of one document; if the table
    grew a row per revision, `list` would show the same source twice and the
    reader would have no way to tell which is current.
    """
    project_id = uuid4()
    await _project(
        projection,
        _events(
            project_id,
            StoreSourceDocument(corpus_id=project_id, source_id="s1", text="v1"),
            StoreSourceDocument(corpus_id=project_id, source_id="s1", text="v2 revised"),
        ),
    )

    found = await rows.find(None)
    assert len(found) == 1
    assert found[0].text == "v2 revised"
    assert found[0].char_count == len("v2 revised")


async def test_a_dropped_document_is_no_longer_returned(projection, rows):
    project_id = uuid4()
    await _project(
        projection,
        _events(
            project_id,
            StoreSourceDocument(corpus_id=project_id, source_id="s1", text="body"),
            DropSourceDocument(source_id="s1", reason="paywalled stub"),
        ),
    )

    row = await rows.get(CorpusDocumentRow.row_id(project_id, "s1"))
    assert row.dropped_reason == "paywalled stub"


async def test_storing_over_a_dropped_source_makes_it_readable_again(projection, rows):
    """Matches the aggregate: storing asserts presence and clears the reason.

    If the projection kept `dropped_reason` set, a re-ingested document would
    stay invisible to every reader while the aggregate insisted it was there.
    """
    project_id = uuid4()
    await _project(
        projection,
        _events(
            project_id,
            StoreSourceDocument(corpus_id=project_id, source_id="s1", text="v1"),
            DropSourceDocument(source_id="s1", reason="wrong paper"),
            StoreSourceDocument(corpus_id=project_id, source_id="s1", text="v2"),
        ),
    )

    row = await rows.get(CorpusDocumentRow.row_id(project_id, "s1"))
    assert row.dropped_reason is None
    assert row.text == "v2"


async def test_rebuilding_from_an_empty_table_reproduces_the_same_rows(rows):
    """The log is truth and this table is derived -- demonstrated, not assumed.

    Everything downstream assumes a corrupted table can be thrown away, which
    is only safe if a replay lands in the same place.
    """
    project_id = uuid4()
    events = _events(
        project_id,
        StoreSourceDocument(
            corpus_id=project_id, source_id="s1", text="v1", uri="https://x/1"
        ),
        StoreSourceDocument(corpus_id=project_id, source_id="s2", text="other", title="Two"),
        StoreSourceDocument(corpus_id=project_id, source_id="s1", text="v2 revised"),
        DropSourceDocument(source_id="s2", reason="duplicate"),
    )

    await _project(CorpusProjection(rows), events)
    first = {
        row.id: row.model_dump(exclude={"created_at", "updated_at", "version"})
        for row in await rows.find(None)
    }

    rebuilt_rows = InMemoryReadModelRepository(CorpusDocumentRow)
    await _project(CorpusProjection(rebuilt_rows), events)
    second = {
        row.id: row.model_dump(exclude={"created_at", "updated_at", "version"})
        for row in await rebuilt_rows.find(None)
    }

    assert first == second


@pytest.mark.parametrize("text", ADVERSARIAL_TEXTS)
async def test_text_round_trips_byte_exactly(db_path, text):
    """The load-bearing guarantee of the whole corpus layer.

    Span offsets are computed against what comes back out of here. A single
    normalised newline shifts every offset after it, and nothing downstream
    could tell the difference between a shifted quote and a wrong one.
    """
    project_id = uuid4()
    store = await CorpusStore.open(db_path)
    try:
        for event in _events(
            project_id, StoreSourceDocument(corpus_id=project_id, source_id="s1", text=text)
        ):
            await store.projection.handle(event)

        document = await store.get(project_id, "s1")
        assert document is not None
        assert document.text == text
        assert document.char_count == len(text)
    finally:
        await store.close()


async def test_the_table_is_created_on_open(db_path):
    """No migration step to forget: opening the store is enough."""
    store = await CorpusStore.open(db_path)
    try:
        assert await store.list(uuid4()) == []
    finally:
        await store.close()


async def test_documents_outlive_the_process(db_path):
    project_id = uuid4()
    events = _events(
        project_id,
        StoreSourceDocument(corpus_id=project_id, source_id="s1", text="remembered"),
    )

    store = await CorpusStore.open(db_path)
    for event in events:
        await store.projection.handle(event)
    await store.close()

    reopened = await CorpusStore.open(db_path)
    try:
        assert (await reopened.get(project_id, "s1")).text == "remembered"
    finally:
        await reopened.close()


async def test_listing_carries_metadata_and_never_text(db_path):
    """A listing must not drag whole corpora through memory.

    `list` returns `DocumentRecord`, the aggregate's own no-text shape, so the
    guarantee is structural: there is no field for the text to arrive in.
    """
    project_id = uuid4()
    store = await CorpusStore.open(db_path)
    try:
        for event in _events(
            project_id,
            StoreSourceDocument(
                corpus_id=project_id,
                source_id="s1",
                text="a body",
                uri="https://x/1",
                title="One",
            ),
            StoreSourceDocument(
                corpus_id=project_id, source_id="s2", text="another body", note="skim only"
            ),
        ):
            await store.projection.handle(event)

        listed = await store.list(project_id)

        assert "text" not in DocumentRecord.model_fields
        assert [record.source_id for record in listed] == ["s1", "s2"]
        assert listed[0].title == "One"
        assert listed[0].char_count == len("a body")
        assert listed[1].note == "skim only"
    finally:
        await store.close()


async def test_get_and_list_both_refuse_a_dropped_document(db_path):
    """The drop is recorded, but a dropped source is not a readable one.

    Serving text for a document somebody excluded is how an excluded source
    ends up cited.
    """
    project_id = uuid4()
    store = await CorpusStore.open(db_path)
    try:
        for event in _events(
            project_id,
            StoreSourceDocument(corpus_id=project_id, source_id="s1", text="kept"),
            StoreSourceDocument(corpus_id=project_id, source_id="s2", text="dropped"),
            DropSourceDocument(source_id="s2", reason="paywalled stub"),
        ):
            await store.projection.handle(event)

        assert await store.get(project_id, "s2") is None
        assert [record.source_id for record in await store.list(project_id)] == ["s1"]
    finally:
        await store.close()


async def test_one_project_cannot_read_another_projects_documents(db_path):
    project_id, other = uuid4(), uuid4()
    store = await CorpusStore.open(db_path)
    try:
        for event in _events(
            project_id, StoreSourceDocument(corpus_id=project_id, source_id="s1", text="mine")
        ):
            await store.projection.handle(event)

        assert await store.get(other, "s1") is None
        assert await store.list(other) == []
    finally:
        await store.close()


async def test_dropping_a_source_with_no_row_is_an_error(projection):
    """A missing row means events arrived out of order or the table was cut.

    The aggregate rejects dropping an unknown source, so this cannot be a
    legitimate stream -- and inventing a row for it would hide the drift.
    """
    project_id = uuid4()
    events = _events(
        project_id,
        StoreSourceDocument(corpus_id=project_id, source_id="s1", text="body"),
        DropSourceDocument(source_id="s1", reason="mistake"),
    )

    with pytest.raises(LookupError, match="s1"):
        await projection.handle(events[-1])


async def test_the_runner_follows_the_log(db_path, store, publisher):
    project_id = uuid4()
    runner = CorpusRunner(store, db_path, publisher)
    await runner.start()
    try:
        corpus = Corpus(project_id)
        corpus.execute(
            StoreSourceDocument(
                corpus_id=corpus.aggregate_id, source_id="s1", text="followed", title="One"
            )
        )
        await build_corpus_repository(store, publisher).save(corpus)

        await runner.caught_up()
        assert (await runner.get(project_id, "s1")).text == "followed"
        assert [record.title for record in await runner.list(project_id)] == ["One"]
    finally:
        await runner.stop()


async def test_a_rebuild_reproduces_the_table_from_the_log(db_path, store, publisher):
    """The repair for drift, over a real store rather than a repository double.

    A rebuild that quietly left the checkpoint in place would resume over an
    empty table and look like success until someone read from it.
    """
    project_id = uuid4()
    runner = CorpusRunner(store, db_path, publisher)
    await runner.start()
    try:
        corpus = Corpus(project_id)
        corpus.execute(
            StoreSourceDocument(corpus_id=corpus.aggregate_id, source_id="s1", text="v1")
        )
        corpus.execute(
            StoreSourceDocument(
                corpus_id=corpus.aggregate_id, source_id="s1", text="v2 revised"
            )
        )
        corpus.execute(
            StoreSourceDocument(
                corpus_id=corpus.aggregate_id, source_id="s2", text="dropped later"
            )
        )
        corpus.execute(DropSourceDocument(source_id="s2", reason="duplicate"))
        await build_corpus_repository(store, publisher).save(corpus)
        await runner.caught_up()
        before = await runner.list(project_id)

        await runner.rebuild()

        assert await runner.list(project_id) == before
        assert (await runner.get(project_id, "s1")).text == "v2 revised"
        assert await runner.get(project_id, "s2") is None
    finally:
        await runner.stop()


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
        assert await reopened.list(uuid4()) == []
    finally:
        await reopened.close()
