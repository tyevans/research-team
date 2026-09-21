"""SSE live event streaming and reconnect cursor tests."""

import asyncio
import json
from uuid import uuid4

import pytest
from eventsource.ports.positions import ExpectedVersion
from httpx import ASGITransport, AsyncClient
from redstring import (
    DocumentExtracted,
    document_stream,
)

from research_team.composition import build_application as _build_application
from research_team.infrastructure.persistence import build_corpus_repository
from research_team.infrastructure.persistence.event_store import build_topic_repository
from research_team.interfaces.web import create_app
from research_team.research.domain import StoreSourceDocument
from research_team.research.domain.topic import OpenTopic
from research_team.session.domain import (
    SendUserMessage,
    SessionPurpose,
    StartSession,
)


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
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield application, client
    await application.close()


@pytest.fixture
def client(app_and_client):
    return app_and_client[1]


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


async def test_sse_frames_each_event_as_a_data_line(repository, session_id):
    from research_team.interfaces.web.app import _sse
    from research_team.platform.shared.live_feed import LiveFeed

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
    from research_team.interfaces.web.app import _sse
    from research_team.platform.shared.live_feed import LiveFeed

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
    from research_team.interfaces.web.app import _sse
    from research_team.platform.shared.live_feed import LiveFeed

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
    from research_team.interfaces.web.app import _sse
    from research_team.platform.shared.live_feed import LiveFeed

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
    from research_team.interfaces.web.app import _sse
    from research_team.platform.shared.live_feed import LiveFeed

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

    from research_team.interfaces.web.app import _sse
    from research_team.platform.shared.live_feed import LiveFeed
    from research_team.research.domain.media_proposals import (
        AcceptMediaProposal,
        MediaProposals,
        ProposeMedia,
    )

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
    from research_team.interfaces.web.app import _sse
    from research_team.platform.shared.live_feed import LiveFeed
    from research_team.tenancy.domain.project import CreateProject, JoinProject

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
