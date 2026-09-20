from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eventsource import StreamId, collect
from redstring import (
    InMemoryChunkStore,
    document_stream,
    rank_chunks,
    tokenize,
)

from research_team.application.knowledge import KnowledgeError, SourceRef
from research_team.infrastructure.knowledge import redstring_adapter


@pytest.mark.asyncio
async def test_ingest_reports_what_it_extracted(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    report = await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    assert report.source_id == "notes"
    assert report.entity_count >= 1
    assert report.domain == "encyclopedia_wiki"


@pytest.mark.asyncio
async def test_indexing_a_document_writes_retrievable_passages(tmp_path, build_adapter):
    """`index` runs with no `provider`/`embeddings` at all -- it must still work
    with the fixture's `fake_provider()` sitting unused, which is the point:
    nothing about indexing touches a model.
    """
    project_id = uuid4()
    chunk_store = InMemoryChunkStore(dimension=8)
    knowledge, _, _ = build_adapter(tmp_path, project_id, chunks=chunk_store)

    await knowledge.index(
        SourceRef(source_id="doc-1", text="Acme Corp builds rockets in Texas.")
    )

    terms = tokenize("Acme")
    candidates = await chunk_store.lexical_candidates(terms, project_id, 10)
    assert list(rank_chunks(terms, candidates, 10))


@pytest.mark.asyncio
async def test_the_quotable_corpus_is_chunked_small_enough_to_rank(tmp_path, build_adapter):
    """A long document becomes several chunks, not one.

    Chunk size is a retrieval parameter, not a storage detail. BM25 discounts
    a term matched inside a long document and does not discount it inside a
    short one, and a source takes its best chunk -- so the same term in the
    same document ranks differently depending only on how it was cut.
    stark-bench measured whole-document against sliding-1000-500 on one corpus
    and model: +0.071 dense, +0.072 lexical, +0.070 hybrid, with the gain 1.7x
    larger on the longest third of documents.

    Fails with the switch reverted: `BoundaryPreferenceChunker` at its
    defaults cuts at 3,000 characters, so this 2,700-character document is a
    single chunk and the discount applies to all of it.

    The ceiling is 1,100 rather than 1,000 because `MarkdownTableChunker`
    prepends a header to a chunk of table rows, which this document has none
    of -- the slack is there so a table document does not fail a test about
    window size for a reason that has nothing to do with it.

    **The sentences are varied, and an earlier version's were not.** It used
    `"The quick brown fox jumps over the lazy dog. " * 60`, where overlapping
    windows produce byte-identical text -- and chunk ids are content-addressed
    over `(source_id, text)`, so those rows collapse to one on upsert. The
    count it asserted was therefore part window size and part deduplication,
    and it broke on a redstring bump that changed neither: removing the
    redundant tail chunk took the surviving distinct texts from 4 to 3. A test
    about how small the windows are must not be readable as a test about how
    many of them happen to differ.
    """
    project_id = uuid4()
    chunk_store = InMemoryChunkStore(dimension=8)
    knowledge, _, _ = build_adapter(tmp_path, project_id, chunks=chunk_store)
    text = "".join(f"Sentence {n} says something entirely of its own. " for n in range(80))

    await knowledge.index(SourceRef(source_id="doc-1", text=text))

    chunks = await chunk_store.get_by_source("doc-1", project_id)

    assert len(chunks) >= 4, f"one long document should be several chunks, got {len(chunks)}"
    assert max(len(chunk.text) for chunk in chunks) <= 1_100


@pytest.mark.asyncio
async def test_indexing_the_same_document_twice_writes_nothing_the_second_time(
    tmp_path, build_adapter
):
    """`record_chunking` refuses a repeat under the same signature, so a
    re-index over an unchanged corpus is free rather than duplicating every
    passage. Without the shared event store (see `RedstringKnowledge.index`)
    it would not be -- the repeat is recognised from the recorded signature,
    not from the store's contents.

    **Counts the writes rather than the passages**, and the distinction is the
    whole test. An earlier version asserted `get_by_source` returned the same
    number of chunks both times; it passed with `event_store` deleted from the
    `index_documents` call, because `ChunkProjection` writes through
    `replace_source` and replacing a source with an identical re-chunking
    leaves the count untouched. That version could not observe the failure it
    was named for -- every passage rewritten while `documents_skipped` read 0.
    Proved red on 2026-08-14 by removing `event_store=self._event_store`: this
    version fails with 2 writes against the expected 1, the earlier one still
    passed.
    """
    project_id = uuid4()
    writes = []

    class CountingChunkStore(InMemoryChunkStore):
        """`replace_source` is the only method `ChunkProjection` calls (its own
        docstring says so: one of the port's nine), so counting it counts every
        write indexing can make."""

        async def replace_source(self, source_id, tenant_id, chunks):
            writes.append(source_id)
            return await super().replace_source(source_id, tenant_id, chunks)

    chunk_store = CountingChunkStore(dimension=8)
    knowledge, _, _ = build_adapter(tmp_path, project_id, chunks=chunk_store)
    source = SourceRef(source_id="doc-1", text="Acme Corp builds rockets in Texas.")

    await knowledge.index(source)
    await knowledge.index(source)

    assert writes == ["doc-1"]


@pytest.mark.asyncio
async def test_indexing_with_no_chunk_store_configured_is_a_no_op(tmp_path, build_adapter):
    """`chunks=None` is `AGENT_CHUNK_STORE=none`. Indexing must not raise over a
    feature that is off -- the same shape `ProjectGraphs.chunks` uses for
    "chunking is off" (see its docstring).
    """
    project_id = uuid4()
    knowledge, _, _ = build_adapter(tmp_path, project_id)

    await knowledge.index(
        SourceRef(source_id="doc-1", text="Acme Corp builds rockets in Texas.")
    )


@pytest.mark.asyncio
async def test_storing_a_document_indexes_it_without_extracting(tmp_path, build_adapter):
    """Indexing must not be conditional on extraction having run: `store_source`
    never extracts, and a document worth reading is worth finding passages in
    regardless. This is what makes `RedstringKnowledge._store_document` the
    right hook rather than `ingest` alone.
    """
    project_id = uuid4()
    chunk_store = InMemoryChunkStore(dimension=8)
    knowledge, _, _ = build_adapter(tmp_path, project_id, chunks=chunk_store)

    await knowledge.store_source(
        SourceRef(source_id="doc-1", text="Acme Corp builds rockets in Texas.")
    )

    terms = tokenize("Acme")
    candidates = await chunk_store.lexical_candidates(terms, project_id, 10)
    assert list(rank_chunks(terms, candidates, 10))


@pytest.mark.asyncio
async def test_ingest_appends_the_extraction_to_the_document_stream(tmp_path, build_adapter):
    """The event is the record; the graph is derived from it.

    **Counted by type, and it used to be counted by length.** This asserted
    `len(envelopes) == 1`, which was true only because the stream happened to
    carry nothing else: `index` was a no-op with no chunk store configured, and
    `build_graph` was given no event store so it persisted nothing. Both
    changed with the co-mention repair, and the length assertion started
    failing on a `DocumentChunked` that is supposed to be there.

    Counting `DocumentExtracted` is what the docstring above always meant, and
    it is the assertion that would catch the ripple most likely to be left in
    by mistake: `build_graph` appends the extraction through its own repository
    now, so an `ingest` that *also* appends `built.event` by hand -- which is
    what this adapter did before it was given an event store -- would put two
    on the stream.

    **Measured on 2026-08-22, and it does not put two on the stream.** With the
    hand-append restored beside `build_graph`'s own, **38 of 56 tests in this
    module failed** and this was not the interesting one: `built.event` is the
    same object, so the second append carries an `event_id` the store already
    holds and `SQLiteEventStore` raises `DuplicateEventError` on the UNIQUE
    constraint. Every ingest fails, loudly, with a message about
    `events.event_id` and nothing about a double append.

    That is worth knowing and it does not make this assertion redundant: an
    in-memory store, or a variant that rebuilt the event rather than re-using
    it, would take both -- and then the only surviving symptom is the count
    this test takes.
    """
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    stream = document_stream(tenant_id=project_id, source_id="notes")
    envelopes = await collect(store.read_stream(stream))
    by_type = [type(envelope.event).__name__ for envelope in envelopes]
    assert by_type.count("DocumentExtracted") == 1, by_type
    assert "DocumentChunked" in by_type, (
        "the chunking is what carries the entity links; a stream without it is "
        "the state the co-mention channel was dead in"
    )


@pytest.mark.asyncio
async def test_a_blank_source_id_is_rejected(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="   ", text="anything"))


