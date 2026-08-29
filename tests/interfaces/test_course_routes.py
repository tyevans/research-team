"""The course detail/realize/abandon/blurb-sweep routes (Task 9).

Composed over the real `build_application`, following
`test_catalog_routes.py`'s own precedent: a build that never wires
`course_service`/`course_repository` answers every route here 503, and a
fixture handing a route a hand-built service could not tell that build from
a working one. `catalog` and `curriculum` are built standalone here for the
same reason `test_catalog_routes.py` builds its own -- neither composes
anything this module is testing.
"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from redstring import Entity, ExtractionMethod, Provenance, Relationship

from research_team.application.course_catalog import CatalogService
from research_team.application.curriculum import CurriculumService
from research_team.composition import build_application
from research_team.domain.session import SessionPurpose
from research_team.infrastructure.knowledge.seeded_art import SeededArtProvider
from research_team.infrastructure.knowledge.type_plurality_grouper import TypePluralityGrouper
from research_team.interfaces.web import create_app
from research_team.interfaces.web.authoring import AuthoringActivity

pytestmark = pytest.mark.asyncio


class _NoBlurbs:
    """A `BlurbCachePort` that has never cached anything -- `candidate_view`
    renders every candidate's blurb as `None`, which is fine: nothing here
    asserts on blurb text."""

    async def get(self, project_id, slug):
        return None

    async def all_for_project(self, project_id):
        return {}

    async def put(self, *args, **kwargs) -> None:  # pragma: no cover -- never called here
        raise AssertionError("nothing in this module caches a blurb")


class _NoFeatures:
    """A `CatalogFeatureStore` stand-in with nothing ever featured -- `_catalog`
    (`app.py`) refuses to build a catalog at all unless it can call
    `featured_for`, even though nothing in this module features anything."""

    async def featured_for(self, project_id):
        return {}


class _GatedAuthor:
    """A `CourseAuthor` that records what it was asked and blocks until let
    through -- the same shape `test_curriculum_routes.py`'s `StubAuthor`
    uses, trimmed to what this module's one busy-run test needs: a way to
    hold a run open long enough for a second request to observe it as active.
    """

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.gate = None  # set by the test that wants to hold a run open

    async def author_area(self, project_id, area, subject, *, lesson_count=3, run_id=None):
        self.asked.append(area.slug)
        if self.gate is not None:
            await self.gate.wait()
        return SimpleNamespace(session_id=uuid4())

    async def author_path(self, project_id, path, areas, *, run_id=None):
        self.asked.append(path.slug)
        if self.gate is not None:
            await self.gate.wait()
        return SimpleNamespace(session_id=uuid4())


@pytest.fixture
async def app_and_client(db_path, fake_model):
    application = build_application(model=fake_model, db_path=db_path)
    await application.start()
    curriculum = CurriculumService()
    catalog = CatalogService(
        grouper=TypePluralityGrouper(), art=SeededArtProvider(), blurbs=_NoBlurbs()
    )
    author = _GatedAuthor()
    authoring = AuthoringActivity(application.authoring_runs, application.authoring)
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=application.blob_store,
        graphs=application.graphs,
        curriculum=curriculum,
        catalog=catalog,
        catalog_features=lambda: _NoFeatures(),
        course_author=author,
        authoring=authoring,
        course_service=application.course_service,
        course_repository=application.course_repository,
        blurb_sweep=application.blurb_sweep,
        blurb_writer=application.blurbs,
        outline_writer=application.outlines,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(
            application=application,
            client=client,
            catalog=catalog,
            author=author,
            authoring=authoring,
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
    created = await client.post("/api/projects", json={"name": f"course-{uuid4()}"})
    assert created.status_code == 200
    return created.json()["id"]


async def _seed_one_cluster(application, project_id: str) -> None:
    """One four-clique -- exactly one candidate, so a test can name its slug
    without first reading the catalog to find out what it is."""
    tenant_id = UUID(project_id)
    store = await application.graphs.open(tenant_id)
    entities = [_entity(tenant_id, f"Gamma {i}") for i in range(4)]
    await store.upsert_entities(entities)
    edges = [
        Relationship(
            id=uuid4(),
            tenant_id=tenant_id,
            source_entity_id=left.id,
            target_entity_id=right.id,
            relationship_type="relates_to",
            confidence=1.0,
        )
        for i, left in enumerate(entities)
        for right in entities[i + 1 :]
    ]
    await store.upsert_relationships(edges)


async def _one_candidate_slug(app_and_client, project_id: str) -> str:
    """The single candidate this module's fixture seeds.

    `?unnamed=true` because the front page hides candidates whose blurb has no
    title, and nothing in this module writes a blurb -- these tests are about
    realizing and abandoning a course, not about its copy. Without the flag the
    catalog comes back empty and the unpack below fails with
    `not enough values to unpack`, which names nothing about the filter.
    """
    url = f"/api/projects/{project_id}/catalog?unnamed=true"
    body = (await app_and_client.client.get(url)).json()
    (slug,) = {c["slug"] for c in body["hero"] + body["highlights"]} | {
        candidate["slug"] for category in body["filed"] for candidate in category["candidates"]
    }
    return slug


async def _hold_a_run_open(app_and_client, project_id: str, target: str) -> None:
    """Start an authoring run on this project that will not settle until the
    test releases `app_and_client.author.gate`.

    `AuthoringActivity.start` calls `run(run_id, target)` with exactly those
    two arguments (see its own signature) -- passing `author.author_area`
    directly, which additionally wants `area` and `subject`, raises a
    `TypeError` the driving loop's blanket `except Exception` swallows as an
    ordinary authoring failure. That failure settles the run in a single
    scheduler tick, so a caller checking `active()` a moment later finds
    nothing running -- which is what made this test pass for the wrong
    reason before this helper existed. Wrapping it in the shape `start`
    actually calls is what keeps the run open until `gate.set()`.
    """

    async def _one(run_id, run_target):
        return await app_and_client.author.author_area(
            project_id, SimpleNamespace(slug=run_target), "subject", run_id=run_id
        )

    # `AuthoringActivity` keys its running-run dict by whatever `project_id`
    # `.start()` was given. The route parses the path segment to a `UUID`;
    # this helper is handed the JSON string `_new_project` returns, and
    # starting under that string would key a run this test's own request
    # could never collide with -- see this function's own docstring.
    await app_and_client.authoring.start(UUID(project_id), [target], _one, kind="area")


async def test_realizing_records_the_decision_even_when_a_run_is_in_flight(app_and_client):
    """The design's load-bearing case. The authoring endpoint answers 409
    when a run is active on this project; letting that propagate would make
    whether you can *choose* a course depend on whether someone else is
    mid-run. 202, `authoring` null, `reason` set, and the row is there.
    """
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_one_cluster(application, project_id)
    slug = await _one_candidate_slug(app_and_client, project_id)

    # Hold a run open on this project before realizing anything -- any
    # target will do, `AuthoringActivity.start` never checks it against the
    # curriculum.
    app_and_client.author.gate = asyncio.Event()
    await _hold_a_run_open(app_and_client, project_id, slug)

    response = await client.post(f"/api/projects/{project_id}/catalog/{slug}/realize")

    assert response.status_code == 202
    body = response.json()
    assert body["realized"] is True
    assert body["authoring"] is None
    assert body["reason"]

    await application.courses_caught_up()
    row = await application.courses.get(UUID(project_id), slug)
    assert row is not None
    assert row.slug == slug

    app_and_client.author.gate.set()


async def test_realizing_an_unknown_slug_is_404(app_and_client):
    client = app_and_client.client
    project_id = await _new_project(client)

    response = await client.post(f"/api/projects/{project_id}/catalog/no-such-course/realize")

    assert response.status_code == 404


async def test_realizing_twice_is_409(app_and_client):
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_one_cluster(application, project_id)
    slug = await _one_candidate_slug(app_and_client, project_id)

    first = await client.post(f"/api/projects/{project_id}/catalog/{slug}/realize")
    assert first.status_code == 202

    second = await client.post(f"/api/projects/{project_id}/catalog/{slug}/realize")

    assert second.status_code == 409


async def test_reading_blurb_progress_is_not_read_as_a_slug(app_and_client):
    """Route ordering. With the declarations swapped this answers 404 for a
    course named 'blurbs' instead of the sweep's progress."""
    client = app_and_client.client
    project_id = await _new_project(client)

    response = await client.get(f"/api/projects/{project_id}/catalog/blurbs")

    assert response.status_code == 200
    assert "running" in response.json()


