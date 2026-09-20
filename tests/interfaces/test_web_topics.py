"""Topic and dispatch routes exercised over ASGI with no network and no real model."""

import json
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from research_team.application import SummaryProjects, WorkerRoster
from research_team.application.knowledge import ExtractionNote
from research_team.composition import build_application as _build_application
from research_team.domain.topic import OpenTopic, RecordFinding
from research_team.infrastructure.persistence.event_store import build_topic_repository
from research_team.interfaces.web import create_app
from research_team.interfaces.web.app import MAX_BULK_DISPATCH
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
async def client_without_workers(db_path, fake_model):
    """A build with no roster wired -- the shape `get_workers` 404s for."""
    application = await _started(model=fake_model, db_path=db_path)
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=application.blob_store,
        workers=None,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await application.close()


async def make_project(client, name: str = "atlas") -> UUID:
    response = await client.post("/api/projects", json={"name": name})
    assert response.status_code == 200
    return UUID(response.json()["id"])


async def join_session(client, project_id: UUID) -> UUID:
    response = await client.post(f"/api/projects/{project_id}/join")
    assert response.status_code == 200
    return UUID(response.json()["id"])


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


# ---------------- workers ----------------


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


# ---------------- topic seeding ----------------


@pytest.fixture
async def seeding_client(db_path, fake_model):
    """A client wired with a `TopicSeeder` and its own `SeedingActivity`.

    Separate from `client`, matching `dispatch_client`: the default app is
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
        blob_store=application.blob_store,
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
    hands one back (a dispatch's `dispatch_id`, for one). An id here
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