@pytest.mark.asyncio
async def test_an_oversized_document_is_refused_before_extraction(tmp_path, build_adapter):
    from research_team.infrastructure.knowledge.redstring_adapter import (
        MAX_DOCUMENT_CHARS,
    )

    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError, match="limit"):
        await adapter.ingest(SourceRef(source_id="huge", text="x" * (MAX_DOCUMENT_CHARS + 1)))

    stream = document_stream(tenant_id=project_id, source_id="huge")
    assert await collect(store.read_stream(stream)) == []


#: One entity, named identically in two documents, each with a *different*
#: neighbour. That difference is the whole point: entity ids are namespaced per
#: document by `redstring.extraction.mapping.entity_id_for`, so the two
#: neighbours are two ids no matter what they are called, and the neighbour sets
#: of the duplicate pair are disjoint by construction.
_BREED_IN_CANADA = {
    "entities": [
        {"name": "Nova Scotia Duck Tolling Retriever", "entity_type": "concept"},
        {"name": "Canada", "entity_type": "concept"},
    ],
    "relationships": [
        {
            "source_name": "Nova Scotia Duck Tolling Retriever",
            "target_name": "Canada",
            "relationship_type": "ORIGINATES_IN",
        }
    ],
}

_BREED_AND_HUNTING = {
    "entities": [
        {"name": "Nova Scotia Duck Tolling Retriever", "entity_type": "concept"},
        {"name": "Duck hunting", "entity_type": "concept"},
    ],
    "relationships": [
        {
            "source_name": "Nova Scotia Duck Tolling Retriever",
            "target_name": "Duck hunting",
            "relationship_type": "USED_FOR",
        }
    ],
}