async def test_the_detail_route_never_calls_a_model_and_reports_no_outline_uncached(
    app_and_client,
):
    """`CourseService._outline_for` is cache-read-only now -- see
    `course_realization.py`'s module docstring. A candidate nothing has ever
    swept renders `outline: None`, the same shape a refusal used to render,
    and this route must not block on a model call to answer that. Outline
    generation moved entirely into the background sweep
    (`POST /catalog/blurbs`, see `blurb_sweep.py`); it is not exercised by
    this fixture's `fake_model`-backed application here.
    """
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_one_cluster(application, project_id)
    slug = await _one_candidate_slug(app_and_client, project_id)

    response = await client.get(f"/api/projects/{project_id}/catalog/{slug}")

    assert response.status_code == 200
    body = response.json()
    assert body["candidate"]["slug"] == slug
    assert body["outline"] is None
    assert body["course"] is None


async def test_abandoning_does_not_cancel_a_running_authoring_run(app_and_client):
    """The decision is withdrawn; the work it caused is not. Deleting a
    person's course because they clicked the wrong thing is the failure this
    guards."""
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_one_cluster(application, project_id)
    slug = await _one_candidate_slug(app_and_client, project_id)

    # Gated *before* realizing, so the run `realize` itself starts is the one
    # under test here -- setting the gate afterwards would race the
    # background task realize's own authoring call schedules.
    app_and_client.author.gate = asyncio.Event()

    realized = await client.post(f"/api/projects/{project_id}/catalog/{slug}/realize")
    assert realized.status_code == 202
    assert realized.json()["authoring"] is not None
    assert app_and_client.authoring.active(UUID(project_id)) is not None

    response = await client.post(f"/api/projects/{project_id}/catalog/{slug}/abandon")

    assert response.status_code == 200
    assert response.json()["realized"] is False
    # Still running -- abandon appended `CourseAbandoned` and touched nothing
    # else.
    assert app_and_client.authoring.active(UUID(project_id)) is not None

    app_and_client.author.gate.set()


