"""`MediaAcceptWorker` and `MediaAcceptReconciler`, against a stubbed transport.

No test here reaches the network -- the transport is `httpx.MockTransport`,
as `tests/infrastructure/test_search.py`'s `_client` does.

The worker tests mirror `test_corpus_editing.py`'s doubling strategy on the
corpus side: a real `Corpus` aggregate over a real `AggregateRepository`
backed by `InMemoryEventStore`, and a real `FilesystemBlobStore` over
`tmp_path`, rather than a hand-written fake reimplementing `store_media`'s
own rules. The proposals side is the same shape -- a real `MediaProposals`
aggregate -- so `StoreMediaProposal`/`FailMediaProposal`'s lifecycle guards
in a test are `decide`'s real guards, not a fake's approximation of them.
"""

from uuid import UUID, uuid4

import httpx
import pytest
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.testing import InMemoryTestHarness

from research_team.application import media_acquisition
from research_team.application.corpus_editing import CorpusEditor
from research_team.application.media_acquisition import (
    AcceptedProposal,
    MediaAcceptReconciler,
    MediaAcceptWorker,
)
from research_team.application.perception import PerceptionUnavailable
from research_team.domain.corpus import Corpus, MediaRecord
from research_team.domain.media_proposals import (
    AcceptMediaProposal,
    MediaProposals,
    ProposeMedia,
)
from research_team.infrastructure.persistence.blob_store import FilesystemBlobStore


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _image_client(body: bytes = b"\xff\xd8\xff", content_type: str = "image/jpeg"):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": content_type}, content=body)

    return _client(handler)


# --- MediaAcceptWorker -------------------------------------------------


class FakeReads:
    """`MediaProposalReadPort` over a plain dict a test seeds directly."""

    def __init__(self, proposals: dict[str, AcceptedProposal]):
        self._proposals = proposals

    async def get(self, proposal_id: str) -> AcceptedProposal | None:
        return self._proposals.get(proposal_id)


class FakePerceiver:
    """Records calls; raises whatever a test configured, matching a real
    `PerceptionPort` implementation's shape of raising a named exception
    rather than returning a sentinel.
    """

    def __init__(self, raises: Exception | None = None):
        self._raises = raises
        self.calls: list[tuple[UUID, str]] = []

    async def perceive(self, project_id: UUID, source_id: str) -> object:
        self.calls.append((project_id, source_id))
        if self._raises is not None:
            raise self._raises
        return None


@pytest.fixture
def project_id() -> UUID:
    return uuid4()


@pytest.fixture
def corpus_repo() -> AggregateRepository[Corpus]:
    return AggregateRepository(InMemoryTestHarness().event_store, Corpus)


@pytest.fixture
def proposals_repo() -> AggregateRepository[MediaProposals]:
    return AggregateRepository(InMemoryTestHarness().event_store, MediaProposals)


@pytest.fixture
def editor(corpus_repo, tmp_path) -> CorpusEditor:
    async def open_knowledge(target_project_id: UUID):
        raise NotImplementedError("store_media does not call open_knowledge")

    return CorpusEditor(
        open_knowledge=open_knowledge,
        # Never called by `store_media` (see its own docstring: no
        # existence check against text), so a reader that would break if
        # used is the honest stand-in.
        readers=lambda target_project_id: None,
        corpus=corpus_repo,
        blobs=FilesystemBlobStore(tmp_path / "blobs"),
    )


async def _accept(
    proposals_repo: AggregateRepository[MediaProposals],
    project_id: UUID,
    proposal_id: str,
    *,
    asset_url: str,
) -> None:
    """Seed one proposal through to `accepted`, the state
    `StoreMediaProposal`/`FailMediaProposal` both require.
    """
    aggregate = await proposals_repo.load_or_create(project_id)
    aggregate.execute(
        ProposeMedia(
            project_id=str(project_id),
            proposal_id=proposal_id,
            need_id="need-0",
            topic_id=str(uuid4()),
            page_url="https://example.org/gallery/trajan",
            asset_url=asset_url,
            thumbnail_url="",
            kind="image",
            title="Trajan's Column, detail",
            reason="shows the relief the finding describes",
            query="trajan column relief",
        )
    )
    aggregate.execute(AcceptMediaProposal(project_id=str(project_id), proposal_id=proposal_id))
    await proposals_repo.save(aggregate)


def _detail(project_id: UUID, *, asset_url: str) -> AcceptedProposal:
    return AcceptedProposal(
        project_id=str(project_id),
        page_url="https://example.org/gallery/trajan",
        asset_url=asset_url,
        title="Trajan's Column, detail",
    )


