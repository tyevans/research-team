"""The corpus's write side, driven the way the routes will drive it.

Doubles throughout, as in `test_document_extraction.py`, but the corpus side
of them is a real `Corpus` aggregate over a real `AggregateRepository` --
backed by `InMemoryEventStore` rather than SQLite. `drop`'s refusals (blank
reason, unknown source, empty corpus) are `decide`'s, not this module's, and a
hand-written fake would have to reimplement `decide` correctly to test that
they are *not* duplicated here. The event-sourced double proves the same rule
the real adapter runs.
"""

import hashlib
import inspect
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from eventsource import CommandRejectedError
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.testing import InMemoryTestHarness

from research_team.application.corpus_editing import (
    CorpusEditor,
    DocumentExists,
    NotDropped,
)
from research_team.application.corpus_read import SourceListing, StoredDocument
from research_team.application.document_extraction import UnknownDocument
from research_team.application.knowledge import MAX_DOCUMENT_CHARS, KnowledgeError, SourceRef
from research_team.domain.corpus import Corpus, StoreSourceDocument, StoreSourceMedia
from research_team.infrastructure.persistence.blob_store import FilesystemBlobStore


async def chunks(payload: bytes) -> AsyncIterator[bytes]:
    """A one-chunk stream -- `put` only needs an async iterator, not a real
    multi-chunk transfer, to exercise the digest and byte count it computes."""
    yield payload


class FakeReader:
    """`CorpusReadPort` over the same in-memory `Corpus` the fake knowledge writes to.

    Reads `corpus.state.documents` directly rather than keeping a projection
    of its own: the state already carries every `TextRecord` the fold
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

    async def list_sources(self, *, include_dropped: bool = False) -> list[SourceListing]:
        corpus = await self._corpus.load_or_create(self._project_id)
        return [
            SourceListing(record=record, extracted=False)
            for record in corpus.state.documents.values()
            if include_dropped or record.dropped_reason is None
        ]

    async def read_document(
        self, source_id: str, *, include_dropped: bool = False
    ) -> StoredDocument | None:
        corpus = await self._corpus.load_or_create(self._project_id)
        record = corpus.state.documents.get(source_id)
        if record is None:
            return None
        if record.dropped_reason is not None and not include_dropped:
            return None
        return StoredDocument(record=record, text=self._texts[source_id])


class FakeKnowledge:
    """`KnowledgePort.store_source` and `.index`, reproducing the one check
    that makes `store_source` unsafe for an edit.

    Executes `StoreSourceDocument` on the same repository `drop` uses, the way
    `RedstringKnowledge.store_source` executes it on the real one: the two
    paths this module's docstring describes reach one aggregate, and a fake
    that wrote text somewhere the aggregate never saw would not catch a
    `store` that forgot to keep the two in sync.

    The digest short-circuit below mirrors `_store_document` in
    `redstring_adapter.py`: a store whose text hashes to what `source_id`
    already holds is skipped. Without it, `test_a_metadata_only_revise_
    changes_the_title` would pass against a `revise` still routed through
    `store_source` -- the exact bug `CorpusEditor.revise` exists to avoid --
    and the test would be asserting nothing. Proved by temporarily reverting
    `revise` to call `store_source` and watching this test fail (see task
    report); it fails here because the digest matches and the title never
    moves, the same way it fails against the real adapter.
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
        self.indexed: list[SourceRef] = []

    async def store_source(self, source) -> None:
        corpus = await self._corpus.load_or_create(self._project_id)
        digest = hashlib.sha256(source.text.encode("utf-8")).hexdigest()
        if corpus.state.by_digest.get(digest) == source.source_id:
            return
        corpus.execute(
            StoreSourceDocument(
                corpus_id=self._project_id,
                source_id=source.source_id,
                text=source.text,
                uri=source.uri,
                title=source.title,
                published_at=source.published_at,
                note=source.note,
                fetched_at=source.fetched_at,
            )
        )
        await self._corpus.save(corpus)
        self._texts[source.source_id] = source.text

    async def index(self, source) -> None:
        self.indexed.append(source)


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
def knowledge(corpus_repo, project_id, texts) -> FakeKnowledge:
    # One instance, reused by `open_knowledge` below, rather than a fresh one
    # per call: `test_a_revise_reindexes` asserts against `.indexed`, and a
    # closure that built a new `FakeKnowledge` each time would scatter that
    # list across instances the test never sees.
    return FakeKnowledge(corpus_repo, project_id, texts)


@pytest.fixture
def blob_store(tmp_path) -> FilesystemBlobStore:
    return FilesystemBlobStore(tmp_path / "blobs")


