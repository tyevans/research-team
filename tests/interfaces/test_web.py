"""The HTTP adapter, exercised over ASGI with no network and no real model."""

from uuid import uuid4

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


async def _new_session(client) -> str:
    """A session over HTTP, by the only route there is: a project, then a join.

    `POST /api/sessions` is gone -- a session belongs to a project, and joining
    one is where the project agrees to it. A project per call, with a unique
    name: a project holds one session at a time and creation rejects a
    duplicate name, so a shared one would fail the second caller in a rejection
    about neither of their subjects.
    """
    project = await client.post("/api/projects", json={"name": f"test project {uuid4()}"})
    assert project.status_code == 200
    response = await client.post(f"/api/projects/{project.json()['id']}/join")
    assert response.status_code == 200
    return response.json()["id"]


# ---------------- sessions ----------------


async def test_create_and_list_sessions(client):
    session_id = await _new_session(client)
    listed = (await client.get("/api/sessions")).json()
    assert [row["id"] for row in listed] == [session_id]


async def test_get_session_reports_its_prompt_and_model(client):
    session_id = await _new_session(client)
    body = (await client.get(f"/api/sessions/{session_id}")).json()
    assert body["id"] == session_id
    assert body["system_prompt"]
    assert body["turn_index"] == 0
    assert body["files"] == []


# `test_create_session_honours_a_custom_prompt` was here. It posted a
# `system_prompt` to `POST /api/sessions`; both the field and the endpoint are
# gone, and there is nothing left to assert -- `start_in_project` composes the
# prompt and takes no override, so no HTTP caller can choose one. The claim
# that a session runs under its own prompt still has a home in
# tests/application/test_session_service.py, driven at the aggregate.


async def test_unknown_session_is_404(client):
    response = await client.get("/api/sessions/8ad0f9de-0000-4000-8000-000000000000")
    assert response.status_code == 404


async def test_malformed_session_id_is_422(client):
    assert (await client.get("/api/sessions/not-a-uuid")).status_code == 422


# ---------------- turns ----------------


async def test_run_turn_records_events_and_returns_the_reply(client):
    session_id = await _new_session(client)
    response = await client.post(f"/api/sessions/{session_id}/turns", json={"input": "hello"})
    assert response.status_code == 200
    assert response.json()["reply"] == "done"

    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    assert [row["type"] for row in events] == [
        "SessionStarted",
        "UserMessageSent",
        "AssistantMessageAdded",
        "TurnCompleted",
    ]
    assert [row["index"] for row in events] == [1, 2, 3, 4]


async def test_messages_are_rendered_with_roles(client):
    session_id = await _new_session(client)
    await client.post(f"/api/sessions/{session_id}/turns", json={"input": "hello"})
    body = (await client.get(f"/api/sessions/{session_id}")).json()
    assert [message["role"] for message in body["messages"]] == ["user", "assistant"]
    assert body["messages"][0]["content"] == "hello"


# ---------------- the page itself ----------------


# `test_index_is_served` moved to `test_web_console.py`, beside the unbuilt
# case. It mounted the real `STATIC_DIR`, which no longer exists in a clone
# that has not run `npm run build` -- so it asserted 200 and got the 503 that
# absence is now supposed to produce, in a CI job with no Node toolchain to
# fix it with. Its replacement builds a one-line `index.html` and tests the
# route, which is what it was ever about.


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
