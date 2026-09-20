"""`/api/projects/{id}/embeddings` and `/curriculum/author` routes: re-embedding and locks."""

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