@pytest.fixture
def editor(corpus_repo, project_id, texts, knowledge, blob_store) -> CorpusEditor:
    async def open_knowledge(target_project_id: UUID) -> FakeKnowledge:
        return knowledge

    return CorpusEditor(
        open_knowledge=open_knowledge,
        readers=lambda target_project_id: FakeReader(corpus_repo, target_project_id, texts),
        corpus=corpus_repo,
        blobs=blob_store,
    )


async def test_store_puts_the_text_in_the_corpus(editor, reader, project_id):
    await editor.store(project_id, "s1", "hello", title="Hello")

    listing = await reader.list_sources()
    assert [row.record.source_id for row in listing] == ["s1"]
    assert listing[0].record.title == "Hello"


async def test_store_refuses_an_id_the_corpus_already_holds(editor, project_id):
    """Upload is creation. Superseding somebody's document silently is not
    what the word means, and the aggregate would allow it -- `decide` treats
    a repeat `source_id` as a revision -- so the refusal has to be here."""
    await editor.store(project_id, "s1", "hello")

    with pytest.raises(DocumentExists):
        await editor.store(project_id, "s1", "different")


async def test_store_refuses_an_id_a_media_source_already_holds(
    editor, corpus_repo, project_id
):
    """One `source_id` namespace, so an upload cannot claim an id a video
    answers to.

    The check widened from `list_documents` to `list_sources` as part of
    removing the former, which made this refusal true without anyone asserting
    it. Fails if the check is ever narrowed back to text -- and the failure
    that would follow is not a crash: the upload would succeed, two records
    would answer to `v1`, and a citation naming it could not say which bytes
    it meant.

    Stores the media by executing on `corpus_repo` directly, which is the
    repository the editor and `FakeReader` share, because `store_media` does
    not exist yet (task 5). `CorpusState.documents` is keyed by `source_id`
    over `SourceRecord`, so the media record lands in the same dict the
    existence check reads.
    """
    corpus = await corpus_repo.load_or_create(project_id)
    corpus.execute(
        StoreSourceMedia(
            corpus_id=project_id,
            source_id="v1",
            sha256="0" * 64,
            media_type="video/mp4",
            byte_count=2048,
        )
    )
    await corpus_repo.save(corpus)

    with pytest.raises(DocumentExists):
        await editor.store(project_id, "v1", "text under a taken id")


async def test_drop_excludes_the_document_and_keeps_the_record(editor, reader, project_id):
    await editor.store(project_id, "s1", "hello")

    await editor.drop(project_id, "s1", "off topic")

    listing = await reader.list_sources(include_dropped=True)
    assert listing[0].record.dropped_reason == "off topic"
    assert await reader.list_sources() == []


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


async def test_a_metadata_only_revise_changes_the_title(editor, reader, project_id):
    """The test the design exists for.

    Against an implementation that routed edits through
    `KnowledgePort.store_source`, this fails: `_store_document` returns early
    when the text hashes to what the id already holds, so the title never
    moves and nothing raises. Reverting `revise` to `store_source` is the way
    to see it go red -- and was, before this test was trusted (see the task
    report for the observed failure).
    """
    await editor.store(project_id, "s1", "hello", title="Typo")

    await editor.revise(project_id, "s1", title="Fixed")

    listing = await reader.list_sources()
    assert listing[0].record.title == "Fixed"
    assert (await reader.read_document("s1")).text == "hello"


async def test_a_revise_reindexes(editor, knowledge, project_id):
    """Indexing rides on `_store_document`, which the direct command path
    bypasses. Nothing else here would notice: the corpus is correct either
    way, and the damage is the chunk store quoting text the document no
    longer contains -- invisible until a citation is checked."""
    await editor.store(project_id, "s1", "hello")
    knowledge.indexed.clear()

    await editor.revise(project_id, "s1", text="goodbye")

    assert [source.source_id for source in knowledge.indexed] == ["s1"]


async def test_a_revise_keeps_fetched_at(editor, reader, corpus_repo, project_id, texts):
    """`_store` executes `StoreSourceDocument` directly, whose `fetched_at`
    defaults to `None` -- a `revise` that forgot to carry the old value
    forward would silently overwrite it, the same way an omitted `uri` would,
    except nothing else here would notice: the corpus stays correct-looking
    and only the provenance of by-reference content is gone.

    Seeded by executing `StoreSourceDocument` on `corpus_repo` directly
    rather than through `editor.store`, because `store`'s own signature (task
    1) has no `fetched_at` parameter -- only the by-reference path that will
    set it in a later task does, and this test only needs a document that
    already carries one.
    """
    corpus = await corpus_repo.load_or_create(project_id)
    corpus.execute(
        StoreSourceDocument(
            corpus_id=project_id,
            source_id="s1",
            text="hello",
            fetched_at="2026-08-01T00:00:00+00:00",
        )
    )
    await corpus_repo.save(corpus)
    texts["s1"] = "hello"

    await editor.revise(project_id, "s1", title="Fixed")

    stored = await reader.read_document("s1")
    assert stored.record.fetched_at == "2026-08-01T00:00:00+00:00"


