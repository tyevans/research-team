"""Worker roster, extraction/activity catch-up, and stream frame tests exercised over ASGI."""

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.composition import build_application as _build_application
from research_team.interfaces.web import TurnActivity, create_app
from research_team.interfaces.web.extraction import ExtractionActivity
from research_team.knowledge.application import ExtractionNote
from research_team.platform.shared.ports import ActivityMessage
from research_team.session.application.workers import (
    SummaryProjects,
    WorkerRoster,
)
from tests.interfaces.test_web_stream import StubRequest, _drain, _subscribed


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
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield application, client
    await application.close()


@pytest.fixture
def client(app_and_client):
    return app_and_client[1]


@pytest.fixture
async def activity_app(db_path, fake_model):
    """One `TurnActivity` on both sides of the wire.

    The supervisor writes into it and the catch-up route reads out of it; two
    instances would give the route a different answer about the same turn than
    the turn itself has.
    """
    activity = TurnActivity()
    application = await _started(model=fake_model, db_path=db_path, activity=activity)
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        activity=activity,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield application, client, activity
    await application.close()


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


async def make_project(client, name: str = "atlas") -> UUID:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 200
    return UUID(response.json()["id"])


# ---------------- turn activity ----------------


async def test_activity_catch_up_route_is_empty_before_a_turn(activity_app):
    _, client, _ = activity_app
    session_id = await _new_session(client)
    body = (await client.get(f"/api/sessions/{session_id}/turns/current/activity")).json()
    assert body == {"running": [], "discarded": []}


async def test_a_turn_reports_activity_into_the_buffer(activity_app):
    """The buffer fills during the turn; it is dropped once the turn commits."""
    _, client, _ = activity_app
    session_id = await _new_session(client)
    response = await client.post(f"/api/sessions/{session_id}/turns", json={"input": "hi"})
    assert response.status_code == 200
    # Committed, so the log is authoritative and the buffer is gone.
    body = (await client.get(f"/api/sessions/{session_id}/turns/current/activity")).json()
    assert body["running"] == []


async def test_activity_frames_ride_the_stream_without_an_id(repository, session_id):
    """Exercises `_sse` directly, like the other frame-shape tests above --
    the ASGI transport cannot stream a still-running response (see
    `test_stream_reaches_a_real_browser_over_a_real_socket`), so going
    through the HTTP client here would just hang.
    """
    from research_team.interfaces.web.app import _sse
    from research_team.platform.shared.live_feed import LiveFeed

    activity = TurnActivity()
    feed = LiveFeed(repository, poll_interval=0.01)

    frames: list[str] = []
    generator = _sse(StubRequest(), feed, None, None, activity)
    await _subscribed(generator)
    task = asyncio.create_task(_drain(generator, frames, wanted=1))
    activity.begin(session_id)
    activity.reporter(session_id)(
        ActivityMessage(message_id="a1", kind="assistant", payload={"content": "hi"})
    )
    await asyncio.wait_for(task, timeout=5)

    assert frames[0].startswith("data: ")
    payload = json.loads(frames[0][len("data: ") :])
    assert payload["type"] == "TurnActivity"
    assert payload["message_id"] == "a1"
    # Not a log entry: no id line precedes the data, unlike a logged event.
    assert "\nid:" not in frames[0]


# ---------------- extraction ----------------


async def test_extraction_catch_up_is_empty_before_anything_runs(client):
    project_id = await make_project(client)

    response = await client.get(f"/api/projects/{project_id}/extraction")

    assert response.status_code == 200
    assert response.json() == {"current": [], "last": []}


async def test_extraction_catch_up_shows_the_running_ingest(client, extraction):
    """A tab that arrived mid-ingest can catch up.

    The frames carry no feed position, so this route is the only way back to
    a pane's state after a reconnect.
    """
    project_id = await make_project(client)
    extraction.reporter(project_id)(
        ExtractionNote(source_id="notes", stage="consolidating", index=3, total=9)
    )

    response = await client.get(f"/api/projects/{project_id}/extraction")

    body = response.json()
    assert [frame["stage"] for frame in body["current"]] == ["consolidating"]
    assert body["current"][0]["total"] == 9
    assert body["last"] == []


async def test_the_roster_shows_a_running_extraction(client, extraction):
    """The roster and the pane read one buffer, so they cannot disagree.

    Asked through `/api/workers` because the per-project route it used to use
    was deleted unused; the buffer being folded is the same one either way.
    """
    project_id = await make_project(client)
    extraction.reporter(project_id)(
        ExtractionNote(source_id="notes", stage="consolidating", index=3, total=9)
    )

    body = (await client.get("/api/workers")).json()

    assert [row["project_id"] for row in body] == [str(project_id)]
    assert [worker["kind"] for worker in body[0]["workers"]] == ["extraction"]
    assert body[0]["workers"][0]["detail"] == "consolidating 3/9"


async def test_extraction_frames_ride_the_stream_without_an_id(repository):
    """The third provisional channel, framed like the other two.

    Exercised against `_sse` directly for the reason the activity test is: the
    ASGI transport cannot stream a still-running response.
    """
    from research_team.interfaces.web.app import _sse
    from research_team.platform.shared.live_feed import LiveFeed

    activity = ExtractionActivity()
    feed = LiveFeed(repository, poll_interval=0.01)
    project_id = uuid4()

    frames: list[str] = []
    generator = _sse(StubRequest(), feed, None, None, None, activity)
    await _subscribed(generator)
    task = asyncio.create_task(_drain(generator, frames, wanted=1))
    activity.reporter(project_id)(ExtractionNote(source_id="notes", stage="chunking"))
    await asyncio.wait_for(task, timeout=5)

    assert frames[0].startswith("data: ")
    payload = json.loads(frames[0][len("data: ") :])
    assert payload["type"] == "Extraction"
    assert payload["source_id"] == "notes"
    # Not a log entry: no id line precedes the data, so a reconnect refetches.
    assert "\nid:" not in frames[0]


async def test_seeding_frames_ride_the_stream_without_an_id(repository):
    """The fourth provisional channel, framed like the other three.

    Wired last because nothing forced it: `SeedingActivity`'s catch-up route
    already answers "what happened" cold, and `open_topic` already streams
    over the log. But a subject-less "running" frame arriving live is what
    lets the panel show something before a browser reloads to find out.
    """
    from research_team.interfaces.web.app import _sse
    from research_team.interfaces.web.seeding import SeedingActivity
    from research_team.platform.shared.live_feed import LiveFeed

    seeding = SeedingActivity()
    feed = LiveFeed(repository, poll_interval=0.01)
    project_id = uuid4()

    frames: list[str] = []
    generator = _sse(StubRequest(), feed, None, None, None, None, seeding)
    await _subscribed(generator)
    task = asyncio.create_task(_drain(generator, frames, wanted=1))

    async def _run(run_id):
        raise RuntimeError("boom")

    seeding.start(project_id, _run)
    await asyncio.wait_for(task, timeout=5)

    assert frames[0].startswith("data: ")
    payload = json.loads(frames[0][len("data: ") :])
    assert payload["type"] == "Seeding"
    assert payload["project_id"] == str(project_id)
    assert payload["status"] == "running"
    # Not a log entry: no id line precedes the data, so a reconnect refetches.
    assert "\nid:" not in frames[0]
    await seeding.wait(project_id)
