"""The corpus, mounted under `/sources/` in the agent's file tools.

The defect these were written against: `grep` searched `session.state.files`
and nothing else, so a phrase appearing in every gathered document returned no
matches -- and an empty result reads exactly like a search that ran against the
right store and found nothing.

Every test here uses a term that appears in *no* session file. A test whose
search term is also in a scratch file passes against an unmounted backend.
"""

import hashlib

import pytest

from research_team.application.corpus_read import SourceListing, StoredDocument
from research_team.domain import MediaRecord, TextRecord
from research_team.infrastructure.agent.backend import EventSourcedBackend
from research_team.infrastructure.agent.read_only_backend import (
    ReadOnlyFilesystem,
    ReadOnlyProjectBackend,
)
from research_team.infrastructure.agent.source_mount import (
    MountedSourceIsReadOnly,
    mounted_sources,
)

# Appears in no fixture file below. The whole suite is worthless if it does.
ONLY_IN_THE_CORPUS = "Theodosius"


def _document(source_id: str, text: str, **metadata) -> StoredDocument:
    return StoredDocument(
        record=TextRecord(
            source_id=source_id,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            char_count=len(text),
            **metadata,
        ),
        text=text,
    )


def _media(source_id: str) -> SourceListing:
    return SourceListing(
        record=MediaRecord(
            source_id=source_id,
            sha256=hashlib.sha256(source_id.encode("utf-8")).hexdigest(),
            byte_count=12,
            media_type="video/mp4",
        ),
        extracted=False,
    )


class FakeCorpus:
    """A corpus read port over a list of listings and documents.

    Takes listings rather than only documents so a media source -- which has no
    text and therefore no `StoredDocument` -- can be in the corpus at all.
    """

    def __init__(
        self, *documents: StoredDocument, extra: tuple[SourceListing, ...] = ()
    ) -> None:
        self._documents = {document.record.source_id: document for document in documents}
        self._extra = extra

    async def list_sources(self) -> list[SourceListing]:
        return [
            SourceListing(record=document.record, extracted=False)
            for document in self._documents.values()
        ] + list(self._extra)

    async def read_document(self, source_id: str) -> StoredDocument | None:
        return self._documents.get(source_id)


@pytest.fixture
def corpus() -> FakeCorpus:
    return FakeCorpus(
        _document("nicaea-3f2a", f"The council met.\n{ONLY_IN_THE_CORPUS} ruled later.\n"),
        _document("arles-77b1", "A different council entirely.\n"),
    )


@pytest.fixture
async def mount(corpus) -> dict:
    return await mounted_sources(corpus)


@pytest.fixture
def backend(session, mount) -> EventSourcedBackend:
    backend = EventSourcedBackend(session, sources=mount)
    backend.write("/notes.md", "my own working notes\n")
    return backend


def test_grep_finds_a_term_only_a_corpus_document_holds(backend):
    """Fails if the mount is absent -- which is the whole defect.

    The term is in no session file, so an unmounted backend answers with no
    matches, which is what shipped.
    """
    result = backend.grep(ONLY_IN_THE_CORPUS)
    assert result.error is None
    assert [match["path"] for match in result.matches] == ["/sources/nicaea-3f2a"]


def test_grep_still_finds_the_sessions_own_files(backend):
    """The mount must widen the search, not replace it."""
    result = backend.grep("working notes")
    assert [match["path"] for match in result.matches] == ["/notes.md"]


def test_ls_shows_a_mounted_source_beside_the_session_files(backend):
    """Fails if the mount is keyed off a prefix `ls` does not walk."""
    entries = {entry["path"] for entry in backend.ls("/sources/").entries}
    assert entries == {"/sources/nicaea-3f2a", "/sources/arles-77b1"}
    assert "/notes.md" in {entry["path"] for entry in backend.ls("/").entries}


def test_glob_matches_mounted_sources(backend):
    matches = {info["path"] for info in backend.glob("/sources/*").matches}
    assert matches == {"/sources/nicaea-3f2a", "/sources/arles-77b1"}


def test_read_file_on_a_mounted_path_names_read_source(backend):
    """The citation hole. `read_file` returning mounted text would let the ask
    page quote gathered material with no `source_id@start-end` attached, which
    is the failure `corpus_tools.py` exists to prevent."""
    result = backend.read("/sources/nicaea-3f2a")
    assert result.error is not None
    assert 'read_source(source_id="nicaea-3f2a")' in result.error


