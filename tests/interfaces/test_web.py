"""The HTTP adapter, exercised over ASGI with no network and no real model."""

import asyncio
import hashlib
import json
from uuid import UUID, uuid4

import pytest
from eventsource.ports.positions import ExpectedVersion
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from redstring.events.document import DocumentExtracted
from redstring.events.streams import document_stream

from research_team.application import GATED_TOOLS, SummaryProjects, WorkerRoster
from research_team.application.autonomy import ADVANCE_STAGE_TOOL
from research_team.application.graph_read import MAX_GRAPH_NODES
from research_team.application.knowledge import ExtractionNote
from research_team.application.ports import ActivityMessage
from research_team.composition import build_application as _build_application
from research_team.domain import (
    AutonomyChanged,
    DeleteFile,
    DropSourceDocument,
    SendUserMessage,
    StartSession,
    StoreSourceDocument,
    WriteFile,
)
from research_team.domain.topic import OpenTopic, RecordFinding
from research_team.infrastructure.persistence import build_corpus_repository
from research_team.infrastructure.persistence.event_store import build_topic_repository
from research_team.interfaces.web import TurnActivity, create_app
from research_team.interfaces.web.dispatch import DispatchQueue
from research_team.interfaces.web.extraction import ExtractionActivity
from research_team.interfaces.web.seeding import SeedingActivity
from tests.conftest import start_session


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
async def client_without_workers(db_path, fake_model):
    """A build with no roster wired -- the shape `get_workers` 404s for."""
    application = await _started(model=fake_model, db_path=db_path)
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        workers=None,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await application.close()


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


# ---------------- live feed ----------------

# httpx's ASGI transport buffers a whole response before returning it, so an
# endless SSE stream can never be read through it. The framing is unit-tested
# against the generator, and the wire is proved once against a real server.


class StubRequest:
    """The only thing `_sse` asks a request: have you gone away yet."""

    def __init__(self, disconnect_after: int = 10_000) -> None:
        self._checks = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._checks += 1
        return self._checks > self._disconnect_after


async def test_sse_frames_each_event_as_a_data_line(repository, session_id):
    from research_team.application import LiveFeed
    from research_team.interfaces.web.app import _sse

    feed = LiveFeed(repository, poll_interval=0.01)
    aggregate = repository.create(session_id)
    aggregate.execute(
        StartSession(
            session_id=aggregate.aggregate_id,
            system_prompt="prompt",
            model_name="test-model",
            project_id=uuid4(),
        )
    )
    await repository.save(aggregate)

    frames: list[str] = []
    generator = _sse(StubRequest(), feed)
    task = asyncio.create_task(_drain(generator, frames, wanted=1))
    await asyncio.sleep(0.05)
    aggregate.execute(SendUserMessage(message={"type": "human", "data": {"content": "hi"}}))
    await repository.save(aggregate)
    await asyncio.wait_for(task, timeout=5)

    assert frames[0].endswith("\n\n")
    payload = json.loads(frames[0].split("data: ", 1)[1])
    assert payload["session_id"] == str(session_id)
    assert payload["type"] == "UserMessageSent"


async def test_sse_frames_a_topic_change_as_its_own_project_shaped_frame(repository):
    """An opened topic reaches the live feed, and does not pretend to be a session.

    The research page's topic list is refreshed off these frames. Two failures
    this pins: no frame at all (what shipped -- the feed read only
    `CodingSession` streams, so a topic appeared only on a reload), and a frame
    carrying the topic's id under `session_id`, which would put the session
    tree to work refetching a session that does not exist.

    The `id:` line matters as much as the data: unlike `Seeding` and
    `Extraction`, a topic change *is* a log entry, so a browser that drops
    mid-run replays it from `Last-Event-ID` rather than losing it.
    """
    from research_team.application import LiveFeed
    from research_team.interfaces.web.app import _sse

    feed = LiveFeed(repository, poll_interval=0.01)
    topics = build_topic_repository(repository.store)
    topic = topics.create_new(uuid4())

    frames: list[str] = []
    generator = _sse(StubRequest(), feed)
    task = asyncio.create_task(_drain(generator, frames, wanted=1))
    await asyncio.sleep(0.05)
    topic.execute(
        OpenTopic(
            topic_id=topic.aggregate_id,
            project_id=uuid4(),
            question="Does spacing help?",
            rationale="the syllabus asserts it without a citation",
        )
    )
    await topics.save(topic)
    await asyncio.wait_for(task, timeout=5)

    assert frames[0].startswith("id: ")
    payload = json.loads(frames[0].split("data: ", 1)[1])
    assert payload["type"] == "Topic"
    assert payload["topic_id"] == str(topic.aggregate_id)
    assert payload["change"] == "TopicOpened"
    assert "session_id" not in payload


async def test_sse_frames_a_graph_change_addressed_to_its_project(repository):
    """An extraction reaches the live feed addressed to the project it changed.

    The graph pane redraws off these frames. Three failures this pins: no frame
    at all (what shipped -- the feed read only `CodingSession` and `Topic`, so
    entities appeared on a reload and never before it); a frame carrying the
    document stream's `uuid5` id under `session_id`, which would set the
    session tree hunting an aggregate that is a document; and a frame with no
    project on it at all, which every open tab would have to act on because
    none of them could tell whether it was theirs.

    The project id is the event's `tenant_id` and nothing else -- unlike a
    topic frame, which carries none because only its creation event knows one.
    Every redstring event is a `TenantDomainEvent`, so the answer is on the
    frame already and costs no read-model lookup on a connection every browser
    holds open.
    """
    from research_team.application import LiveFeed
    from research_team.interfaces.web.app import _sse

    feed = LiveFeed(repository, poll_interval=0.01)
    project_id = uuid4()
    stream = document_stream(tenant_id=project_id, source_id="paper-1")

    frames: list[str] = []
    generator = _sse(StubRequest(), feed)
    task = asyncio.create_task(_drain(generator, frames, wanted=1))
    await asyncio.sleep(0.05)
    await repository.store.append(
        stream,
        [
            DocumentExtracted(
                aggregate_id=stream.aggregate_id,
                tenant_id=project_id,
                source_id="paper-1",
                model_version="test-model",
            )
        ],
        ExpectedVersion.any_(),
    )
    await asyncio.wait_for(task, timeout=5)

    assert frames[0].startswith("id: ")
    payload = json.loads(frames[0].split("data: ", 1)[1])
    assert payload["type"] == "Graph"
    assert payload["project_id"] == str(project_id)
    assert payload["change"] == "DocumentExtracted"
    assert "session_id" not in payload


async def test_sse_frames_a_stored_document_as_a_corpus_frame(repository):
    """A stored source reaches the live feed addressed to its project.

    The documents pane redraws off these frames. It shipped with no live path
    of any kind -- the feed read only `CodingSession` and `Topic`, so a source
    the agent stored mid-session appeared in the rail only on a reload, while
    the reader watched the turn that fetched it scroll past.

    Its own frame type rather than a graph frame, though both move on one
    ingest: the document is stored first and an extraction that fails emits
    nothing on redstring's streams, so a pane keyed to graph frames would drop
    exactly the sources whose failure a reader needs to see. `project_id` is
    the corpus's own aggregate id -- a corpus shares its project's UUID.
    """
    from research_team.application import LiveFeed
    from research_team.interfaces.web.app import _sse

    feed = LiveFeed(repository, poll_interval=0.01)
    project_id = uuid4()
    corpus = build_corpus_repository(repository.store)
    aggregate = await corpus.load_or_create(project_id)

    frames: list[str] = []
    generator = _sse(StubRequest(), feed)
    task = asyncio.create_task(_drain(generator, frames, wanted=1))
    await asyncio.sleep(0.05)
    aggregate.execute(
        StoreSourceDocument(
            corpus_id=project_id, source_id="paper-1", text="Ada worked with Charles."
        )
    )
    await corpus.save(aggregate)
    await asyncio.wait_for(task, timeout=5)

    assert frames[0].startswith("id: ")
    payload = json.loads(frames[0].split("data: ", 1)[1])
    assert payload["type"] == "Corpus"
    assert payload["project_id"] == str(project_id)
    assert payload["change"] == "SourceDocumentStored"
    assert "session_id" not in payload


async def _drain(generator, frames: list[str], *, wanted: int) -> None:
    """Collect `wanted` data frames, then shut the generator down.

    Leaving it suspended would leave its poll loop holding the store open past
    the end of the test, which surfaces much later as a stray database error.
    """
    try:
        async for frame in generator:
            # Event frames carry an id line ahead of their data; the only other
            # thing on the wire is a `:` keepalive comment.
            if not frame.startswith(":"):
                frames.append(frame)
                if len(frames) >= wanted:
                    return
    finally:
        await generator.aclose()


async def test_sse_emits_a_keepalive_while_the_log_is_idle(repository, monkeypatch):
    """A minute of model thinking must not look like a dead connection."""
    from research_team.application import LiveFeed
    from research_team.interfaces.web import app as web_app
    from research_team.interfaces.web.app import _sse

    monkeypatch.setattr(web_app, "KEEPALIVE_SECONDS", 0.05)
    generator = _sse(StubRequest(), LiveFeed(repository, poll_interval=0.01))
    frame = await asyncio.wait_for(anext(generator), timeout=5)
    assert frame == ": keepalive\n\n"
    await generator.aclose()


async def test_sse_stops_when_the_client_goes_away(repository, monkeypatch):
    from research_team.application import LiveFeed
    from research_team.interfaces.web import app as web_app
    from research_team.interfaces.web.app import _sse

    monkeypatch.setattr(web_app, "KEEPALIVE_SECONDS", 0.01)
    generator = _sse(StubRequest(disconnect_after=2), LiveFeed(repository, poll_interval=0.01))
    frames = [frame async for frame in generator]
    assert all(frame == ": keepalive\n\n" for frame in frames)  # then it ended


async def test_stream_reaches_a_real_browser_over_a_real_socket(db_path, fake_model):
    """One end-to-end proof over the wire, since the ASGI transport cannot."""
    import uvicorn

    application = await _started(model=fake_model, db_path=db_path)
    api = create_app(application.service, application.feed, application.turns)
    config = uvicorn.Config(api, host="127.0.0.1", port=8749, log_level="error")
    server = uvicorn.Server(config)
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)

    received: list[dict] = []

    async def listen() -> None:
        async with (
            AsyncClient(timeout=20) as browser,
            browser.stream("GET", "http://127.0.0.1:8749/api/stream") as response,
        ):
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    received.append(json.loads(line[len("data: ") :]))
                    return

    listener = asyncio.create_task(listen())
    try:
        await asyncio.sleep(0.4)  # let the subscriber take its position
        session_id = await start_session(application.service)
        await asyncio.wait_for(listener, timeout=10)
    finally:
        # Let the server notice the browser has gone and unwind the streaming
        # response before shutting down: a poll still in flight when the store
        # closes is harmless but noisy.
        await asyncio.sleep(0.3)
        server.should_exit = True
        await serving
        await application.close()

    assert received[0]["session_id"] == str(session_id)
    assert received[0]["type"] == "SessionStarted"


# ---------------- the page itself ----------------


async def test_index_is_served(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


# ---------------- concurrent clients ----------------


async def test_two_turns_at_once_on_one_session_conflict_rather_than_interleave(
    app_and_client,
):
    """Two tabs, one session. One turn wins; the other is told to retry.

    The loser's events are discarded whole, so the log gains exactly one turn
    -- the all-or-nothing guarantee holding under concurrency, not just under
    failure.
    """
    application, client = app_and_client
    session_id = await start_session(application.service)

    first, second = await asyncio.gather(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "a"}),
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "b"}),
    )

    assert sorted([first.status_code, second.status_code]) == [200, 409]

    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    assert [row["type"] for row in events] == [
        "SessionStarted",
        "UserMessageSent",
        "AssistantMessageAdded",
        "TurnCompleted",
    ]


async def test_turns_on_different_sessions_run_concurrently(app_and_client):
    application, client = app_and_client
    first_id = await start_session(application.service)
    second_id = await start_session(application.service)

    responses = await asyncio.gather(
        client.post(f"/api/sessions/{first_id}/turns", json={"input": "a"}),
        client.post(f"/api/sessions/{second_id}/turns", json={"input": "b"}),
    )

    assert [response.status_code for response in responses] == [200, 200]
    for session_id in (first_id, second_id):
        events = (await client.get(f"/api/sessions/{session_id}/events")).json()
        assert len(events) == 4


