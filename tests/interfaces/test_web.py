"""The HTTP adapter, exercised over ASGI with no network and no real model."""

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from research_team.application import GATED_TOOLS, SummaryProjects, WorkerRoster
from research_team.application.knowledge import ExtractionNote
from research_team.application.ports import ActivityMessage
from research_team.composition import build_application as _build_application
from research_team.domain import (
    AutonomyChanged,
    DeleteFile,
    WriteFile,
)
from research_team.interfaces.web import TurnActivity, create_app
from research_team.interfaces.web.extraction import ExtractionActivity
from tests.conftest import start_session
from tests.interfaces.test_web_projects import _project_with_sources
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


# ---------------- files, history, diffs ----------------


@pytest.fixture
def writing_model(fake_model):
    """A model that writes a file, then edits it -- two turns of provenance."""
    fake_model.responses = [
        AIMessage(
            content="",
            id="a1",
            tool_calls=[
                {
                    "name": "write_file",
                    "args": {"file_path": "/hello.py", "content": "print('hi')\n"},
                    "id": "t1",
                }
            ],
        ),
        AIMessage(content="wrote it", id="a2"),
        AIMessage(
            content="",
            id="a3",
            tool_calls=[
                {
                    "name": "edit_file",
                    "args": {
                        "file_path": "/hello.py",
                        "old_string": "hi",
                        "new_string": "hello",
                    },
                    "id": "t2",
                }
            ],
        ),
        AIMessage(content="edited it", id="a4"),
    ]
    return fake_model


@pytest.fixture
async def written(db_path, writing_model):
    application = await _started(model=writing_model, db_path=db_path)
    api = create_app(application.service, application.feed, application.turns)
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        session_id = await _new_session(client)
        await client.post(f"/api/sessions/{session_id}/turns", json={"input": "write"})
        await client.post(f"/api/sessions/{session_id}/turns", json={"input": "edit"})
        yield client, session_id
    await application.close()


async def test_file_is_listed_with_size_and_revisions(written):
    client, session_id = written
    body = (await client.get(f"/api/sessions/{session_id}")).json()
    assert [entry["path"] for entry in body["files"]] == ["/hello.py"]
    assert body["files"][0]["revisions"] == 2  # one write, one edit


async def test_file_contents_are_served(written):
    client, session_id = written
    body = (
        await client.get(f"/api/sessions/{session_id}/files", params={"path": "/hello.py"})
    ).json()
    assert "hello" in body["content"]


async def test_missing_file_is_404(written):
    client, session_id = written
    response = await client.get(
        f"/api/sessions/{session_id}/files", params={"path": "/nope.py"}
    )
    assert response.status_code == 404


async def test_file_history_carries_the_edit_intent(written):
    client, session_id = written
    rows = (
        await client.get(
            f"/api/sessions/{session_id}/files/history", params={"path": "/hello.py"}
        )
    ).json()
    assert [row["type"] for row in rows] == ["FileWritten", "FileEdited"]
    assert rows[0]["old_string"] is None
    assert rows[1]["old_string"] == "hi"
    assert rows[1]["new_string"] == "hello"


# ---------------- time travel ----------------


async def test_scrubbing_reproduces_the_earlier_workspace(written):
    """The point of the whole project: fold to a prefix, see the past."""
    client, session_id = written
    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    write_index = next(row["index"] for row in events if row["type"] == "FileWritten")

    past = (await client.get(f"/api/sessions/{session_id}/at/{write_index}")).json()
    assert past["at"] == write_index
    assert [entry["path"] for entry in past["files"]] == ["/hello.py"]

    head = (await client.get(f"/api/sessions/{session_id}")).json()
    assert head["at"] is None
    # The edit happened after the fold point, so the past is genuinely smaller.
    assert past["files"][0]["size"] < head["files"][0]["size"]


async def test_scrubbing_writes_nothing(written):
    client, session_id = written
    before = (await client.get(f"/api/sessions/{session_id}/events")).json()
    await client.get(f"/api/sessions/{session_id}/at/2")
    after = (await client.get(f"/api/sessions/{session_id}/events")).json()
    assert after == before
    assert len((await client.get("/api/sessions")).json()) == 1


async def test_scrubbing_out_of_range_is_400(written):
    client, session_id = written
    assert (await client.get(f"/api/sessions/{session_id}/at/999")).status_code == 400
    assert (await client.get(f"/api/sessions/{session_id}/at/0")).status_code == 400


# ---------------- forks ----------------


