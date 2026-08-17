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

from research_team import composition
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


async def test_the_reconciler_reads_only_after_caught_up_returns(db_path, monkeypatch):
    """B101: the ordering in `Application.start()` -- `caught_up()` before the
    reconciler task is created -- was stated in the spec and in a comment
    above the call, but nothing exercised it. The two existing tests above
    pass either way: their fixture's projection catches up fast enough
    in-process that the reconciler finds the row settled whichever line ran
    first, so they would not fail if the two lines were swapped.

    This test stalls `caught_up()` on purpose -- a fake that blocks on an
    `asyncio.Event` until released -- and records, on a shared list, the
    moment the reconciler makes its read (`accepted_proposal_ids()`) against
    the moment the fake returns. The assertion is on that list's order, not
    on the absence of an exception: `start()` completing or `reconciled()`
    returning would both be silent about which line ran first.

    Verified against the mutation it exists to catch: with the two lines in
    `Application.start()` swapped (reconciler task created *before*
    `await self.media_proposals.caught_up()`), this test FAILED --
    `events == ['reconciler_read', 'caught_up_released']`, because
    `create_task` schedules the reconciler and the very next `await` (the
    swapped `caught_up()` call) yields control to it before the fake
    unblocks. Restored to the correct order, it PASSED. Neither of the
    tests above was disturbed by the swap.
    """
    project_id, proposal_id = uuid4(), str(uuid4())
    await _crash_after_accepting(db_path, project_id, proposal_id, stored=False)

    # The periodic sweep (`Application._sweep_reconciliation`) calls the same
    # `accepted_proposal_ids` this test records on, so a sweep landing inside
    # the test would append a third event and fail an assertion that has
    # nothing to do with sweeps. Pinned rather than tolerated: at the default
    # interval the full-jitter draw from `[0, 300]` lands under this test's
    # ~10ms lifetime about 1.7e-4 of the time, and an intermittent failure in
    # the one test whose job is pinning the reconciler's *ordering* is exactly
    # what trains people to shrug at a real one (`BACKLOG.md` B4 is the entry
    # about a test called flaky for months that was actually broken).
    #
    # Both halves are needed and neither is enough alone: the huge interval
    # sets the ceiling, and removing the jitter makes the draw *be* that
    # ceiling rather than merely usually near it -- so the first sweep is
    # scheduled eleven days out by construction, not by probability. Nothing
    # here weakens full jitter itself; it is turned off for this one
    # application, in the one test that cannot observe a sweep.
    monkeypatch.setenv("AGENT_MEDIA_RECONCILE_INTERVAL", "1000000")
    monkeypatch.setattr(composition.random, "uniform", lambda _low, high: high)

    application = _build(db_path)
    events: list[str] = []
    release = asyncio.Event()

    real_caught_up = application.media_proposals.caught_up
    real_reads = application.media_proposals.accepted_proposal_ids

    async def stalled_caught_up() -> None:
        # Stands in for a projection still mid-replay: does not return until
        # the test releases it, so a reconciler that reads before this
        # returns is reading an under-reported accepted set -- exactly the
        # defect the spec's ordering ruling exists to prevent.
        await real_caught_up()
        await release.wait()
        events.append("caught_up_released")

    async def recording_reads() -> list[str]:
        events.append("reconciler_read")
        return await real_reads()

    application.media_proposals.caught_up = stalled_caught_up
    application.media_proposals.accepted_proposal_ids = recording_reads
    try:
        start_task = asyncio.create_task(application.start())
        # One tick: enough for `start()` to run everything up to and
        # including the call to (stalled) `caught_up()`, not enough for
        # anything scheduled after it to have run yet.
        await asyncio.sleep(0)
        assert events == [], "reconciler read before caught_up() was even released"

        release.set()
        await start_task
        await application.reconciled()

        assert events == ["caught_up_released", "reconciler_read"]
    finally:
        await application.close()
