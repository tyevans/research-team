"""`/api/projects/{id}/curriculum`: the envelope, and the seam behind it.

The arithmetic belongs to `test_area_projection.py` and `test_learning_paths.py`.
What can only break here is the field names the browser parses by exact key,
and one seam this repository has been caught by before: `CLAUDE.md` records a
defect where a call site fetched a project's chunks *before* opening it, so
the first request for any newly-touched project answered 503 and every later
one succeeded -- once per project, and indistinguishable from flakiness. Every
test in that feature missed it because each fixture had already opened the
project while seeding. `test_the_first_request_for_an_untouched_project_works`
below is written to start from a project the fixture has not opened.

Follows `test_timeline_route.py`'s `app_and_client`, duplicated module-locally
for that module's stated reason.
"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from redstring import Entity, ExtractionMethod, Provenance, Relationship

from research_team.application import SummaryProjects, WorkerRoster
from research_team.application.curriculum import CurriculumService
from research_team.composition import build_application
from research_team.domain.session import SessionPurpose
from research_team.interfaces.web import create_app
from research_team.interfaces.web.authoring import AuthoringActivity
from research_team.interfaces.web.extraction import ExtractionActivity

pytestmark = pytest.mark.asyncio


class StubAuthor:
    """A `CourseAuthor` that records its asks and runs no turns.

    The real one is four model turns per area against a joined project, and a
    route test that drove it would be testing `TurnSupervisor` -- slowly, and
    while leaving a background task running past the fixture that owns the
    application. `test_course_authoring.py` owns the sequencing; what can only
    break *here* is which areas the route decides to hand over.
    """

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.sessions: dict[str, UUID] = {}
        #: Held open by the cancel tests so a run can be stopped mid-target.
        #: `None` -- the default -- means every target returns at once, which
        #: is what every other test in this module wants.
        self.gate: asyncio.Event | None = None
        #: One permit per target allowed to finish, for the cancel tests.
        #:
        #: An `asyncio.Event` cannot express "let exactly one through". A test
        #: that sets the event, waits for the first session and then clears it
        #: has a window: the driver starts the *second* target and passes the
        #: still-open event before `clear()` runs. Both cancel tests were
        #: written that way and both passed locally and failed on CI, where a
        #: loaded runner widened the window -- 2 targets finished where the
        #: assertion expected 1, so the abandoned count came back one short.
        #: A semaphore has no such window: with no permits left, the next
        #: target blocks whatever the scheduler does.
        self.permits: asyncio.Semaphore | None = None

    async def _one(self, target: str):
        self.asked.append(target)
        if self.permits is not None:
            await self.permits.acquire()
        if self.gate is not None:
            await self.gate.wait()
        session_id = uuid4()
        self.sessions[target] = session_id
        return SimpleNamespace(session_id=session_id)

    async def author_area(self, project_id, area, subject, *, lesson_count=3, run_id=None):
        return await self._one(area.slug)

    async def author_path(self, project_id, path, areas, *, run_id=None):
        return await self._one(path.slug)


@pytest.fixture
async def app_and_client(db_path, fake_model):
    application = build_application(model=fake_model, db_path=db_path)
    await application.start()
    extraction = ExtractionActivity()
    author = StubAuthor()
    authoring = AuthoringActivity(application.authoring_runs, application.authoring)
    curriculum = CurriculumService()
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
        curriculum=curriculum,
        course_author=author,
        authoring=authoring,
        reembed=application.reembed,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(
            application=application,
            client=client,
            authoring=authoring,
            author=author,
            curriculum=curriculum,
        )
    await application.close()


def _entity(tenant_id: UUID, name: str) -> Entity:
    return Entity(
        id=uuid4(),
        tenant_id=tenant_id,
        name=name,
        normalized_name=name.lower(),
        entity_type="concept",
        provenance=Provenance(
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            extraction_method=ExtractionMethod.MANUAL,
            confidence=1.0,
        ),
    )


async def _new_project(client) -> str:
    created = await client.post("/api/projects", json={"name": f"curriculum-{uuid4()}"})
    assert created.status_code == 200
    return created.json()["id"]


async def _seed_two_clusters(application, project_id: str) -> None:
    """Two four-cliques joined by one edge: an unambiguous two-area graph.

    Seeded through `GraphStore.upsert_entities` -- `test_timeline_route.py`'s
    shortcut -- because what is under test is the read route, not extraction.
    """
    tenant_id = UUID(project_id)
    store = await application.graphs.open(tenant_id)
    groups = [
        [_entity(tenant_id, f"Alpha {i}") for i in range(4)],
        [_entity(tenant_id, f"Beta {i}") for i in range(4)],
    ]
    await store.upsert_entities([e for group in groups for e in group])

    edges = []
    for group in groups:
        for i, left in enumerate(group):
            for right in group[i + 1 :]:
                edges.append(
                    Relationship(
                        id=uuid4(),
                        tenant_id=tenant_id,
                        source_entity_id=left.id,
                        target_entity_id=right.id,
                        relationship_type="relates_to",
                        confidence=1.0,
                    )
                )
    await store.upsert_relationships(edges)


async def test_the_curriculum_route_returns_the_keys_the_browser_parses(app_and_client):
    """Field names, asserted literally.

    The browser parses these by exact key, so a rename fails as a
    `ContractError` there with nothing failing in Python. Written out rather
    than compared against a constant, so the two spellings are independent.
    """
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(application, project_id)

    response = await client.get(f"/api/projects/{project_id}/curriculum")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"areas", "path", "derived_from"}
    assert set(body["derived_from"]) == {
        "entities",
        "relationships",
        "passages",
        "semantic_edges",
        "used_embeddings",
        "truncated",
    }
    assert set(body["path"]) == {"slug", "title", "destination", "areas", "edges"}
    assert set(body["areas"][0]) == {
        "slug",
        "title",
        "summary",
        "size",
        "truncated_members",
        "members",
    }


async def test_the_route_finds_the_areas_that_are_there(app_and_client):
    """Not merely that the request succeeded.

    `CLAUDE.md` is explicit that asserting a 200 is worthless as a test of a
    projection: an endpoint answers 200 with nothing in it when the machinery
    was never wired. The assertion has to be that the *data* is there.
    """
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(application, project_id)

    body = (await client.get(f"/api/projects/{project_id}/curriculum")).json()

    assert len(body["areas"]) == 2
    assert body["derived_from"]["entities"] == 8
    assert sorted(body["path"]["areas"]) == sorted(a["slug"] for a in body["areas"])


async def test_the_first_request_for_an_untouched_project_works(app_and_client):
    """The seam `CLAUDE.md` records: chunks fetched before the project is open.

    This fixture deliberately does **not** seed a graph, so nothing has called
    `graphs.open` for this project before the request arrives. A route that
    reached for `graphs.chunks` first would answer 503 here and succeed on
    every later call in the same process -- once per project, and looking
    exactly like flakiness.
    """
    _application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)

    response = await client.get(f"/api/projects/{project_id}/curriculum")

    assert response.status_code == 200
    assert response.json()["areas"] == []


async def test_an_area_route_returns_its_full_membership(app_and_client):
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(application, project_id)
    listed = (await client.get(f"/api/projects/{project_id}/curriculum")).json()
    slug = listed["areas"][0]["slug"]

    response = await client.get(f"/api/projects/{project_id}/curriculum/areas/{slug}")

    assert response.status_code == 200
    assert len(response.json()["members"]) == 4
    assert set(response.json()["members"][0]) == {
        "entity_id",
        "name",
        "entity_type",
        "centrality",
        "temporal",
    }


async def test_an_unknown_area_is_a_404(app_and_client):
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(application, project_id)

    response = await client.get(f"/api/projects/{project_id}/curriculum/areas/nope")

    assert response.status_code == 404


async def test_the_complete_path_is_readable_by_its_own_slug(app_and_client):
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(application, project_id)

    response = await client.get(f"/api/projects/{project_id}/curriculum/paths/complete")

    assert response.status_code == 200
    assert len(response.json()["areas"]) == 2
    assert response.json()["destination"] is None


async def test_a_path_toward_an_area_is_cut_to_that_area(app_and_client):
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(application, project_id)
    complete = (
        await client.get(f"/api/projects/{project_id}/curriculum/paths/complete")
    ).json()
    destination = complete["areas"][-1]

    response = await client.get(f"/api/projects/{project_id}/curriculum/paths/{destination}")

    assert response.status_code == 200
    body = response.json()
    assert body["destination"] == destination
    assert body["areas"][-1] == destination
    positions = [complete["areas"].index(s) for s in body["areas"]]
    assert positions == sorted(positions)


async def test_an_unknown_project_is_a_404(app_and_client):
    _application, client = app_and_client.application, app_and_client.client

    assert (await client.get(f"/api/projects/{uuid4()}/curriculum")).status_code == 404


async def test_authoring_with_no_areas_is_refused_rather_than_reported_started(
    app_and_client,
):
    """202 over an empty target list settles instantly as "done" and reads, on
    every surface, exactly like a run that authored everything."""
    _application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)

    response = await client.post(f"/api/projects/{project_id}/curriculum/author", json={})

    assert response.status_code == 409


async def test_a_single_area_run_does_not_write_the_path_overview(app_and_client):
    """A one-area run has no order to write up.

    Worth its own test because the overview is appended to `targets` rather
    than run after them, and an append that forgot its condition would have
    every single-area run rewrite the whole path's file from a projection the
    reader did not ask about.
    """
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(application, project_id)
    listed = (await client.get(f"/api/projects/{project_id}/curriculum")).json()
    slug = listed["areas"][0]["slug"]

    response = await client.post(
        f"/api/projects/{project_id}/curriculum/author", json={"area": slug}
    )

    assert response.status_code == 202
    assert response.json()["targets"] == [slug]
    await app_and_client.authoring.wait(UUID(project_id))
    assert app_and_client.author.asked == [slug]


async def test_authoring_an_unknown_area_is_a_404(app_and_client):
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(application, project_id)

    response = await client.post(
        f"/api/projects/{project_id}/curriculum/author", json={"area": "nope"}
    )

    assert response.status_code == 404


async def test_an_authoring_run_is_reported_before_it_finishes(app_and_client):
    """202 and a frame naming what it will do, matching `seed_topics`."""
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(application, project_id)

    response = await client.post(f"/api/projects/{project_id}/curriculum/author", json={})

    assert response.status_code == 202
    frame = response.json()
    assert frame["status"] == "running"
    assert frame["kind"] == "path"
    # Two areas plus the path's own overview file.
    assert frame["targets"] == [*frame["targets"][:2], "complete"]
    assert len(frame["targets"]) == 3
    # Settled before the fixture tears the application down. A background task
    # outliving the app it was started against is how this module first hung.
    await app_and_client.authoring.wait(UUID(project_id))
    assert app_and_client.author.asked == frame["targets"]


async def test_the_authoring_catch_up_route_answers_before_anything_has_run(
    app_and_client,
):
    """An absent run is a state, not a missing resource."""
    _application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)

    response = await client.get(f"/api/projects/{project_id}/curriculum/author")

    assert response.status_code == 200
    assert response.json() == {"current": None, "last": None}


async def test_cancelling_with_nothing_running_answers_zero_rather_than_refusing(
    app_and_client,
):
    """A stop control pressed twice is a person pressing a button.

    200 with a count, matching `cancel_extraction_queue`, rather than a 409 --
    the second press has nothing to stop and that is not a bad request.
    """
    _application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)

    response = await client.post(f"/api/projects/{project_id}/curriculum/author/cancel")

    assert response.status_code == 200
    assert response.json() == {"cancelled": 0}


async def test_cancelling_an_unknown_project_is_a_404(app_and_client):
    """`_require_project` first, like every other route in this file."""
    client = app_and_client.client

    response = await client.post(f"/api/projects/{uuid4()}/curriculum/author/cancel")

    assert response.status_code == 404


async def test_a_cancelled_run_keeps_the_courses_it_already_wrote(app_and_client):
    """The point of cancelling rather than killing the process.

    The assertion is on the *session id* of the target that finished before
    the stop, not on the status alone: those courses exist, in that session's
    workspace, and a cancel that dropped the mapping would leave them exactly
    as unreachable as a crash did.

    Read back through the catch-up route, which reads the log -- so this also
    covers the route awaiting `last` rather than the dict it used to read.
    """
    application, client = app_and_client.application, app_and_client.client
    author = app_and_client.author
    author.permits = asyncio.Semaphore(0)
    project_id = await _new_project(client)
    await _seed_two_clusters(application, project_id)

    started = await client.post(f"/api/projects/{project_id}/curriculum/author", json={})
    assert started.status_code == 202
    first_target = started.json()["targets"][0]
    # Exactly one permit, so exactly one target can finish however the
    # scheduler interleaves. Every later target blocks on `acquire`.
    author.permits.release()
    while first_target not in author.sessions:
        await asyncio.sleep(0.01)

    cancelled = await client.post(f"/api/projects/{project_id}/curriculum/author/cancel")
    assert cancelled.status_code == 200
    # Three targets, one written: two abandoned.
    assert cancelled.json() == {"cancelled": 2}

    await app_and_client.authoring.wait(UUID(project_id))
    await application.authoring.caught_up()

    status = (await client.get(f"/api/projects/{project_id}/curriculum/author")).json()
    assert status["current"] is None
    assert status["last"]["status"] == "cancelled"
    assert status["last"]["completed"] == [first_target]
    assert status["last"]["sessions"] == [str(author.sessions[first_target])]


async def test_deleting_a_project_forgets_its_curriculum(app_and_client):
    """A cache holding a dead project's clusters for the life of the process.

    Asserted on the cache rather than through a second request, because a
    second request on a deleted project 404s before it reaches the cache --
    which is exactly why the leak would be invisible without this.
    """
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(application, project_id)
    await client.get(f"/api/projects/{project_id}/curriculum")
    assert UUID(project_id) in app_and_client.curriculum._cache

    deleted = await client.delete(f"/api/projects/{project_id}")

    assert deleted.status_code == 200
    assert UUID(project_id) not in app_and_client.curriculum._cache


async def _client_with(application, **overrides):
    """An app over the same application, with these dependencies swapped."""
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        graphs=application.graphs,
        **overrides,
    )
    return AsyncClient(transport=ASGITransport(app=api), base_url="http://test")


async def test_re_embedding_reports_how_many_it_wrote(app_and_client):
    """The envelope, over a stub rather than a provider.

    Deliberately not driven through the real `reembed`: whether anything gets
    embedded depends on an endpoint being up, which a route test does not
    control -- the first draft of this asserted a count and failed against a
    connection error, which was the test discovering it had no business
    reaching the network. What can only break here is the status and the key.
    """
    project_id = await _new_project(app_and_client.client)

    async with await _client_with(
        app_and_client.application, reembed=lambda _project_id: _seven()
    ) as client:
        response = await client.post(f"/api/projects/{project_id}/embeddings")

    assert response.status_code == 202
    assert response.json() == {"embedded": 7}


async def _seven() -> int:
    return 7


async def test_re_embedding_drops_the_cached_curriculum(app_and_client):
    """Otherwise the run succeeds and changes nothing anybody can see.

    `CurriculumService` keys its cache on entity and relationship counts, and
    re-embedding moves neither -- so without the `forget` the new vectors sit
    in the store until the next extraction happens to change a count. The
    button would appear to work and do nothing, which is worse than an error.

    Proved by *identity*: the service returns the same `Curriculum` object on a
    cache hit, so a new object is the only evidence the projection re-ran.
    """
    project_id = await _new_project(app_and_client.client)
    await _seed_two_clusters(app_and_client.application, project_id)
    curriculum = CurriculumService()

    async with await _client_with(
        app_and_client.application,
        curriculum=curriculum,
        reembed=lambda _project_id: _seven(),
    ) as client:
        await client.get(f"/api/projects/{project_id}/curriculum")
        cached = curriculum._cache[UUID(project_id)][1]

        await client.post(f"/api/projects/{project_id}/embeddings")
        await client.get(f"/api/projects/{project_id}/curriculum")

    assert curriculum._cache[UUID(project_id)][1] is not cached


async def test_a_dead_embedding_endpoint_is_reported_rather_than_a_500(app_and_client):
    """502, and the provider's message with it.

    Three outcomes a browser must be able to tell apart: this build has no
    embedding wiring (503), embeddings are configured but off or empty (202
    with `embedded: 0`), and the endpoint is there and refused (502). Collapsed
    into one status they are indistinguishable, and only the third is worth
    waking anybody for.

    The real `reembed` is used here on purpose -- there is no embedding server
    in a test run, so the failure is the genuine one rather than a stubbed
    stand-in for it.
    """
    project_id = await _new_project(app_and_client.client)
    await _seed_two_clusters(app_and_client.application, project_id)

    async with await _client_with(
        app_and_client.application, reembed=app_and_client.application.reembed
    ) as client:
        response = await client.post(f"/api/projects/{project_id}/embeddings")

    assert response.status_code == 502
    assert "embed" in response.json()["detail"].lower()


async def test_re_embedding_an_unwired_build_says_so(app_and_client):
    """503 rather than a silent 202 that embedded nothing."""
    project_id = await _new_project(app_and_client.client)

    async with await _client_with(app_and_client.application) as client:
        response = await client.post(f"/api/projects/{project_id}/embeddings")

    assert response.status_code == 503


async def test_authoring_a_held_project_is_refused_by_name(app_and_client):
    """Refused here, where the caller can read it, rather than 30ms later in
    a background task nothing renders.

    The holder is in the detail because the console's next call is this same
    route with `take_over`, and an offer to take a lock has to be able to say
    whose it is.
    """
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(application, project_id)
    holder = await application.service.start_in_project(UUID(project_id), SessionPurpose.CHAT)

    response = await client.post(f"/api/projects/{project_id}/curriculum/author", json={})

    assert response.status_code == 409
    assert str(holder) in response.json()["detail"]
    assert app_and_client.author.asked == []


async def test_take_over_releases_the_holder_and_authors(app_and_client):
    """The console's "take the lock?" answered yes.

    Asserts the *release*, not merely the 202: a build that accepted the flag
    and ignored it would answer 202 here and then fail every target in the
    background, which is the exact silence this whole change is about.
    """
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(application, project_id)
    await application.service.start_in_project(UUID(project_id), SessionPurpose.CHAT)

    response = await client.post(
        f"/api/projects/{project_id}/curriculum/author", json={"take_over": True}
    )

    assert response.status_code == 202
    state = await application.service.project_state(UUID(project_id))
    assert state.active_session_id is None
    await app_and_client.authoring.wait(UUID(project_id))
    assert app_and_client.author.asked != []


async def test_take_over_refuses_a_holder_that_is_mid_turn(app_and_client):
    """`release_project` advances the tip to `session.version`, so releasing a
    session still writing detaches everything it writes next -- the bug
    `_catch_up_tip` exists to repair. Same refusal `join_project`'s own
    take-over makes, and it has to be repeated here because this route does
    not go through that one.
    """
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(application, project_id)
    holder = await application.service.start_in_project(UUID(project_id), SessionPurpose.CHAT)
    # A turn that will not finish, registered where `is_running` reads. Not a
    # real turn: this test is about the refusal, and driving a model to get a
    # task into that dict would make the assertion depend on how long a fake
    # model takes to answer.
    gate = asyncio.Event()
    application.turns._running[holder] = asyncio.ensure_future(gate.wait())

    response = await client.post(
        f"/api/projects/{project_id}/curriculum/author", json={"take_over": True}
    )

    assert response.status_code == 409
    assert "turn running" in response.json()["detail"]
    state = await application.service.project_state(UUID(project_id))
    assert state.active_session_id == holder

    gate.set()
