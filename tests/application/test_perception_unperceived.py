"""Tests for perception listing unperceived sources, dropped transcripts, and derived IDs.

Extracted from tests/application/test_perception.py.
"""

from uuid import UUID, uuid4

import pytest
from eventsource import DomainEvent, ExpectedVersion, StreamId
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.testing import InMemoryTestHarness

from research_team.platform.shared.blobs import BlobStat
from research_team.research.application.corpus_read import (
    MediaHandle,
    SourceListing,
    StoredDocument,
)
from research_team.research.application.perception import (
    LocatorSpan,
    MediaPerceiver,
    Perceived,
    PerceptionCapabilities,
    derived_source_id,
)
from research_team.research.domain.corpus import (
    Corpus,
    CorpusDocumentDropped,
    CorpusDocumentStored,
    CorpusMediaStored,
    MediaRecord,
    StoreDerivedText,
    TextRecord,
)

MAX_CHARS = 4321


class FakePerception:
    """`PerceptionPort`, with the reading and the capabilities both dictated."""

    def __init__(
        self,
        perceived: Perceived | None = None,
        capabilities: PerceptionCapabilities | None = None,
        error: Exception | None = None,
    ) -> None:
        self._perceived = perceived or Perceived(
            text="A talk about otters.",
            locators=(
                LocatorSpan(0, 10, {"kind": "time", "start_s": 0.0, "end_s": 4.0}),
                LocatorSpan(10, 20, {"kind": "time", "start_s": 4.0, "end_s": 8.0}),
            ),
            fingerprint="vision=v1,asr=w1",
            degradations=(),
        )
        self._capabilities = capabilities or PerceptionCapabilities(
            vision=True, asr=True, ffmpeg=True
        )
        self._error = error
        self.calls: list[dict[str, object]] = []

    async def perceive(self, *, sha256: str, max_chars: int) -> Perceived:
        self.calls.append({"sha256": sha256, "max_chars": max_chars})
        if self._error is not None:
            raise self._error
        return self._perceived

    def capabilities(self) -> PerceptionCapabilities:
        return self._capabilities


class FakeReader:
    """`CorpusReadPort` over the same `Corpus` the perceiver writes to."""

    def __init__(
        self,
        corpus: AggregateRepository[Corpus],
        project_id: UUID,
        dangling: frozenset[str] = frozenset(),
    ) -> None:
        self._corpus = corpus
        self._project_id = project_id
        self._dangling = dangling

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
        if not isinstance(record, TextRecord):
            return None
        if record.dropped_reason is not None and not include_dropped:
            return None
        return StoredDocument(record=record, text="stored prose")

    async def read_media(
        self, source_id: str, *, include_dropped: bool = False
    ) -> MediaHandle | None:
        corpus = await self._corpus.load_or_create(self._project_id)
        record = corpus.state.documents.get(source_id)
        if not isinstance(record, MediaRecord):
            return None
        if record.dropped_reason is not None and not include_dropped:
            return None

        async def _no_bytes():
            return
            yield b""

        stat = (
            None
            if source_id in self._dangling
            else BlobStat(sha256=record.sha256, byte_count=record.byte_count)
        )
        return MediaHandle(record=record, stat=stat, open=lambda start=0: _no_bytes())


@pytest.fixture
def project_id() -> UUID:
    return uuid4()


@pytest.fixture
def harness() -> InMemoryTestHarness:
    return InMemoryTestHarness()


@pytest.fixture
def corpus_repo(harness) -> AggregateRepository[Corpus]:
    return AggregateRepository(harness.event_store, Corpus)


async def _seed(harness: InMemoryTestHarness, project_id: UUID, *events: DomainEvent) -> None:
    stream = StreamId(project_id, "Corpus")
    version = await harness.event_store.get_stream_version(stream)
    await harness.event_store.append(
        stream,
        [
            event.model_copy(update={"aggregate_version": version + offset})
            for offset, event in enumerate(events, start=1)
        ],
        ExpectedVersion.any_(),
    )


