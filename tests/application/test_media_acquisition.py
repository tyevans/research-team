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

from research_team.application.corpus_editing import CorpusEditor
from research_team.application.media_acquisition import (
    AcceptedProposal,
    MediaAcceptWorker,
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
    authority to follow it can decide to. Surfaced as `UnsupportedMedia`
    naming the Location, since there is no media type to report yet.
    """
    with pytest.raises(UnsupportedMedia) as excinfo:
        await download_media(
            "https://a.example/x.jpg", client=_redirect_client(), max_bytes=10_000
        )
    assert "https://a.example/real.jpg" in str(excinfo.value)


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
