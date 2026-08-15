"""Extracting a document the corpus already holds, without going back to the network.

The thing this exists to prevent is a second ingest path that stores the
document differently from the first: a `SourceRef` rebuilt from the text alone
would drop the title, URI and publication date the original fetch established,
and the re-store would overwrite good provenance with none. Most of these
tests are about that.

Doubles rather than a real adapter throughout: `KnowledgePort.ingest` is
minutes of model time, and what is under test is which `SourceRef` reaches it.
"""

from uuid import uuid4

import pytest

from research_team.application.corpus_read import DocumentListing, StoredDocument
from research_team.application.document_extraction import DocumentExtractor, UnknownDocument
from research_team.application.knowledge import ExtractionNote, IngestReport, SourceRef
from research_team.domain import DocumentRecord


class Corpus:
    """One project's stored sources."""

    def __init__(self, *documents: tuple[DocumentRecord, str, bool]) -> None:
        self._documents = {record.source_id: (record, text) for record, text, _ in documents}
        self._extracted = {record.source_id: done for record, _, done in documents}

    async def list_documents(self, *, include_dropped: bool = False):
        return [
            DocumentListing(record=record, extracted=self._extracted[source_id])
            for source_id, (record, _) in self._documents.items()
        ]

    async def read_document(self, source_id: str):
        found = self._documents.get(source_id)
        if found is None:
            return None
        record, text = found
        return StoredDocument(record=record, text=text)


class Knowledge:
    """Records what it was asked to ingest, and reports one note if given a reporter."""

    def __init__(self) -> None:
        self.ingested: list[SourceRef] = []
        self.indexed: list[SourceRef] = []
        self.reports: list[ExtractionNote] = []

    async def index(self, source: SourceRef) -> None:
        self.indexed.append(source)

    async def ingest(self, source: SourceRef, *, report=None) -> IngestReport:
        self.ingested.append(source)
        if report is not None:
            report(ExtractionNote(source_id=source.source_id, stage="storing"))
            self.reports.append(ExtractionNote(source_id=source.source_id, stage="storing"))
        return IngestReport(
            source_id=source.source_id,
            entity_count=4,
            relationship_count=1,
            domain=None,
            domain_confidence=None,
        )


def _record(source_id: str, **overrides) -> DocumentRecord:
    fields = {
        "source_id": source_id,
        "sha256": "0" * 64,
        "char_count": 12,
    } | overrides
    return DocumentRecord(**fields)


def _extractor(corpus: Corpus, knowledge: Knowledge, *, reporters=None) -> DocumentExtractor:
    return DocumentExtractor(
        open_knowledge=lambda _project_id: _resolved(knowledge),
        corpus_readers=lambda _project_id: corpus,
        reporters=reporters,
    )


async def _resolved(value):
    return value


async def test_it_ingests_the_text_the_corpus_already_holds():
    corpus = Corpus((_record("s1"), "the stored text", False))
    knowledge = Knowledge()

    report = await _extractor(corpus, knowledge).extract(uuid4(), "s1")

    assert [source.text for source in knowledge.ingested] == ["the stored text"]
    assert report.entity_count == 4


async def test_it_carries_the_records_provenance_back_through():
    """The provenance survives the round trip, which is this module's whole point.

    Proved red by building the `SourceRef` from `source_id` and `text` alone:
    the ingest then re-stores the document with no title, no URI and no date,
    and every citation of it afterwards is uncheckable.
    """
    corpus = Corpus(
        (
            _record(
                "s1",
                uri="https://example.test/a",
                title="A Title",
                published_at="2019-04-01",
                note="worth keeping",
            ),
            "the stored text",
            False,
        )
    )
    knowledge = Knowledge()

    await _extractor(corpus, knowledge).extract(uuid4(), "s1")

    (source,) = knowledge.ingested
    assert source.uri == "https://example.test/a"
    assert source.title == "A Title"
    assert source.published_at == "2019-04-01"
    assert source.note == "worth keeping"


