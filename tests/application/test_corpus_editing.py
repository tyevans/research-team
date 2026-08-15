"""The corpus's write side, driven the way the routes will drive it.

Doubles throughout, as in `test_document_extraction.py`, but the corpus side
of them is a real `Corpus` aggregate over a real `AggregateRepository` --
backed by `InMemoryEventStore` rather than SQLite. `drop`'s refusals (blank
reason, unknown source, empty corpus) are `decide`'s, not this module's, and a
hand-written fake would have to reimplement `decide` correctly to test that
they are *not* duplicated here. The event-sourced double proves the same rule
the real adapter runs.
"""

from uuid import UUID, uuid4

import pytest
from eventsource import CommandRejectedError
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.testing import InMemoryTestHarness

from research_team.application.corpus_editing import (
    CorpusEditor,
    DocumentExists,
)
from research_team.application.corpus_read import DocumentListing, StoredDocument
from research_team.application.document_extraction import UnknownDocument
from research_team.domain.corpus import Corpus, StoreSourceDocument


class FakeReader:
    """`CorpusReadPort` over the same in-memory `Corpus` the fake knowledge writes to.

    Reads `corpus.state.documents` directly rather than keeping a projection
    of its own: the state already carries every `DocumentRecord` the fold
    produces, and a second copy of that bookkeeping is exactly the kind of
    duplicate `CorpusReadPort`'s docstring warns would disagree with the fold
    eventually. `extracted` is always False -- nothing here exercises it.
    """

    def __init__(
        self,
        corpus: AggregateRepository[Corpus],
        project_id: UUID,
        texts: dict[str, str],
    ):
        self._corpus = corpus
        self._project_id = project_id
        self._texts = texts

    async def list_documents(self, *, include_dropped: bool = False) -> list[DocumentListing]:
        corpus = await self._corpus.load_or_create(self._project_id)
        return [
            DocumentListing(record=record, extracted=False)
            for record in corpus.state.documents.values()
            if include_dropped or record.dropped_reason is None
        ]

    async def read_document(self, source_id: str) -> StoredDocument | None:
        corpus = await self._corpus.load_or_create(self._project_id)
        record = corpus.state.documents.get(source_id)
        if record is None:
            return None
        return StoredDocument(record=record, text=self._texts[source_id])


class FakeKnowledge:
    """`KnowledgePort.store_source`, and nothing else -- `store` is all this task exercises.

    Executes `StoreSourceDocument` on the same repository `drop` uses, the way
    `RedstringKnowledge.store_source` executes it on the real one: the two
    paths this module's docstring describes reach one aggregate, and a fake
    that wrote text somewhere the aggregate never saw would not catch a
    `store` that forgot to keep the two in sync.
    """

    def __init__(
        self,
        corpus: AggregateRepository[Corpus],
        project_id: UUID,
        texts: dict[str, str],
    ):
        self._corpus = corpus
        self._project_id = project_id
        self._texts = texts

    async def store_source(self, source) -> None:
        corpus = await self._corpus.load_or_create(self._project_id)
        corpus.execute(
            StoreSourceDocument(
                corpus_id=self._project_id,
                source_id=source.source_id,
                text=source.text,
                uri=source.uri,
                title=source.title,
                published_at=source.published_at,
                note=source.note,
            )
        )
        await self._corpus.save(corpus)
        self._texts[source.source_id] = source.text


@pytest.fixture
def project_id() -> UUID:
    return uuid4()


@pytest.fixture
def corpus_repo() -> AggregateRepository[Corpus]:
    return AggregateRepository(InMemoryTestHarness().event_store, Corpus)


@pytest.fixture
def texts() -> dict[str, str]:
    return {}


@pytest.fixture
def reader(corpus_repo, project_id, texts) -> FakeReader:
    return FakeReader(corpus_repo, project_id, texts)


@pytest.fixture
def editor(corpus_repo, project_id, texts) -> CorpusEditor:
    async def open_knowledge(target_project_id: UUID) -> FakeKnowledge:
        return FakeKnowledge(corpus_repo, target_project_id, texts)

    return CorpusEditor(
        open_knowledge=open_knowledge,
        readers=lambda target_project_id: FakeReader(corpus_repo, target_project_id, texts),
        corpus=corpus_repo,
    )


async def test_store_puts_the_text_in_the_corpus(editor, reader, project_id):
    await editor.store(project_id, "s1", "hello", title="Hello")

    listing = await reader.list_documents()
    assert [row.record.source_id for row in listing] == ["s1"]
    assert listing[0].record.title == "Hello"


async def test_store_refuses_an_id_the_corpus_already_holds(editor, project_id):
    """Upload is creation. Superseding somebody's document silently is not
    what the word means, and the aggregate would allow it -- `decide` treats
    a repeat `source_id` as a revision -- so the refusal has to be here."""
    await editor.store(project_id, "s1", "hello")

    with pytest.raises(DocumentExists):
        await editor.store(project_id, "s1", "different")


async def test_drop_excludes_the_document_and_keeps_the_record(editor, reader, project_id):
    await editor.store(project_id, "s1", "hello")

    await editor.drop(project_id, "s1", "off topic")

    listing = await reader.list_documents(include_dropped=True)
    assert listing[0].record.dropped_reason == "off topic"
    assert await reader.list_documents() == []


async def test_drop_refuses_a_blank_reason(editor, project_id):
    """The refusal is the aggregate's, not this service's. Asserted here so
    that a future editor that validates ahead of the command -- and drifts
    from it -- fails rather than merely duplicating it."""
    await editor.store(project_id, "s1", "hello")

    with pytest.raises(CommandRejectedError):
        await editor.drop(project_id, "s1", "   ")


async def test_drop_refuses_a_source_the_corpus_does_not_hold(editor, project_id):
    await editor.store(project_id, "s1", "hello")

    with pytest.raises(CommandRejectedError):
        await editor.drop(project_id, "missing", "off topic")


async def test_drop_on_an_empty_corpus_is_unknown_not_rejected(editor, project_id):
    """A corpus with no documents has no stream, and `decide` answers "corpus
    is empty" for every command but a store. The route needs a 404 there, not
    a 409, so the editor turns that one case into `UnknownDocument`."""
    with pytest.raises(UnknownDocument):
        await editor.drop(project_id, "s1", "off topic")