def test_writing_to_a_mounted_path_appends_no_event(backend, session):
    """Asserts on the log, not on the raised error.

    A guard that refuses *after* executing the command still satisfies an
    exception-shaped assertion while having already appended a `FileWritten`
    that shadows the corpus for every later read -- durably, since events are
    not rewritten.

    Proven red before it was trusted green: against a build with no mount,
    `/sources/nicaea-3f2a` is an ordinary scratch path and this write appends
    an ordinary event.
    """
    before = len(session.uncommitted_events)
    with pytest.raises(MountedSourceIsReadOnly):
        backend.write("/sources/nicaea-3f2a", "rewritten\n")
    assert len(session.uncommitted_events) == before


def test_editing_a_mounted_path_appends_no_event(backend, session):
    before = len(session.uncommitted_events)
    with pytest.raises(MountedSourceIsReadOnly):
        backend.edit("/sources/nicaea-3f2a", "council", "COUNCIL")
    assert len(session.uncommitted_events) == before


def test_deleting_a_mounted_path_appends_no_event(backend, session):
    before = len(session.uncommitted_events)
    with pytest.raises(MountedSourceIsReadOnly):
        backend.delete("/sources/nicaea-3f2a")
    assert len(session.uncommitted_events) == before


def test_the_refusal_names_the_tool_that_works(backend):
    """The message is what the model reads, so it has to carry the next call."""
    expected = 'read_source\\(source_id="nicaea-3f2a"\\)'
    with pytest.raises(MountedSourceIsReadOnly, match=expected):
        backend.write("/sources/nicaea-3f2a", "rewritten\n")


async def test_a_media_source_is_not_mounted():
    """Fails if the snapshot mounts every listing rather than the text ones.

    A media source has no text, so mounting it puts an empty file in front of
    every `grep` -- which reads as "searched it, found nothing" for a source
    that was never searchable.
    """
    corpus = FakeCorpus(_document("a", "text\n"), extra=(_media("clip-9c11"),))
    assert set(await mounted_sources(corpus)) == {"/sources/a"}


async def test_a_dropped_document_is_not_mounted():
    """A dropped document is one the project decided against.

    The port's own default already excludes them; this asserts the snapshot
    refuses one that reaches it anyway, because `list_sources` is a Protocol
    and a second implementation defaulting the other way would silently
    resurrect every exclusion.
    """
    corpus = FakeCorpus(
        _document("kept", "kept text\n"),
        _document("gone", "dropped text\n", dropped_reason="superseded"),
    )
    assert set(await mounted_sources(corpus)) == {"/sources/kept"}


async def test_a_session_file_under_sources_does_not_shadow_the_corpus(session, corpus):
    """An older build could have written one before the guard existed.

    Those events still replay -- events are not rewritten -- so the mount has
    to win over what the fold produced, or a stale scratch copy answers every
    search for that source forever.
    """
    stale = EventSourcedBackend(session)
    stale.write("/sources/nicaea-3f2a", "a stale copy with no Theodosius in it\n")

    backend = EventSourcedBackend(session, sources=await mounted_sources(corpus))
    assert backend.grep(ONLY_IN_THE_CORPUS).matches != []


async def test_the_ask_agents_backend_mounts_too(corpus):
    """The ask path builds its own backend, so the tests above prove nothing
    about it -- and it is the page whose prompt most directly promises that
    gathered sources can be searched."""
    backend = ReadOnlyProjectBackend({}, sources=await mounted_sources(corpus))
    assert [match["path"] for match in backend.grep(ONLY_IN_THE_CORPUS).matches] == [
        "/sources/nicaea-3f2a"
    ]


async def test_the_ask_agent_still_refuses_every_write(corpus):
    backend = ReadOnlyProjectBackend({}, sources=await mounted_sources(corpus))
    with pytest.raises((ReadOnlyFilesystem, MountedSourceIsReadOnly)):
        backend.write("/sources/nicaea-3f2a", "rewritten\n")


def test_an_unmounted_backend_is_unchanged(session):
    """The default is no mount, so every existing call site keeps its exact
    behaviour -- including writing to a `/sources/` path, which is an ordinary
    scratch file when nothing is mounted there."""
    backend = EventSourcedBackend(session)
    assert backend.write("/sources/anything", "x\n").error is None
