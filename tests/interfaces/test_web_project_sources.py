"""Project source route tests exercised over ASGI with no network and no real model."""

import hashlib
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.application import SummaryProjects, WorkerRoster
from research_team.composition import build_application as _build_application
from research_team.domain import (
    DropSourceDocument,
    StoreSourceDocument,
)
from research_team.infrastructure.persistence import build_corpus_repository
from research_team.interfaces.web import create_app
from research_team.interfaces.web.extraction import ExtractionActivity


async def _started(**kwargs):
    """Build an application and start its projection.

    These tests construct their own applications rather than take the fixture,
    because they need the FastAPI app wired around the same instance. Starting
    is still not optional -- `/sessions` reads a projection that has to be
    following the log before it can answer.
    """
    application = _build_application(**kwargs)
    await application.start()
    return application


@pytest.fixture
def extraction():
    """The buffer the app and its roster share -- the reporter's other end.

    Its own fixture so both sides of `app_and_client` and any test that drives
    it get the one instance. Two would let the `/workers` answer and the
    `/extraction` answer disagree about the same ingest, which is the failure
    the single-channel design rules out.
    """
    return ExtractionActivity()


@pytest.fixture
async def app_and_client(db_path, fake_model, extraction):
    application = await _started(model=fake_model, db_path=db_path)
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=application.blob_store,
        workers=WorkerRoster(
            application.service,
            turns=application.turns,
            runs=application.research,
            extractions=extraction,
            # Wired as the composition root wires it, so `/api/workers` is
            # exercised in its real shape: without this a running turn has no
            # way back to its project and the cross-project route would answer
            # empty while looking correct.
            summaries=SummaryProjects(application.summaries),
        ),
        extraction=extraction,
        # The application's own policy, not a fresh one: the routes are only
        # able to change anything because they hold the object the executor
        # reads, and a test against a copy would pass while proving nothing.
        policy=application.policy,
        topics=application.topic_readers,
        topic_repository=application.topic_repository,
        graphs=application.graphs,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield application, client
    await application.close()


@pytest.fixture
def client(app_and_client):
    return app_and_client[1]


async def _project_with_sources(application, client, *documents) -> str:
    """A project holding `documents`, with the corpus projection caught up.

    Takes document *specs* -- keyword dicts -- rather than built commands,
    because `StoreSourceDocument` names the corpus it targets and this helper
    is what decides which corpus that is. A caller cannot name an id the helper
    has not created yet.

    Stores through the `Corpus` aggregate rather than through `remember`,
    because `remember` runs an extraction and these tests are about the read
    path. The projection follows the log asynchronously, so the wait is what
    makes the assertions deterministic rather than timing-dependent.
    """
    created = await client.post("/api/projects", json={"name": f"corpus-{uuid4()}"})
    assert created.status_code == 200
    project_id = created.json()["id"]

    corpus = build_corpus_repository(
        application.service._repository.store,
        application.service._repository.publisher,
        snapshot_store=application.service._repository.snapshot_store,
    )
    aggregate = await corpus.load_or_create(UUID(project_id))
    for spec in documents:
        # A dict is a store spec this helper addresses; anything else is
        # already a command (a drop), which names no corpus and needs none.
        aggregate.execute(
            StoreSourceDocument(corpus_id=UUID(project_id), **spec)
            if isinstance(spec, dict)
            else spec
        )
    await corpus.save(aggregate)
    await application.corpus_caught_up()
    return project_id


async def test_listing_sources_reports_metadata_and_never_text(app_and_client):
    application, client = app_and_client
    project_id = await _project_with_sources(
        application,
        client,
        {
            "source_id": "s1",
            "text": "Ada Lovelace worked with Charles Babbage.",
            "uri": "https://example.test/ada",
            "title": "Ada Lovelace",
            "published_at": "1843-07-10",
            "note": "for the timeline",
        },
        {"source_id": "s2", "text": "Grace Hopper."},
    )

    response = await client.get(f"/api/projects/{project_id}/sources")

    assert response.status_code == 200
    rows = response.json()
    assert [row["source_id"] for row in rows] == ["s1", "s2"]
    assert rows[0]["char_count"] == 41
    assert rows[0]["uri"] == "https://example.test/ada"
    assert rows[0]["title"] == "Ada Lovelace"
    assert rows[0]["published_at"] == "1843-07-10"
    assert rows[0]["note"] == "for the timeline"
    # The digest describes the bytes, so a quote can be checked against the
    # document it claims to come from even after that source is revised.
    assert (
        rows[0]["sha256"]
        == hashlib.sha256(b"Ada Lovelace worked with Charles Babbage.").hexdigest()
    )
    # The contract that makes a listing affordable for a corpus of hundreds.
    assert all("text" not in row for row in rows)