async def test_an_accepted_proposal_becomes_a_source_carrying_its_page_url(
    project_id, corpus_repo, proposals_repo, editor
):
    """`uri` is the page, not the asset: provenance is where it was found,
    not the CDN path it happened to be served from. Fails if the worker
    passes `detail.asset_url` (what it downloaded from) instead of
    `detail.page_url` (where a reader would go to see it in context).
    """
    proposal_id = "p1"
    await _accept(
        proposals_repo, project_id, proposal_id, asset_url="https://cdn.example/trajan.jpg"
    )
    reads = FakeReads(
        {proposal_id: _detail(project_id, asset_url="https://cdn.example/trajan.jpg")}
    )
    perceiver = FakePerceiver()
    worker = MediaAcceptWorker(
        reads=reads,
        proposals=proposals_repo,
        editor=editor,
        perceiver=perceiver,
        client=_image_client(),
    )

    await worker.run(proposal_id=proposal_id)

    corpus = await corpus_repo.load_or_create(project_id)
    record = corpus.state.documents[proposal_id]
    assert isinstance(record, MediaRecord)
    assert record.uri == "https://example.org/gallery/trajan"

    proposal_state = await proposals_repo.load_or_create(project_id)
    assert proposal_state.state.proposals[proposal_id].status == "stored"
    # Perception ran eagerly, against the corpus source_id the worker chose.
    assert perceiver.calls == [(project_id, proposal_id)]


async def test_an_accepted_proposal_is_stored_even_when_perception_cannot_run(
    project_id, corpus_repo, proposals_repo, editor
):
    """A capability gap -- no vision model configured -- is not a reason to
    discard a source that downloaded and stored correctly. `PerceptionUnavailable`
    is one of `perceive_source`'s own ordinary outcomes (503, not 500); the
    worker's eager perception is a warm read, not a gate. Fails if the worker
    lets `PerceptionUnavailable` propagate and the proposal never reaches
    `stored`.
    """
    proposal_id = "p1"
    await _accept(
        proposals_repo, project_id, proposal_id, asset_url="https://cdn.example/trajan.jpg"
    )
    reads = FakeReads(
        {proposal_id: _detail(project_id, asset_url="https://cdn.example/trajan.jpg")}
    )
    perceiver = FakePerceiver(raises=PerceptionUnavailable("no vision model configured"))
    worker = MediaAcceptWorker(
        reads=reads,
        proposals=proposals_repo,
        editor=editor,
        perceiver=perceiver,
        client=_image_client(),
    )

    await worker.run(proposal_id=proposal_id)

    corpus = await corpus_repo.load_or_create(project_id)
    assert isinstance(corpus.state.documents[proposal_id], MediaRecord)
    proposal_state = await proposals_repo.load_or_create(project_id)
    assert proposal_state.state.proposals[proposal_id].status == "stored"


class _BlobsFailingMidStream:
    """A `BlobStorePort` double that reads one chunk of the stream `put` is
    handed, then raises -- simulating a blob-store I/O error partway
    through `store_media`'s write, the scenario `download_media`'s docstring
    warns about: abandoning the returned generator partway leaks the
    underlying httpx connection unless the caller closes it explicitly.
    """

    def __init__(self):
        self.captured_stream = None

    async def put(self, stream):
        self.captured_stream = stream
        await stream.__anext__()
        raise RuntimeError("disk full")


async def test_a_corpus_store_raising_mid_write_closes_the_download_stream(
    project_id, proposals_repo
):
    """This is the test that would fail if someone later removes the
    `try/except BaseException: await stream.aclose()` around `store_media`
    in `MediaAcceptWorker.run` -- without it, `download_media`'s generator
    is left suspended mid-iteration when `put` raises, and its `finally`
    (which closes the httpx response) never runs until GC gets to it, which
    is not promised to happen promptly or at all for a suspended coroutine.
    A closed async generator's `ag_frame` is `None`, which is what a caller
    that *did* close it leaves behind.
    """
    proposal_id = "p1"
    await _accept(
        proposals_repo, project_id, proposal_id, asset_url="https://cdn.example/trajan.jpg"
    )
    reads = FakeReads(
        {proposal_id: _detail(project_id, asset_url="https://cdn.example/trajan.jpg")}
    )
    blobs = _BlobsFailingMidStream()

    async def open_knowledge(target_project_id: UUID):
        raise NotImplementedError("store_media does not call open_knowledge")

    failing_editor = CorpusEditor(
        open_knowledge=open_knowledge,
        readers=lambda target_project_id: None,
        corpus=AggregateRepository(InMemoryTestHarness().event_store, Corpus),
        blobs=blobs,
    )
    worker = MediaAcceptWorker(
        reads=reads,
        proposals=proposals_repo,
        editor=failing_editor,
        perceiver=FakePerceiver(),
        client=_image_client(),
    )

    with pytest.raises(RuntimeError, match="disk full"):
        await worker.run(proposal_id=proposal_id)

    assert blobs.captured_stream is not None
    assert blobs.captured_stream.ag_frame is None


