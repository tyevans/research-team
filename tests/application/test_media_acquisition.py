"""`download_media` and `MediaAcceptWorker`, against a stubbed transport.

No test here reaches the network -- the transport is `httpx.MockTransport`,
as `tests/infrastructure/test_search.py`'s `_client` does. `download_media` is
shared by the accept worker (Task 11, below) and a gated agent tool (Task
13), so it is exercised here once rather than twice downstream.

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
    MediaMoved,
    MediaTooLarge,
    UnsupportedMedia,
    download_media,
)
from research_team.application.perception import PerceptionUnavailable
from research_team.domain.corpus import Corpus, MediaRecord
from research_team.domain.media_proposals import (
    AcceptMediaProposal,
    MediaProposalFailed,
    MediaProposals,
    ProposeMedia,
)
from research_team.infrastructure.persistence.blob_store import FilesystemBlobStore


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _html_client() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"<html><body>please log in</body></html>",
        )

    return _client(handler)


def _image_client(body: bytes = b"\xff\xd8\xff", content_type: str = "image/jpeg"):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": content_type}, content=body)

    return _client(handler)


def _redirect_client(location: str = "https://a.example/real.jpg"):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": location})

    return _client(handler)


async def _drain(stream) -> bytes:
    out = b""
    async for part in stream:
        out += part
    return out


async def test_an_html_interstitial_is_a_failure_and_not_a_source():
    """A judged candidate whose URL serves a login page must not become a
    corpus row whose bytes are HTML and whose transcript is empty."""
    with pytest.raises(UnsupportedMedia):
        await download_media(
            "https://a.example/x.jpg", client=_html_client(), max_bytes=10_000
        )


async def test_the_refused_media_type_is_reported():
    try:
        await download_media(
            "https://a.example/x.jpg", client=_html_client(), max_bytes=10_000
        )
        pytest.fail("expected UnsupportedMedia")
    except UnsupportedMedia as error:
        assert error.media_type == "text/html"


async def test_an_image_content_type_is_accepted():
    stream, media_type = await download_media(
        "https://a.example/x.jpg", client=_image_client(), max_bytes=10_000
    )
    assert media_type == "image/jpeg"
    assert await _drain(stream) == b"\xff\xd8\xff"


async def test_video_and_audio_are_also_accepted():
    for content_type in ("video/mp4", "audio/mpeg"):
        stream, media_type = await download_media(
            "https://a.example/x",
            client=_image_client(content_type=content_type),
            max_bytes=10_000,
        )
        assert media_type == content_type
        assert await _drain(stream) == b"\xff\xd8\xff"


async def test_a_body_over_the_ceiling_is_refused():
    body = b"a" * 20
    with pytest.raises(MediaTooLarge):
        stream, _ = await download_media(
            "https://a.example/x.jpg", client=_image_client(body=body), max_bytes=10
        )
        await _drain(stream)


async def test_a_redirect_is_reported_rather_than_followed():
    """Mirrors `fetch.py`'s decision on the read side: a redirect is
    reported rather than resolved automatically, so a caller with the
    authority to follow it can decide to. Surfaced as its own `MediaMoved`,
    not `UnsupportedMedia` -- a `media_type` of `""` would be indistinguishable
    from a genuinely missing content-type, and a caller needs to tell "this
    asset is the wrong kind" apart from "this URL moved" without parsing a
    message string. Fails if the redirect collapses back into `UnsupportedMedia`.
    """
    with pytest.raises(MediaMoved) as excinfo:
        await download_media(
            "https://a.example/x.jpg", client=_redirect_client(), max_bytes=10_000
        )
    assert excinfo.value.location == "https://a.example/real.jpg"


# --- MediaAcceptWorker -------------------------------------------------


class SpyProposalsRepo:
    """Wraps a real `AggregateRepository[MediaProposals]`, recording every
    event a `save` actually persists.

    `aggregate.uncommitted_events` is read *before* delegating to the real
    `save`, which clears it -- reading after would always see an empty list.
    This is what lets a test assert on a `MediaProposalFailed`'s `error`
    directly, rather than only the folded `status` string `ProposalRecord`
    reduces it to.
    """

    def __init__(self, inner: AggregateRepository[MediaProposals]):
        self._inner = inner
        self.appended: list = []

    async def load_or_create(self, aggregate_id: UUID) -> MediaProposals:
        return await self._inner.load_or_create(aggregate_id)

    async def save(self, aggregate: MediaProposals) -> None:
        self.appended.extend(aggregate.uncommitted_events)
        await self._inner.save(aggregate)


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


async def test_a_failed_download_records_why_and_leaves_the_proposal_visible(
    project_id, corpus_repo, proposals_repo, editor
):
    """A proposal that vanishes on failure is one nobody can retry or
    understand. Fails if the worker swallows the error, leaves the proposal
    stuck at `accepted`, or writes a corpus row for bytes that were never
    media.
    """
    proposal_id = "p1"
    await _accept(
        proposals_repo, project_id, proposal_id, asset_url="https://a.example/login-wall.jpg"
    )
    reads = FakeReads(
        {proposal_id: _detail(project_id, asset_url="https://a.example/login-wall.jpg")}
    )
    perceiver = FakePerceiver()
    worker = MediaAcceptWorker(
        reads=reads,
        proposals=proposals_repo,
        editor=editor,
        perceiver=perceiver,
        client=_html_client(),
    )

    await worker.run(proposal_id=proposal_id)

    corpus = await corpus_repo.load_or_create(project_id)
    assert proposal_id not in corpus.state.documents
    proposal_state = await proposals_repo.load_or_create(project_id)
    assert proposal_state.state.proposals[proposal_id].status == "failed"
    assert perceiver.calls == []  # never reached: the download failed first


async def test_the_failure_reason_names_the_wrong_kind_not_a_generic_failure(
    project_id, corpus_repo, proposals_repo, editor
):
    """The reason a person reads in the pane must distinguish "this asset is
    the wrong kind" from "this URL moved" -- `download_media` raises
    `UnsupportedMedia` naming the refused content-type for the former, and a
    worker that collapsed it into a generic "download failed" would lose
    that distinction. Checked against `MediaProposalFailed.error` directly
    (via `SpyProposalsRepo`), not the folded `status` string, because
    `ProposalRecord` does not carry the reason at all.
    """
    proposal_id = "p1"
    await _accept(
        proposals_repo, project_id, proposal_id, asset_url="https://a.example/login-wall.jpg"
    )
    spy = SpyProposalsRepo(proposals_repo)
    reads = FakeReads(
        {proposal_id: _detail(project_id, asset_url="https://a.example/login-wall.jpg")}
    )
    worker = MediaAcceptWorker(
        reads=reads,
        proposals=spy,
        editor=editor,
        perceiver=FakePerceiver(),
        client=_html_client(),
    )

    await worker.run(proposal_id=proposal_id)

    assert isinstance(spy.appended[-1], MediaProposalFailed)
    assert "text/html" in spy.appended[-1].error


async def test_a_moved_asset_records_a_failure_rather_than_leaving_the_proposal_stuck(
    project_id, corpus_repo, proposals_repo, editor
):
    """Review finding 2: before the fix, `MediaMoved` *was* caught around
    `download_media` (unlike the two exceptions below), so this test alone
    would not have caught the regression -- it is here for completeness of
    "a test per failure mode" and to guard the exception set from narrowing
    again by accident.
    """
    proposal_id = "p1"
    await _accept(
        proposals_repo, project_id, proposal_id, asset_url="https://a.example/moved.jpg"
    )
    spy = SpyProposalsRepo(proposals_repo)
    reads = FakeReads(
        {proposal_id: _detail(project_id, asset_url="https://a.example/moved.jpg")}
    )
    worker = MediaAcceptWorker(
        reads=reads,
        proposals=spy,
        editor=editor,
        perceiver=FakePerceiver(),
        client=_redirect_client(),
    )

    await worker.run(proposal_id=proposal_id)

    proposal_state = await proposals_repo.load_or_create(project_id)
    assert proposal_state.state.proposals[proposal_id].status == "failed"
    assert isinstance(spy.appended[-1], MediaProposalFailed)
    assert "redirected" in spy.appended[-1].error


async def test_an_oversized_asset_records_a_failure_instead_of_propagating_uncaught(
    project_id, corpus_repo, proposals_repo, editor
):
    """This is the review's finding 2a, red against the code as it shipped:
    `MediaTooLarge` is not raised by `download_media` itself -- it is raised
    from inside `chunks()`, mid-iteration, and the only thing that iterates
    is `CorpusEditor.store_media`'s `put`, one try block later than the old
    `except (UnsupportedMedia, MediaMoved, MediaTooLarge)` around
    `download_media` alone. Against the reverted worker, this exception
    propagates out of `run` entirely and no `MediaProposalFailed` is ever
    appended -- the proposal stays `accepted` and the pane renders
    "Storing…" forever. Proven red by reverting `media_acquisition.py`'s
    `except MediaTooLarge` clause around `store_media` before writing this.
    """
    proposal_id = "p1"
    await _accept(
        proposals_repo, project_id, proposal_id, asset_url="https://a.example/huge.jpg"
    )
    spy = SpyProposalsRepo(proposals_repo)
    reads = FakeReads(
        {proposal_id: _detail(project_id, asset_url="https://a.example/huge.jpg")}
    )
    worker = MediaAcceptWorker(
        reads=reads,
        proposals=spy,
        editor=editor,
        perceiver=FakePerceiver(),
        client=_image_client(body=b"\xff\xd8\xff" * 100),
        max_bytes=10,
    )

    await worker.run(proposal_id=proposal_id)

    corpus = await corpus_repo.load_or_create(project_id)
    assert proposal_id not in corpus.state.documents
    proposal_state = await proposals_repo.load_or_create(project_id)
    assert proposal_state.state.proposals[proposal_id].status == "failed"
    assert isinstance(spy.appended[-1], MediaProposalFailed)
    assert "ceiling" in spy.appended[-1].error


async def test_a_transport_error_records_a_failure_instead_of_propagating_uncaught(
    project_id, corpus_repo, proposals_repo, editor
):
    """Review finding 2b: `httpx.HTTPError` -- DNS failure, refused
    connection, TLS error, read timeout -- was not caught at all. Red against
    the reverted worker for the same reason as the oversized test above: the
    exception propagates out of `run`, is logged by the route's
    fire-and-forget wrapper, and no `MediaProposalFailed` is ever recorded.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    proposal_id = "p1"
    await _accept(
        proposals_repo, project_id, proposal_id, asset_url="https://unreachable.example/x.jpg"
    )
    spy = SpyProposalsRepo(proposals_repo)
    reads = FakeReads(
        {proposal_id: _detail(project_id, asset_url="https://unreachable.example/x.jpg")}
    )
    worker = MediaAcceptWorker(
        reads=reads,
        proposals=spy,
        editor=editor,
        perceiver=FakePerceiver(),
        client=_client(handler),
    )

    await worker.run(proposal_id=proposal_id)

    proposal_state = await proposals_repo.load_or_create(project_id)
    assert proposal_state.state.proposals[proposal_id].status == "failed"
    assert isinstance(spy.appended[-1], MediaProposalFailed)
    assert "download failed" in spy.appended[-1].error