async def test_a_revise_keeps_the_text_when_none_is_given(editor, reader, project_id):
    await editor.store(project_id, "s1", "hello", title="Hello")

    await editor.revise(project_id, "s1", note="checked")

    stored = await reader.read_document("s1")
    assert stored.text == "hello"
    assert stored.record.note == "checked"


async def test_revise_refuses_an_unknown_source(editor, project_id):
    await editor.store(project_id, "s1", "hello")

    with pytest.raises(UnknownDocument):
        await editor.revise(project_id, "missing", title="x")


async def test_revise_refuses_text_over_the_length_cap(editor, project_id):
    """`decide` has no size opinion, and `revise` bypasses `store_source` --
    the one place that check normally lives -- so nothing upstream refuses
    this on its own. `MAX_DOCUMENT_CHARS` lives in `knowledge.py` precisely
    so `_store` can reach it without the application layer importing
    `redstring_adapter.py`.
    """
    await editor.store(project_id, "s1", "hello")

    with pytest.raises(KnowledgeError):
        await editor.revise(project_id, "s1", text="x" * (MAX_DOCUMENT_CHARS + 1))


async def test_restore_puts_a_dropped_document_back(editor, reader, project_id):
    await editor.store(project_id, "s1", "hello", title="Hello")
    await editor.drop(project_id, "s1", "off topic")

    await editor.restore(project_id, "s1")

    listing = await reader.list_sources()
    assert [row.record.source_id for row in listing] == ["s1"]
    assert listing[0].record.title == "Hello"
    assert listing[0].record.dropped_reason is None


async def test_restore_refuses_a_document_that_is_not_dropped(editor, project_id):
    await editor.store(project_id, "s1", "hello")

    with pytest.raises(NotDropped):
        await editor.restore(project_id, "s1")


async def test_store_media_puts_the_bytes_in_the_blob_store(editor, blob_store, project_id):
    """A successful store leaves the bytes retrievable under their digest.

    **This test does not hold the ordering, despite what an earlier draft of it
    claimed.** Measured by reordering `store_media` to issue the command first
    and stream after: this test still passed, because on a store that succeeds
    the blob is there at the end either way. The ordering is held by
    `test_a_rejected_store_leaves_the_blob_and_no_record` below, which was the
    only failure under that reordering. What is left here is still worth
    asserting -- that `put` was called at all, with the whole stream -- and
    `byte_count` is the part that would fail if a chunk were dropped.
    """
    await editor.store_media(project_id, "v1", chunks(b"payload"), "video/mp4")

    stat = await blob_store.stat(hashlib.sha256(b"payload").hexdigest())
    assert stat is not None and stat.byte_count == 7


async def test_a_rejected_store_leaves_the_blob_and_no_record(
    editor, blob_store, corpus_repo, project_id
):
    """The orphan is accepted, deliberately. Assert it rather than pretend.

    Documents the cost so nobody later "fixes" it by reordering the writes and
    reintroduces the dangling reference -- and it is the *only* test that would
    catch that reordering, measured by making it: the blob assertion below goes
    from present to None, and no other test in this file moves.

    The record half is asserted too, because the name promises it: the text
    record `s1` already held must survive unchanged rather than be superseded
    by a media one, which is the refusal `decide`'s `_kind_of` guard exists for.
    """
    await editor.store(project_id, "s1", "prose")

    with pytest.raises(CommandRejectedError):
        await editor.store_media(project_id, "s1", chunks(b"payload"), "video/mp4")

    assert await blob_store.stat(hashlib.sha256(b"payload").hexdigest()) is not None
    corpus = await corpus_repo.load_or_create(project_id)
    assert corpus.state.documents["s1"].kind == "text"


async def test_the_recorded_digest_is_the_one_the_store_computed(editor, project_id):
    """`store_media` has no digest parameter, and this asserts the consequence.

    The mitigation for the domain taking a digest on trust is that no call site
    can supply one. If a parameter is ever added, this test still passes -- so
    it is paired with a signature assertion below, which does not.
    """
    record = await editor.store_media(project_id, "v1", chunks(b"payload"), "video/mp4")

    assert record.sha256 == hashlib.sha256(b"payload").hexdigest()


def test_store_media_takes_no_digest_from_its_caller() -> None:
    """The signature is the mitigation, so the signature is asserted.

    Reads as a strange test and is the honest one: `application/blobs.py`
    claims a wrong digest requires a bug in the store rather than a mistake at
    a call site, and that claim is only true while this parameter list has no
    `sha256` in it.
    """
    assert "sha256" not in inspect.signature(CorpusEditor.store_media).parameters
