"""Failure handling and retry tests for `MediaAcceptWorker`."""

from uuid import UUID, uuid4

import httpx
import pytest
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.testing import InMemoryTestHarness

from research_team.infrastructure.persistence.blob_store import FilesystemBlobStore
from research_team.research.application.corpus_editing import CorpusEditor
from research_team.research.application.media_acquisition import (
    AcceptedProposal,
    MediaAcceptWorker,
)
from research_team.research.domain.corpus import Corpus
from research_team.research.domain.media_proposals import (
    AcceptMediaProposal,
    MediaProposalFailed,
    MediaProposals,
    ProposeMedia,
)


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
