"""Perceiving a stored medium into a text source the graph already reads.

Doubles for the port and the reader, a real `Corpus` aggregate over a real
`AggregateRepository` behind `InMemoryTestHarness` -- `test_corpus_editing.py`'s
shape, and for its reason: the refusals this use case leans on
(`derived_from` naming a text source, derivedness flipping) are `decide`'s, and
a hand-written fake would have to reimplement `decide` correctly in order to
show that they are not duplicated here.

**Nothing in this file reaches a network or names a model host.** The port is a
fake; the adapter that speaks to one is tested in
`tests/infrastructure/test_readeverything_adapter.py`.

**Every fixture seeds by appending `CorpusMediaStored` to the event store**,
not by calling the perceiver or the editor. That is the `graphs.open` finding
in CLAUDE.md wearing this task's clothes: a fixture that arranges its data
through the same collaborator call the code under test is supposed to make
cannot see that call go missing. Here the call at risk is
`corpus_readers(project_id).read_media` -- seed through the perceiver and every
project would already be in whatever state the perceiver leaves it.
"""

import json
from uuid import UUID, uuid4

import pytest
from eventsource import DomainEvent, ExpectedVersion, StreamId
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.testing import InMemoryTestHarness

from research_team.application.blobs import BlobStat
from research_team.application.corpus_read import MediaHandle, SourceListing, StoredDocument
from research_team.application.document_extraction import UnknownDocument
from research_team.application.locators import resolve
from research_team.application.perception import (
    LocatorSpan,
    MediaBytesMissing,
    MediaPerceiver,
    NotPerceivable,
    Perceived,
    PerceptionCapabilities,
    PerceptionUnavailable,
    SourceDropped,
    derived_source_id,
)
from research_team.domain.corpus import (
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
    """`PerceptionPort`, with the reading and the capabilities both dictated.

    Records every call, because two tests are about a call that must *not*
    happen: an install with no models must not pay for one, and a store the
    domain refuses must not be preceded by... well, it must, and that is the
    trade the order comment in `perceive` names. The recording is what lets
    either claim be measured rather than asserted.
    """

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
    """`CorpusReadPort` over the same `Corpus` the perceiver writes to.

    Reads `corpus.state.documents` directly rather than keeping a projection,
    for `test_corpus_editing.py`'s reason: the fold already carries every
    record, and a second copy of that bookkeeping would eventually disagree
    with it.

    **`stat` is a real `BlobStat` unless a test asks otherwise**, and the
    default used to be the other way round. `stat is None` is this
    repository's spelling of "the record is here and the bytes are gone" --
    `app.py` answers 410 on it -- so a fake that returned it unconditionally
    modelled a corpus in which every blob had been deleted, and the whole
    suite ran green against the one state a correct perceiver must refuse.
    Adding that refusal turned thirteen tests red at once, which reads as the
    fix breaking things rather than as the fixture having described the wrong
    world. `dangling` names the ids that really are missing their bytes.
    """

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
            # The real reader answers None for a media id: it promises text.
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
            # Nothing here reads the blob: the port takes a digest, not a
            # stream, which is the whole point of it taking a digest.
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
    """Write events onto the corpus stream with no application code involved.

    Deliberately not `CorpusEditor.store_media` and deliberately not the
    perceiver: see this module's docstring. `StreamId(project_id, "Corpus")`
    is the stream the aggregate reads, as `domain/corpus.py` names it.

    `aggregate_version` is stamped here because nothing else will. A loaded
    aggregate takes its version from the last event's, and `save` computes the
    expected version from that -- so events appended with the default 1 make
    the *next* ordinary save raise `OptimisticLockError` against a corpus that
    is not concurrently modified at all. Found by writing this fixture; the
    repository stamps it on the path everything else uses.
    """
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


@pytest.fixture
def port_without_models() -> FakePerception:
    return FakePerception(
        capabilities=PerceptionCapabilities(vision=False, asr=False, ffmpeg=True)
    )


@pytest.fixture
def perceiver_without_models(corpus_repo, port_without_models, seeded) -> MediaPerceiver:
    return _build(corpus_repo, port_without_models)


@pytest.fixture
def perceiver_asr_only(corpus_repo, seeded) -> MediaPerceiver:
    port = FakePerception(
        perceived=Perceived(
            text="Otters, in their own words.",
            locators=(LocatorSpan(0, 27, {"kind": "time", "start_s": 0.0, "end_s": 9.0}),),
            fingerprint="asr=w1",
            degradations=("vision unavailable: frames were not described",),
        ),
        capabilities=PerceptionCapabilities(vision=False, asr=True, ffmpeg=True),
    )
    return _build(corpus_repo, port)


def _find(listings: list[SourceListing], source_id: str) -> SourceListing:
    for listing in listings:
        if listing.record.source_id == source_id:
            return listing
    held = [listing.record.source_id for listing in listings]
    raise AssertionError(f"no source {source_id!r} in {held}")


async def test_perceiving_stores_a_derived_source_under_the_parent(
    perceiver, corpus, project_id
):
    await perceiver.perceive(project_id, "vid")

    listing = await corpus.list_sources()
    derived = [x for x in listing if x.record.source_id == "vid#perceived"]
    assert derived, "no derived source was stored"
    assert derived[0].record.derived_from == "vid"


async def test_a_dropped_medium_is_refused_as_dropped_and_not_as_missing(
    corpus_repo, harness, port, project_id, seeded
):
    """ "No such source" and "a source you excluded" are different answers,
    and this method gave the first one for the second case until a reviewer
    measured it.

    Both reads at their default width answer `None` for a dropped medium --
    `read_media` hides it, `read_document` declines it as media -- so the
    conflation `CorpusReadPort.read_media`'s docstring forbids was reachable
    by a route that docstring never anticipated. An operator told a recording
    does not exist goes looking for an ingest that never happened.
    """
    await _seed(
        harness,
        project_id,
        CorpusDocumentDropped(aggregate_id=project_id, source_id="vid", reason="off-topic"),
    )
    perceiver = _build(corpus_repo, port)

    with pytest.raises(SourceDropped) as raised:
        await perceiver.perceive(project_id, "vid")

    assert "off-topic" in str(raised.value)
    assert port.calls == []


async def test_a_medium_whose_bytes_are_gone_is_refused_as_gone(
    corpus_repo, port, project_id, seeded
):
    """A dangling reference: the record is here and the blob is not.

    Detected in the perceiver because the perceiver is what holds the
    `MediaHandle`; the route has only a project and a `source_id`, and would
    need a second `read_media` purely to inspect `stat` in order to answer
    410. Its own type so Task 7 can map it to the same 410 the content route
    already gives, instead of the operator meeting a traceback from inside
    the perceiving library.

    This is also the one test that asks `FakeReader` for `stat=None`. Every
    other test in this file used to get it by default, which meant the whole
    suite ran against a corpus whose blobs had all been deleted.
    """
    perceiver = MediaPerceiver(
        port=port,
        corpus_readers=lambda target: FakeReader(corpus_repo, target, frozenset({"vid"})),
        corpus=corpus_repo,
        max_chars=lambda: MAX_CHARS,
    )

    with pytest.raises(MediaBytesMissing):
        await perceiver.perceive(project_id, "vid")

    assert port.calls == []


async def test_the_derived_source_carries_the_text_and_the_locators(
    perceiver, corpus, project_id
):
    """The row and its fields, not "the call returned".

    An event no projection handles counts as APPLIED, and a use case whose
    only assertion is that nothing raised passes with the store deleted. The
    locator map is asserted as parsed JSON in the resolver's own shape,
    because `application/locators.py` is the reader and a map it cannot walk
    is a citation with no moment on it.
    """
    report = await perceiver.perceive(project_id, "vid")

    record = _find(await corpus.list_sources(), "vid#perceived").record
    assert record.char_count == len("A talk about otters.")
    assert record.perceived_with == "vision=v1,asr=w1"
    assert record.title == "A talk (perceived)"
    assert report.source_id == "vid#perceived"
    assert report.derived_from == "vid"

    assert resolve(report.locator_map, 2, 4) == (
        {"kind": "time", "start_s": 0.0, "end_s": 4.0},
    )
    assert json.loads(report.locator_map)[1] == {
        "char_start": 10,
        "char_end": 20,
        "locator": {"kind": "time", "start_s": 4.0, "end_s": 8.0},
    }


async def test_the_port_is_called_with_the_stored_digest_and_the_configured_cap(
    perceiver, port, project_id
):
    """The digest, not the source id and not a path.

    Passing the wrong one would still perceive *something* against a blob
    store keyed some other way; against this one it would fail, and against
    the real one it would read the wrong file if two ids ever collided.
    """
    await perceiver.perceive(project_id, "vid")

    assert port.calls == [{"sha256": "a" * 64, "max_chars": MAX_CHARS}]


async def test_perceiving_a_text_source_is_refused(perceiver, project_id):
    with pytest.raises(NotPerceivable):
        await perceiver.perceive(project_id, "paper")


async def test_perceiving_a_source_the_corpus_does_not_hold_is_unknown(perceiver, project_id):
    """`UnknownDocument`, not `NotPerceivable`: the route answers 404 for one
    and 409 for the other, and "there is no such id" and "that id holds
    prose" send an operator to two different places."""
    with pytest.raises(UnknownDocument):
        await perceiver.perceive(project_id, "nothing-here")


async def test_an_install_with_no_models_stores_nothing(
    perceiver_without_models, corpus, project_id
):
    """The assertion is the absent row. With no models, `represent` still
    returns a metadata stub -- "Image x, 64x48 PNG, 469 bytes" -- and storing
    it would put a sentence no human wrote into the corpus to be extracted as
    evidence."""
    with pytest.raises(PerceptionUnavailable):
        await perceiver_without_models.perceive(project_id, "vid")

    assert not [x for x in await corpus.list_sources() if "#perceived" in x.record.source_id]


async def test_an_install_with_no_models_names_what_is_missing(
    perceiver_without_models, project_id
):
    """A 503 that can only say "not configured" sends nobody anywhere."""
    with pytest.raises(PerceptionUnavailable) as raised:
        await perceiver_without_models.perceive(project_id, "vid")

    assert "AGENT_VISION_MODEL" in str(raised.value)
    assert "AGENT_TRANSCRIBER_URL" in str(raised.value)


async def test_an_install_with_no_models_does_not_pay_for_a_call(
    perceiver_without_models, port_without_models, project_id
):
    """The capability check is before the port call, not after it. Reversed,
    every refusal above would still hold and each would cost a model call
    whose output is discarded -- which is money, quietly."""
    with pytest.raises(PerceptionUnavailable):
        await perceiver_without_models.perceive(project_id, "vid")

    assert port_without_models.calls == []


async def test_partial_degradation_still_stores_and_records_the_gap(
    perceiver_asr_only, corpus, project_id
):
    """A transcript with no frame descriptions is real evidence with a named
    gap. Refusing it would mean an install without vision could never
    transcribe anything."""
    await perceiver_asr_only.perceive(project_id, "vid")

    record = _find(await corpus.list_sources(), "vid#perceived").record
    assert record.degradations
    assert any("vision" in degradation for degradation in record.degradations)


async def test_a_failed_perception_stores_nothing(corpus_repo, corpus, project_id):
    """Perceive first, store second -- this is the half of the order that is
    load-bearing for correctness rather than for cost.

    Reversed, a port that raises would leave a derived record claiming a
    perception that did not happen: the dangling reference the media design
    refused to allow, except pointing at a reading rather than at bytes. The
    other half of the trade is accepted and cannot be tested for, because it
    is a cost rather than a state: a store the domain refuses leaves a model
    call already paid for.
    """
    perceiver = _build(corpus_repo, FakePerception(error=RuntimeError("the model fell over")))

    with pytest.raises(RuntimeError):
        await perceiver.perceive(project_id, "vid")

    assert not [x for x in await corpus.list_sources() if "#perceived" in x.record.source_id]


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