async def test_listing_sources_of_an_empty_corpus_is_an_empty_list(app_and_client):
    """An existing project with nothing stored is empty, not missing."""
    _, client = app_and_client
    created = await client.post("/api/projects", json={"name": f"bare-{uuid4()}"})
    project_id = created.json()["id"]

    response = await client.get(f"/api/projects/{project_id}/sources")

    assert response.status_code == 200
    assert response.json() == []


async def test_reading_a_source_returns_its_text_and_citation(app_and_client):
    application, client = app_and_client
    project_id = await _project_with_sources(
        application,
        client,
        {
            "source_id": "s1",
            "text": "Ada Lovelace worked with Charles Babbage.",
            "title": "Ada Lovelace",
        },
    )

    response = await client.get(f"/api/projects/{project_id}/sources/s1")

    assert response.status_code == 200
    body = response.json()
    assert body["source_id"] == "s1"
    assert body["text"] == "Ada Lovelace worked with Charles Babbage."
    assert body["title"] == "Ada Lovelace"
    assert body["char_count"] == 41
    assert body["start"] == 0
    assert body["end"] == 41


async def test_reading_a_range_reports_the_offsets_it_actually_returned(app_and_client):
    """The offsets describe the text in the response, not the text requested."""
    application, client = app_and_client
    project_id = await _project_with_sources(
        application,
        client,
        {"source_id": "s1", "text": "Ada Lovelace worked with Charles Babbage."},
    )

    response = await client.get(
        f"/api/projects/{project_id}/sources/s1", params={"start": 4, "end": 12}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "Lovelace"
    assert (body["start"], body["end"]) == (4, 12)
    assert body["char_count"] == 41, "the whole document's size, not the range's"


async def test_a_range_past_the_end_is_clamped_rather_than_refused(app_and_client):
    application, client = app_and_client
    project_id = await _project_with_sources(
        application,
        client,
        {"source_id": "s1", "text": "Ada Lovelace."},
    )

    response = await client.get(
        f"/api/projects/{project_id}/sources/s1", params={"start": 4, "end": 9_000}
    )

    assert response.status_code == 200
    assert response.json()["end"] == 13


async def test_an_unknown_source_is_a_404(app_and_client):
    application, client = app_and_client
    project_id = await _project_with_sources(
        application,
        client,
        {"source_id": "s1", "text": "Ada Lovelace."},
    )

    response = await client.get(f"/api/projects/{project_id}/sources/nope")

    assert response.status_code == 404
    assert "nope" in response.json()["detail"]


async def test_an_unknown_project_is_a_404_on_both_routes(client):
    unknown = uuid4()

    listing = await client.get(f"/api/projects/{unknown}/sources")
    reading = await client.get(f"/api/projects/{unknown}/sources/s1")

    assert listing.status_code == 404
    assert reading.status_code == 404


async def test_a_dropped_source_leaves_the_default_listing_but_stays_readable(
    app_and_client,
):
    """Dropped means excluded from the default listing, not unreadable.

    This test used to assert 404 on the read as well, under the name
    `..._is_gone_from_both_routes`. That was right while nothing could drop a
    document from the console; now the console lists dropped rows, opens them,
    and offers Restore, so the read route is where someone looks at the text
    they are deciding about. The listing default is unchanged -- it is what the
    agent's own tool sees -- and only the read route opted in.
    """
    application, client = app_and_client
    project_id = await _project_with_sources(
        application,
        client,
        {"source_id": "s1", "text": "Ada Lovelace."},
        DropSourceDocument(source_id="s1", reason="superseded by the 1843 notes"),
    )

    listing = await client.get(f"/api/projects/{project_id}/sources")
    reading = await client.get(f"/api/projects/{project_id}/sources/s1")

    assert listing.json() == []
    assert reading.status_code == 200
    assert reading.json()["dropped_reason"] == "superseded by the 1843 notes"


async def test_dropped_sources_can_be_listed_with_their_reason(app_and_client):
    """The corpus keeps dropped documents deliberately. A browser that hid
    them would misreport what the project holds."""
    application, client = app_and_client
    project_id = await _project_with_sources(
        application,
        client,
        {"source_id": "s1", "text": "Ada Lovelace."},
        DropSourceDocument(source_id="s1", reason="superseded by a later edition"),
    )

    rows = (
        await client.get(f"/api/projects/{project_id}/sources?include_dropped=true")
    ).json()

    assert rows[0]["dropped_reason"] == "superseded by a later edition"


async def test_listing_without_include_dropped_omits_the_reason_key_too(app_and_client):
    """The default answer says nothing about drops at all, live or dropped."""
    application, client = app_and_client
    project_id = await _project_with_sources(
        application, client, {"source_id": "s1", "text": "Ada Lovelace."}
    )

    rows = (await client.get(f"/api/projects/{project_id}/sources")).json()

    assert rows[0]["dropped_reason"] is None
