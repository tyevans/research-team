"""Health and rebuild route tests exercised over ASGI."""

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.composition import build_application as _build_application
from research_team.interfaces.web import create_app
from tests.conftest import start_session
from tests.interfaces.test_web_projects import _project_with_sources


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
async def app_and_client(db_path, fake_model):
    application = await _started(model=fake_model, db_path=db_path)
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=application.blob_store,
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


@pytest.fixture
def service(app_and_client):
    return app_and_client[0].service


# ---------------- health and rebuild ----------------


async def test_health_reports_the_projection_is_trustworthy(client):
    body = (await client.get("/api/health")).json()
    assert body["summaries"]["healthy"] is True
    assert body["summaries"]["failed_events"] == 0


async def test_rebuild_endpoint_rederives_the_session_list(client, service):
    """A browser is the primary surface, so the repair has to be reachable there.

    Safe to expose: it discards derived data and recomputes it from the log,
    which is idempotent and cannot lose anything the log still holds.
    """
    session_id = await start_session(service)

    response = await client.post("/api/summaries/rebuild")

    assert response.status_code == 200
    assert response.json()["healthy"] is True
    listed = (await client.get("/api/sessions")).json()
    assert [row["id"] for row in listed] == [str(session_id)]


async def test_rebuilding_the_corpus_rederives_its_table(app_and_client):
    """The corpus's own repair, separate from the session list's.

    Separate because the two runners are: rebuilding stops a manager,
    truncates a table and resets a checkpoint, and repairing `/sessions` must
    not truncate the corpus. Asserting the sources survive is what says this
    rebuilt rather than merely emptied.
    """
    application, client = app_and_client
    project_id = await _project_with_sources(
        application, client, {"source_id": "s1", "text": "a body"}
    )

    response = await client.post("/api/corpus/rebuild")

    assert response.status_code == 200
    assert response.json()["rebuilt"] is True
    listed = (await client.get(f"/api/projects/{project_id}/sources")).json()
    assert [row["source_id"] for row in listed] == ["s1"]


async def test_rebuilding_the_corpus_without_one_configured_is_a_503(app_and_client):
    """Mirrors `_reader`: an unwired read model is a configuration fault, and
    503 is what every other corpus route says about it.

    Built unwired here rather than taking the `client` fixture, which supplies
    a corpus -- the same shape `test_graph_routes_503_when_no_graph_reader_is_configured`
    uses, and for the same reason: a build without the read model is a valid
    thing to serve, so the absence has to be constructed rather than assumed.
    """
    application, _ = app_and_client
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=None,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as unwired:
        response = await unwired.post("/api/corpus/rebuild")

    assert response.status_code == 503


async def test_a_corpus_wired_without_a_blob_store_still_refuses_the_source_routes(
    app_and_client,
):
    """The half-wired build, which is the one worth constructing.

    Every other 503 test here passes `corpus=None`, so the first disjunct in
    `_reader` fires and the second is never reached -- deleting
    `or blob_store is None` leaves all of them green. This passes a real
    corpus and no blob store, which is the only arrangement that can tell the
    two apart.

    503 rather than serving text reads and failing only on a download: a build
    that can list sources but cannot open one's bytes is not a working corpus
    surface, and answering 200 here would move the discovery of the missing
    wiring to the first person who pressed play.
    """
    application, client = app_and_client
    # A project that exists, because `_require_project` runs before `_reader`:
    # against a made-up id this route answers 404 and never reaches the
    # disjunct under test.
    project_id = (await client.post("/api/projects", json={"name": "half-wired"})).json()["id"]
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=None,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as unwired:
        response = await unwired.get(f"/api/projects/{project_id}/sources")

    assert response.status_code == 503
    assert "corpus read model" in response.json()["detail"]