#: What the adjudicator says when it is asked. One verdict, because the
#: identical-name pair is the only thing that should ever reach the band --
#: `zip(strict=True)` upstream turns a count mismatch into "no answer", so a
#: second candidate arriving here would show up as a failed merge rather than
#: as a silently mis-paired verdict.
_SAYS_THEY_ARE_THE_SAME = {
    "verdicts": [
        {"same": True, "confidence": 0.99, "reason": "the same dog breed, named identically"}
    ]
}


# `test_one_entity_named_the_same_in_two_documents_becomes_one_node` lived
# here from PR #84 until the floor it depended on was deleted. It is now two
# tests in `test_embedded_consolidation.py` -- one showing the pair merging on
# three-feature evidence, one showing it staying two nodes on two -- because
# the single test could no longer say which of those it was pinning. The
# fixtures it used stay here; both modules read them.


@pytest.mark.asyncio
async def test_a_provider_failure_records_no_extraction(tmp_path, build_adapter):
    """No extraction is appended, and the caller gets an error it can render.

    The corpus write is a separate guarantee and deliberately does survive
    this -- see `test_the_document_survives_a_failed_extraction`.
    """

    class Failing:
        async def complete(self, *args, **kwargs):
            raise RuntimeError("endpoint down")

    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id, provider=Failing())

    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="notes", text="Ada Lovelace."))

    stream = document_stream(tenant_id=project_id, source_id="notes")
    assert await collect(store.read_stream(stream)) == []


@pytest.fixture
def captured_documents(monkeypatch):
    """Records every `SourceDocument` the adapter hands to `build_graph`.

    The citation fields are asserted against the document rather than the
    `IngestReport`, which carries none of them and so would pass whether or
    not they were ever set -- the exact bug these tests exist to catch.
    """

    documents = []
    real_build_graph = redstring_adapter.build_graph

    async def recording_build_graph(document, **kwargs):
        documents.append(document)
        return await real_build_graph(document, **kwargs)

    monkeypatch.setattr(redstring_adapter, "build_graph", recording_build_graph)
    return documents


@pytest.mark.asyncio
async def test_citation_fields_reach_the_source_document(
    tmp_path, build_adapter, captured_documents
):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(
        SourceRef(
            source_id="notes",
            text="Ada Lovelace worked with Charles Babbage.",
            uri="https://example.test/ada",
            title="Ada Lovelace",
            published_at="1843-07-10",
        )
    )

    document = captured_documents[0]
    assert document.uri == "https://example.test/ada"
    assert document.title == "Ada Lovelace"
    assert document.published_at == datetime(1843, 7, 10, tzinfo=UTC)