async def test_reads_are_safe_while_a_turn_is_in_flight(app_and_client):
    application, client = app_and_client
    session_id = await start_session(application.service)
    await client.post(f"/api/sessions/{session_id}/turns", json={"input": "first"})

    turn, events, listing, scrub = await asyncio.gather(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "second"}),
        client.get(f"/api/sessions/{session_id}/events"),
        client.get("/api/sessions"),
        client.get(f"/api/sessions/{session_id}/at/2"),
    )

    assert turn.status_code == 200
    assert events.status_code == 200
    assert listing.status_code == 200
    assert scrub.status_code == 200


async def test_a_failed_turn_is_recorded_and_reported(app_and_client, monkeypatch):
    """A turn the model could not complete: 500 to the browser, and a marker in
    the log so the audit trail records the attempt."""
    from research_team.infrastructure.agent.deep_agent import DeepAgentTurnExecutor

    application, client = app_and_client
    session_id = await start_session(application.service)

    async def boom(self, session, messages, system_prompt, on_activity):
        raise RuntimeError("model endpoint is down")

    monkeypatch.setattr(DeepAgentTurnExecutor, "_invoke", boom)

    # The default transport re-raises app exceptions instead of turning them
    # into a response; a browser sees the 500, so this test should too.
    api = create_app(application.service, application.feed, application.turns)
    async with AsyncClient(
        transport=ASGITransport(app=api, raise_app_exceptions=False),
        base_url="http://test",
    ) as browser:
        response = await browser.post(
            f"/api/sessions/{session_id}/turns", json={"input": "hello"}
        )
    assert response.status_code == 500

    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    assert [row["type"] for row in events] == ["SessionStarted", "TurnFailed"]
    assert "model endpoint is down" in events[1]["summary"]
    # The user's message from the failed turn was discarded with the rest of it.
    body = (await client.get(f"/api/sessions/{session_id}")).json()
    assert body["messages"] == []
    assert body["turn_index"] == 0


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


# ---------------- turn outcome and cancellation ----------------


async def test_a_turn_reports_the_events_it_wrote(client):
    """So a client can say "this turn produced events 2-4" and jump to them."""
    session_id = await _new_session(client)
    body = (
        await client.post(f"/api/sessions/{session_id}/turns", json={"input": "hello"})
    ).json()

    assert body["turn_index"] == 1
    assert (body["from_index"], body["to_index"]) == (2, 4)

    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    span = [r for r in events if body["from_index"] <= r["index"] <= body["to_index"]]
    assert [row["type"] for row in span] == [
        "UserMessageSent",
        "AssistantMessageAdded",
        "TurnCompleted",
    ]


async def test_the_reported_span_continues_across_turns(client):
    session_id = await _new_session(client)
    first = (
        await client.post(f"/api/sessions/{session_id}/turns", json={"input": "one"})
    ).json()
    second = (
        await client.post(f"/api/sessions/{session_id}/turns", json={"input": "two"})
    ).json()

    assert second["from_index"] == first["to_index"] + 1
    assert second["turn_index"] == 2


async def test_nothing_is_running_on_a_quiet_session(client):
    session_id = await _new_session(client)
    body = (await client.get(f"/api/sessions/{session_id}/turns/current")).json()
    assert body["running"] is False


async def test_cancelling_when_nothing_runs_reports_so(client):
    session_id = await _new_session(client)
    body = (await client.post(f"/api/sessions/{session_id}/turns/cancel")).json()
    assert body["cancelled"] is False


@pytest.fixture
async def slow_app(db_path):
    """A server whose turns are slow enough to interrupt on purpose."""
    from tests.application.test_turn_supervisor import SlowModel

    model = SlowModel(responses=[AIMessage(content="eventually", id="s1")])
    application = await _started(model=model, db_path=db_path)
    api = create_app(application.service, application.feed, application.turns)
    async with AsyncClient(
        transport=ASGITransport(app=api, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield application, client, model
    await application.close()


async def test_an_in_flight_turn_is_visible_and_cancellable(slow_app):
    application, client, _ = slow_app
    session_id = await start_session(application.service)

    turn = asyncio.create_task(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "slow"})
    )
    await asyncio.sleep(0.4)

    running = (await client.get(f"/api/sessions/{session_id}/turns/current")).json()
    assert running["running"] is True

    cancelled = (await client.post(f"/api/sessions/{session_id}/turns/cancel")).json()
    assert cancelled["cancelled"] is True

    response = await turn
    assert response.status_code == 499  # abandoned on purpose, not a failure

    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    assert [row["type"] for row in events] == ["SessionStarted", "TurnFailed"]
    assert (await client.get(f"/api/sessions/{session_id}/turns/current")).json()[
        "running"
    ] is False


async def test_a_second_turn_is_refused_while_one_is_running(slow_app):
    """Refused immediately, rather than after spending a minute in the model."""
    application, client, _ = slow_app
    session_id = await start_session(application.service)

    turn = asyncio.create_task(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "slow"})
    )
    await asyncio.sleep(0.4)

    second = await client.post(f"/api/sessions/{session_id}/turns", json={"input": "me too"})
    assert second.status_code == 409

    await client.post(f"/api/sessions/{session_id}/turns/cancel")
    assert (await turn).status_code == 499


async def test_the_session_still_works_after_a_cancellation(slow_app):
    application, client, model = slow_app
    session_id = await start_session(application.service)

    turn = asyncio.create_task(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "slow"})
    )
    await asyncio.sleep(0.4)
    await client.post(f"/api/sessions/{session_id}/turns/cancel")
    await turn

    model.delay = 0.0
    response = await client.post(f"/api/sessions/{session_id}/turns", json={"input": "quick"})

    assert response.status_code == 200
    assert response.json()["turn_index"] == 1  # the cancelled attempt never counted


async def test_a_running_turn_is_described_not_just_flagged(slow_app):
    """A tab arriving mid-turn should be able to say which turn, and for how long."""
    application, client, _ = slow_app
    session_id = await start_session(application.service)

    turn = asyncio.create_task(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "slow"})
    )
    await asyncio.sleep(0.4)

    body = (await client.get(f"/api/sessions/{session_id}/turns/current")).json()
    assert body["running"] is True
    assert body["turn_index"] == 1
    assert body["started_at"] is not None
    assert 0 < body["elapsed_seconds"] < 60

    await client.post(f"/api/sessions/{session_id}/turns/cancel")
    await turn


async def test_a_quiet_session_reports_no_running_turn_details(client):
    session_id = await _new_session(client)
    body = (await client.get(f"/api/sessions/{session_id}/turns/current")).json()
    assert body == {
        "running": False,
        "turn_index": None,
        "started_at": None,
        "elapsed_seconds": None,
    }


async def test_a_cancellation_is_marked_as_such_in_the_log(slow_app):
    """Stopped on purpose must be distinguishable from broke, without prose."""
    application, client, _ = slow_app
    session_id = await start_session(application.service)

    turn = asyncio.create_task(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "slow"})
    )
    await asyncio.sleep(0.4)
    body = (await client.post(f"/api/sessions/{session_id}/turns/cancel")).json()
    await turn

    assert body == {"cancelled": True, "settled": True}

    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    failed = next(row for row in events if row["type"] == "TurnFailed")
    assert failed["cancelled"] is True
    assert "cancelled" in failed["summary"]


async def test_a_genuine_failure_is_not_marked_cancelled(app_and_client, monkeypatch):
    from research_team.infrastructure.agent.deep_agent import DeepAgentTurnExecutor

    application, client = app_and_client
    session_id = await start_session(application.service)

    async def boom(self, session, messages, system_prompt, on_activity):
        raise RuntimeError("model endpoint is down")

    monkeypatch.setattr(DeepAgentTurnExecutor, "_invoke", boom)
    with pytest.raises(RuntimeError):
        await application.turns.run(session_id, "hello")

    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    failed = next(row for row in events if row["type"] == "TurnFailed")
    assert failed["cancelled"] is False
    assert "RuntimeError" in failed["summary"]


async def test_ordinary_events_carry_no_cancellation_flag(client):
    session_id = await _new_session(client)
    await client.post(f"/api/sessions/{session_id}/turns", json={"input": "hello"})
    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    assert all(row["cancelled"] is None for row in events)


def _cursor_of(frame: str) -> str:
    return frame.split("id: ", 1)[1].split("\n", 1)[0]


async def _watch(feed, resume_from=None, wanted: int = 1):
    """Start an `_sse` stream and collect frames in the background.

    Returns the task and the list it fills. Starting the drain *before* the
    events are appended is what makes the test meaningful: a stream takes its
    position when it is first iterated, not when it is constructed.
    """
    from research_team.interfaces.web.app import _sse

    frames: list[str] = []
    generator = _sse(StubRequest(), feed, resume_from)
    task = asyncio.create_task(_drain(generator, frames, wanted=wanted))
    await asyncio.sleep(0.05)
    return task, frames


async def test_each_frame_carries_the_cursor_that_follows_it(repository, session_id):
    """Without an id, a browser has nothing to reconnect with."""
    from research_team.application import LiveFeed

    feed = LiveFeed(repository, poll_interval=0.01)
    aggregate = repository.create(session_id)
    aggregate.execute(
        StartSession(
            session_id=aggregate.aggregate_id,
            system_prompt="prompt",
            model_name="test-model",
            project_id=uuid4(),
        )
    )
    await repository.save(aggregate)

    task, frames = await _watch(feed)
    aggregate.execute(SendUserMessage(message={"type": "human", "data": {"content": "hi"}}))
    await repository.save(aggregate)
    await asyncio.wait_for(task, timeout=5)

    assert frames[0].startswith("id: ")
    assert repository.decode_position(_cursor_of(frames[0])) is not None


async def test_reconnecting_with_a_cursor_delivers_what_was_missed(repository, session_id):
    """The gap a dropped connection leaves is the whole point of the id.

    The second message is appended while no stream is open at all, so a feed
    that started at the live end would never show it -- and the browser would
    have no way to know it had missed anything.
    """
    from research_team.application import LiveFeed

    feed = LiveFeed(repository, poll_interval=0.01)
    aggregate = repository.create(session_id)
    aggregate.execute(
        StartSession(
            session_id=aggregate.aggregate_id,
            system_prompt="prompt",
            model_name="test-model",
            project_id=uuid4(),
        )
    )
    await repository.save(aggregate)

    task, frames = await _watch(feed)
    aggregate.execute(SendUserMessage(message={"type": "human", "data": {"content": "seen"}}))
    await repository.save(aggregate)
    await asyncio.wait_for(task, timeout=5)
    cursor = _cursor_of(frames[0])

    # Nobody is listening for this one.
    aggregate.execute(
        SendUserMessage(message={"type": "human", "data": {"content": "missed"}})
    )
    await repository.save(aggregate)

    resumed, recovered = await _watch(feed, resume_from=cursor)
    await asyncio.wait_for(resumed, timeout=5)

    assert json.loads(recovered[0].split("data: ", 1)[1])["type"] == "UserMessageSent"
    assert _cursor_of(recovered[0]) != cursor


async def test_an_unplaceable_cursor_falls_back_to_the_live_end(repository, session_id):
    """A stale or foreign id must not replay the whole log at a browser."""
    from research_team.application import LiveFeed

    feed = LiveFeed(repository, poll_interval=0.01)
    aggregate = repository.create(session_id)
    aggregate.execute(
        StartSession(
            session_id=aggregate.aggregate_id,
            system_prompt="prompt",
            model_name="test-model",
            project_id=uuid4(),
        )
    )
    await repository.save(aggregate)  # already in the log, must not be replayed

    task, frames = await _watch(feed, resume_from="junk-from-another-database")
    aggregate.execute(SendUserMessage(message={"type": "human", "data": {"content": "after"}}))
    await repository.save(aggregate)
    await asyncio.wait_for(task, timeout=5)

    payload = json.loads(frames[0].split("data: ", 1)[1])
    assert payload["type"] == "UserMessageSent"


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


# ---------------- projects ----------------


async def test_list_projects_starts_empty_then_shows_a_created_one(client):
    assert (await client.get("/api/projects")).json() == []

    response = await client.post("/api/projects", json={"name": "atlas"})
    assert response.status_code == 200
    created = response.json()
    assert created["name"] == "atlas"
    assert created["id"]

    listed = (await client.get("/api/projects")).json()
    # A fresh project is held by nobody and has no tip: exactly the state a
    # row needs to offer "open" rather than a join that would be rejected.
    # No workflow either -- creating and choosing one are separate decisions,
    # and the aggregate refuses a second choice, so nothing may be assumed.
    assert listed == [
        {
            "id": created["id"],
            "name": "atlas",
            "active_session_id": None,
            "tip_at_event": 0,
            "workflow": None,
            "stage": None,
        }
    ]


