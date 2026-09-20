"""Topic dispatch routes exercised over ASGI with no network
and no real model.
"""

import json
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from research_team.application import SummaryProjects, WorkerRoster
from research_team.composition import build_application as _build_application
from research_team.interfaces.web import create_app
from research_team.interfaces.web.dispatch import DispatchQueue
from research_team.interfaces.web.extraction import ExtractionActivity
from research_team.interfaces.web.seeding import SeedingActivity


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


class StubRequest:
    """The only thing `_sse` asks a request: have you gone away yet."""

    def __init__(self, disconnect_after: int = 10_000) -> None:
        self._checks = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._checks += 1
        return self._checks > self._disconnect_after


async def _subscribed(generator) -> None:
    ready = await anext(generator)
    assert ready.startswith(": ready"), f"expected the ready comment, got {ready!r}"


@pytest.fixture
def extraction():
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
            summaries=SummaryProjects(application.summaries),
        ),
        extraction=extraction,
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
        blob_store=application.blob_store,
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
    """`lesson` is designed and deliberately not built. A 422 that named
    nothing would read as a typo; this says which actions exist.

    **This is the test that notices a half-widened vocabulary.**
    `DISPATCH_ACTIONS` and `DispatchAction` are two spellings of one set, and
    only the runtime one reaches this route -- so asserting that the refusal
    names all three is what fails if someone adds a fourth to the `Literal`
    alone. Proved red on this branch by reverting `DISPATCH_ACTIONS` to
    `frozenset({"understanding"})` and leaving the `Literal` widened: the
    refusal came back naming only `understanding` and the two new assertions
    below failed, while every other dispatch test still passed.
    """
    application, _queue, http = dispatch_client
    project_id, topic_id = await _project_with_a_topic(application, http, fake_model)

    response = await http.post(
        f"/api/projects/{project_id}/topics/{topic_id}/dispatch", json={"action": "lesson"}
    )

    assert response.status_code == 422
    assert "understanding" in response.text
    assert "research" in response.text
    assert "refine" in response.text


async def test_a_research_dispatch_asks_for_no_file(dispatch_client, fake_model):
    """`research`'s output is links and findings on the topic, not a document,
    so its `done` frame carries an empty path.

    Fails against the code without this change twice over: `research` was not
    in `DISPATCH_ACTIONS` at all, so the POST answered 422 rather than 202.
    """
    application, queue, http = dispatch_client
    project_id, topic_id = await _project_with_a_topic(application, http, fake_model)
    fake_model.responses = [AIMessage(content="searched", id="a1")]

    response = await http.post(
        f"/api/projects/{project_id}/topics/{topic_id}/dispatch",
        json={"action": "research"},
    )
    await queue.wait(UUID(project_id))

    assert response.status_code == 202
    assert response.json()["action"] == "research"
    finished = queue.last(UUID(project_id), UUID(topic_id))
    assert finished["status"] == "done"
    assert finished["path"] == ""


async def test_a_refine_dispatch_writes_beside_the_understanding(dispatch_client, fake_model):
    """`refine` lands in the same topic directory, which is the case
    `TOPICS_DIR` chose one-directory-per-topic to allow.

    Fails without this change: `refine` was not an action, and there was no
    `refinement_path` for it to be asked to write.
    """
    application, queue, http = dispatch_client
    project_id, topic_id = await _project_with_a_topic(application, http, fake_model)
    fake_model.responses = [AIMessage(content="judged", id="a1")]

    await http.post(
        f"/api/projects/{project_id}/topics/{topic_id}/dispatch",
        json={"action": "refine"},
    )
    await queue.wait(UUID(project_id))

    finished = queue.last(UUID(project_id), UUID(topic_id))
    assert finished["path"] == "/topics/00-how-does-spacing-work/refinement.md"


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
    # No `at` parameter, because the response no longer carries one: the
    # documents are folded at HEAD, so HEAD is where they are read. Sending the
    # tip offset here is what this route did until 2026-08-27, and it is what
    # made the pair unusable -- a file this same body listed answering
    # `404 ... not found as of event 7`.
    readable = await http.get(
        f"/api/sessions/{body['session_id']}/files", params={"path": path}
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

    await _subscribed(generator)
    queue.start(project_id, topic_id, "understanding", _run)
    frames = [await anext(generator) for _ in range(2)]
    await queue.wait(project_id)
    await generator.aclose()

    assert all(frame.startswith("data: ") for frame in frames)
    assert all("id:" not in frame for frame in frames)
    assert json.loads(frames[0].removeprefix("data: ").strip())["type"] == "Dispatch"


# ---------------- the bulk fan-out ----------------


async def _project_with_several_topics(application, http, fake_model, questions):
    """A project holding one topic per question, opened through a real turn.

    Seeded through `TopicSeeder` rather than by writing rows, so the topic ids
    these tests fan out over are ids the read model actually issued. A fixture
    that inserted them directly could not tell a bulk route that skips
    resolution from one that does it -- the fixture rule CLAUDE.md records.
    """
    project_id = (await http.post("/api/projects", json={"name": "atlas"})).json()["id"]
    fake_model.responses = [
        AIMessage(
            content="",
            id="open",
            tool_calls=[
                {
                    "name": "open_topic",
                    "args": {"question": question, "rationale": "core"},
                    "id": f"t{index}",
                }
                for index, question in enumerate(questions)
            ],
        ),
        AIMessage(content="opened", id="reply"),
    ]
    await application.topic_seeder.seed(
        UUID(project_id), "spaced repetition", max_topics=len(questions) + 4
    )
    topics = (await http.get(f"/api/projects/{project_id}/topics")).json()
    return project_id, [topic["topic_id"] for topic in topics]


async def test_the_autonomous_run_routes_are_gone(dispatch_client, fake_model):
    """Deleted surface, asserted rather than assumed.

    A 404 here is what a *route that was never wired* also answered, so this
    is a weak test on its own and is written down as such: what it actually
    pins is that no later change reintroduces the three routes without a
    decision. The capability is not deleted -- `application/research_run.py`
    and its supervisor still drive the REPL's `/research [n]` -- and this test
    would be the wrong place to notice if it were.
    """
    application, _queue, http = dispatch_client
    project_id, _topic_id = await _project_with_a_topic(application, http, fake_model)

    started = await http.post(f"/api/projects/{project_id}/auto-research", json={})
    status = await http.get(f"/api/projects/{project_id}/auto-research")
    cancelled = await http.post(f"/api/projects/{project_id}/auto-research/cancel")

    assert started.status_code == 404
    assert status.status_code == 404
    assert cancelled.status_code == 404
