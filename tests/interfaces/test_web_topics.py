"""Topic routes exercised over ASGI with no network and no real model."""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.application import SummaryProjects, WorkerRoster
from research_team.application.knowledge import ExtractionNote
from research_team.composition import build_application as _build_application
from research_team.domain.topic import OpenTopic, RecordFinding
from research_team.infrastructure.persistence.event_store import build_topic_repository
from research_team.interfaces.web import create_app
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