async def test_creating_a_project_with_a_taken_name_does_not_create_a_second(client):
    first = await client.post("/api/projects", json={"name": "atlas"})
    assert first.status_code == 200

    second = await client.post("/api/projects", json={"name": "atlas"})
    assert second.status_code == 409

    listed = (await client.get("/api/projects")).json()
    # The proof that matters: still exactly one project, not just an error
    # response for the second attempt.
    assert len(listed) == 1
    assert listed[0]["id"] == first.json()["id"]


async def test_joining_a_project_starts_a_session_that_inherits_its_files(client, service):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]

    first_join = await client.post(f"/api/projects/{project_id}/join")
    assert first_join.status_code == 200
    first_session_id = first_join.json()["id"]
    assert first_join.json()["project_id"] == project_id

    # Put a known file on the first holder's stream directly -- deterministic,
    # unlike relying on the fake model to decide to write one -- then hand the
    # project's tip back so a second join has something to inherit.
    from uuid import UUID as _UUID

    session = await service.load(_UUID(first_session_id))
    session.execute(WriteFile(path="/atlas.py", file_data={"content": "shared content\n"}))
    await service._repository.save(session)
    await service.release_project(_UUID(first_session_id))

    second_join = await client.post(f"/api/projects/{project_id}/join")
    assert second_join.status_code == 200
    second_session_id = second_join.json()["id"]
    assert second_session_id != first_session_id

    second_body = (await client.get(f"/api/sessions/{second_session_id}")).json()
    assert second_body["project_id"] == project_id
    assert any(f["path"] == "/atlas.py" for f in second_body["files"])

    file_body = (
        await client.get(
            f"/api/sessions/{second_session_id}/files", params={"path": "/atlas.py"}
        )
    ).json()
    # The assertion that actually proves inheritance: the byte content of the
    # file on the *second* session matches what was written on the first.
    assert file_body["content"] == "shared content\n"


async def test_joining_a_project_attaches_the_knowledge_tools(app_and_client):
    """The web-route counterpart of the REPL's `/project use` attach fix.

    `application.turns_tools()` is the surface the executor actually reads
    from on the next turn -- the same surface
    `test_project_use_attaches_the_knowledge_graph` asserts on for the REPL.
    Before `POST /api/projects/{id}/join`, no project is attached, so the
    knowledge tools must be absent; asserting that first is what lets this
    test fail if the join route stops calling `attach_project`.
    """
    application, client = app_and_client

    names_before = {tool.name for tool in application.turns_tools()}
    assert "remember" not in names_before
    assert "graph_search" not in names_before
    assert "unmerge" not in names_before

    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    join = await client.post(f"/api/projects/{project_id}/join")
    assert join.status_code == 200

    names_after = {tool.name for tool in application.turns_tools()}
    assert "remember" in names_after
    assert "graph_search" in names_after
    assert "unmerge" in names_after


async def test_joining_an_already_held_project_names_the_holder(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    first_join = await client.post(f"/api/projects/{project_id}/join")
    holder_session_id = first_join.json()["id"]

    second_join = await client.post(f"/api/projects/{project_id}/join")

    assert second_join.status_code == 409
    assert holder_session_id in second_join.json()["detail"]


async def test_releasing_a_session_frees_its_project_for_the_next_one(client):
    """The loop the web app could not close: finish here, start fresh there.

    Before `POST /api/sessions/{id}/release` this took a REPL, or a restart:
    the browser had no verb that gave a project back, so the second join in
    this test could only ever be the 409 above.
    """
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    first = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]

    release = await client.post(f"/api/sessions/{first}/release")
    assert release.status_code == 200
    assert release.json() == {"released": True, "project_id": project_id}

    listed = (await client.get("/api/projects")).json()
    assert listed[0]["active_session_id"] is None

    second = await client.post(f"/api/projects/{project_id}/join")
    assert second.status_code == 200
    assert second.json()["id"] != first


async def test_releasing_a_session_twice_is_not_an_error(client):
    """Releasing what you no longer hold answers calmly rather than raising.

    This replaces a test that made a project-less session with
    `POST /api/sessions` and released that, asserting
    `{"released": False, "project_id": None}`. A session outside a project can
    no longer be built, so that response shape is unreachable and the branch in
    `release_session` that returns it is dead. The second release stands in as
    the reachable way to release something you do not hold, which is the case
    that has to stay quiet -- every REPL and browser exit path calls release
    unconditionally.

    Note what the second call answers: `released: True`, though nothing moved.
    `release_project` no-ops when the session is not the holder and the route
    reports success either way. Asserted as it stands rather than as it ought
    to be; changing the route is not this test's to do.
    """
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    session_id = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]
    assert (await client.post(f"/api/sessions/{session_id}/release")).status_code == 200

    response = await client.post(f"/api/sessions/{session_id}/release")

    assert response.status_code == 200
    assert response.json() == {"released": True, "project_id": project_id}


async def test_release_advances_the_tip_so_the_next_session_inherits(client, service):
    """Releasing is how work travels between sessions, not just cleanup.

    `release_project` advances the project's tip; a UI that only ever joined
    would fork every new session from a tip that never moved, silently losing
    everything the previous session wrote.
    """
    from uuid import UUID as _UUID

    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    first = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]

    session = await service.load(_UUID(first))
    session.execute(WriteFile(path="/atlas.py", file_data={"content": "shared content\n"}))
    await service._repository.save(session)

    assert (await client.post(f"/api/sessions/{first}/release")).status_code == 200

    second = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]
    body = (
        await client.get(f"/api/sessions/{second}/files", params={"path": "/atlas.py"})
    ).json()
    assert body["content"] == "shared content\n"


async def test_taking_over_a_held_project_ends_the_holder_and_starts_fresh(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    first = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]

    second = await client.post(f"/api/projects/{project_id}/join", json={"take_over": True})

    assert second.status_code == 200
    assert second.json()["id"] != first
    listed = (await client.get("/api/projects")).json()
    assert listed[0]["active_session_id"] == second.json()["id"]


async def test_a_session_reports_whether_it_still_holds_its_project(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    first = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]

    assert (await client.get(f"/api/sessions/{first}")).json()["holds_project"] is True

    await client.post(f"/api/projects/{project_id}/join", json={"take_over": True})

    # The fact the UI needs to stop offering this session as the live one.
    assert (await client.get(f"/api/sessions/{first}")).json()["holds_project"] is False


async def test_deleting_a_project_removes_it_from_the_listing(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await client.delete(f"/api/projects/{project_id}")

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "project_id": project_id}
    assert (await client.get("/api/projects")).json() == []


async def test_a_deleted_project_cannot_be_joined(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    await client.delete(f"/api/projects/{project_id}")

    join = await client.post(f"/api/projects/{project_id}/join")

    assert join.status_code == 409
    assert "deleted" in join.json()["detail"]


async def test_deleting_a_held_project_needs_the_holder_released_first(client):
    """The 409 names the holder, so the UI can offer the thing that fixes it."""
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    holder = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]

    refused = await client.delete(f"/api/projects/{project_id}")
    assert refused.status_code == 409
    assert holder in refused.json()["detail"]
    assert len((await client.get("/api/projects")).json()) == 1

    accepted = await client.delete(f"/api/projects/{project_id}?release_holder=true")
    assert accepted.status_code == 200
    assert (await client.get("/api/projects")).json() == []


async def test_deleting_a_project_leaves_its_sessions_readable(client, service):
    """Deletion retires the project, not the work done inside it."""
    from uuid import UUID as _UUID

    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    session_id = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]
    session = await service.load(_UUID(session_id))
    session.execute(WriteFile(path="/atlas.py", file_data={"content": "kept\n"}))
    await service._repository.save(session)

    await client.delete(f"/api/projects/{project_id}?release_holder=true")

    body = (await client.get(f"/api/sessions/{session_id}")).json()
    assert body["id"] == session_id
    assert any(f["path"] == "/atlas.py" for f in body["files"])
    file_body = (
        await client.get(f"/api/sessions/{session_id}/files", params={"path": "/atlas.py"})
    ).json()
    assert file_body["content"] == "kept\n"


async def test_a_deleted_projects_name_can_be_used_again(client):
    first = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    await client.delete(f"/api/projects/{first}")

    again = await client.post("/api/projects", json={"name": "atlas"})

    assert again.status_code == 200
    assert again.json()["id"] != first


async def test_deleting_an_unknown_project_is_a_404(client):
    response = await client.delete(f"/api/projects/{uuid4()}")

    assert response.status_code == 404


async def test_a_turn_reattaches_the_sessions_own_knowledge_graph(app_and_client):
    """The bug behind "the agent says it has no knowledge graph".

    Attaching only at join meant any later turn ran with whatever graph was
    attached last -- or none, after a restart -- even though the session's
    recorded prompt promises `remember`/`graph_search`/`unmerge`. Detaching
    here stands in for that drift; the turn has to put it back.
    """
    application, client = app_and_client

    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    session_id = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]

    await application.service.detach_project()
    assert "remember" not in {tool.name for tool in application.turns_tools()}

    response = await client.post(f"/api/sessions/{session_id}/turns", json={"input": "hi"})
    assert response.status_code == 200

    assert "remember" in {tool.name for tool in application.turns_tools()}


# ---------------- turn activity ----------------


@pytest.fixture
async def activity_app(db_path, fake_model):
    application = await _started(model=fake_model, db_path=db_path)
    activity = TurnActivity()
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
    task = asyncio.create_task(_drain(generator, frames, wanted=1))
    await asyncio.sleep(0.05)
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


# ---------------- corpus ----------------


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


async def test_a_dropped_source_is_gone_from_both_routes(app_and_client):
    """Dropped means unreadable. The row survives for the audit, not for callers."""
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
    assert reading.status_code == 404


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


# ---------------- topics ----------------


async def _project_with_topics(application, client) -> tuple[str, str]:
    """A project holding one live, never-investigated topic, projection caught up.

    Opens the topic through the `Topic` aggregate directly rather than through
    `open_topic`, the same reasoning `_project_with_sources` gives for storing
    through `Corpus` rather than `remember`: these routes are about the read
    path, not about how a topic came to exist. Returns both ids because every
    test needs the project and most need the topic too.
    """
    created = await client.post("/api/projects", json={"name": f"topics-{uuid4()}"})
    assert created.status_code == 200
    project_id = created.json()["id"]

    repository = build_topic_repository(
        application.service._repository.store,
        application.service._repository.publisher,
        snapshot_store=application.service._repository.snapshot_store,
    )
    topic = repository.create_new(uuid4())
    topic.execute(
        OpenTopic(
            topic_id=topic.aggregate_id,
            project_id=UUID(project_id),
            question="Does spacing help?",
            rationale="because it is the whole question",
        )
    )
    await repository.save(topic)
    await application.topics_caught_up()
    return project_id, str(topic.aggregate_id)


async def test_listing_topics_reports_status_counts_and_triggers(app_and_client):
    application, client = app_and_client
    project_id, _ = await _project_with_topics(application, client)

    response = await client.get(f"/api/projects/{project_id}/topics")

    assert response.status_code == 200
    row = response.json()[0]
    assert row["question"] == "Does spacing help?"
    assert row["status"] == "open"
    assert row["needs_attention"] is True
    assert "topic.never_investigated" in row["triggers"]


async def test_reading_a_topic_adds_what_the_row_leaves_out(app_and_client):
    application, client = app_and_client
    project_id, topic_id = await _project_with_topics(application, client)

    body = (await client.get(f"/api/projects/{project_id}/topics/{topic_id}")).json()

    assert body["rationale"] == "because it is the whole question"
    assert body["sub_questions"] == []
    assert body["source_ids"] == []


async def test_a_topic_detail_reports_the_same_finding_count_as_its_row(app_and_client):
    """`findings` must mean a count on both routes, or a caller cannot trust it.

    The list route has always answered `findings` with an int -- how many
    were recorded, not what they say -- because a queue row has no room to
    print prose. The detail route used to overwrite that same key with the
    array of finding summaries, which made the count unrecoverable from the
    page that actually has the findings to count. This asserts the property
    that regression broke: the detail's `findings` must still be the count,
    matching the list route for the same topic, with the prose available
    separately under `finding_notes`.
    """
    application, client = app_and_client
    project_id, topic_id = await _project_with_topics(application, client)

    repository = build_topic_repository(
        application.service._repository.store,
        application.service._repository.publisher,
        snapshot_store=application.service._repository.snapshot_store,
    )
    topic = await repository.load(UUID(topic_id))
    topic.execute(
        RecordFinding(summary="24 hours seems to be the consensus", source_ids=["a"])
    )
    topic.execute(RecordFinding(summary="one SME says 48", source_ids=["b"]))
    await repository.save(topic)
    await application.topics_caught_up()

    row = (await client.get(f"/api/projects/{project_id}/topics")).json()[0]
    detail = (await client.get(f"/api/projects/{project_id}/topics/{topic_id}")).json()

    assert row["findings"] == 2
    assert detail["findings"] == 2
    assert detail["finding_notes"] == [
        "24 hours seems to be the consensus",
        "one SME says 48",
    ]