@pytest.fixture
async def seeded(harness, project_id) -> None:
    """One video and one paper, both written straight into the log."""
    await _seed(
        harness,
        project_id,
        CorpusMediaStored(
            aggregate_id=project_id,
            source_id="vid",
            sha256="a" * 64,
            media_type="video/mp4",
            byte_count=2048,
            title="A talk",
        ),
        CorpusDocumentStored(
            aggregate_id=project_id,
            source_id="paper",
            text="prose",
            sha256="b" * 64,
        ),
    )


@pytest.fixture
def corpus(corpus_repo, project_id, seeded) -> FakeReader:
    return FakeReader(corpus_repo, project_id)


def _build(corpus_repo, port) -> MediaPerceiver:
    return MediaPerceiver(
        port=port,
        corpus_readers=lambda target: FakeReader(corpus_repo, target),
        corpus=corpus_repo,
        max_chars=lambda: MAX_CHARS,
    )


@pytest.fixture
def port() -> FakePerception:
    return FakePerception()


@pytest.fixture
def perceiver(corpus_repo, port, seeded) -> MediaPerceiver:
    return _build(corpus_repo, port)


def _find(listings: list[SourceListing], source_id: str) -> SourceListing:
    for listing in listings:
        if listing.record.source_id == source_id:
            return listing
    held = [listing.record.source_id for listing in listings]
    raise AssertionError(f"no source {source_id!r} in {held}")


async def test_unperceived_lists_media_with_no_transcript_and_stops_listing_it(
    perceiver, project_id
):
    assert "vid" in await perceiver.unperceived(project_id)

    await perceiver.perceive(project_id, "vid")

    assert "vid" not in await perceiver.unperceived(project_id)


async def test_unperceived_does_not_re_offer_a_medium_whose_transcript_was_dropped(
    perceiver, harness, project_id
):
    """The batch hole, and it was a wrong write rather than a stalled queue.

    Superseding a dropped derived source does not merely replace its text:
    `evolve` builds a fresh `TextRecord` with no `dropped_reason`, so the
    exclusion is erased and the transcript comes back to the listing, to
    chunking and to extraction. A "perceive all" that re-offered this parent
    would undo an operator's deliberate exclusion with nobody having chosen
    it -- so the parent has to stay out of the queue while the transcript
    exists in *any* state, which the default listing cannot express because it
    hides the dropped row.
    """
    await perceiver.perceive(project_id, "vid")
    await _seed(
        harness,
        project_id,
        CorpusDocumentDropped(
            aggregate_id=project_id, source_id="vid#perceived", reason="a bad reading"
        ),
    )

    assert "vid" not in await perceiver.unperceived(project_id)


async def test_unperceived_does_not_offer_a_dropped_medium(perceiver, harness, project_id):
    """The other width, and the other direction. A drop is a judgement that
    the source should not inform the project, and a transcript of it would be
    extracted into the graph the drop was meant to keep it out of. This is the
    condition that used to be inherited from `list_sources`' default and is now
    spelled out, because the perceived set needs the wider listing."""
    await _seed(
        harness,
        project_id,
        CorpusDocumentDropped(aggregate_id=project_id, source_id="vid", reason="off-topic"),
    )

    assert await perceiver.unperceived(project_id) == ()


async def test_an_explicit_perceive_still_un_drops_its_transcript(
    perceiver, corpus, harness, project_id
):
    """Accepted, and asserted so that it is a decision rather than a surprise.

    This is not perception behaving oddly; it is the property every source in
    this corpus has. `CorpusEditor.restore` is *implemented* as a re-store on
    exactly this mechanism -- `evolve` builds a fresh record and does not carry
    `dropped_reason` across, guarded by
    `test_storing_over_a_dropped_source_id_brings_it_back` -- so refusing it
    only for derived text would make perception the one kind whose re-store
    behaves differently. The path where nobody chose it is closed by
    `test_unperceived_does_not_re_offer_a_medium_whose_transcript_was_dropped`
    above; this one costs an explicit call naming the medium.
    """
    await perceiver.perceive(project_id, "vid")
    await _seed(
        harness,
        project_id,
        CorpusDocumentDropped(
            aggregate_id=project_id, source_id="vid#perceived", reason="a bad reading"
        ),
    )
    assert not [
        x for x in await corpus.list_sources() if x.record.source_id == "vid#perceived"
    ]

    await perceiver.perceive(project_id, "vid")

    restored = _find(await corpus.list_sources(), "vid#perceived")
    assert restored.record.dropped_reason is None


