"""Autonomy and tool permission tests exercised over ASGI."""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.composition import build_application as _build_application
from research_team.interfaces.web import create_app
from research_team.interfaces.web.extraction import ExtractionActivity
from research_team.session.application.autonomy import GATED_TOOLS
from research_team.session.application.workers import (
    SummaryProjects,
    WorkerRoster,
)
from research_team.session.domain import AutonomyChanged


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


@pytest.fixture
async def client_without_policy(db_path, fake_model):
    """A build with no policy wired -- the shape the autonomy routes 404 for.

    Yields a live session id alongside the client, so the 404 under test is
    unambiguously "no policy here" rather than "no such session".
    """
    application = await _started(model=fake_model, db_path=db_path)
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        policy=None,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, await _new_session(client)
    await application.close()


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


@pytest.fixture
async def session_id(client) -> str:
    return await _new_session(client)


# ---------------- autonomy ----------------


async def test_get_autonomy_reports_levels_and_the_tool_lists(client):
    """The read the UI draws its switches from, including the list that keeps
    it from hardcoding `GATED_TOOLS` in JavaScript and drifting from it.

    `stage_gates` was a third key here until the workflow removal. It named
    exactly one tool and that tool is being deleted, so the key would shortly
    have named nothing. `set(body)` rather than only checking the two keys
    present, because a test that asserts what it wants passes with a removed
    key still being sent.
    """
    body = (await client.get("/api/autonomy")).json()

    assert set(body["levels"]) == set(GATED_TOOLS)
    assert body["gated"] == list(GATED_TOOLS)
    assert set(body) == {"levels", "gated"}


async def test_setting_one_tool_changes_the_reported_level(client):
    session_id = await _new_session(client)

    response = await client.post(
        f"/api/sessions/{session_id}/autonomy",
        json={"tool": "write_file", "level": "deny"},
    )

    assert response.status_code == 200
    assert response.json()["levels"]["write_file"] == "deny"
    assert (await client.get("/api/autonomy")).json()["levels"]["write_file"] == "deny"


async def test_setting_a_tool_records_the_change_in_the_session_log(client, service):
    """The audit guarantee. The policy is what the executor consults, so a route
    that only mutated it would leave a session whose behaviour changed mid-run
    with nothing in the log to say so -- and every decision after that point
    unreadable, in a system whose whole point is the complete trail.
    """
    session_id = await _new_session(client)

    await client.post(
        f"/api/sessions/{session_id}/autonomy",
        json={"tool": "web_search", "level": "ask"},
    )

    events = await service.history(UUID(session_id))
    changes = [event for event in events if isinstance(event, AutonomyChanged)]
    assert [(change.tool_name, change.level) for change in changes] == [("web_search", "ask")]


async def test_a_bad_level_is_a_400_carrying_the_policys_own_message(client, service):
    """The policy words this better than a generic error, so it is relayed
    rather than restated -- and nothing is recorded, because nothing changed.
    """
    session_id = await _new_session(client)

    response = await client.post(
        f"/api/sessions/{session_id}/autonomy",
        json={"tool": "web_search", "level": "sometimes"},
    )

    assert response.status_code == 400
    assert "sometimes" in response.json()["detail"]
    events = await service.history(UUID(session_id))
    assert not [event for event in events if isinstance(event, AutonomyChanged)]


async def test_a_tool_that_is_not_gated_is_a_400(client):
    session_id = await _new_session(client)

    response = await client.post(
        f"/api/sessions/{session_id}/autonomy",
        json={"tool": "read_file", "level": "ask"},
    )

    assert response.status_code == 400
    assert "read_file" in response.json()["detail"]


async def test_allow_all_records_exactly_the_changes_it_made(client, service):
    """One event per level that really moved, never one per gated tool: a log
    claiming eight decisions where a person made one is as unreadable as one
    that omitted them.

    `fetch_media` now appears in `changed` alongside `fetch` -- intended, not
    drift: it floors at `ask` for the same reason `fetch` does (a network
    tool a model can point at any URL, see `TOOL_FLOORS`), so allow-all
    genuinely relaxes it too. It is the first floored tool where "allow all"
    means authorizing megabytes to disk and, downstream, a perception pass --
    worth a person seeing named in the log, not folded into a count.
    """
    session_id = await _new_session(client)
    await client.post(
        f"/api/sessions/{session_id}/autonomy",
        json={"tool": "write_file", "level": "deny"},
    )

    body = (await client.post(f"/api/sessions/{session_id}/autonomy/allow-all")).json()

    assert body["changed"] == {"write_file": "auto", "fetch": "auto", "fetch_media": "auto"}
    events = await service.history(UUID(session_id))
    changes = [event for event in events if isinstance(event, AutonomyChanged)]
    assert [(change.tool_name, change.level) for change in changes] == [
        ("write_file", "deny"),
        # `GATED_TOOLS` order, which is the order `relax_all` walks.
        ("fetch", "auto"),
        ("fetch_media", "auto"),
        ("write_file", "auto"),
    ]


async def test_autonomy_routes_404_when_no_policy_is_wired(client_without_policy):
    """ "This build cannot tell you" is a different claim from "everything is
    auto", so the routes are absent rather than answering permissively.
    """
    client, session_id = client_without_policy

    assert (await client.get("/api/autonomy")).status_code == 404
    setting = await client.post(
        f"/api/sessions/{session_id}/autonomy",
        json={"tool": "write_file", "level": "ask"},
    )
    assert setting.status_code == 404
    relaxing = await client.post(f"/api/sessions/{session_id}/autonomy/allow-all")
    assert relaxing.status_code == 404


async def test_setting_autonomy_on_an_unknown_session_is_a_404(client):
    response = await client.post(
        f"/api/sessions/{uuid4()}/autonomy",
        json={"tool": "write_file", "level": "ask"},
    )
    assert response.status_code == 404
