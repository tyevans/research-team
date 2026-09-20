"""The HTTP adapter, exercised over ASGI with no network and no real model."""

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from eventsource.ports.positions import ExpectedVersion
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from redstring import (
    DocumentExtracted,
    document_stream,
)

from research_team.application import GATED_TOOLS, SummaryProjects, WorkerRoster
from research_team.application.knowledge import ExtractionNote
from research_team.application.ports import ActivityMessage
from research_team.composition import build_application as _build_application
from research_team.domain import (
    AutonomyChanged,
    DeleteFile,
    SendUserMessage,
    SessionPurpose,
    StartSession,
    StoreSourceDocument,
    WriteFile,
)
from research_team.domain.topic import OpenTopic
from research_team.infrastructure.persistence import build_corpus_repository
from research_team.infrastructure.persistence.event_store import build_topic_repository
from research_team.interfaces.web import TurnActivity, create_app
from research_team.interfaces.web.extraction import ExtractionActivity
from tests.application.test_turn_supervisor import once_inside_the_model
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
            purpose=SessionPurpose.CHAT,
        )
    )
    await repository.save(aggregate)

    frames: list[str] = []
    generator = _sse(StubRequest(), feed)
    await _subscribed(generator)
    task = asyncio.create_task(_drain(generator, frames, wanted=1))
    aggregate.execute(SendUserMessage(message={"type": "human", "data": {"content": "hi"}}))
    await repository.save(aggregate)
    await asyncio.wait_for(task, timeout=5)

    assert frames[0].endswith("\n\n")
    payload = json.loads(frames[0].split("data: ", 1)[1])
    assert payload["session_id"] == str(session_id)
    assert payload["type"] == "UserMessageSent"


async def test_the_first_event_in_an_empty_log_still_reaches_a_subscriber(repository):
    """Subscribing to a database nothing has been written to yet.

    An empty log has no position, so `latest_position()` answers `None` -- and
    `None` is also how `follow` is told "you decide where to start", which it
    does on the pump task's first turn, some time after the response has begun.
    Anything appended in that window was dropped, permanently: the subscriber's
    cursor ended up *after* it.

    Narrow, but not hypothetical -- it is the first run of a fresh install,
    where the console connects to an empty database and the first thing that
    happens is the first thing anyone does. `_sse` reads the position itself
    and passes `from_start` when there was none, which is not a wider replay:
    the log was empty when it looked, so from the start *is* from now.

    Reverting either half of that fix fails here. The test is only meaningful
    because `: ready` makes "the subscriber is placed" observable; with the
    0.05s sleep this file used to use, the append landed after the cursor was
    taken by luck and the bug was invisible.
    """
    from research_team.application import LiveFeed
    from research_team.interfaces.web.app import _sse

    feed = LiveFeed(repository, poll_interval=0.01)
    topics = build_topic_repository(repository.store)
    topic = topics.create_new(uuid4())

    frames: list[str] = []
    generator = _sse(StubRequest(), feed)
    await _subscribed(generator)
    task = asyncio.create_task(_drain(generator, frames, wanted=1))
    topic.execute(
        OpenTopic(
            topic_id=topic.aggregate_id,
            project_id=uuid4(),
            question="Is anybody there?",
            rationale="the log is empty and something has to be first",
        )
    )
    await topics.save(topic)
    await asyncio.wait_for(task, timeout=5)

    payload = json.loads(frames[0].split("data: ", 1)[1])
    assert payload["change"] == "TopicOpened"