async def test_unperceived_lists_no_text_source(perceiver, project_id):
    """Not the paper, and -- after perception -- not the transcript either. A
    transcript is an ordinary text source; queueing it for perception would
    ask a vision model to look at prose."""
    await perceiver.perceive(project_id, "vid")

    assert await perceiver.unperceived(project_id) == ()


async def test_unperceived_reads_derived_from_rather_than_the_id_convention(
    corpus_repo, harness, port, project_id
):
    """A second reading under a second id still counts as perceived.

    `StoreDerivedText.source_id` is unconstrained by design so that a second
    model can perceive one medium under its own id; `unperceived` matching on
    `f"{parent}#perceived"` would go on offering perception for a medium that
    has a transcript, and the operator who took it would get a third.
    """
    await _seed(
        harness,
        project_id,
        CorpusMediaStored(
            aggregate_id=project_id,
            source_id="vid",
            sha256="a" * 64,
            media_type="video/mp4",
            byte_count=2048,
        ),
    )
    perceiver = _build(corpus_repo, port)
    corpus = await corpus_repo.load_or_create(project_id)
    corpus.execute(
        StoreDerivedText(
            corpus_id=project_id,
            source_id="vid-by-another-model",
            derived_from="vid",
            text="another reading",
            locator_map="[]",
            perceived_with="vision=v2",
            degradations="[]",
        )
    )
    await corpus_repo.save(corpus)

    assert await perceiver.unperceived(project_id) == ()


async def test_perception_works_against_a_corpus_no_application_code_built(
    corpus_repo, harness, port
):
    """The fixture rule, made explicit rather than left implicit in `_seed`.

    This project's corpus is written directly to the event store, so nothing
    in the process has ever opened it, listed it, or stored into it through a
    service. A perceiver that depended on some other call having happened
    first -- the shape of the `graphs.open` finding -- fails here and passes
    everywhere else in this file, once per project and looking exactly like
    flakiness.
    """
    fresh_project = uuid4()
    await _seed(
        harness,
        fresh_project,
        CorpusMediaStored(
            aggregate_id=fresh_project,
            source_id="untouched",
            sha256="c" * 64,
            media_type="audio/mpeg",
            byte_count=17,
        ),
    )
    perceiver = _build(corpus_repo, port)

    await perceiver.perceive(fresh_project, "untouched")

    reader = FakeReader(corpus_repo, fresh_project)
    record = _find(await reader.list_sources(), "untouched#perceived").record
    assert record.derived_from == "untouched"


async def test_a_medium_with_no_title_is_named_for_its_id(corpus_repo, harness, port):
    """`f"{title or source_id} (perceived)"`. A transcript listed as
    "(perceived)" with nothing in front of it is a row a reader cannot tell
    from any other transcript in the corpus."""
    fresh_project = uuid4()
    await _seed(
        harness,
        fresh_project,
        CorpusMediaStored(
            aggregate_id=fresh_project,
            source_id="untitled",
            sha256="d" * 64,
            media_type="audio/mpeg",
            byte_count=17,
        ),
    )
    perceiver = _build(corpus_repo, port)

    await perceiver.perceive(fresh_project, "untitled")

    reader = FakeReader(corpus_repo, fresh_project)
    record = _find(await reader.list_sources(), "untitled#perceived").record
    assert record.title == "untitled (perceived)"


def test_the_derived_id_is_the_parent_and_a_suffix() -> None:
    """One spelling, in one place. The domain deliberately does not enforce
    it (`StoreDerivedText`'s docstring says why), so this function is the
    only thing that keeps the console, the perceiver and `unperceived`'s
    successor readers agreeing about what a transcript is called."""
    assert derived_source_id("vid") == "vid#perceived"


async def test_re_perceiving_supersedes_rather_than_duplicating(perceiver, corpus, project_id):
    """Same id, so `decide` treats the second reading as a revision of one
    reading of one medium. Two rows would give a citation two transcripts to
    resolve against and no rule for choosing."""
    await perceiver.perceive(project_id, "vid")
    await perceiver.perceive(project_id, "vid")

    derived = [x for x in await corpus.list_sources() if x.record.source_id == "vid#perceived"]
    assert len(derived) == 1
