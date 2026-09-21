"""Bulk topic dispatch routes exercised over ASGI with no network and no real
model.
"""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from research_team.composition import build_application as _build_application
from research_team.interfaces.web import create_app
from research_team.interfaces.web.app import MAX_BULK_DISPATCH
from research_team.interfaces.web.dispatch import DispatchQueue
from research_team.interfaces.web.extraction import ExtractionActivity
from research_team.interfaces.web.seeding import SeedingActivity
from research_team.session.application.workers import (
    SummaryProjects,
    WorkerRoster,
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


async def test_bulk_dispatch_enqueues_one_per_topic_the_client_named(
    dispatch_client, fake_model
):
    """The fan-out's whole point: the count on screen and the number of turns
    started are the same number.

    Asserted on the queue rather than on the response alone -- a route that
    answered with three frames and enqueued one would pass a response-only
    check, and the queue is what actually spends the model time.

    Fails without this change: the route did not exist and the POST was 404.
    """
    application, queue, http = dispatch_client
    project_id, topic_ids = await _project_with_several_topics(
        application, http, fake_model, ["How does spacing work?", "What is recall?"]
    )
    fake_model.responses = [
        AIMessage(content="one", id="b1"),
        AIMessage(content="two", id="b2"),
    ]

    response = await http.post(
        f"/api/projects/{project_id}/dispatch/bulk",
        json={"action": "research", "topic_ids": topic_ids},
    )

    assert response.status_code == 202
    body = response.json()
    assert len(body["queued"]) == 2
    assert body["unknown"] == []
    assert {frame["topic_id"] for frame in body["queued"]} == set(topic_ids)
    assert all(frame["action"] == "research" for frame in body["queued"])
    await queue.wait(UUID(project_id))
    assert {frame["topic_id"] for frame in queue.finished(UUID(project_id))} == set(topic_ids)


async def test_bulk_dispatch_runs_each_topic_rather_than_one_of_them_twice(
    dispatch_client, fake_model
):
    """The late-binding defect, pinned.

    A `lambda` in the enqueue loop that closed over the loop variable rather
    than binding it would hand every dispatch the *last* topic id, and every
    other assertion in this file would still pass: two frames go out, two
    turns run, the queue drains. The only visible difference is which topic
    each turn was actually briefed about, so that is what this asserts.
    """
    application, queue, http = dispatch_client
    project_id, topic_ids = await _project_with_several_topics(
        application, http, fake_model, ["How does spacing work?", "What is recall?"]
    )
    fake_model.responses = [
        AIMessage(content="one", id="b1"),
        AIMessage(content="two", id="b2"),
    ]

    await http.post(
        f"/api/projects/{project_id}/dispatch/bulk",
        json={"action": "understanding", "topic_ids": topic_ids},
    )
    await queue.wait(UUID(project_id))

    finished = queue.finished(UUID(project_id))
    # The slug, not the whole path, and the numeric prefix is deliberately not
    # asserted. `TopicRunner.list` orders by `(created_at, str(row.id))`, so
    # two topics opened in the same instant tie on the timestamp and the
    # tie-break is a random uuid -- which decides the `00-`/`01-` prefix and
    # nothing else. Asserting the prefix passed locally, where the two opens
    # land on different timestamps, and failed on CI, where they do not.
    #
    # Nothing is lost. The defect this test exists for is a `lambda` that
    # closed over the loop variable, handing every dispatch the *last* topic;
    # under it both files would carry the same slug, which this still catches.
    # Position instability is a separate, already-documented property -- see
    # `topic_directory`, which reads the position at dispatch time and says
    # what that costs.
    assert {frame["path"].split("-", 1)[1] for frame in finished} == {
        "how-does-spacing-work/understanding.md",
        "what-is-recall/understanding.md",
    }


async def test_bulk_dispatch_reports_an_unknown_id_rather_than_refusing_the_rest(
    dispatch_client, fake_model
):
    """The list a browser sends is what it was showing a moment ago. A topic
    deleted in that moment must not cost the others their dispatch -- but it
    must not vanish silently either, or the client renders fewer chips than
    rows and nothing says why.
    """
    application, queue, http = dispatch_client
    project_id, topic_ids = await _project_with_several_topics(
        application, http, fake_model, ["How does spacing work?"]
    )
    missing = str(uuid4())
    fake_model.responses = [AIMessage(content="one", id="b1")]

    response = await http.post(
        f"/api/projects/{project_id}/dispatch/bulk",
        json={"action": "research", "topic_ids": [*topic_ids, missing]},
    )

    assert response.status_code == 202
    assert response.json()["unknown"] == [missing]
    assert len(response.json()["queued"]) == 1
    await queue.wait(UUID(project_id))


async def test_bulk_dispatch_refuses_a_list_longer_than_a_project_can_hold(
    dispatch_client, fake_model
):
    """Capped at `MAX_BULK_DISPATCH`, which is `MAX_OPEN_TOPICS`: "every topic
    the filter is showing me" always fits, and nothing larger is a request
    anybody meant to make.

    Refused before any topic is resolved, so there is no half-enqueued queue
    to unwind -- which is why the cap is on the model rather than in the route
    body.
    """
    application, _queue, http = dispatch_client
    project_id, _topic_ids = await _project_with_several_topics(
        application, http, fake_model, ["How does spacing work?"]
    )

    response = await http.post(
        f"/api/projects/{project_id}/dispatch/bulk",
        json={
            "action": "research",
            "topic_ids": [str(uuid4()) for _ in range(MAX_BULK_DISPATCH + 1)],
        },
    )

    assert response.status_code == 422


async def test_bulk_dispatch_refuses_an_empty_list(dispatch_client, fake_model):
    """An empty fan-out is a client bug -- a button pressed with no rows
    shown -- and answering 202 with nothing queued would hide it behind a
    success."""
    application, _queue, http = dispatch_client
    project_id, _topic_ids = await _project_with_several_topics(
        application, http, fake_model, ["How does spacing work?"]
    )

    response = await http.post(
        f"/api/projects/{project_id}/dispatch/bulk",
        json={"action": "research", "topic_ids": []},
    )

    assert response.status_code == 422


async def test_bulk_dispatch_refuses_an_unknown_action_by_name(dispatch_client, fake_model):
    """Same refusal as the per-topic route, checked separately because it is a
    second copy of the check and a second place to forget it."""
    application, _queue, http = dispatch_client
    project_id, topic_ids = await _project_with_several_topics(
        application, http, fake_model, ["How does spacing work?"]
    )

    response = await http.post(
        f"/api/projects/{project_id}/dispatch/bulk",
        json={"action": "lesson", "topic_ids": topic_ids},
    )

    assert response.status_code == 422
    assert "research" in response.text


async def test_bulk_dispatch_is_503_unless_the_instance_was_wired(client):
    """Matching the per-topic route: this build is missing configuration, not
    the project the id names."""
    project_id = (await client.post("/api/projects", json={"name": "atlas"})).json()["id"]

    response = await client.post(
        f"/api/projects/{project_id}/dispatch/bulk",
        json={"action": "research", "topic_ids": [str(uuid4())]},
    )

    assert response.status_code == 503