async def test_an_unknown_topic_is_a_404(app_and_client):
    application, client = app_and_client
    project_id, _ = await _project_with_topics(application, client)
    unknown_topic = uuid4()

    response = await client.get(f"/api/projects/{project_id}/topics/{unknown_topic}")

    # A bare status code cannot tell "this route refused" from "no such route
    # is registered" -- FastAPI answers 404 for both, so an unregistered path
    # would pass this assertion with none of the code under test ever
    # running. The detail is the route's own message, and only the route
    # produces it.
    assert response.status_code == 404
    assert response.json()["detail"] == f"no such topic in project {project_id}"


async def test_an_unknown_project_is_a_404_on_both_topic_routes(client):
    missing = uuid4()

    listing = await client.get(f"/api/projects/{missing}/topics")
    reading = await client.get(f"/api/projects/{missing}/topics/{uuid4()}")

    # Same reasoning as above: `_require_project`'s message is what proves
    # these went through the route rather than matching nothing at all.
    assert listing.status_code == 404
    assert listing.json()["detail"] == f"no project {missing}"
    assert reading.status_code == 404
    assert reading.json()["detail"] == f"no project {missing}"


async def test_a_topic_from_another_project_reads_as_404_identically_to_unknown(
    app_and_client,
):
    """A caller must not be able to tell "wrong project" from "never existed".

    `ProjectTopicReader.read_topic` collapses both to `None` on purpose --
    see its docstring -- because telling them apart is exactly the
    information a project boundary exists to withhold. The status code alone
    cannot prove that: two different messages that both happen to carry 404
    would still leak "that topic exists but is not yours" to anyone reading
    the body. Byte-identical detail is the assertion that actually closes
    that gap, and the one a future refactor could not "helpfully" break
    without this test catching it.
    """
    application, client = app_and_client
    _owning_project_id, topic_id = await _project_with_topics(application, client)
    other_project_id, _ = await _project_with_topics(application, client)

    foreign = await client.get(f"/api/projects/{other_project_id}/topics/{topic_id}")
    never_existed = await client.get(f"/api/projects/{other_project_id}/topics/{uuid4()}")

    assert foreign.status_code == 404
    assert foreign.json() == never_existed.json()


async def test_closing_a_topic_records_the_justification(app_and_client):
    application, client = app_and_client
    project_id, topic_id = await _project_with_topics(application, client)

    response = await client.post(
        f"/api/projects/{project_id}/topics/{topic_id}/status",
        json={"to_status": "answered", "justification": "the sources agree"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "answered"


async def test_a_blank_justification_is_refused(app_and_client):
    """The aggregate went out of its way to make an unexplained status change
    impossible, and a transport that supplied a default to get past it would
    quietly undo that."""
    application, client = app_and_client
    project_id, topic_id = await _project_with_topics(application, client)

    response = await client.post(
        f"/api/projects/{project_id}/topics/{topic_id}/status",
        json={"to_status": "answered", "justification": "   "},
    )

    assert response.status_code == 422


async def test_reopening_an_answered_topic_is_allowed(app_and_client):
    """`decide` rejects only a no-op transition, so this is legal, and a
    reader who closed a topic too early needs it."""
    application, client = app_and_client
    project_id, topic_id = await _project_with_topics(application, client)
    await client.post(
        f"/api/projects/{project_id}/topics/{topic_id}/status",
        json={"to_status": "answered", "justification": "done"},
    )

    response = await client.post(
        f"/api/projects/{project_id}/topics/{topic_id}/status",
        json={"to_status": "open", "justification": "new material arrived"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "open"


async def test_a_repeated_status_is_a_409(app_and_client):
    """`decide` refuses a no-op transition; the transport must relay that
    rather than swallow it as a success."""
    application, client = app_and_client
    project_id, topic_id = await _project_with_topics(application, client)

    response = await client.post(
        f"/api/projects/{project_id}/topics/{topic_id}/status",
        json={"to_status": "open", "justification": "still open"},
    )

    assert response.status_code == 409


async def test_a_sub_question_can_be_added_and_resolved(app_and_client):
    application, client = app_and_client
    project_id, topic_id = await _project_with_topics(application, client)

    await client.post(
        f"/api/projects/{project_id}/topics/{topic_id}/sub-questions",
        json={"key": "motor", "question": "Does it hold for motor skills?"},
    )
    body = (
        await client.post(
            f"/api/projects/{project_id}/topics/{topic_id}/sub-questions/motor/resolve",
            json={"answer": "Yes, with a smaller effect."},
        )
    ).json()

    assert body["sub_questions"][0]["resolved"] is True
    assert body["sub_questions"][0]["answer"] == "Yes, with a smaller effect."


async def test_a_status_change_on_a_foreign_topic_is_the_same_404(app_and_client):
    """The unknown-topic 404 must not distinguish "foreign" from "never
    existed" on the write routes either, or a caller could probe project
    boundaries through a write instead of a read."""
    application, client = app_and_client
    _owning_project_id, topic_id = await _project_with_topics(application, client)
    other_project_id, _ = await _project_with_topics(application, client)

    response = await client.post(
        f"/api/projects/{other_project_id}/topics/{topic_id}/status",
        json={"to_status": "answered", "justification": "n/a"},
    )
    never_existed = await client.get(f"/api/projects/{other_project_id}/topics/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == never_existed.json()


# ---------------- workflows ----------------


async def test_the_workflow_list_says_what_each_preset_produces_and_where_it_stops(client):
    """The list is the whole basis for the choice, so it carries the consequences.

    A preset that stops before the production half yields a design and not
    materials, and someone who expected materials finding out at the end is
    the failure this endpoint exists to prevent.
    """
    body = (await client.get("/api/workflows")).json()

    by_id = {row["id"]: row for row in body}
    assert set(by_id) == {"hybrid.default", "ubd.pure", "addie.pure"}
    assert by_id["ubd.pure"]["produces"] == "design"
    assert by_id["hybrid.default"]["produces"] == "materials"
    assert by_id["ubd.pure"]["terminates_at"]["spine"] < 8
    assert all(row["label"] for row in body)


async def test_the_recommended_preset_is_listed_first(client):
    """Order is the recommendation. Whichever pure methodology a user picks,
    they inherit that tradition's structural defect, and knowing which defect
    to tolerate needs the expertise they came here without."""
    body = (await client.get("/api/workflows")).json()
    assert body[0]["id"] == "hybrid.default"


async def test_selecting_a_workflow_puts_the_project_at_the_presets_first_stage(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await client.post(
        f"/api/projects/{project_id}/workflow", json={"preset_id": "ubd.pure"}
    )
    assert response.status_code == 200

    body = (await client.get(f"/api/projects/{project_id}/workflow")).json()
    assert body["workflow"]["id"] == "ubd.pure"
    # No event records entering a stage nobody advanced to, so "the first
    # stage" is resolved from the preset rather than read off the log.
    assert body["stage"]["index"] == 1
    assert body["stage"]["of"] == 6


async def test_a_project_row_carries_its_workflow_and_stage(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    await client.post(f"/api/projects/{project_id}/workflow", json={"preset_id": "ubd.pure"})

    [row] = (await client.get("/api/projects")).json()

    assert row["workflow"]["id"] == "ubd.pure"
    assert row["workflow"]["name"] == "Understanding by Design (unit plan)"
    assert row["stage"]["index"] == 1


async def test_a_project_with_no_workflow_reports_neither(client):
    await client.post("/api/projects", json={"name": "atlas"})

    [row] = (await client.get("/api/projects")).json()

    assert row["workflow"] is None
    assert row["stage"] is None


async def test_selecting_a_second_workflow_is_a_409_naming_the_first(client):
    """The domain's refusal names the running preset, and that name is the
    whole value of it -- "already selected" leaves the user with no idea what
    they are already running."""
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    await client.post(f"/api/projects/{project_id}/workflow", json={"preset_id": "ubd.pure"})

    response = await client.post(
        f"/api/projects/{project_id}/workflow", json={"preset_id": "addie.pure"}
    )

    assert response.status_code == 409
    assert "ubd.pure" in response.json()["detail"]

    # The refusal changed nothing, which is the half an error code cannot say.
    body = (await client.get(f"/api/projects/{project_id}/workflow")).json()
    assert body["workflow"]["id"] == "ubd.pure"


async def test_an_unknown_preset_is_a_404_naming_the_ones_that_exist(client):
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await client.post(
        f"/api/projects/{project_id}/workflow", json={"preset_id": "tyler.pure"}
    )

    assert response.status_code == 404
    assert "hybrid.default" in response.json()["detail"]


async def test_an_unknown_project_is_a_404_on_both_workflow_routes(client):
    missing = uuid4()

    assert (await client.get(f"/api/projects/{missing}/workflow")).status_code == 404
    post = await client.post(
        f"/api/projects/{missing}/workflow", json={"preset_id": "ubd.pure"}
    )
    assert post.status_code == 404


async def test_a_deleted_project_refuses_a_workflow(client):
    """409 rather than 404: a tombstone is not an absence.

    The project is still there and still readable -- that is what retiring
    means here -- so the honest answer is the domain's, which says it was
    deleted. Joining a deleted project relays the same refusal the same way.
    """
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    await client.delete(f"/api/projects/{project_id}")

    response = await client.post(
        f"/api/projects/{project_id}/workflow", json={"preset_id": "ubd.pure"}
    )

    assert response.status_code == 409
    assert "deleted" in response.json()["detail"]


# ---------------- the course ----------------


async def _course_project(client, preset_id: str = "ubd.pure") -> str:
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]
    await client.post(f"/api/projects/{project_id}/workflow", json={"preset_id": preset_id})
    return project_id


async def test_the_course_lists_every_stage_whether_or_not_it_has_run(client):
    """The rail shows the plan, so a stage that has produced nothing still appears.

    A view built from the `/course` directory instead would show what happened
    and leave what was supposed to happen underivable -- backwards for a
    surface whose job is to show a run against its plan.
    """
    project_id = await _course_project(client)

    body = (await client.get(f"/api/projects/{project_id}/course")).json()

    assert body["preset"]["id"] == "ubd.pure"
    assert body["position"] == 1
    assert body["stage_count"] == len(body["stages"]) == 6
    assert body["stages"][0]["status"] == "current"
    assert {stage["status"] for stage in body["stages"][1:]} == {"upcoming"}


async def test_declared_artifacts_appear_as_named_gaps_before_anything_is_written(client):
    project_id = await _course_project(client)

    body = (await client.get(f"/api/projects/{project_id}/course")).json()
    slots = [slot for stage in body["stages"] for slot in stage["outputs"]]

    assert slots, "the preset declares outputs; the course must name them"
    assert all(slot["present"] is False for slot in slots)
    assert all(slot["path"].startswith("/course/") for slot in slots)
    assert all(slot["provenance"] is None for slot in slots)


async def test_a_written_artifact_shows_up_with_the_provenance_it_claims(client, service):
    """The course reads the filesystem of whichever session currently holds it.

    Written through the session that joined the project rather than through a
    fixture, because "which stream carries this project's files" is the part
    the endpoint has to get right.
    """
    project_id = await _course_project(client)
    body = (await client.get(f"/api/projects/{project_id}/course")).json()
    path = body["stages"][0]["outputs"][0]["path"]

    session_id = (await client.post(f"/api/projects/{project_id}/join")).json()["id"]
    session = await service.load(UUID(session_id))
    session.execute(
        WriteFile(
            path=path,
            file_data={
                "content": (
                    "---\n"
                    "artifact_type: Intent\n"
                    "stage: s\n"
                    "preset: ubd.pure\n"
                    "preset_version: '1.0'\n"
                    "provenance:\n"
                    "  - source_id: doc-1\n"
                    "    start: 0\n"
                    "    end: 40\n"
                    "---\n\nthe body\n"
                )
            },
        )
    )
    await service._repository.save(session)

    slot = (await client.get(f"/api/projects/{project_id}/course")).json()["stages"][0][
        "outputs"
    ][0]

    assert slot["present"] is True
    assert slot["has_frontmatter"] is True
    assert slot["missing_fields"] == []
    assert slot["provenance"]["sources"] == [{"source_id": "doc-1", "start": 0, "end": 40}]
    assert slot["provenance"]["empty"] is False
    assert slot["provenance"]["inferred"] is False


async def test_a_project_with_no_workflow_has_no_course(client):
    """409, not 404: the project is here; the choice has not been made."""
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await client.get(f"/api/projects/{project_id}/course")

    assert response.status_code == 409
    assert "no workflow" in response.json()["detail"]


async def test_an_unknown_project_has_no_course(client):
    response = await client.get(f"/api/projects/{uuid4()}/course")
    assert response.status_code == 404


# ---------------- components ----------------
#
# The parsed route and the attempt route are two halves of one decision: the
# learner projection strips the answer key, so the browser cannot grade and has
# to ask. Both halves are tested here rather than only the parse, because a
# projection that withholds and an endpoint that hands the key back would each
# pass on their own.

LESSON = """\
---
type: lesson
---

# Declaring severity

```component:mcq
id: sev-1
prompt: What severity?
options:
  - text: "SEV-1"
    correct: false
    feedback: "No data loss."
  - text: "SEV-2"
    correct: true
    feedback: "Textbook SEV-2."
rationale: |
  Severity is a communication decision.
```

```component:from-the-future
shape: unknowable
```
"""

LESSON_PATH = "/course/01-lesson.md"


async def _with_lesson(service, content=LESSON, path=LESSON_PATH) -> str:
    session_id = await start_session(service)
    session = await service.load(session_id)
    session.execute(WriteFile(path=path, file_data={"content": content}))
    await service._repository.save(session)
    return str(session_id)


async def test_the_parsed_view_returns_frontmatter_and_blocks_in_order(client, service):
    session_id = await _with_lesson(service)

    body = (
        await client.get(
            f"/api/sessions/{session_id}/files/parsed", params={"path": LESSON_PATH}
        )
    ).json()

    assert body["frontmatter"] == {"type": "lesson"}
    assert [b["kind"] for b in body["blocks"]] == ["markdown", "component", "component"]
    assert body["blocks"][2]["unknown"] is True


async def test_the_author_view_is_the_default_and_carries_the_key(client, service):
    session_id = await _with_lesson(service)

    body = (
        await client.get(
            f"/api/sessions/{session_id}/files/parsed", params={"path": LESSON_PATH}
        )
    ).json()

    assert body["view"] == "author"
    assert body["blocks"][1]["data"]["options"][1]["correct"] is True


async def test_the_learner_view_does_not_ship_the_answer(client, service):
    """Asserted over the response text, because the failure that matters is a
    secret reaching the wire by any route, not one particular field surviving."""
    session_id = await _with_lesson(service)

    response = await client.get(
        f"/api/sessions/{session_id}/files/parsed",
        params={"path": LESSON_PATH, "view": "learner"},
    )

    assert "Textbook SEV-2" not in response.text
    assert "communication decision" not in response.text
    assert "What severity?" in response.text


async def test_an_unrecognised_view_is_refused_rather_than_defaulted(client, service):
    """Defaulting a typo to the author view would leak the key on `view=learnr`."""
    session_id = await _with_lesson(service)

    response = await client.get(
        f"/api/sessions/{session_id}/files/parsed",
        params={"path": LESSON_PATH, "view": "learnr"},
    )

    assert response.status_code == 422


async def test_a_parsed_file_can_be_read_in_the_past(client, service):
    session_id = await start_session(service)
    session = await service.load(session_id)
    session.execute(WriteFile(path="/c.md", file_data={"content": LESSON}))
    session.execute(DeleteFile(path="/c.md"))
    await service._repository.save(session)

    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    written_at = next(r["index"] for r in events if r["type"] == "FileWritten")

    gone = await client.get(
        f"/api/sessions/{session_id}/files/parsed", params={"path": "/c.md"}
    )
    past = await client.get(
        f"/api/sessions/{session_id}/files/parsed",
        params={"path": "/c.md", "at": written_at},
    )

    assert gone.status_code == 404
    assert len(past.json()["blocks"]) == 3


async def test_a_missing_file_is_a_404_from_the_parsed_route_too(client, service):
    session_id = await _with_lesson(service)
    response = await client.get(
        f"/api/sessions/{session_id}/files/parsed", params={"path": "/nope.md"}
    )
    assert response.status_code == 404


async def test_a_right_answer_is_graded_and_the_rationale_returned(client, service):
    session_id = await _with_lesson(service)

    body = (
        await client.post(
            f"/api/sessions/{session_id}/attempts",
            json={"path": LESSON_PATH, "component_id": "sev-1", "response": 1},
        )
    ).json()

    assert body["correct"] is True
    assert body["feedback"] == ["Textbook SEV-2."]
    assert "communication decision" in body["rationale"]


async def test_a_wrong_answer_is_graded_rather_than_refused(client, service):
    session_id = await _with_lesson(service)

    response = await client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"path": LESSON_PATH, "component_id": "sev-1", "response": 0},
    )

    assert response.status_code == 200
    assert response.json()["correct"] is False
    assert response.json()["correct_options"] == [1]


async def test_an_attempt_at_a_component_that_is_not_there_is_a_404(client, service):
    session_id = await _with_lesson(service)

    response = await client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"path": LESSON_PATH, "component_id": "nope", "response": 1},
    )

    assert response.status_code == 404


async def test_a_response_of_the_wrong_shape_is_a_400_not_a_500(client, service):
    session_id = await _with_lesson(service)

    response = await client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"path": LESSON_PATH, "component_id": "sev-1", "response": {"a": 1}},
    )

    assert response.status_code == 400