async def test_fork_creates_a_child_and_leaves_the_original(client):
    session_id = await _new_session(client)
    await client.post(f"/api/sessions/{session_id}/turns", json={"input": "hello"})
    before = (await client.get(f"/api/sessions/{session_id}/events")).json()

    forked = (await client.post(f"/api/sessions/{session_id}/forks", json={"at": 1})).json()[
        "id"
    ]

    assert forked != session_id
    assert (await client.get(f"/api/sessions/{session_id}/events")).json() == before
    child = (await client.get(f"/api/sessions/{forked}")).json()
    assert child["forked_from"] == session_id
    assert child["forked_at"] == 1


async def test_fork_out_of_range_is_400(client):
    session_id = await _new_session(client)
    response = await client.post(f"/api/sessions/{session_id}/forks", json={"at": 99})
    assert response.status_code == 400


async def test_tree_nests_forks_under_their_parent(client):
    parent = await _new_session(client)
    await client.post(f"/api/sessions/{parent}/turns", json={"input": "hello"})
    child = (await client.post(f"/api/sessions/{parent}/forks", json={"at": 1})).json()["id"]

    tree = (await client.get("/api/tree")).json()
    assert [node["id"] for node in tree] == [parent]
    assert [node["id"] for node in tree[0]["children"]] == [child]
    assert tree[0]["children"][0]["forked_at"] == 1


async def test_tree_keeps_unforked_sessions_as_roots(client):
    first = await _new_session(client)
    second = await _new_session(client)
    tree = (await client.get("/api/tree")).json()
    assert {node["id"] for node in tree} == {first, second}
    assert all(node["children"] == [] for node in tree)


# ---------------- the page itself ----------------


# `test_index_is_served` moved to `test_web_console.py`, beside the unbuilt
# case. It mounted the real `STATIC_DIR`, which no longer exists in a clone
# that has not run `npm run build` -- so it asserted 200 and got the 503 that
# absence is now supposed to produce, in a CI job with no Node toolchain to
# fix it with. Its replacement builds a one-line `index.html` and tests the
# route, which is what it was ever about.


# ---------------- reading files in the past ----------------


async def test_a_file_can_be_read_as_of_an_earlier_event(written):
    """Scrubbing must reach file *contents*, not just the file list."""
    client, session_id = written
    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    write_index = next(row["index"] for row in events if row["type"] == "FileWritten")

    past = (
        await client.get(
            f"/api/sessions/{session_id}/files",
            params={"path": "/hello.py", "at": write_index},
        )
    ).json()
    head = (
        await client.get(f"/api/sessions/{session_id}/files", params={"path": "/hello.py"})
    ).json()

    assert past["at"] == write_index
    assert "hi" in past["content"]
    assert "hello" not in past["content"]
    assert "hello" in head["content"]


async def test_a_file_deleted_later_is_still_readable_in_the_past(db_path, fake_model):
    """The headline case: seeing a deleted file again is the point."""
    application = await _started(model=fake_model, db_path=db_path)
    api = create_app(application.service, application.feed, application.turns)
    session_id = await start_session(application.service)
    session = await application.service.load(session_id)
    session.execute(WriteFile(path="/doomed.py", file_data={"content": "still here\n"}))
    session.execute(DeleteFile(path="/doomed.py"))
    await application.service._repository.save(session)

    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        events = (await client.get(f"/api/sessions/{session_id}/events")).json()
        written_at = next(r["index"] for r in events if r["type"] == "FileWritten")

        gone = await client.get(
            f"/api/sessions/{session_id}/files", params={"path": "/doomed.py"}
        )
        past = await client.get(
            f"/api/sessions/{session_id}/files",
            params={"path": "/doomed.py", "at": written_at},
        )

    assert gone.status_code == 404
    assert past.status_code == 200
    assert past.json()["content"] == "still here\n"
    await application.close()


async def test_reading_a_file_at_an_impossible_point_is_400(written):
    client, session_id = written
    response = await client.get(
        f"/api/sessions/{session_id}/files", params={"path": "/hello.py", "at": 999}
    )
    assert response.status_code == 400


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


# ---------------- turn activity ----------------


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
    from research_team.application import LiveFeed
    from research_team.interfaces.web.app import _sse

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


async def make_project(client, name: str = "atlas") -> UUID:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 200
    return UUID(response.json()["id"])


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
    from research_team.application import LiveFeed
    from research_team.interfaces.web.app import _sse

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
    from research_team.application import LiveFeed
    from research_team.interfaces.web.app import _sse
    from research_team.interfaces.web.seeding import SeedingActivity

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
