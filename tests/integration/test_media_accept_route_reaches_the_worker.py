"""Accepting a proposal reaching `MediaAcceptWorker`, through a composed app.

Task 9 built the accept route (appends `MediaProposalAccepted`, answers 202).
Task 11 built `MediaAcceptWorker` (download, store, perceive, record).
Nothing called the worker from the route -- both tasks' own tests stayed
green with the two unconnected, because the route's tests assert a 202 and
the worker's tests drive it directly, and neither can see that no caller
exists between them. This is Task 11b: wire the two together, and prove it
the same way `test_media_reaches_the_graph.py` proves perception is wired --
against a composed `build_application`/`create_app`, asserting the *effect*
rather than the response.

**A 202 is not proof.** It was true before this task and would stay true if
`accept_media_proposal` never scheduled the worker at all -- see the route's
own prior docstring, which said as much outright ("the fetch ... does not
exist in this build"). What this file asserts instead is that a corpus
source appears whose `uri` is the proposal's `page_url`, which only happens
if the accept route actually reached `MediaAcceptWorker.run`.

**No network.** `client` is an `httpx.AsyncClient` over `httpx.MockTransport`,
mirroring `tests/application/test_media_acquisition.py`'s own `_client`
helper -- the exact fake this suite already trusts for the download step.
`perception` is a fake `PerceptionPort`, mirroring
`test_media_reaches_the_graph.py`'s `FakeTranscriber`, so eager perception
after storing also touches nothing real. Neither curation port
(`MediaCurationTextPort`/`MediaSearchPort`) is built at all: this file seeds
the proposal directly with `ProposeMedia` against
`application.media_proposal_repository`, the same command
`MediaCurationService` would append, because what this test is proving is
the accept -> worker seam, not the curation chain that produces a proposal
in the first place -- `test_media_proposals_reach_the_read_model.py` already
covers curation reaching its own read model.
"""

import asyncio
from uuid import UUID, uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from research_team.application.perception import (
    LocatorSpan,
    Perceived,
    PerceptionCapabilities,
)
from research_team.composition import build_application
from research_team.domain.media_proposals import ProposeMedia
from research_team.interfaces.web.app import create_app

pytestmark = pytest.mark.asyncio

ASSET_URL = "https://example.test/media-corpus/trajan-column.jpg"
PAGE_URL = "https://example.test/gallery/trajan-column"
IMAGE_BYTES = b"\xff\xd8\xff" + b"fake jpeg bytes for the accept-route test"


def _mock_transport() -> httpx.AsyncClient:
    """A stubbed download: any GET answers one small JPEG. `MockTransport`,
    like `test_media_acquisition.py`'s own `_client` helper -- no request
    here ever reaches a socket.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=IMAGE_BYTES)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class FakeVision:
    """A `PerceptionPort` that describes an image without a vision model.

    Only `perceive`/`capabilities` are used -- `MediaAcceptWorker` calls
    `perceive` through `MediaPerceiver`, not this port directly, but
    `build_application(perception=...)` is the only injection seam either
    way.
    """

    async def perceive(self, *, sha256: str, max_chars: int) -> Perceived:
        return Perceived(
            text="a marble relief showing a triumphal procession",
            locators=(LocatorSpan(0, 10, {"kind": "region"}),),
            fingerprint="vision=fake-1",
            degradations=(),
        )

    def capabilities(self) -> PerceptionCapabilities:
        return PerceptionCapabilities(vision=True, asr=True, ffmpeg=True)


@pytest.fixture
async def wired(db_path, monkeypatch):
    """A composed application and its HTTP surface, with no network reachable
    from either the download or the perception step.
    """
    monkeypatch.setenv("AGENT_VECTOR_STORE", "none")
    application = build_application(
        db_path=db_path,
        perception=FakeVision(),
        media_http_client=_mock_transport(),
    )
    await application.start()
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=application.blob_store,
        editor=application.editor,
        media_proposals=application.media_proposals,
        media_proposal_repository=application.media_proposal_repository,
        media_accept_worker=application.media_accept_worker,
    )
    client = AsyncClient(transport=ASGITransport(app=api), base_url="http://test")
    async with client:
        yield application, client
    await application.close()


async def _propose(application, project_id: UUID, proposal_id: str) -> None:
    """Seed one proposal directly with the command `MediaCurationService`
    itself would append -- see the module docstring for why this test does
    not go through curation to get there.
    """
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
            title="Trajan's Column, detail",
            reason="shows the relief the finding describes",
            query="trajan column relief",
        )
    )
    await application.media_proposal_repository.save(aggregate)
    await application.media_proposals.caught_up()


async def test_accepting_a_proposal_stores_it_as_a_source(wired):
    """The whole point of this task: POST .../accept makes a source appear.

    Proposed -> accepted (202) -> the worker runs unawaited -- so the source
    is polled for, not assumed present the instant the response returns --
    -> `/sources` lists one row whose `uri` is the proposal's page, not its
    asset URL (`MediaAcceptWorker`'s own docstring explains why: provenance
    is where a thing was found, and a signed asset URL may not resolve
    tomorrow).
    """
    application, client = wired
    proposal_id = str(uuid4())

    created = await client.post("/api/projects", json={"name": "media-accept-wiring"})
    assert created.status_code == 200
    project_id = UUID(created.json()["id"])

    await _propose(application, project_id, proposal_id)

    accepted = await client.post(
        f"/api/projects/{project_id}/media-proposals/{proposal_id}/accept"
    )
    assert accepted.status_code == 202

    # Polled rather than asserted immediately: the route schedules the
    # worker with `asyncio.create_task` and returns before it has run, which
    # is the entire point of the 202 -- see the accept route's docstring.
    for _ in range(200):
        listed = await client.get(f"/api/projects/{project_id}/sources")
        assert listed.status_code == 200
        rows = listed.json()
        if rows:
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("no source appeared within the poll budget")

    assert len(rows) == 1
    assert rows[0]["uri"] == PAGE_URL
    assert rows[0]["source_id"] == proposal_id