@pytest.mark.asyncio
async def test_a_source_without_citation_fields_leaves_them_unset(
    tmp_path, build_adapter, captured_documents
):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    document = captured_documents[0]
    assert document.uri is None
    assert document.title is None
    assert document.published_at is None
    assert "published_at" not in document.metadata


@pytest.mark.asyncio
async def test_an_unparseable_date_is_kept_verbatim_rather_than_dropped(
    tmp_path, build_adapter, captured_documents
):
    """An unreadable date must not cost us the document, nor the string itself."""
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    report = await adapter.ingest(
        SourceRef(
            source_id="notes",
            text="Ada Lovelace worked with Charles Babbage.",
            published_at="sometime last spring",
        )
    )

    assert report.entity_count >= 1
    document = captured_documents[0]
    assert document.published_at is None
    assert document.metadata["published_at"] == "sometime last spring"


@pytest.mark.asyncio
async def test_a_timestamp_with_a_zone_is_accepted(
    tmp_path, build_adapter, captured_documents
):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(
        SourceRef(
            source_id="notes",
            text="Ada Lovelace worked with Charles Babbage.",
            published_at="2026-08-05T12:30:00Z",
        )
    )

    assert captured_documents[0].published_at == datetime(2026, 8, 5, 12, 30, tzinfo=UTC)


def _corpus_events(store, project_id):
    """The corpus stream's events, read directly rather than via a projection.

    The read model for the corpus is built in a separate workstream; reading
    the log keeps these assertions independent of it, and the log is the
    thing B12 is actually about -- a projection could be rebuilt, a missing
    event could not.
    """
    return collect(store.read_stream(StreamId(project_id, "Corpus")))


@pytest.mark.asyncio
async def test_ingest_keeps_the_source_text(tmp_path, build_adapter):
    """After `remember` the system holds the document, not just a graph about it.

    The guarantee the corpus layer exists to provide: extraction used to be
    handed the text and drop it, leaving a graph whose every claim named a
    source nothing could produce.
    """
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(
        SourceRef(
            source_id="notes",
            text="Ada Lovelace worked with Charles Babbage.",
            uri="https://example.test/ada",
            title="Ada Lovelace",
            published_at="sometime last spring",
            note="for the timeline",
        )
    )

    envelopes = await _corpus_events(store, project_id)
    assert len(envelopes) == 1
    stored = envelopes[0].event
    assert type(stored).__name__ == "CorpusDocumentStored"
    assert stored.source_id == "notes"
    assert stored.text == "Ada Lovelace worked with Charles Babbage."
    assert stored.uri == "https://example.test/ada"
    assert stored.title == "Ada Lovelace"
    # Verbatim, unlike redstring's `published_at`: the corpus event is the
    # archival copy, so it keeps what the source said even when it is prose.
    assert stored.published_at == "sometime last spring"
    assert stored.note == "for the timeline"


@pytest.mark.asyncio
async def test_the_document_survives_a_failed_extraction(tmp_path, build_adapter):
    """Store first, extract second -- and a failed extraction keeps the text."""

    class Failing:
        async def complete(self, *args, **kwargs):
            raise RuntimeError("endpoint down")

    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id, provider=Failing())

    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="notes", text="Ada Lovelace."))

    envelopes = await _corpus_events(store, project_id)
    assert [e.event.text for e in envelopes] == ["Ada Lovelace."]
    extraction = document_stream(tenant_id=project_id, source_id="notes")
    assert await collect(store.read_stream(extraction)) == []


@pytest.mark.asyncio
async def test_nothing_is_stored_when_the_document_is_refused(tmp_path, build_adapter):
    """The size and id guards run before the corpus write, not after."""
    from research_team.infrastructure.knowledge.redstring_adapter import (
        MAX_DOCUMENT_CHARS,
    )

    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="huge", text="x" * (MAX_DOCUMENT_CHARS + 1)))
    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="  ", text="Ada Lovelace."))

    assert await _corpus_events(store, project_id) == []
