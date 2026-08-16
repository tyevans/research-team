"""Reconciliation reaching `MediaAcceptWorker` from `Application.start()`.

The defect (designed in
`docs/superpowers/specs/2026-08-16-accept-reconciliation-design.md`): a
proposal accepted just before the process dies stays `accepted` forever,
because the download was handed to `asyncio.create_task` and nothing re-runs
it. The fix is a call in `Application.start()`, and the spec's central ruling
is *where* that call lives -- `web.py` carries three separate "was missing:
these routes have been 503ing in this entrypoint while the test fixture wired
one and passed" comments, and `tests/interfaces/test_web_entrypoint.py` exists
because that happened three times.

So this file asserts against a **composed** application. A test that built its
own `MediaAcceptReconciler` would pass against a build where nothing in
`start()` calls it -- and that build's symptom is silence, since a
reconciliation that never ran and one that found nothing to do render
identically.

**The crash is simulated with two applications over one database**, rather
than by extending
`tests/integration/test_media_accept_route_reaches_the_worker.py`: that file's
fixture starts the application and *then* seeds, which is the one order this
feature cannot be observed in. The events have to already be on the log when
`start()` is called.

**No network.** `media_http_client` is an `httpx.MockTransport` and
`perception` is a fake port, mirroring that file exactly --
`build_application` promises no network by default and `BACKLOG.md` B92 is the
entry about a composed test that broke the promise.
"""

import asyncio
from uuid import UUID, uuid4

import httpx
import pytest

from research_team.application.perception import (
    LocatorSpan,
    Perceived,
    PerceptionCapabilities,
)
from research_team.composition import build_application
from research_team.domain.media_proposals import (
    AcceptMediaProposal,
    ProposeMedia,
    StoreMediaProposal,
)
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader

pytestmark = pytest.mark.asyncio

ASSET_URL = "https://example.test/media-corpus/aqueduct.jpg"
PAGE_URL = "https://example.test/gallery/aqueduct"
IMAGE_BYTES = b"\xff\xd8\xff" + b"fake jpeg bytes for the reconciliation test"


def _mock_transport() -> httpx.AsyncClient:
    """Any GET answers one small JPEG -- the same stub
    `test_media_accept_route_reaches_the_worker.py` uses, so no request in
    this file reaches a socket.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=IMAGE_BYTES)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class FakeVision:
    """A `PerceptionPort` that describes an image without a vision model.

    `MediaAcceptWorker` perceives eagerly after storing (step 3 of its
    docstring), so a reconciled proposal reaches this port too.
    """

    async def perceive(self, *, sha256: str, max_chars: int) -> Perceived:
        return Perceived(
            text="an arcade of arches carrying a channel",
            locators=(LocatorSpan(0, 10, {"kind": "region"}),),
            fingerprint="vision=fake-1",
            degradations=(),
        )

    def capabilities(self) -> PerceptionCapabilities:
        return PerceptionCapabilities(vision=True, asr=True, ffmpeg=True)


def _build(db_path):
    return build_application(
        db_path=db_path,
        perception=FakeVision(),
        media_http_client=_mock_transport(),
    )


async def _crash_after_accepting(db_path, project_id: UUID, proposal_id: str, *, stored: bool):
    """Leave a proposal on the log and close the process that accepted it.

    Appends through a first application and closes it without the worker ever
    running -- which is the crash, expressed at the only level a test can
    express it: `MediaProposalAccepted` is on the log and no
    `MediaProposalStored` follows it.

    `stored=True` appends that follow-up too, for the case the reconciler must
    leave alone.
    """
    application = _build(db_path)
    await application.start()
    try:
        aggregate = await application.media_proposal_repository.load_or_create(project_id)
        aggregate.execute(
            ProposeMedia(
                project_id=str(project_id),
                proposal_id=proposal_id,
                need_id="need-0",
                topic_id=str(uuid4()),
                page_url=PAGE_URL,
                asset_url=ASSET_URL,
                thumbnail_url="",
                kind="image",
                title="An aqueduct",
                reason="shows the structure the finding describes",
                query="roman aqueduct",
            )
        )
        aggregate.execute(
            AcceptMediaProposal(project_id=str(project_id), proposal_id=proposal_id)
        )
        if stored:
            aggregate.execute(
                StoreMediaProposal(
                    project_id=str(project_id),
                    proposal_id=proposal_id,
                    source_id=proposal_id,
                )
            )
        await application.media_proposal_repository.save(aggregate)
        await application.media_proposals.caught_up()
    finally:
        await application.close()


async def _status(application, project_id: UUID, proposal_id: str) -> str | None:
    rows = await application.media_proposals.for_project(project_id)
    return next((row.status for row in rows if row.proposal_id == proposal_id), None)


async def test_an_accepted_proposal_is_reconciled_when_the_application_starts(db_path):
    """The test the three `web.py` gaps would have been caught by.

    Composed, not hand-wired: it fails if the call in `Application.start()` is
    deleted -- proved by deleting it, not assumed. The assertion is on the
    data, per CLAUDE.md's Events section: a corpus source exists for the
    proposal id and the proposal now reads `stored`. That `start()` returned
    proves nothing at all here.
    """
    project_id, proposal_id = uuid4(), str(uuid4())
    await _crash_after_accepting(db_path, project_id, proposal_id, stored=False)

    application = _build(db_path)
    try:
        await application.start()
        await application.reconciled()
        await application.media_proposals.caught_up()
        assert await _status(application, project_id, proposal_id) == "stored"

        # Polled rather than `corpus_caught_up()`: that method waits for the
        # store's *global* latest position, and the last event this test
        # appends is the reconciler's own `MediaProposalStored` -- a
        # media-proposal event the corpus subscription never advances past,
        # so the wait times out at 10s against a projection that is in fact
        # up to date. Measured here on 2026-08-16, not reasoned: the call
        # raised `TimeoutError ... did not reach Position(key=(5,))` while
        # the row it was waiting for was already readable.
        reader = ProjectCorpusReader(application.corpus, project_id, application.blob_store)
        for _ in range(200):
            handle = await reader.read_media(proposal_id)
            if handle is not None:
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail("no corpus source for the reconciled proposal within the poll budget")

        # The *page* url, not the asset the download fetched -- what
        # `MediaAcceptWorker` stores as provenance. Asserted so this is a
        # claim about that worker having run, not merely about some row
        # appearing under the id.
        assert handle.record.uri == PAGE_URL
    finally:
        await application.close()


async def test_a_stored_proposal_is_not_re_run(db_path):
    """The assertion is that the worker was *not called*.

    Asserting the end state is unchanged would prove nothing: a proposal that
    was re-run lands back on `stored` too (`MediaAcceptWorker`'s docstring:
    an already-`stored` refusal is read back as its own success signal), so
    the state is identical either way and the wasted download is invisible.
    """
    project_id, proposal_id = uuid4(), str(uuid4())
    await _crash_after_accepting(db_path, project_id, proposal_id, stored=True)

    application = _build(db_path)
    calls: list[str] = []

    async def record(proposal_id: str) -> None:
        calls.append(proposal_id)

    # Patched on the worker instance rather than through a fake handed to
    # `build_application`: there is no injection seam for the worker, and
    # replacing it wholesale would stop testing the composed object. The
    # reconciler resolves `self._worker.run` at call time, so this is the
    # call it makes.
    application.media_accept_worker.run = record
    try:
        await application.start()
        await application.reconciled()
        assert calls == []
    finally:
        await application.close()