async def test_it_does_not_stamp_a_fetch_time_it_did_not_perform():
    """`fetched_at` means "read off the network", and this call reads a database."""
    corpus = Corpus((_record("s1"), "the stored text", False))
    knowledge = Knowledge()

    await _extractor(corpus, knowledge).extract(uuid4(), "s1")

    (source,) = knowledge.ingested
    assert source.fetched_at is None


async def test_an_unknown_document_raises_rather_than_ingesting_nothing():
    corpus = Corpus((_record("s1"), "the stored text", False))
    knowledge = Knowledge()

    with pytest.raises(UnknownDocument):
        await _extractor(corpus, knowledge).extract(uuid4(), "nope")

    assert knowledge.ingested == []


async def test_the_reporter_is_bound_to_the_project_being_extracted():
    """The queued extraction reports into the same pane the agent's `remember` does.

    Proved red by passing `report=None`: the pane then stays empty for the
    whole of a minutes-long extraction somebody just pressed a button to
    start, which is indistinguishable from nothing having happened.
    """
    corpus = Corpus((_record("s1"), "the stored text", False))
    knowledge = Knowledge()
    project_id = uuid4()
    asked: list = []

    def reporters(target_project_id):
        asked.append(target_project_id)
        return lambda note: None

    await _extractor(corpus, knowledge, reporters=reporters).extract(project_id, "s1")

    assert asked == [project_id]
    assert [note.source_id for note in knowledge.reports] == ["s1"]


async def test_unextracted_names_only_the_documents_with_no_graph():
    corpus = Corpus(
        (_record("s1"), "one", True),
        (_record("s2"), "two", False),
        (_record("s3"), "three", False),
    )

    pending = await _extractor(corpus, Knowledge()).unextracted(uuid4())

    assert pending == ("s2", "s3")


async def test_unextracted_is_empty_when_everything_has_a_graph():
    """Passes with the change reverted -- it asserts an absence.

    Kept because it is what makes "extract all" answer 0 rather than re-running
    a corpus that is already fully extracted, and that is the press people will
    make most often once they have used the button once.
    """
    corpus = Corpus((_record("s1"), "one", True), (_record("s2"), "two", True))

    assert await _extractor(corpus, Knowledge()).unextracted(uuid4()) == ()


async def test_reindex_puts_every_stored_document_through_indexing():
    """Including the ones that already have a graph.

    Extraction status says nothing about whether a document was *chunked* --
    the corpus this exists to repair was extracted normally and simply
    predates indexing -- so filtering on `extracted` here would skip exactly
    the documents that need it. Fails if `reindex` reuses `unextracted`.
    """
    corpus = Corpus(
        (_record("s1"), "one", True),
        (_record("s2"), "two", False),
    )
    knowledge = Knowledge()

    indexed = await _extractor(corpus, knowledge).reindex(uuid4())

    assert [source.source_id for source in knowledge.indexed] == ["s1", "s2"]
    assert [source.text for source in knowledge.indexed] == ["one", "two"]
    assert indexed == 2


async def test_reindex_carries_the_records_provenance_the_way_extract_does():
    """A chunk's citations are checked against the document they came from, so
    a `SourceRef` rebuilt from text alone would index passages whose source has
    no title or URI to show a reader. Fails if the ref is built from
    `source_id`/`text` only."""
    corpus = Corpus(
        (
            _record("s1", uri="https://example.test/a", title="A", published_at="2024-01-01"),
            "one",
            True,
        ),
    )
    knowledge = Knowledge()

    await _extractor(corpus, knowledge).reindex(uuid4())

    (source,) = knowledge.indexed
    assert source.uri == "https://example.test/a"
    assert source.title == "A"
    assert source.published_at == "2024-01-01"


async def test_reindex_ingests_nothing():
    """The repair is chunking, not extraction: `ingest` is minutes of model
    time per document and re-running it over a whole corpus is the cost this
    path exists to avoid. Fails if `reindex` calls `ingest`."""
    corpus = Corpus((_record("s1"), "one", False))
    knowledge = Knowledge()

    await _extractor(corpus, knowledge).reindex(uuid4())

    assert knowledge.ingested == []