async def test_a_retry_after_a_crash_between_store_and_record_is_treated_as_success(
    project_id, corpus_repo, proposals_repo, editor
):
    """The controller ruling from the task-11 brief: `StoreMediaProposal`
    against an already-`stored` proposal is refused by `decide`, not made
    idempotent, because `decide` cannot arbitrate between two different
    `source_id`s both claiming to be the same result. A worker retrying
    after its own successful run must read that refusal as confirmation, not
    surface it as an error. Fails if the worker lets `CommandRejectedError`
    propagate on a second run.
    """
    proposal_id = "p1"
    await _accept(
        proposals_repo, project_id, proposal_id, asset_url="https://cdn.example/trajan.jpg"
    )
    reads = FakeReads(
        {proposal_id: _detail(project_id, asset_url="https://cdn.example/trajan.jpg")}
    )
    worker = MediaAcceptWorker(
        reads=reads,
        proposals=proposals_repo,
        editor=editor,
        perceiver=FakePerceiver(),
        client=_image_client(),
    )

    await worker.run(proposal_id=proposal_id)
    # A second run over the same already-stored proposal -- what a supervisor
    # replaying an unacknowledged dispatch after a crash would do. Must not
    # raise.
    await worker.run(proposal_id=proposal_id)

    proposal_state = await proposals_repo.load_or_create(project_id)
    assert proposal_state.state.proposals[proposal_id].status == "stored"


async def test_an_unknown_proposal_id_is_a_no_op(
    project_id, corpus_repo, proposals_repo, editor
):
    """Nothing to act on and nothing to report against -- `FailMediaProposal`
    needs a `project_id` this read is the only source of, and `decide`
    refuses it for an unknown id regardless. A dispatch racing its own
    projection should not crash the worker.
    """
    worker = MediaAcceptWorker(
        reads=FakeReads({}),
        proposals=proposals_repo,
        editor=editor,
        perceiver=FakePerceiver(),
        client=_image_client(),
    )

    await worker.run(proposal_id="never-proposed")  # must not raise


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
