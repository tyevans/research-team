"""Tests for media event projection and derived text / degradations in the
corpus read model.
"""

import json
from uuid import uuid4

import pytest

from research_team.domain.corpus import (
    UNREADABLE_DEGRADATIONS,
    CorpusDerivedTextStored,
    CorpusDocumentDropped,
    CorpusDocumentStored,
    CorpusMediaStored,
)
from research_team.infrastructure.persistence.read_models import (
    CorpusDocumentRow,
    CorpusStore,
    to_record,
)


@pytest.fixture
async def corpus_store(db_path):
    """A real `CorpusStore`, for the media tests -- which drive the
    projection through `corpus_store.projection.handle` and read back
    through `corpus_store.get_media`/`list_all`, both of which are only on
    the store, not on bare in-memory repository fixtures.
    """
    store = await CorpusStore.open(db_path)
    try:
        yield store
    finally:
        await store.close()


def _media_stored(project_id, source_id: str, **overrides) -> CorpusMediaStored:
    """A `CorpusMediaStored` with sane defaults, for tests that don't care
    about a specific field.
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


def _derived_text_stored(project_id, source_id: str, **overrides) -> CorpusDerivedTextStored:
    """A `CorpusDerivedTextStored` with sane defaults, mirroring `_media_stored`."""
    fields = {
        "aggregate_id": project_id,
        "source_id": source_id,
        "derived_from": "vid",
        "text": "[0:00:01.0] (speech) hello",
        "sha256": "deadbeef",
        "locator_map": (
            '[{"char_start": 0, "char_end": 26, '
            '"locator": {"kind": "time", "start_s": 1.0, "end_s": 2.0}}]'
        ),
        "perceived_with": "fingerprint123",
        "degradations": '["no vision model configured"]',
    }
    fields.update(overrides)
    return CorpusDerivedTextStored(**fields)


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


async def test_a_derived_source_lands_in_the_documents_table_with_its_map(
    corpus_store,
) -> None:
    """Asserts the row and the map, because an assertion that the projection
    "ran" passes with the handler deleted -- an event no projection handles
    counts as applied.
    """
    project_id = uuid4()
    await corpus_store.projection.handle(_derived_text_stored(project_id, "vid#perceived"))

    row = await corpus_store.get(project_id, "vid#perceived")
    assert row is not None
    assert row.derived_from == "vid"
    assert row.perceived_with == "fingerprint123"
    assert json.loads(row.locator_map)[0]["locator"]["start_s"] == 1.0
    assert row.text == "[0:00:01.0] (speech) hello"
    assert row.char_count == len("[0:00:01.0] (speech) hello")


async def test_a_fetched_document_leaves_the_derived_columns_null(corpus_store) -> None:
    """The columns are nullable and a plain document is what makes them so."""
    project_id = uuid4()
    await corpus_store.projection.handle(
        CorpusDocumentStored(
            aggregate_id=project_id, source_id="paper", text="prose", sha256="b" * 64
        )
    )
    row = await corpus_store.get(project_id, "paper")
    assert row is not None
    assert row.derived_from is None
    assert row.locator_map is None
    assert row.perceived_with is None
    assert row.degradations is None


async def test_to_record_carries_derivedness_back_out(corpus_store) -> None:
    project_id = uuid4()
    await corpus_store.projection.handle(
        _derived_text_stored(
            project_id,
            "vid#perceived",
            degradations='["a gap"]',
        )
    )
    row = await corpus_store.get(project_id, "vid#perceived")
    record = to_record(row)
    assert record.kind == "text"
    assert record.derived_from == "vid"
    assert record.perceived_with == "fingerprint123"
    assert record.degradations == ("a gap",)


async def test_an_unreadable_stored_degradations_reads_as_the_marker(corpus_store) -> None:
    """A row that predates or otherwise carries an unparsable `degradations`
    column must not read back as `()` -- `TextRecord.degradations` docstring
    says empty means a complete perception, and a column that could not be
    read is not that. The projection stores the domain's own
    `UNREADABLE_DEGRADATIONS` marker rather than nulling the column, so this
    case is indistinguishable from the one `_degradations_from` guards in the
    aggregate's own fold -- one string, one meaning, wherever it is read.
    """
    project_id = uuid4()
    await corpus_store.projection.handle(
        _derived_text_stored(project_id, "vid#perceived", degradations="not json")
    )
    row = await corpus_store.get(project_id, "vid#perceived")
    assert row is not None
    assert json.loads(row.degradations) == list(UNREADABLE_DEGRADATIONS)
    record = to_record(row)
    assert record.degradations == UNREADABLE_DEGRADATIONS
    assert record.degradations != ()


async def test_a_replayed_derived_text_event_rewrites_rather_than_duplicates(
    corpus_store,
) -> None:
    """Idempotent by overwrite, matching the media and document handlers."""
    project_id = uuid4()
    await corpus_store.projection.handle(_derived_text_stored(project_id, "vid#perceived"))
    await corpus_store.projection.handle(
        _derived_text_stored(project_id, "vid#perceived", text="revised transcript")
    )
    rows = await corpus_store.list_all(project_id)
    assert len(rows) == 1
    assert rows[0].text == "revised transcript"


def test_to_record_reads_a_wrong_shaped_degradations_column_as_the_marker() -> None:
    """`to_record` must not trust a stored `degradations` column any more than
    `_on_derived_text` trusts an incoming event -- a row is not an event, and
    nothing refuses a row's shape the way `decide` refuses an event's. Built
    by hand rather than through the projection precisely to bypass the
    write-time sanitizer and reach a row `_on_derived_text` would never
    itself produce, the way an earlier build's bug or a direct edit could.

    Guards against the failure a reviewer caught in `_degradations_from` one
    task ago and that a bare `tuple(json.loads(...))` on the read side would
    reintroduce here: well-formed JSON of the wrong shape silently becoming a
    tuple of dict keys, which is a plausible-looking degradation list nobody
    ever wrote.
    """
    project_id = uuid4()
    row = CorpusDocumentRow(
        id=CorpusDocumentRow.row_id(project_id, "vid#perceived"),
        project_id=project_id,
        source_id="vid#perceived",
        text="transcript",
        sha256="deadbeef",
        char_count=len("transcript"),
        derived_from="vid",
        # Well-formed JSON, wrong shape: an object, not a list of strings.
        # `tuple(json.loads(...))` would iterate its keys into `("a",)`.
        degradations='{"a": 1}',
    )
    record = to_record(row)
    assert record.degradations == UNREADABLE_DEGRADATIONS
    assert record.degradations != ("a",)


def test_to_record_reads_an_empty_degradations_column_as_a_complete_perception() -> None:
    """`[]` is a claim, not an absence, and reading it as the marker is a bug
    this file shipped.

    `to_record` decoded the column as
    `_decode_degradations(...) or UNREADABLE_DEGRADATIONS`, and
    `_decode_degradations("[]")` returns `()` -- falsy. So the *ordinary* case,
    a perception that missed nothing, fell through to
    `<degradations could not be read from the event>`, and every clean
    transcript carried a fabricated degradation all the way to the console
    (`presenters.py` -> `dto.ts`). Found on 2026-08-16 by the end-to-end test
    in `tests/integration/test_media_reaches_the_graph.py`; pinned here so the
    cheap test catches the regression rather than the expensive one.

    Both neighbouring cases are asserted in the same test because the whole
    defect is a collapse *between* them: a column that was never written
    (`None`) and one holding `[]` must both read as `()`, while the test above
    keeps the third case -- junk -- distinct from both. Proved red against the
    `or` form: this fails on the `"[]"` row and passes on the `None` one.
    """
    project_id = uuid4()

    def _row(degradations: str | None) -> CorpusDocumentRow:
        return CorpusDocumentRow(
            id=CorpusDocumentRow.row_id(project_id, "vid#perceived"),
            project_id=project_id,
            source_id="vid#perceived",
            text="transcript",
            sha256="deadbeef",
            char_count=len("transcript"),
            derived_from="vid",
            degradations=degradations,
        )

    assert to_record(_row("[]")).degradations == ()
    assert to_record(_row("[]")).degradations != UNREADABLE_DEGRADATIONS
    # A fetched document has no column at all, and reads the same way.
    assert to_record(_row(None)).degradations == ()