async def test_an_attempt_is_graded_against_the_file_as_it_was(client, service):
    """Grading at HEAD would mark yesterday's attempt against today's key."""
    session_id = await start_session(service)
    session = await service.load(session_id)
    session.execute(WriteFile(path="/c.md", file_data={"content": LESSON}))
    await service._repository.save(session)
    events = (await client.get(f"/api/sessions/{session_id}/events")).json()
    original = next(r["index"] for r in events if r["type"] == "FileWritten")

    # The revision moves the answer rather than adding one: a second `correct`
    # option would make the item multiple-response and change what "0" means.
    revised = (
        LESSON.replace("correct: false", "correct: WAS_FALSE")
        .replace("correct: true", "correct: false")
        .replace("correct: WAS_FALSE", "correct: true")
    )
    session = await service.load(session_id)
    session.execute(WriteFile(path="/c.md", file_data={"content": revised}))
    await service._repository.save(session)

    now = await client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"path": "/c.md", "component_id": "sev-1", "response": 0},
    )
    then = await client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"path": "/c.md", "component_id": "sev-1", "response": 0, "at": original},
    )

    assert now.json()["correct"] is True
    assert then.json()["correct"] is False


# ---------------- autonomous research ----------------


@pytest.fixture
async def research_client(db_path, fake_model):
    """A client whose app was wired *with* a research supervisor.

    Separate from `client` because the default app is deliberately built
    without one: `AGENT_AUTO_RESEARCH` gates the wiring in `web.py`, and the
    unwired case is a behaviour these tests check rather than a setup detail.
    """
    application = await _started(model=fake_model, db_path=db_path)
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        research=application.research,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield application, http
    await application.close()


async def test_the_run_routes_are_absent_unless_the_instance_was_wired_for_them(client):
    """404 rather than 403: a refusal announces the loop to whoever asked."""
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await client.post(f"/api/projects/{project_id}/auto-research", json={})

    assert response.status_code == 404
    assert "AGENT_AUTO_RESEARCH" in response.json()["detail"]


