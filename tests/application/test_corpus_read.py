"""`CorpusReadPort` over a real `CorpusStore` and a real `FilesystemBlobStore`.

Real adapters rather than doubles, unlike `test_document_extraction.py`: what
is under test here is the join between two stores that agree on a
`source_id` but nothing else -- the corpus table for the claim, the blob
store for the bytes -- and a hand-written fake of either would have to
reimplement the exact behaviour (a missing row, a missing blob) this test
exists to check. `test_corpus_read_model.py` already covers the projection
in isolation; this covers what `ProjectCorpusReader` does with it.
"""

from uuid import uuid4

import pytest

from research_team.application.corpus_read import MediaHandle, SourceListing
from research_team.domain.corpus import Corpus, StoreSourceDocument, StoreSourceMedia
from research_team.infrastructure.persistence.blob_store import FilesystemBlobStore
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.infrastructure.persistence.read_models import CorpusStore


async def _bytes(payload: bytes):
    yield payload


@pytest.fixture
def project_id():
    return uuid4()


@pytest.fixture
def blob_store(tmp_path) -> FilesystemBlobStore:
    return FilesystemBlobStore(tmp_path / "blobs")


@pytest.fixture
async def corpus_store(db_path) -> CorpusStore:
    store = await CorpusStore.open(db_path)
    yield store
    await store.close()


@pytest.fixture
def reader(corpus_store, project_id, blob_store) -> ProjectCorpusReader:
    # `CorpusStore` rather than a full `CorpusRunner`: `ProjectCorpusReader`
    # calls `list_all`/`get`/`get_media`, all three of which are on the store
    # itself, and the runner above it only adds the subscription that keeps
    # the store following the log -- machinery this test drives directly
    # through `corpus_store.projection.handle`, the same shortcut
    # `test_corpus_read_model.py` takes.
    return ProjectCorpusReader(corpus_store, project_id, blob_store)


async def _store_text(reader: ProjectCorpusReader, source_id: str, text: str) -> None:
    """Store a text source, by driving the real aggregate and folding its
    event straight into the reader's own store -- the same round trip
    `CorpusRunner`'s subscription performs, minus the event log and the wait
    for it to catch up."""
    corpus = Corpus(reader._project_id)
    corpus.execute(
        StoreSourceDocument(corpus_id=reader._project_id, source_id=source_id, text=text)
    )
    for event in corpus.uncommitted_events:
        await reader._runner.projection.handle(event)


async def _store_media(reader: ProjectCorpusReader, source_id: str, payload: bytes) -> None:
    """Store a media source: the bytes go into the reader's own blob store
    first, exactly as `store_media` (task 5) will, so the digest the aggregate
    is told is one the blob store actually holds."""
    stat = await reader._blobs.put(_bytes(payload))
    corpus = Corpus(reader._project_id)
    corpus.execute(
        StoreSourceMedia(
            corpus_id=reader._project_id,
            source_id=source_id,
            sha256=stat.sha256,
            media_type="video/mp4",
            byte_count=stat.byte_count,
        )
    )
    for event in corpus.uncommitted_events:
        await reader._runner.projection.handle(event)


def _delete_the_blob_underneath(blob_store: FilesystemBlobStore, source_id: str) -> None:
    """Make a stored media record's bytes disappear without telling the corpus.

    `source_id` is unused -- deliberately. The blob store is addressed by
    digest, not by source id, and every test in this module stores at most one
    media blob, so removing everything under the store's root is exactly
    removing that one's bytes. A digest lookup here would just be
    `reader.read_media(source_id).record.sha256`, which is the very call this
    helper exists to leave answerable-but-dangling for.
    """
    for path in blob_store._root.rglob("*"):
        if path.is_file():
            path.unlink()


async def test_read_media_answers_none_for_a_source_that_does_not_exist(reader) -> None:
    """`None` is "nothing was ever stored here", distinct from a dangling
    reference below -- collapsing the two is exactly what this port's
    docstring says an operator pays for."""
    assert await reader.read_media("nope") is None


async def test_read_media_answers_a_handle_with_no_stat_when_the_bytes_are_gone(
    reader, blob_store
) -> None:
    """Three outcomes, not two -- and this is the one that matters.

    A record whose blob is missing is not the same as a source that was never
    stored, and a caller that could not tell them apart would report a
    dangling reference as a 404: an operator would go looking for an ingest
    that never happened instead of for bytes that went away.
    """
    await _store_media(reader, "v1", b"payload")
    _delete_the_blob_underneath(blob_store, "v1")
    handle = await reader.read_media("v1")
    assert handle is not None
    assert handle.stat is None


async def test_read_media_answers_a_handle_whose_open_streams_the_bytes_back(reader) -> None:
    """The working case, proven by actually reading through `open` -- a test
    that only checked `stat is not None` would pass even if `open` pointed at
    the wrong digest or nothing at all."""
    await _store_media(reader, "v1", b"payload")
    handle = await reader.read_media("v1")
    assert handle is not None
    assert handle.stat is not None
    assert handle.stat.byte_count == len(b"payload")
    collected = b""
    async for chunk in handle.open():
        collected += chunk
    assert collected == b"payload"


async def test_read_document_answers_none_for_a_media_source(reader) -> None:
    """It promises text, and a media source has none.

    Not an exception: `read_document`'s contract already reserves the exception
    for storage failure, and a model guessing at a source id is the expected
    case rather than a bug.
    """
    await _store_media(reader, "v1", b"payload")
    assert await reader.read_document("v1") is None


async def test_list_sources_returns_both_kinds(reader) -> None:
    """The whole reason `list_documents` was deleted rather than kept.

    Fails if `list_sources` queries only the documents table -- which is what
    the old method did, and which no caller could have noticed, because half a
    corpus renders exactly like a whole one.
    """
    await _store_text(reader, "s1", "prose")
    await _store_media(reader, "v1", b"payload")
    assert sorted(listing.record.kind for listing in await reader.list_sources()) == [
        "media",
        "text",
    ]


async def test_list_sources_reports_a_text_source_as_extracted_from_its_column(reader) -> None:
    """`extracted` on a `SourceListing` for a text source tracks the row's
    `extracted_at`, exactly as it did under the old `DocumentListing` name --
    this is the rename proving nothing about the fold moved with it."""
    await _store_text(reader, "s1", "prose")
    [listing] = await reader.list_sources()
    assert isinstance(listing, SourceListing)
    assert listing.extracted is False


async def test_list_sources_reports_a_media_source_as_never_extracted(reader) -> None:
    """Nothing extracts media yet, so the honest answer is `False` -- not an
    error, and not a value borrowed from a column the media table does not
    have. Fails if `list_sources` reaches for `extracted_at` on a media row,
    which would raise `AttributeError` rather than answer `False`."""
    await _store_media(reader, "v1", b"payload")
    [listing] = await reader.list_sources()
    assert listing.record.kind == "media"
    assert listing.extracted is False


async def test_read_media_handle_carries_the_media_record(reader) -> None:
    """The metadata a caller needs before deciding to stream anything.

    Fails if `read_media` builds its handle from the row rather than through
    `to_record`, or if `to_record` loses the mimetype or byte count on the way
    -- both of which would leave a working `open` beside a record that could
    not say what the bytes are, and the mimetype is what the eventual download
    route sets `Content-Type` from.
    """
    await _store_media(reader, "v1", b"payload")
    handle = await reader.read_media("v1")
    assert isinstance(handle, MediaHandle)
    assert handle.record.source_id == "v1"
    assert handle.record.media_type == "video/mp4"
    assert handle.record.byte_count == len(b"payload")
