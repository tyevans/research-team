"""`/api/projects/{id}/timeline`: the shape the browser's zod DTO parses.

The route is thin, so these tests are about the envelope rather than the
arithmetic -- `test_timeline_reader.py` owns that. What can only break here is
the field names, which the frontend parses by exact key.

Follows `test_web.py`'s `app_and_client` fixture and its `_project_with_graph`
seeding helper, both duplicated here module-locally rather than imported --
the same call `test_repl_project.py`'s `current` fixture makes over
`test_repl.py`'s fixture of the same name: `app_and_client` is module-local to
`test_web.py`, not in a shared `conftest.py`, and importing it across modules
would either need a `conftest.py` this suite does not have or would redefine
the name and trip `ruff`'s F811. Trimmed to what this route needs -- one
project, one dated entity, no relationships -- rather than the two-entity
graph `test_web.py` seeds for its own edge-following tests.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from redstring import DatePrecision, Entity, ExtractionMethod, Provenance, TemporalExtent

from research_team.application import SummaryProjects, WorkerRoster
from research_team.composition import build_application
from research_team.interfaces.web import create_app
from research_team.interfaces.web.extraction import ExtractionActivity

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def app_and_client(db_path, fake_model):
    """`(application, client)` over a fresh app, wired the way `test_web.py`
    wires it -- see that module's `app_and_client` for what each argument is
    for. Duplicated rather than shared; see the module docstring.
    """
    application = build_application(model=fake_model, db_path=db_path)
    await application.start()
    extraction = ExtractionActivity()
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


def _year(year: int) -> TemporalExtent:
    return TemporalExtent(
        start_date=datetime(year, 1, 1, tzinfo=UTC),
        end_date=datetime(year, 12, 31, tzinfo=UTC),
        precision=DatePrecision.YEAR,
    )


async def _project_with_dated_entity(application, client) -> str:
    """A project holding one dated entity in its graph store, seeded directly.

    Seeded through `GraphStore.upsert_entities` -- the same shortcut
    `test_web.py`'s `_project_with_graph` takes -- rather than through
    `remember`, because what is under test is the read route, not extraction.
    One entity is enough: `bands` needs at least one row to assert its keys
    against, and `undated_count`'s arithmetic belongs to
    `test_timeline_reader.py`, not this route.
    """
    created = await client.post("/api/projects", json={"name": f"timeline-{uuid4()}"})
    assert created.status_code == 200
    project_id = created.json()["id"]
    tenant_id = UUID(project_id)

    store = await application.graphs.open(tenant_id)
    entity = Entity(
        id=uuid4(),
        tenant_id=tenant_id,
        name="Battle of Waterloo",
        normalized_name="battle of waterloo",
        entity_type="event",
        provenance=Provenance(
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            extraction_method=ExtractionMethod.MANUAL,
            confidence=1.0,
        ),
        temporal=_year(1815),
    )
    await store.upsert_entities([entity])
    return project_id


async def test_the_timeline_route_returns_bands_with_the_keys_the_browser_parses(
    app_and_client,
):
    """Field names, asserted literally.

    `dto.ts` parses these by exact key and a rename here fails as a
    `ContractError` in the browser with nothing failing in Python. Written out
    rather than compared against a constant so the two spellings are
    independent.
    """
    application, client = app_and_client
    project_id = await _project_with_dated_entity(application, client)

    response = await client.get(f"/api/projects/{project_id}/timeline")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"bands", "undated_count", "truncated"}
    assert set(body["bands"][0]) == {
        "entity_id",
        "name",
        "entity_type",
        "extent",
        "start",
        "end",
        "precision",
        "uncertainty",
    }


async def test_an_unknown_project_is_a_404(app_and_client):
    _application, client = app_and_client

    response = await client.get(f"/api/projects/{uuid4()}/timeline")

    assert response.status_code == 404


async def test_a_limit_past_the_cap_is_clamped_rather_than_refused(app_and_client):
    """The opposite of what `neighborhood` does with `depth`, deliberately.

    A depth past the bound asks for a *shape* of answer the server will not
    produce, and the caller needs to know its question was wrong. A limit past
    the bound asks for as much as possible, which is what the clamp returns --
    and `truncated` already says the timeline did not fit, so a 422 would tell
    the caller nothing the answer does not.
    """
    application, client = app_and_client
    project_id = await _project_with_dated_entity(application, client)

    response = await client.get(f"/api/projects/{project_id}/timeline?limit=100000")

    assert response.status_code == 200