async def test_starting_a_run_answers_with_its_ids_before_it_has_finished(research_client):
    application, http = research_client
    project_id = (await http.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await http.post(f"/api/projects/{project_id}/auto-research", json={})

    assert response.status_code == 202
    body = response.json()
    assert body["project_id"] == project_id
    # The run works turns on a session, and the caller is told which -- that
    # is where everything the agent actually said is visible.
    assert UUID(body["session_id"])
    await application.research.wait(UUID(project_id))


async def test_a_started_run_reports_its_own_fold(research_client):
    application, http = research_client
    project_id = (await http.post("/api/projects", json={"name": "atlas"})).json()["id"]
    started = await http.post(
        f"/api/projects/{project_id}/auto-research", json={"max_rounds": 2}
    )

    status = await http.get(f"/api/projects/{project_id}/auto-research")

    # Either the run is still in flight and reports its counters, or it has
    # already drained an empty queue -- both are folds of the same stream, and
    # which one this lands on is a race with a run that has nothing to do.
    if status.status_code == 200:
        assert status.json()["run_id"] == started.json()["run_id"]
        assert status.json()["budget"]["max_rounds"] == 2
    else:
        assert status.status_code == 404
    await application.research.wait(UUID(project_id))


async def test_asking_about_a_project_with_no_run_is_a_404(research_client):
    _, http = research_client
    project_id = (await http.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await http.get(f"/api/projects/{project_id}/auto-research")

    assert response.status_code == 404


async def test_cancelling_nothing_reports_that_nothing_was_running(research_client):
    _, http = research_client
    project_id = (await http.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await http.post(f"/api/projects/{project_id}/auto-research/cancel")

    assert response.status_code == 200
    assert response.json() == {"cancelled": False, "run": None}


async def test_a_finished_run_puts_its_session_away(research_client):
    """Or the second run on a project is refused by a session nobody is driving.

    This route starts the session the run works in, so nothing else will ever
    release it. Releasing is also what advances the project's tip, which is how
    anything a run wrote reaches the session that comes after it.
    """
    application, http = research_client
    project_id = (await http.post("/api/projects", json={"name": "atlas"})).json()["id"]

    first = await http.post(f"/api/projects/{project_id}/auto-research", json={})
    await application.research.wait(UUID(project_id))

    assert first.status_code == 202
    held = (await application.service.project_state(UUID(project_id))).active_session_id
    assert held is None
    second = await http.post(f"/api/projects/{project_id}/auto-research", json={})
    assert second.status_code == 202
    await application.research.wait(UUID(project_id))


async def test_a_run_on_an_unknown_project_is_a_404(research_client):
    _, http = research_client
    response = await http.post(f"/api/projects/{uuid4()}/auto-research", json={})
    assert response.status_code == 404


# ---------------- learner progress (B28) ----------------
#
# An attempt used to be graded and then forgotten: a reload lost every answer,
# `persist: true` was accepted and ignored, and the sequence of attempts on one
# item existed nowhere. These pin the other half -- that the verdict the learner
# was shown is also a fact the log holds.

CHECKLIST_LESSON = """\
# Runbook

```component:checklist
id: triage
persist: true
items:
  - text: "Page the on-call"
  - text: "Open an incident channel"
  - text: "Declare a severity"
```

```component:checklist
id: ephemeral
items:
  - text: "Stretch"
```
"""


async def test_an_attempt_is_remembered(client, service):
    session_id = await _with_lesson(service)

    marked = await client.post(
        f"/api/sessions/{session_id}/attempts",
        json={"path": LESSON_PATH, "component_id": "sev-1", "response": 1},
    )
    assert marked.status_code == 200
    # The verdict still comes back unchanged; progress rides alongside it.
    assert marked.json()["correct"] is True
    assert marked.json()["progress"]["attempts"] == 1

    progress = await client.get(
        f"/api/sessions/{session_id}/progress", params={"path": LESSON_PATH}
    )
    assert progress.json()["items"]["sev-1"]["correct"] is True


async def test_three_attempts_are_three_attempts_and_the_best_one_is_kept(client, service):
    session_id = await _with_lesson(service)

    for response in (0, 0, 1):
        await client.post(
            f"/api/sessions/{session_id}/attempts",
            json={"path": LESSON_PATH, "component_id": "sev-1", "response": response},
        )

    item = (
        await client.get(f"/api/sessions/{session_id}/progress", params={"path": LESSON_PATH})
    ).json()["items"]["sev-1"]
    assert item["attempts"] == 3
    assert item["correct"] is True
    assert item["best_score"] == 1.0


async def test_being_wrong_after_being_right_does_not_lose_the_completion(client, service):
    session_id = await _with_lesson(service)

    for response in (1, 0):
        await client.post(
            f"/api/sessions/{session_id}/attempts",
            json={"path": LESSON_PATH, "component_id": "sev-1", "response": response},
        )

    item = (
        await client.get(f"/api/sessions/{session_id}/progress", params={"path": LESSON_PATH})
    ).json()["items"]["sev-1"]
    assert item["correct"] is True
    assert item["last_score"] == 0.0


async def test_a_session_nobody_has_answered_anything_in_reports_nothing(client, service):
    """The ordinary case for every course before its first learner, and not a
    404 -- a client that has to handle "no progress stream yet" as an error
    handles it wrong somewhere."""
    session_id = await _with_lesson(service)

    progress = await client.get(f"/api/sessions/{session_id}/progress")
    assert progress.status_code == 200
    assert progress.json()["items"] == {}


async def test_progress_for_the_whole_session_keys_by_path_and_id(client, service):
    """Ids are only unique within a document, so the unnarrowed shape has to
    carry the path or two lessons' `sev-1` would collide."""
    session_id = await _with_lesson(service)
    session = await service.load(UUID(session_id))
    session.execute(WriteFile(path="/other.md", file_data={"content": LESSON}))
    await service._repository.save(session)

    for path in (LESSON_PATH, "/other.md"):
        await client.post(
            f"/api/sessions/{session_id}/attempts",
            json={"path": path, "component_id": "sev-1", "response": 1},
        )

    body = (await client.get(f"/api/sessions/{session_id}/progress")).json()
    assert body["scope"] == "session"
    assert set(body["items"]) == {f"{LESSON_PATH}#sev-1", "/other.md#sev-1"}


# --- checklists, which is what `persist: true` was promising ---------------


async def test_a_persisting_checklist_remembers_its_boxes(client, service):
    session_id = await _with_lesson(service, content=CHECKLIST_LESSON, path="/r.md")

    saved = await client.post(
        f"/api/sessions/{session_id}/progress/checklist",
        json={"path": "/r.md", "component_id": "triage", "checked": [2, 0]},
    )
    assert saved.status_code == 200
    assert saved.json()["checked"] == [0, 2]

    reloaded = await client.get(
        f"/api/sessions/{session_id}/progress", params={"path": "/r.md"}
    )
    assert reloaded.json()["items"]["triage"]["checked"] == [0, 2]


async def test_unticking_a_box_sticks(client, service):
    session_id = await _with_lesson(service, content=CHECKLIST_LESSON, path="/r.md")

    for checked in ([0, 1], [1]):
        await client.post(
            f"/api/sessions/{session_id}/progress/checklist",
            json={"path": "/r.md", "component_id": "triage", "checked": checked},
        )

    reloaded = await client.get(
        f"/api/sessions/{session_id}/progress", params={"path": "/r.md"}
    )
    assert reloaded.json()["items"]["triage"]["checked"] == [1]


async def test_a_checklist_that_did_not_ask_to_persist_is_refused(client, service):
    """`persist` is honoured rather than assumed, so a client cannot quietly
    accumulate state the author never opted into."""
    session_id = await _with_lesson(service, content=CHECKLIST_LESSON, path="/r.md")

    refused = await client.post(
        f"/api/sessions/{session_id}/progress/checklist",
        json={"path": "/r.md", "component_id": "ephemeral", "checked": [0]},
    )
    assert refused.status_code == 400
    assert "persist" in refused.json()["detail"]


async def test_a_box_that_is_not_on_the_checklist_is_refused(client, service):
    session_id = await _with_lesson(service, content=CHECKLIST_LESSON, path="/r.md")

    refused = await client.post(
        f"/api/sessions/{session_id}/progress/checklist",
        json={"path": "/r.md", "component_id": "triage", "checked": [9]},
    )
    assert refused.status_code == 400
    assert "9" in refused.json()["detail"]


async def test_checklist_state_cannot_be_posted_to_an_mcq(client, service):
    session_id = await _with_lesson(service)

    refused = await client.post(
        f"/api/sessions/{session_id}/progress/checklist",
        json={"path": LESSON_PATH, "component_id": "sev-1", "checked": [0]},
    )
    assert refused.status_code == 400
    assert "mcq" in refused.json()["detail"]


# ---------------- workers ----------------


async def make_project(client, name: str = "atlas") -> UUID:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 200
    return UUID(response.json()["id"])


async def join_session(client, project_id: UUID) -> UUID:
    response = await client.post(f"/api/projects/{project_id}/join")
    assert response.status_code == 200
    return UUID(response.json()["id"])


async def test_workers_lists_an_idle_member_session(client):
    """A project with a session attached and nothing running.

    The 200-with-empty-workers case matters as much as the busy one: the panel
    must be able to say "attached, nothing running" without an error.
    """
    project_id = await make_project(client)
    session_id = await join_session(client, project_id)

    response = await client.get(f"/api/projects/{project_id}/workers")

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == str(project_id)
    assert body["workers"] == []
    assert body["idle_session_ids"] == [str(session_id)]


async def test_workers_404s_on_an_unknown_project(client):
    response = await client.get(f"/api/projects/{uuid4()}/workers")
    assert response.status_code == 404


async def test_all_workers_is_empty_while_nothing_anywhere_is_running(client):
    """The ordinary answer, and the one the widget gets on almost every page.

    An empty list rather than a row per project: a project with nothing running
    is not in the answer at all, which is what keeps this from folding an
    aggregate per project on every page load.
    """
    project_id = await make_project(client)
    await join_session(client, project_id)

    response = await client.get("/api/workers")

    assert response.status_code == 200
    assert response.json() == []


async def test_all_workers_reports_the_project_that_is_working(client, extraction):
    """One request answers "what is running", with no project in the URL.

    The widget is on every page and has no project to ask about. Reverting the
    route would leave the widget asking per project, which is the cost this
    exists to remove.
    """
    busy = await make_project(client, "busy")
    quiet = await make_project(client, "quiet")
    await join_session(client, quiet)
    extraction.reporter(busy)(
        ExtractionNote(source_id="notes", stage="consolidating", index=3, total=9)
    )

    body = (await client.get("/api/workers")).json()

    assert [row["project_id"] for row in body] == [str(busy)]
    assert [worker["kind"] for worker in body[0]["workers"]] == ["extraction"]


async def test_all_workers_is_404_when_the_roster_is_not_wired(client_without_workers):
    """Matches the per-project route rather than answering an empty list.

    An empty list is a real state here -- "nothing is running anywhere" -- so a
    build that cannot tell must not produce one, or the widget would sit at
    zero forever and look correct.
    """
    response = await client_without_workers.get("/api/workers")
    assert response.status_code == 404


async def test_workers_is_404_when_the_roster_is_not_wired(client_without_workers):
    """A build with no roster says so, rather than reporting an empty project.

    The same shape `auto-research` uses for a disabled feature: 200 with an
    empty list would tell a browser that nothing is running, which is a
    different claim from "this build cannot tell you".
    """
    project_id = await make_project(client_without_workers)
    response = await client_without_workers.get(f"/api/projects/{project_id}/workers")
    assert response.status_code == 404


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
    """The roster and the pane read one buffer, so they cannot disagree."""
    project_id = await make_project(client)
    extraction.reporter(project_id)(
        ExtractionNote(source_id="notes", stage="consolidating", index=3, total=9)
    )

    body = (await client.get(f"/api/projects/{project_id}/workers")).json()

    assert [worker["kind"] for worker in body["workers"]] == ["extraction"]
    assert body["workers"][0]["detail"] == "consolidating 3/9"


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
    task = asyncio.create_task(_drain(generator, frames, wanted=1))
    await asyncio.sleep(0.05)
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
    task = asyncio.create_task(_drain(generator, frames, wanted=1))
    await asyncio.sleep(0.05)

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
    """The read the UI draws its switches from, including the two lists that
    keep it from hardcoding `GATED_TOOLS` in JavaScript and drifting from it.
    """
    body = (await client.get("/api/autonomy")).json()

    assert set(body["levels"]) == set(GATED_TOOLS)
    assert body["gated"] == list(GATED_TOOLS)
    assert body["stage_gates"] == [ADVANCE_STAGE_TOOL]
    assert body["levels"][ADVANCE_STAGE_TOOL] == "ask"


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


async def test_allow_all_leaves_the_stage_gate_asking(client):
    """ "Stop asking me" must not silently mean "and cross every stage boundary
    unseen" -- the review gate is not a hazard rating.
    """
    session_id = await _new_session(client)

    body = (await client.post(f"/api/sessions/{session_id}/autonomy/allow-all")).json()

    assert ADVANCE_STAGE_TOOL not in body["changed"]
    assert body["levels"][ADVANCE_STAGE_TOOL] == "ask"
    assert body["levels"]["fetch"] == "auto"


async def test_allow_all_can_be_asked_to_include_the_stage_gate(client):
    session_id = await _new_session(client)

    body = (
        await client.post(
            f"/api/sessions/{session_id}/autonomy/allow-all",
            json={"include_stage_gates": True},
        )
    ).json()

    assert body["changed"][ADVANCE_STAGE_TOOL] == "auto"
    assert body["levels"][ADVANCE_STAGE_TOOL] == "auto"


async def test_allow_all_records_exactly_the_changes_it_made(client, service):
    """One event per level that really moved, never one per gated tool: a log
    claiming eight decisions where a person made one is as unreadable as one
    that omitted them.
    """
    session_id = await _new_session(client)
    await client.post(
        f"/api/sessions/{session_id}/autonomy",
        json={"tool": "write_file", "level": "deny"},
    )

    body = (await client.post(f"/api/sessions/{session_id}/autonomy/allow-all")).json()

    assert body["changed"] == {"write_file": "auto", "fetch": "auto"}
    events = await service.history(UUID(session_id))
    changes = [event for event in events if isinstance(event, AutonomyChanged)]
    assert [(change.tool_name, change.level) for change in changes] == [
        ("write_file", "deny"),
        # `GATED_TOOLS` order, which is the order `relax_all` walks.
        ("fetch", "auto"),
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


# ---------------- graph ----------------


def _graph_entity(entity_id, tenant_id, name: str, entity_type: str = "person"):
    from redstring.domain.entity import Entity, ExtractionMethod

    return Entity(
        id=entity_id,
        tenant_id=tenant_id,
        name=name,
        normalized_name=name.lower(),
        entity_type=entity_type,
        extraction_method=ExtractionMethod.MANUAL,
        confidence=1.0,
    )


def _graph_relationship(
    relationship_id, tenant_id, source_id, target_id, relationship_type: str
):
    from redstring.domain.relationship import Relationship

    return Relationship(
        id=relationship_id,
        tenant_id=tenant_id,
        source_entity_id=source_id,
        target_entity_id=target_id,
        relationship_type=relationship_type,
        confidence=1.0,
    )


async def _project_with_graph(application, client) -> tuple[str, dict]:
    """A project holding two linked entities in its graph store, seeded directly.

    Seeded through `GraphStore.upsert_entities`/`upsert_relationships` --
    the same shortcut `test_graph_read.py` takes -- rather than through
    `remember`, because what is under test is the read route, not extraction.
    """
    created = await client.post("/api/projects", json={"name": f"graph-{uuid4()}"})
    assert created.status_code == 200
    project_id = created.json()["id"]
    tenant_id = UUID(project_id)

    store = await application.graphs.open(tenant_id)
    prandtl_id, karman_id = uuid4(), uuid4()
    await store.upsert_entities(
        [
            _graph_entity(prandtl_id, tenant_id, "Ludwig Prandtl"),
            _graph_entity(karman_id, tenant_id, "Theodore von Kármán"),
        ]
    )
    await store.upsert_relationships(
        [_graph_relationship(uuid4(), tenant_id, prandtl_id, karman_id, "advised")]
    )
    return project_id, {"prandtl_id": prandtl_id, "karman_id": karman_id}


async def test_listing_graph_entities_finds_what_was_seeded(app_and_client):
    application, client = app_and_client
    project_id, ids = await _project_with_graph(application, client)

    response = await client.get(f"/api/projects/{project_id}/graph/entities")

    assert response.status_code == 200
    body = response.json()
    assert {row["name"] for row in body["entities"]} == {
        "Ludwig Prandtl",
        "Theodore von Kármán",
    }
    assert {row["entity_id"] for row in body["entities"]} == {
        str(ids["prandtl_id"]),
        str(ids["karman_id"]),
    }
    assert body["next_after"] is None


async def test_listing_graph_entities_filters_by_name(app_and_client):
    """`name` matches case-insensitively as a substring of the entity's
    display name -- the same give `RedstringKnowledge.search` gives an
    agent's free text, because a human typing a partial name into a search
    box needs no less. `GraphStore.find_entities(name=...)` alone would
    require the full normalized name; the route must not be held to that.
    """
    application, client = app_and_client
    project_id, ids = await _project_with_graph(application, client)

    response = await client.get(
        f"/api/projects/{project_id}/graph/entities", params={"name": "prandtl"}
    )

    assert response.status_code == 200
    body = response.json()
    assert [row["entity_id"] for row in body["entities"]] == [str(ids["prandtl_id"])]


async def test_a_neighborhood_carries_root_entities_and_relationships(app_and_client):
    application, client = app_and_client
    project_id, ids = await _project_with_graph(application, client)

    response = await client.get(
        f"/api/projects/{project_id}/graph/entities/{ids['prandtl_id']}/neighborhood"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["root"]["entity_id"] == str(ids["prandtl_id"])
    assert [row["entity_id"] for row in body["entities"]] == [str(ids["karman_id"])]
    assert body["relationships"] == [
        {
            "source_id": str(ids["prandtl_id"]),
            "target_id": str(ids["karman_id"]),
            "relationship_type": "advised",
        }
    ]


async def test_asking_past_the_depth_cap_is_refused(app_and_client):
    """A caller asking for depth 5 has misunderstood the API; quietly handing
    back depth `MAX_NEIGHBORHOOD_DEPTH` would hide that from them. The port
    underneath still clamps -- see `test_depth_is_clamped_by_the_port_not_only_the_route`
    -- but that is a different guarantee for a different caller: the port
    protects any future in-process caller, this 422 tells an HTTP client it
    was wrong.
    """
    application, client = app_and_client
    project_id, ids = await _project_with_graph(application, client)

    response = await client.get(
        f"/api/projects/{project_id}/graph/entities/{ids['prandtl_id']}/neighborhood",
        params={"depth": 5},
    )

    assert response.status_code == 422
    assert "depth" in response.json()["detail"]


async def test_a_malformed_after_cursor_is_a_422_not_a_500(app_and_client):
    """`after` arrives straight off the query string. `neighborhood`'s
    `entity_id` handles the same kind of caller mistake with a 404; this
    route should not let an unparseable UUID reach `UUID(after)` inside the
    reader and blow up as an unhandled 500.
    """
    application, client = app_and_client
    project_id, _ids = await _project_with_graph(application, client)

    response = await client.get(
        f"/api/projects/{project_id}/graph/entities", params={"after": "not-a-uuid"}
    )

    assert response.status_code == 422


async def test_an_unknown_entity_is_a_404(app_and_client):
    application, client = app_and_client
    project_id, _ids = await _project_with_graph(application, client)

    response = await client.get(
        f"/api/projects/{project_id}/graph/entities/{uuid4()}/neighborhood"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == f"no such entity in project {project_id}"


async def test_reading_the_whole_graph_returns_every_entity_and_edge(app_and_client):
    """What the browser opens with, before a reader knows a name to search
    for: the graph entire, wired, in one response."""
    application, client = app_and_client
    project_id, ids = await _project_with_graph(application, client)

    response = await client.get(f"/api/projects/{project_id}/graph")

    assert response.status_code == 200
    body = response.json()
    assert {row["entity_id"] for row in body["entities"]} == {
        str(ids["prandtl_id"]),
        str(ids["karman_id"]),
    }
    assert body["relationships"] == [
        {
            "source_id": str(ids["prandtl_id"]),
            "target_id": str(ids["karman_id"]),
            "relationship_type": "advised",
        }
    ]
    assert body["truncated"] is False


async def test_reading_the_whole_graph_of_an_empty_project_is_not_an_error(
    app_and_client,
):
    """A project with nothing extracted yet is what most first visits to the
    research page hit; it answers with an empty graph, not a failure."""
    _application, client = app_and_client
    created = await client.post("/api/projects", json={"name": f"graph-{uuid4()}"})
    project_id = created.json()["id"]

    response = await client.get(f"/api/projects/{project_id}/graph")

    assert response.status_code == 200
    assert response.json() == {"entities": [], "relationships": [], "truncated": False}


async def test_an_oversized_limit_is_clamped_rather_than_refused(app_and_client):
    """The opposite of `neighborhood`'s treatment of `depth`, deliberately:
    "as much as possible" is a question this route can answer, and
    `truncated` in the body is how it reports what that came to."""
    application, client = app_and_client
    project_id, _ids = await _project_with_graph(application, client)

    response = await client.get(
        f"/api/projects/{project_id}/graph", params={"limit": MAX_GRAPH_NODES + 1_000}
    )

    assert response.status_code == 200
    assert len(response.json()["entities"]) == 2


async def test_a_truncated_graph_says_so(app_and_client):
    """A client cannot tell a complete graph from the first page of a bigger
    one by counting, so the flag has to travel with the body."""
    application, client = app_and_client
    project_id, _ids = await _project_with_graph(application, client)

    response = await client.get(f"/api/projects/{project_id}/graph", params={"limit": 1})

    assert response.status_code == 200
    body = response.json()
    assert len(body["entities"]) == 1
    assert body["truncated"] is True
    # The one surviving entity's edge had its other end cut off, so there is
    # nothing left to draw a line between.
    assert body["relationships"] == []


async def test_an_unknown_project_is_a_404_on_every_graph_route(client):
    missing = uuid4()

    whole = await client.get(f"/api/projects/{missing}/graph")
    listing = await client.get(f"/api/projects/{missing}/graph/entities")
    neighborhood = await client.get(
        f"/api/projects/{missing}/graph/entities/{uuid4()}/neighborhood"
    )

    assert whole.status_code == 404
    assert whole.json()["detail"] == f"no project {missing}"
    assert listing.status_code == 404
    assert listing.json()["detail"] == f"no project {missing}"
    assert neighborhood.status_code == 404
    assert neighborhood.json()["detail"] == f"no project {missing}"


async def test_a_404_on_an_unknown_project_does_not_cache_a_graph_store(app_and_client):
    """`_graph_reader` opens and caches a store as a side effect of building
    a reader -- `graphs.open` is the first call that talks to Neo4j and
    `ProjectGraphs` never evicts except on `close`/`close_all`. Calling it
    for a project that turns out not to exist would grow `graphs._stores`
    without bound for every caller that walks unknown ids, and would pay a
    schema round trip per garbage id behind Neo4j. The 404 must be decided
    before the reader is ever built.
    """
    application, client = app_and_client
    missing = uuid4()

    response = await client.get(f"/api/projects/{missing}/graph/entities")

    assert response.status_code == 404
    assert missing not in application.graphs._stores


async def test_graph_routes_503_when_no_graph_reader_is_configured(app_and_client):
    """A build with no graph read model configured is a valid thing to serve
    -- see `_reader`'s own docstring for the reasoning -- so the caller needs
    to know the server cannot answer, not that the project has no graph.
    """
    application, client = app_and_client
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        topics=application.topic_readers,
        graphs=None,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as unwired:
        project_id, ids = await _project_with_graph(application, client)

        listing = await unwired.get(f"/api/projects/{project_id}/graph/entities")
        neighborhood = await unwired.get(
            f"/api/projects/{project_id}/graph/entities/{ids['prandtl_id']}/neighborhood"
        )

    assert listing.status_code == 503
    assert neighborhood.status_code == 503


# ---------------- topic seeding ----------------


@pytest.fixture
async def seeding_client(db_path, fake_model):
    """A client wired with a `TopicSeeder` and its own `SeedingActivity`.

    Separate from `client`, matching `research_client`: the default app is
    built without a seeder, and that unwired case is one of the behaviours
    these tests check.
    """
    application = await _started(model=fake_model, db_path=db_path)
    activity = SeedingActivity()
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        topic_seeder=application.topic_seeder,
        seeding=activity,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield application, activity, http
    await application.close()


async def test_the_seed_routes_are_absent_unless_the_instance_was_wired_for_them(client):
    """503 rather than 404: this build is missing configuration, not the
    project this particular id names -- matching `_reader`'s own reasoning."""
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await client.post(
        f"/api/projects/{project_id}/topics/seed", json={"subject": "spaced repetition"}
    )

    assert response.status_code == 503


async def test_starting_a_seed_answers_with_its_run_before_it_has_finished(seeding_client):
    _application, activity, http = seeding_client
    project_id = (await http.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await http.post(
        f"/api/projects/{project_id}/topics/seed", json={"subject": "spaced repetition"}
    )

    assert response.status_code == 202
    body = response.json()
    assert body["project_id"] == project_id
    assert body["status"] == "running"
    await activity.wait(UUID(project_id))


async def test_a_second_concurrent_seed_on_the_same_project_is_refused(seeding_client):
    _application, activity, http = seeding_client
    project_id = (await http.post("/api/projects", json={"name": "atlas"})).json()["id"]

    first = await http.post(
        f"/api/projects/{project_id}/topics/seed", json={"subject": "spaced repetition"}
    )
    second = await http.post(
        f"/api/projects/{project_id}/topics/seed", json={"subject": "second wave"}
    )

    assert first.status_code == 202
    assert second.status_code == 409
    assert project_id in second.json()["detail"]
    await activity.wait(UUID(project_id))


async def test_the_catch_up_route_reports_what_a_finished_seed_did(seeding_client):
    _application, activity, http = seeding_client
    project_id = (await http.post("/api/projects", json={"name": "atlas"})).json()["id"]
    empty = await http.get(f"/api/projects/{project_id}/topics/seed")
    assert empty.json()["current"] is None
    assert empty.json()["last"] is None

    started = await http.post(
        f"/api/projects/{project_id}/topics/seed", json={"subject": "spaced repetition"}
    )
    assert started.status_code == 202
    await activity.wait(UUID(project_id))

    caught_up = await http.get(f"/api/projects/{project_id}/topics/seed")

    assert caught_up.status_code == 200
    body = caught_up.json()
    assert body["current"] is None
    assert body["last"]["status"] == "done"
    assert body["last"]["subject"] == "spaced repetition"


async def test_the_202s_run_id_is_the_id_the_finished_run_reports(seeding_client):
    """A client's only reasonable reading of `run_id` in a 202 is "the run I
    just started" -- that is what the field means everywhere else this API
    hands one back (`run_view`'s `run_id`, `ActiveRun.run_id`). An id here
    that never shows up again would be worse than no id at all: a panel
    correlating "the run I started" with "the run that just finished" has to
    be able to do it by this field."""
    _application, activity, http = seeding_client
    project_id = (await http.post("/api/projects", json={"name": "atlas"})).json()["id"]

    started = await http.post(
        f"/api/projects/{project_id}/topics/seed", json={"subject": "spaced repetition"}
    )
    await activity.wait(UUID(project_id))

    caught_up = await http.get(f"/api/projects/{project_id}/topics/seed")

    assert caught_up.json()["last"]["run_id"] == started.json()["run_id"]


# ---------------- topic dispatch ----------------


@pytest.fixture
async def dispatch_client(db_path, fake_model):
    """A client wired with a `TopicDispatcher` and its own `DispatchQueue`.

    Separate from `client`, matching `seeding_client`: the default app is
    built without a dispatcher, and that unwired case is one of the behaviours
    these tests check.
    """
    application = await _started(model=fake_model, db_path=db_path)
    queue = DispatchQueue()
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        topics=application.topic_readers,
        topic_seeder=application.topic_seeder,
        seeding=SeedingActivity(),
        dispatcher=application.dispatcher,
        dispatch=queue,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield application, queue, http
    await application.close()


async def _project_with_a_topic(
    application, http, fake_model, question="How does spacing work?"
):
    """A project holding exactly one topic, opened through a real seeding turn."""
    project_id = (await http.post("/api/projects", json={"name": "atlas"})).json()["id"]
    fake_model.responses = [
        AIMessage(
            content="",
            id="open",
            tool_calls=[
                {
                    "name": "open_topic",
                    "args": {"question": question, "rationale": "core"},
                    "id": "t1",
                }
            ],
        ),
        AIMessage(content="opened", id="reply"),
    ]
    await application.topic_seeder.seed(UUID(project_id), "spaced repetition", max_topics=4)
    topics = (await http.get(f"/api/projects/{project_id}/topics")).json()
    return project_id, topics[0]["topic_id"]


async def test_the_dispatch_routes_are_absent_unless_the_instance_was_wired(client):
    """503 rather than 404, matching every other unwired route here: this build
    is missing configuration, not the project the id names."""
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await client.post(
        f"/api/projects/{project_id}/topics/{uuid4()}/dispatch",
        json={"action": "understanding"},
    )

    assert response.status_code == 503


async def test_dispatching_answers_202_before_the_work_is_done(dispatch_client, fake_model):
    application, queue, http = dispatch_client
    project_id, topic_id = await _project_with_a_topic(application, http, fake_model)
    fake_model.responses = [AIMessage(content="written", id="a1")]

    response = await http.post(
        f"/api/projects/{project_id}/topics/{topic_id}/dispatch",
        json={"action": "understanding"},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["topic_id"] == topic_id
    assert body["action"] == "understanding"
    assert body["dispatch_id"]
    await queue.wait(UUID(project_id))


async def test_a_second_dispatch_is_queued_rather_than_409(dispatch_client, fake_model):
    """The behavioural difference from seeding, asserted at the route: a
    control on every topic row cannot answer 409 to every second press."""
    application, queue, http = dispatch_client
    project_id, topic_id = await _project_with_a_topic(application, http, fake_model)
    fake_model.responses = [
        AIMessage(content="one", id="a1"),
        AIMessage(content="two", id="a2"),
    ]

    first = await http.post(
        f"/api/projects/{project_id}/topics/{topic_id}/dispatch",
        json={"action": "understanding"},
    )
    second = await http.post(
        f"/api/projects/{project_id}/topics/{topic_id}/dispatch",
        json={"action": "understanding"},
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["position"] >= 1
    await queue.wait(UUID(project_id))


async def test_dispatching_an_unknown_topic_is_404(dispatch_client, fake_model):
    """Refused at the route rather than enqueued and failed asynchronously: a
    typo'd id should come back as an error the caller can see, not as a
    failure chip on a row that does not exist."""
    application, _queue, http = dispatch_client
    project_id, _topic_id = await _project_with_a_topic(application, http, fake_model)

    response = await http.post(
        f"/api/projects/{project_id}/topics/{uuid4()}/dispatch",
        json={"action": "understanding"},
    )

    assert response.status_code == 404


async def test_an_unsupported_action_is_refused_by_name(dispatch_client, fake_model):
    """`research` and `lesson` are designed and deliberately not built. A 422
    that named neither would read as a typo; this says which actions exist."""
    application, _queue, http = dispatch_client
    project_id, topic_id = await _project_with_a_topic(application, http, fake_model)

    response = await http.post(
        f"/api/projects/{project_id}/topics/{topic_id}/dispatch", json={"action": "lesson"}
    )

    assert response.status_code == 422
    assert "understanding" in response.text


async def test_the_catch_up_route_reports_the_finished_dispatch(dispatch_client, fake_model):
    """A tab that reconnected has no other way back -- these frames carry no
    feed position, so `Last-Event-ID` cannot replay them."""
    application, queue, http = dispatch_client
    project_id, topic_id = await _project_with_a_topic(application, http, fake_model)

    empty = await http.get(f"/api/projects/{project_id}/dispatch")
    assert empty.status_code == 200
    assert empty.json() == {"running": None, "queued": [], "finished": []}

    fake_model.responses = [AIMessage(content="written", id="a1")]
    await http.post(
        f"/api/projects/{project_id}/topics/{topic_id}/dispatch",
        json={"action": "understanding"},
    )
    await queue.wait(UUID(project_id))

    caught_up = (await http.get(f"/api/projects/{project_id}/dispatch")).json()
    assert caught_up["running"] is None
    assert caught_up["queued"] == []
    [finished] = caught_up["finished"]
    assert finished["status"] == "done"
    assert finished["topic_id"] == topic_id
    assert finished["path"].startswith("/topics/00-")


async def test_the_202s_dispatch_id_is_the_id_the_finished_dispatch_reports(
    dispatch_client, fake_model
):
    """A panel correlating "the dispatch I started" with "the one that just
    finished" has to be able to do it by this field, the same way `run_id`
    works for seeding."""
    application, queue, http = dispatch_client
    project_id, topic_id = await _project_with_a_topic(application, http, fake_model)
    fake_model.responses = [AIMessage(content="written", id="a1")]

    started = await http.post(
        f"/api/projects/{project_id}/topics/{topic_id}/dispatch",
        json={"action": "understanding"},
    )
    await queue.wait(UUID(project_id))

    caught_up = (await http.get(f"/api/projects/{project_id}/dispatch")).json()
    assert caught_up["finished"][0]["dispatch_id"] == started.json()["dispatch_id"]


async def test_cancelling_empties_the_queue(dispatch_client, fake_model):
    application, queue, http = dispatch_client
    project_id, topic_id = await _project_with_a_topic(application, http, fake_model)
    fake_model.responses = [
        AIMessage(content="one", id="a1"),
        AIMessage(content="two", id="a2"),
    ]

    await http.post(
        f"/api/projects/{project_id}/topics/{topic_id}/dispatch",
        json={"action": "understanding"},
    )
    await http.post(
        f"/api/projects/{project_id}/topics/{topic_id}/dispatch",
        json={"action": "understanding"},
    )
    response = await http.post(f"/api/projects/{project_id}/dispatch/cancel")

    assert response.status_code == 200
    assert response.json()["cancelled"] >= 1
    await queue.wait(UUID(project_id))
    assert (await http.get(f"/api/projects/{project_id}/dispatch")).json()["queued"] == []


async def test_a_dispatch_writes_a_file_the_project_can_read_back(dispatch_client, fake_model):
    """End to end, and the only test here that proves the feature does its job:
    the route, the queue, the dispatcher and the turn all ran, and a file
    exists at the path the convention names."""
    application, queue, http = dispatch_client
    project_id, topic_id = await _project_with_a_topic(application, http, fake_model)
    path = "/topics/00-how-does-spacing-work/understanding.md"
    fake_model.responses = [
        AIMessage(
            content="",
            id="w",
            tool_calls=[
                {
                    "name": "write_file",
                    "args": {"file_path": path, "content": "# Understanding"},
                    "id": "w1",
                }
            ],
        ),
        AIMessage(content="written", id="a1"),
    ]

    await http.post(
        f"/api/projects/{project_id}/topics/{topic_id}/dispatch",
        json={"action": "understanding"},
    )
    await queue.wait(UUID(project_id))

    files = await application.service.project_files(UUID(project_id))
    assert path in files


# ---------------- the topic document viewer ----------------


async def test_a_topic_with_no_documents_answers_an_empty_listing(dispatch_client, fake_model):
    """An empty listing, not a 404: a topic nobody has dispatched at is the
    ordinary case, and the directory it *would* be written to is the thing a
    viewer wants to name in its empty state."""
    application, _queue, http = dispatch_client
    project_id, topic_id = await _project_with_a_topic(application, http, fake_model)

    body = (await http.get(f"/api/projects/{project_id}/topics/{topic_id}/documents")).json()

    assert body["documents"] == []
    assert body["directory"] == "/topics/00-how-does-spacing-work"


async def test_a_topic_lists_the_document_a_dispatch_wrote(dispatch_client, fake_model):
    """The whole reason this route exists: without it a dispatch's output is
    reachable only by knowing which session wrote it, and nothing on the
    research view knows that."""
    application, queue, http = dispatch_client
    project_id, topic_id = await _project_with_a_topic(application, http, fake_model)
    path = "/topics/00-how-does-spacing-work/understanding.md"
    fake_model.responses = [
        AIMessage(
            content="",
            id="w",
            tool_calls=[
                {
                    "name": "write_file",
                    "args": {"file_path": path, "content": "# What we know"},
                    "id": "w1",
                }
            ],
        ),
        AIMessage(content="written", id="a1"),
    ]
    await http.post(
        f"/api/projects/{project_id}/topics/{topic_id}/dispatch",
        json={"action": "understanding"},
    )
    await queue.wait(UUID(project_id))

    body = (await http.get(f"/api/projects/{project_id}/topics/{topic_id}/documents")).json()

    assert [document["name"] for document in body["documents"]] == ["understanding.md"]
    assert body["documents"][0]["path"] == path


async def test_the_listing_says_which_session_to_read_the_file_from(
    dispatch_client, fake_model
):
    """The point of the whole route, and the reason it is not just a list of
    paths. Every reader of a file -- the raw route, the parsed route, the
    attempt route -- is keyed by `(session_id, path)`, and a dispatch writes
    on a session it creates and releases. This is the only thing that can
    say which one, so a viewer can reuse all three unchanged."""
    application, queue, http = dispatch_client
    project_id, topic_id = await _project_with_a_topic(application, http, fake_model)
    path = "/topics/00-how-does-spacing-work/understanding.md"
    fake_model.responses = [
        AIMessage(
            content="",
            id="w",
            tool_calls=[
                {
                    "name": "write_file",
                    "args": {"file_path": path, "content": "hi"},
                    "id": "w1",
                }
            ],
        ),
        AIMessage(content="written", id="a1"),
    ]
    await http.post(
        f"/api/projects/{project_id}/topics/{topic_id}/dispatch",
        json={"action": "understanding"},
    )
    await queue.wait(UUID(project_id))

    body = (await http.get(f"/api/projects/{project_id}/topics/{topic_id}/documents")).json()

    assert body["session_id"] is not None
    readable = await http.get(
        f"/api/sessions/{body['session_id']}/files",
        params={"path": path, **({"at": body["at"]} if body["at"] is not None else {})},
    )
    assert readable.status_code == 200
    assert readable.json()["content"] == "hi"


async def test_one_topic_s_listing_does_not_show_another_topic_s_documents(
    dispatch_client, fake_model
):
    """The `<nn>-<slug>` directory is the only thing separating them, so a
    prefix match that forgot the trailing slash would put `/topics/01-...`
    under `/topics/0`. Two topics, asserted apart."""
    application, queue, http = dispatch_client
    project_id, first = await _project_with_a_topic(application, http, fake_model)

    fake_model.responses = [
        AIMessage(
            content="",
            id="open2",
            tool_calls=[
                {
                    "name": "open_topic",
                    "args": {"question": "Second question?", "rationale": "core"},
                    "id": "t2",
                }
            ],
        ),
        AIMessage(content="opened", id="r2"),
    ]
    await application.topic_seeder.seed(UUID(project_id), "more", max_topics=4)
    rows = (await http.get(f"/api/projects/{project_id}/topics")).json()
    second = next(row["topic_id"] for row in rows if row["question"] == "Second question?")

    for topic_id, path in (
        (first, "/topics/00-how-does-spacing-work/understanding.md"),
        (second, "/topics/01-second-question/understanding.md"),
    ):
        fake_model.responses = [
            AIMessage(
                content="",
                id=f"w-{path}",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {"file_path": path, "content": path},
                        "id": f"c-{path}",
                    }
                ],
            ),
            AIMessage(content="ok", id=f"a-{path}"),
        ]
        await http.post(
            f"/api/projects/{project_id}/topics/{topic_id}/dispatch",
            json={"action": "understanding"},
        )
        await queue.wait(UUID(project_id))

    one = (await http.get(f"/api/projects/{project_id}/topics/{first}/documents")).json()
    two = (await http.get(f"/api/projects/{project_id}/topics/{second}/documents")).json()

    assert [d["path"] for d in one["documents"]] == [
        "/topics/00-how-does-spacing-work/understanding.md"
    ]
    assert [d["path"] for d in two["documents"]] == [
        "/topics/01-second-question/understanding.md"
    ]


async def test_documents_for_an_unknown_topic_are_404(dispatch_client, fake_model):
    """The status alone would pass with this route deleted -- FastAPI answers
    404 for a path it does not serve. So the message is asserted too: this one
    names the project, and a missing route's does not."""
    application, _queue, http = dispatch_client
    project_id, _topic_id = await _project_with_a_topic(application, http, fake_model)

    response = await http.get(f"/api/projects/{project_id}/topics/{uuid4()}/documents")

    assert response.status_code == 404
    assert project_id in response.json()["detail"]


async def test_dispatch_frames_ride_the_stream_without_an_id(repository):
    """Like seeding frames: no feed position, so no SSE id -- a browser must
    not resume from one. A `Dispatch` frame carrying an id would have
    `Last-Event-ID` asking the server to resume from a position the log does
    not have."""
    from research_team.application import LiveFeed
    from research_team.application.topic_dispatch import DispatchRun
    from research_team.interfaces.web.app import _sse

    feed = LiveFeed(repository)
    queue = DispatchQueue()
    project_id = uuid4()
    topic_id = uuid4()

    generator = _sse(StubRequest(), feed, None, None, None, None, None, queue)

    async def _run(dispatch_id):
        return DispatchRun(
            dispatch_id=dispatch_id,
            project_id=project_id,
            topic_id=topic_id,
            session_id=uuid4(),
            action="understanding",
            question="q",
            path="/topics/00-q/understanding.md",
            reply="done",
        )

    queue.start(project_id, topic_id, "understanding", _run)
    frames = [await anext(generator) for _ in range(2)]
    await queue.wait(project_id)
    await generator.aclose()

    assert all(frame.startswith("data: ") for frame in frames)
    assert all("id:" not in frame for frame in frames)
    assert json.loads(frames[0].removeprefix("data: ").strip())["type"] == "Dispatch"