class _FakeStream:
    """A minimal stand-in for `download_media`'s returned generator, whose
    only job is to record whether `aclose()` was called on it -- direct
    evidence of closure, rather than `ag_frame is None`'s indirect one.
    """

    def __init__(self, chunks: list[bytes]):
        self._chunks = iter(chunks)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration from None

    async def aclose(self) -> None:
        self.closed = True


async def test_a_corpus_store_raising_mid_write_calls_aclose_on_the_stream(
    project_id, proposals_repo, editor, monkeypatch
):
    """Direct evidence for the `try/except BaseException: await stream.aclose()`
    around `store_media` in `MediaAcceptWorker.run`: a fake stream that
    records whether `aclose()` was called, rather than only asserting the
    exception propagated -- propagation alone passes with the handler
    removed (`except BaseException: raise` with no `aclose()` still
    re-raises), so it would not have caught the regression this exists to
    catch. Proven red by temporarily removing the `aclose()` call: this test
    is the one that failed, and only this one.
    """
    proposal_id = "p1"
    await _accept(
        proposals_repo, project_id, proposal_id, asset_url="https://cdn.example/trajan.jpg"
    )
    reads = FakeReads(
        {proposal_id: _detail(project_id, asset_url="https://cdn.example/trajan.jpg")}
    )
    fake_stream = _FakeStream([b"\xff\xd8\xff"])

    async def fake_download_media(url, *, client, max_bytes):
        return fake_stream, "image/jpeg"

    monkeypatch.setattr(media_acquisition, "download_media", fake_download_media)

    class BlobsRaisingOnPut:
        async def put(self, stream):
            raise RuntimeError("disk full")

    async def open_knowledge(target_project_id: UUID):
        raise NotImplementedError("store_media does not call open_knowledge")

    failing_editor = CorpusEditor(
        open_knowledge=open_knowledge,
        readers=lambda target_project_id: None,
        corpus=AggregateRepository(InMemoryTestHarness().event_store, Corpus),
        blobs=BlobsRaisingOnPut(),
    )
    worker = MediaAcceptWorker(
        reads=reads,
        proposals=proposals_repo,
        editor=failing_editor,
        perceiver=FakePerceiver(),
        client=_image_client(),
    )

    with pytest.raises(RuntimeError, match="disk full"):
        await worker.run(proposal_id=proposal_id)

    assert fake_stream.closed is True


# --- MediaAcceptReconciler -----------------------------------------------
#
# `worker` here is a bare fake recording calls, not a real `MediaAcceptWorker`
# -- the reconciler's contract is "loop the ids, call `worker.run` on each,
# never let one raise stop the rest", which does not depend on anything
# `MediaAcceptWorker` itself does. Re-run safety is `MediaAcceptWorker`'s own
# docstring's argument and is not re-tested here.


class FakeReconcilerReads:
    def __init__(self, ids: list[str]) -> None:
        self._ids = ids

    async def accepted_proposal_ids(self) -> list[str]:
        return self._ids


class FakeReconcilerWorker:
    def __init__(self, *, raise_on: str | None = None) -> None:
        self.calls: list[str] = []
        self.raise_on = raise_on

    async def run(self, proposal_id: str) -> None:
        self.calls.append(proposal_id)
        if proposal_id == self.raise_on:
            raise RuntimeError(f"asset for {proposal_id} is gone")


async def test_every_accepted_proposal_is_re_run():
    worker = FakeReconcilerWorker()
    reconciler = MediaAcceptReconciler(reads=FakeReconcilerReads(["p1", "p2"]), worker=worker)

    await reconciler.run()

    assert worker.calls == ["p1", "p2"]


async def test_one_proposal_failing_does_not_abandon_the_rest():
    """The reconciler must be total. Fails if the `except` is removed: the
    first raise would end the loop and `p2` would never be attempted.
    """
    worker = FakeReconcilerWorker(raise_on="p1")
    reconciler = MediaAcceptReconciler(reads=FakeReconcilerReads(["p1", "p2"]), worker=worker)

    await reconciler.run()

    assert worker.calls == ["p1", "p2"]


async def test_nothing_accepted_is_not_an_error():
    worker = FakeReconcilerWorker()
    reconciler = MediaAcceptReconciler(reads=FakeReconcilerReads([]), worker=worker)

    await reconciler.run()

    assert worker.calls == []