async def test_an_unrealized_courses_write_side_is_503_when_unwired(app_and_client):
    api = create_app(
        app_and_client.application.service,
        app_and_client.application.feed,
        app_and_client.application.turns,
        graphs=app_and_client.application.graphs,
    )
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        project_id = await _new_project(client)
        response = await client.post(f"/api/projects/{project_id}/catalog/some-slug/realize")

    assert response.status_code == 503


async def test_realizing_a_held_project_names_the_holder_instead_of_starting(app_and_client):
    """The defect this route shipped with, and the whole reason `heldBy` exists.

    `CourseAuthor.author_area` opens with `start_in_project`, whose
    `JoinProject` refuses while anybody holds the project -- so a project
    somebody has open in chat refused every authoring run, ~30ms after a 202
    the console read as "it started". Measured on the owner's database on
    2026-08-29: three `CourseAuthoringFailed` events in half an hour, all
    naming one `purpose: chat` session that had done nothing since it joined.

    Reverting the holder check in `realize_course` does not merely change
    `heldBy` to `None` here -- it makes `author.asked` non-empty, because the
    run starts, and that is the assertion that separates "asked before
    starting" from "reported after failing".
    """
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_one_cluster(application, project_id)
    slug = await _one_candidate_slug(app_and_client, project_id)

    holder = await application.service.start_in_project(UUID(project_id), SessionPurpose.CHAT)

    response = await client.post(f"/api/projects/{project_id}/catalog/{slug}/realize")

    assert response.status_code == 202
    body = response.json()
    # The decision is still recorded -- holding is about where the next write
    # goes, not about whether a person may choose a course.
    assert body["realized"] is True
    assert body["authoring"] is None
    assert body["heldBy"] == str(holder)
    assert str(holder) in body["reason"]
    assert app_and_client.author.asked == []

    await application.courses_caught_up()
    assert await application.courses.get(UUID(project_id), slug) is not None


async def test_realizing_an_unheld_project_starts_the_run_and_names_nobody(app_and_client):
    """The other side of the check above.

    Without it this file could not tell a holder check that is right from one
    that fires on every project -- which would refuse authoring everywhere and
    look, from `test_realizing_a_held_project_...` alone, exactly correct.
    """
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_one_cluster(application, project_id)
    slug = await _one_candidate_slug(app_and_client, project_id)

    response = await client.post(f"/api/projects/{project_id}/catalog/{slug}/realize")

    assert response.status_code == 202
    body = response.json()
    assert body["heldBy"] is None
    assert body["reason"] is None
    assert body["authoring"] is not None
    await app_and_client.authoring.wait(UUID(project_id))
    assert app_and_client.author.asked == [slug]
