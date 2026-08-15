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
from redstring import DocumentExtracted

from research_team.domain.corpus import (
    Corpus,
    CorpusDocumentDropped,
    CorpusDocumentStored,
    CorpusMediaStored,
    DropSourceDocument,
    StoreSourceDocument,
    TextRecord,
)
from research_team.infrastructure.persistence.event_store import build_corpus_repository
from research_team.infrastructure.persistence.read_models import (
    CorpusDocumentRow,
    CorpusMediaRow,
    CorpusProjection,
    CorpusRunner,
    CorpusStore,
    to_record,
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
def media_rows() -> InMemoryReadModelRepository:
    return InMemoryReadModelRepository(CorpusMediaRow)


@pytest.fixture
def projection(rows, media_rows) -> CorpusProjection:
    return CorpusProjection(rows, media_rows)


@pytest.fixture
async def corpus_store(db_path):
    """A real `CorpusStore`, for the media tests -- which drive the
    projection through `corpus_store.projection.handle` and read back
    through `corpus_store.get_media`/`list_all`, both of which are only on
    the store, not on the bare `InMemoryReadModelRepository` fixtures above.
    """
    store = await CorpusStore.open(db_path)
    try:
        yield store
    finally:
        await store.close()


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

    await _project(CorpusProjection(rows, InMemoryReadModelRepository(CorpusMediaRow)), events)
    first = {
        row.id: row.model_dump(exclude={"created_at", "updated_at", "version"})
        for row in await rows.find(None)
    }

    rebuilt_rows = InMemoryReadModelRepository(CorpusDocumentRow)
    await _project(
        CorpusProjection(rebuilt_rows, InMemoryReadModelRepository(CorpusMediaRow)), events
    )
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

    `list` returns `DocumentListing`, whose `record` is the aggregate's own
    no-text shape, so the guarantee is structural: there is no field for the
    text to arrive in. The listing wraps the record rather than widening it
    precisely so that stays true as read-side facts are added beside it.
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

        assert "text" not in TextRecord.model_fields
        assert [listing.record.source_id for listing in listed] == ["s1", "s2"]
        assert listed[0].record.title == "One"
        assert listed[0].record.char_count == len("a body")
        assert listed[1].record.note == "skim only"
        # Stored is not extracted. Both are False here because no
        # `DocumentExtracted` has been handled, which is the state every
        # document sits in between being kept and being queued.
        assert [listing.extracted for listing in listed] == [False, False]
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
        listed = await store.list(project_id)
        assert [listing.record.source_id for listing in listed] == ["s1"]
    finally:
        await store.close()


async def test_get_with_include_dropped_returns_a_dropped_documents_text(db_path):
    """`CorpusEditor.restore` is the one caller that needs a dropped
    document's own bytes back, to re-store them unchanged. `include_dropped`
    exists for exactly that: the default stays False (proved by the previous
    test, which would fail here if it did not), and this is the opt-in path.
    """
    project_id = uuid4()
    store = await CorpusStore.open(db_path)
    try:
        for event in _events(
            project_id,
            StoreSourceDocument(corpus_id=project_id, source_id="s1", text="dropped"),
            DropSourceDocument(source_id="s1", reason="paywalled stub"),
        ):
            await store.projection.handle(event)

        assert await store.get(project_id, "s1") is None
        row = await store.get(project_id, "s1", include_dropped=True)
        assert row is not None
        assert row.text == "dropped"
        assert row.dropped_reason == "paywalled stub"
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
        assert [listing.record.title for listing in await runner.list(project_id)] == ["One"]
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
        assert await reopened.list(uuid4()) == []
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


async def test_a_stored_media_event_lands_as_a_row(corpus_store) -> None:
    """Assert the row, not the call.

    An assertion that the projection "handled" the event, or that a request
    returned 200, passes with the media handler deleted entirely: an event no
    projection handles counts as APPLIED. The row is the only thing that does
    not.
    """
    project_id = uuid4()
    await corpus_store.projection.handle(
        CorpusMediaStored(
            aggregate_id=project_id,
            source_id="v1",
            sha256="a" * 64,
            media_type="video/mp4",
            byte_count=999,
            title="A talk",
        )
    )
    row = await corpus_store.get_media(project_id, "v1")
    assert row is not None
    assert row.sha256 == "a" * 64
    assert row.byte_count == 999
    assert row.media_type == "video/mp4"
    assert row.title == "A talk"


async def test_dropping_media_marks_the_media_row(corpus_store) -> None:
    """One drop event, two tables. Fails if `_on_dropped` only ever looked in
    `corpus_documents` -- in which case a dropped video keeps listing as live
    and the console offers to drop it again forever."""
    project_id = uuid4()
    await corpus_store.projection.handle(_media_stored(project_id, "v1"))
    await corpus_store.projection.handle(
        CorpusDocumentDropped(aggregate_id=project_id, source_id="v1", reason="wrong talk")
    )
    assert await corpus_store.get_media(project_id, "v1") is None
    dropped = await corpus_store.get_media(project_id, "v1", include_dropped=True)
    assert dropped is not None and dropped.dropped_reason == "wrong talk"


async def test_listing_returns_both_kinds_in_one_answer(corpus_store) -> None:
    """The Documents page renders one table.

    Fails if `list_all` queries only one table, which reads downstream as half
    a corpus -- and half a corpus looks exactly like a whole one.
    """
    project_id = uuid4()
    await corpus_store.projection.handle(
        CorpusDocumentStored(
            aggregate_id=project_id, source_id="s1", text="prose", sha256="b" * 64
        )
    )
    await corpus_store.projection.handle(_media_stored(project_id, "v1"))
    kinds = sorted(to_record(row).kind for row in await corpus_store.list_all(project_id))
    assert kinds == ["media", "text"]


async def test_a_replayed_media_event_rewrites_rather_than_duplicates(corpus_store) -> None:
    """Idempotent by overwrite, like both document handlers.

    Replay from a checkpoint that is behind must re-derive the same row rather
    than accumulate, because that is what makes `rebuild()` safe to reach for.
    """
    project_id = uuid4()
    await corpus_store.projection.handle(_media_stored(project_id, "v1"))
    await corpus_store.projection.handle(_media_stored(project_id, "v1"))
    rows = await corpus_store.list_all(project_id)
    assert len(rows) == 1


async def test_dropping_a_source_in_neither_table_still_raises(corpus_store) -> None:
    """The fallback in `_on_dropped` must still refuse an id that matches
    nothing, not silently succeed against an invented media row -- the same
    guarantee `test_dropping_a_source_with_no_row_is_an_error` gives for the
    document-only path, extended across both tables.
    """
    project_id = uuid4()
    with pytest.raises(LookupError, match="v1"):
        await corpus_store.projection.handle(
            CorpusDocumentDropped(aggregate_id=project_id, source_id="v1", reason="mistake")
        )