async def test_sse_frames_a_topic_change_as_its_own_project_shaped_frame(repository):
    """An opened topic reaches the live feed, and does not pretend to be a session.

    The research page's topic list is refreshed off these frames. Two failures
    this pins: no frame at all (what shipped -- the feed read only
    `Session` streams, so a topic appeared only on a reload), and a frame
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
    await _subscribed(generator)
    task = asyncio.create_task(_drain(generator, frames, wanted=1))
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
    at all (what shipped -- the feed read only `Session` and `Topic`, so
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
    await _subscribed(generator)
    task = asyncio.create_task(_drain(generator, frames, wanted=1))
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
    of any kind -- the feed read only `Session` and `Topic`, so a source
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
    await _subscribed(generator)
    task = asyncio.create_task(_drain(generator, frames, wanted=1))
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
    assert payload["change"] == "CorpusDocumentStored"
    assert "session_id" not in payload


async def test_sse_frames_a_media_proposal_change_as_a_media_frame(repository):
    """A media proposal reaching the browser over the live feed, not a poll.

    `MediaProposals` was in `FEED_AGGREGATE_TYPES` (so events for it were
    read off the log) but `_sse` had no branch for it -- its events fell to
    the generic `feed_event`, which stamps `index: 0`, which the frontend's
    `decodeFrame` requires be `>= 1` to treat a frame as a log entry. Every
    one of those frames was silently dropped, and `MediaProposalPane` polled
    every 3s instead while a proposal sat in `accepted`. This test would have
    passed with only a presenter added and no branch in `_sse` -- proving a
    dict shape, not that a frame reaches a consumer -- so it goes through the
    same `_sse` generator the browser is served from, the way the corpus and
    project frame tests above do.
    """
    from eventsource import AggregateRepository

    from research_team.application import LiveFeed
    from research_team.domain.media_proposals import (
        AcceptMediaProposal,
        MediaProposals,
        ProposeMedia,
    )
    from research_team.interfaces.web.app import _sse

    feed = LiveFeed(repository, poll_interval=0.01)
    project_id = uuid4()
    proposals = AggregateRepository(repository.store, MediaProposals)
    aggregate = await proposals.load_or_create(project_id)

    frames: list[str] = []
    generator = _sse(StubRequest(), feed)
    await _subscribed(generator)
    task = asyncio.create_task(_drain(generator, frames, wanted=1))
    aggregate.execute(
        ProposeMedia(
            project_id=str(project_id),
            proposal_id="proposal-1",
            need_id="need-0",
            topic_id=str(uuid4()),
            page_url="https://example.org/gallery/trajan",
            asset_url="https://example.org/gallery/trajan.jpg",
            thumbnail_url="",
            kind="image",
            title="Trajan's Column, detail",
            reason="shows the relief the finding describes",
            query="trajan column relief",
        )
    )
    aggregate.execute(
        AcceptMediaProposal(project_id=str(project_id), proposal_id="proposal-1")
    )
    await proposals.save(aggregate)
    await asyncio.wait_for(task, timeout=5)

    assert frames[0].startswith("id: ")
    payload = json.loads(frames[0].split("data: ", 1)[1])
    assert payload["type"] == "Media"
    assert payload["project_id"] == str(project_id)
    assert payload["change"] == "MediaProposed"
    assert "session_id" not in payload


async def test_sse_frames_a_project_change_as_a_project_frame(repository):
    """A change to a project reaches the live feed addressed to that project.

    The reported bug, at the layer where it is visible: a project's page moved
    only on a reload, because the feed read `Session`, `Topic`, `Corpus` and
    redstring's categories and nothing else.

    A `Project` frame rather than a log frame, for the reason `Topic` and
    `Corpus` are: the session tree keys off `session_id`, and a project's
    aggregate id under that name would send it after a session that does not
    exist -- which is why `session_id` is asserted absent. And it carries an
    SSE id, unlike a `Dispatch` or `Seeding` frame: a project event is
    appended to the log, so a reconnect replays it from `Last-Event-ID`
    rather than needing a catch-up route.

    `change` and nothing else off the payload, so the frame stays independent
    of any one event's shape. It was written against `ProjectStageAdvanced`,
    which the workflow removal deleted along with the `decision` key this used
    to assert; a join makes the identical point about the admission, which is
    per aggregate rather than per event class.
    """
    from research_team.application import LiveFeed
    from research_team.domain.project import CreateProject, JoinProject
    from research_team.interfaces.web.app import _sse

    feed = LiveFeed(repository, poll_interval=0.01)
    project_id = uuid4()
    project = repository.projects.create_new(project_id)
    project.execute(CreateProject(project_id=project_id, name="Spacing"))
    await repository.projects.save(project)

    frames: list[str] = []
    generator = _sse(StubRequest(), feed)
    await _subscribed(generator)
    task = asyncio.create_task(_drain(generator, frames, wanted=1))
    project.execute(JoinProject(session_id=uuid4()))
    await repository.projects.save(project)
    await asyncio.wait_for(task, timeout=5)

    assert frames[0].startswith("id: ")
    payload = json.loads(frames[0].split("data: ", 1)[1])
    assert payload["type"] == "Project"
    assert payload["project_id"] == str(project_id)
    assert payload["change"] == "ProjectSessionJoined"
    assert "session_id" not in payload


async def _subscribed(generator) -> None:
    """Advance a stream to the point where it is actually listening.

    `_sse` takes its feed position and then yields `: ready`, so receiving that
    comment is a *fact* about the subscription rather than a guess about how
    long one takes to establish. Every test below that appends an event and
    expects to see it needs this first: an append that lands before the cursor
    is taken is not in the stream, and the test reads as "the feed is broken".

    It replaces `await asyncio.sleep(0.05)` -- and in the two tests that talk
    to a real server, `sleep(0.4)`. `BACKLOG.md` B4 is what those cost: a
    precondition expressed as a duration fails on a machine that is merely
    busy, and the failure looks exactly like a defect in the thing under test.
    """
    ready = await anext(generator)
    assert ready.startswith(": ready"), f"expected the ready comment, got {ready!r}"


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
    await _subscribed(generator)
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
    # The stream announces itself, then keeps the connection warm, then ends.
    assert frames[0] == ": ready\n\n"
    assert all(frame == ": keepalive\n\n" for frame in frames[1:])


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
    # Set when the server says it is subscribed. `response.headers` arriving is
    # not that -- the route returns before the generator has taken its feed
    # position -- which is why this used to be a 0.4s sleep and why a busy
    # machine could put the write in front of the subscription.
    subscribed = asyncio.Event()

    async def listen() -> None:
        async with (
            AsyncClient(timeout=20) as browser,
            browser.stream("GET", "http://127.0.0.1:8749/api/stream") as response,
        ):
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            async for line in response.aiter_lines():
                if line.startswith(": ready"):
                    subscribed.set()
                    continue
                if not line.startswith("data: "):
                    continue
                received.append(json.loads(line[len("data: ") :]))
                # Read until the session's own frame rather than stopping at
                # the first one. `start_session` also writes to the `Project`
                # stream, and since the feed learned to carry `Project` those
                # frames arrive first -- so "the first frame" stopped being
                # the session's and this test failed asserting the wire was
                # broken when it was carrying more than before.
                if received[-1].get("type") == "SessionStarted":
                    return

    listener = asyncio.create_task(listen())
    try:
        await asyncio.wait_for(subscribed.wait(), timeout=10)
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

    assert received[-1]["session_id"] == str(session_id)
    assert received[-1]["type"] == "SessionStarted"


# ---------------- the page itself ----------------


# `test_index_is_served` moved to `test_web_console.py`, beside the unbuilt
# case. It mounted the real `STATIC_DIR`, which no longer exists in a clone
# that has not run `npm run build` -- so it asserted 200 and got the 503 that
# absence is now supposed to produce, in a CI job with no Node toolchain to
# fix it with. Its replacement builds a one-line `index.html` and tests the
# route, which is what it was ever about.


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
    application, client, model = slow_app
    session_id = await start_session(application.service)

    turn = asyncio.create_task(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "slow"})
    )
    await once_inside_the_model(model)

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
    application, client, model = slow_app
    session_id = await start_session(application.service)

    turn = asyncio.create_task(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "slow"})
    )
    await once_inside_the_model(model)

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
    await once_inside_the_model(model)
    await client.post(f"/api/sessions/{session_id}/turns/cancel")
    await turn

    model.delay = 0.0
    response = await client.post(f"/api/sessions/{session_id}/turns", json={"input": "quick"})

    assert response.status_code == 200
    assert response.json()["turn_index"] == 1  # the cancelled attempt never counted


async def test_a_running_turn_is_described_not_just_flagged(slow_app):
    """A tab arriving mid-turn should be able to say which turn, and for how long."""
    application, client, model = slow_app
    session_id = await start_session(application.service)

    turn = asyncio.create_task(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "slow"})
    )
    await once_inside_the_model(model)

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
    application, client, model = slow_app
    session_id = await start_session(application.service)

    turn = asyncio.create_task(
        client.post(f"/api/sessions/{session_id}/turns", json={"input": "slow"})
    )
    await once_inside_the_model(model)
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

    Returns the task and the list it fills. Subscribing *before* the events are
    appended is what makes the test meaningful: a stream takes its position
    when it is first iterated, not when it is constructed. `_subscribed` is
    what makes "before" a fact rather than a hope -- it used to be a 0.05s
    sleep, and the whole point of these tests is which side of the cursor an
    event landed on.
    """
    from research_team.interfaces.web.app import _sse

    frames: list[str] = []
    generator = _sse(StubRequest(), feed, resume_from)
    await _subscribed(generator)
    task = asyncio.create_task(_drain(generator, frames, wanted=wanted))
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
            purpose=SessionPurpose.CHAT,
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
            purpose=SessionPurpose.CHAT,
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
            purpose=SessionPurpose.CHAT,
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
