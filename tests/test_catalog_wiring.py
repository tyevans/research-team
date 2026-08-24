"""The test CLAUDE.md asks for: both ends of every port, over real data.

A stub on one side and a unit test on the other proves the halves work and
cannot prove they meet. The co-mention channel shipped exactly that way and
produced nothing for a whole feature, with every piece tested. This drives a
real ingest through `Application.catalog`, `.catalog_features` and
`.catalog_recorder` -- `composition.py`'s own wiring, not a hand-assembled
stand-in -- so a regression in that wiring (the projection dropped from the
subscription set, the recorder pointed at a different store than the
projection reads, the grouper never reaching the catalog) fails here rather
than only in a fixture that happens to compose the pieces correctly itself.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from redstring import Entity, ExtractionMethod, Provenance, Relationship

from research_team.application.curriculum import CurriculumService
from research_team.composition import build_application
from research_team.interfaces.web import create_app

pytestmark = pytest.mark.asyncio


def _entity(tenant_id: UUID, name: str, entity_type: str) -> Entity:
    return Entity(
        id=uuid4(),
        tenant_id=tenant_id,
        name=name,
        normalized_name=name.lower(),
        entity_type=entity_type,
        provenance=Provenance(
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            extraction_method=ExtractionMethod.MANUAL,
            confidence=1.0,
        ),
    )


async def _seed_two_categories(application, project_id: str) -> None:
    """Two four-cliques joined by nothing, of two different entity types.

    `test_catalog_routes.py`'s own fixture seeds both clusters as
    `entity_type="concept"`, which is fine for asserting a non-empty hero but
    cannot catch the grouper going unwired -- `TypePluralityGrouper` keys a
    category on the commonest anchor type, so two same-typed clusters land in
    one category whether or not the grouper is threaded through at all.
    Different types is the point here: it is what separates a working
    grouper from every candidate falling into one bucket (or
    "unclassified").
    """
    tenant_id = UUID(project_id)
    store = await application.graphs.open(tenant_id)
    groups = [
        [_entity(tenant_id, f"Person {i}", "person") for i in range(4)],
        [_entity(tenant_id, f"Place {i}", "location") for i in range(4)],
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


async def test_a_catalog_over_a_real_ingest_has_cards_in_more_than_one_category(
    db_path, fake_model
):
    """Drives a real ingest through a composed application and asserts on the
    catalog's *contents*.

    The category count is the assertion that matters. With the grouper
    unwired -- or with `CatalogFeatureProjection` dropped from the
    subscription set, which leaves `catalog_features` perpetually empty but
    changes nothing about grouping -- every candidate can still land in a
    single bucket and the catalog still renders with a 200 and a non-empty
    hero. `>= 2` distinct category keys is what a working grouper produces
    over this seed and a silent default cannot.

    Would fail before this task with `AttributeError: 'Application' object
    has no attribute 'catalog'` -- there was no code path to reach an
    assertion at all.
    """
    application = build_application(model=fake_model, db_path=db_path)
    await application.start()
    curriculum = CurriculumService()
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=application.blob_store,
        graphs=application.graphs,
        curriculum=curriculum,
        catalog=application.catalog,
        catalog_features=lambda: application.catalog_features,
        catalog_recorder=application.catalog_recorder,
    )
    transport = ASGITransport(app=api)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/projects", json={"name": f"catalog-wiring-{uuid4()}"}
            )
            assert created.status_code == 200
            project_id = created.json()["id"]

            await _seed_two_categories(application, project_id)

            response = await client.get(f"/api/projects/{project_id}/catalog?unnamed=true")
            assert response.status_code == 200
            body = response.json()

            # The feature round-trip: this is what the step-5 check in this
            # task's report drops `CatalogFeatureProjection` to prove.
            # Featuring the second-ranked candidate with rank 0 appends
            # `CourseFeatured` through `application.catalog_recorder`; the GET
            # below reads through `application.catalog_features`, which only
            # reflects that append once `CatalogFeatureProjection` has
            # replayed it. Without the projection registered, `featured_for`
            # stays permanently empty and this candidate would never move to
            # the front of `hero`. Only two areas exist over this seed (one
            # four-clique each), so both land in `hero` and `filed` is empty
            # -- `hero[-1]`, not `filed`, is the candidate to move, matching
            # `test_catalog_routes.py::test_featuring_puts_a_candidate_first_in_hero`.
            candidate_slug = body["hero"][-1]["slug"]

            feature_response = await client.post(
                f"/api/projects/{project_id}/catalog/{candidate_slug}/feature",
                json={"rank": 0},
            )
            assert feature_response.status_code == 200
            await application.catalog_caught_up()

            after = (
                await client.get(f"/api/projects/{project_id}/catalog?unnamed=true")
            ).json()
    finally:
        await application.close()

    all_candidates = [
        *body["hero"],
        *body["highlights"],
        *(c for cat in body["filed"] for c in cat["candidates"]),
    ]
    assert len(all_candidates) > 0
    assert len(all_candidates[0]["anchors"]) > 0
    assert len(body["categories"]) >= 2
    assert after["hero"][0]["slug"] == candidate_slug


async def test_the_catalog_answers_when_the_app_is_built_before_start(db_path, fake_model):
    """The ordering `web.py` actually uses: `create_app` first, `start()` after.

    Every other test in this file and in `tests/interfaces/test_catalog_routes.py`
    calls `application.start()` *before* `create_app`, so the store they hand
    the factory is already open. `web.py` cannot do that -- `start()` opens an
    aiosqlite connection and has to run under uvicorn's loop, which is why it
    lives in the lifespan -- so the entrypoint reads `catalog_features` while
    it is still `None` and the factory captures that `None` for the life of
    the process. Nothing else here can see it: the shape of the arrange phase
    is what hides the defect, which is the general failure CLAUDE.md names
    under "Read models".

    So this test runs the app's own lifespan rather than starting the
    application by hand, and asserts on the catalog's *contents*. Before the
    fix it fails: `create_app` treats the getter as a store and the route
    answers 500 (and answered 503 in the running server, where the entrypoint
    passed the `None` itself).
    """
    application = build_application(model=fake_model, db_path=db_path)

    @asynccontextmanager
    async def lifespan(_app):
        await application.start()
        yield
        await application.close()

    curriculum = CurriculumService()
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        lifespan,
        corpus=application.corpus,
        blob_store=application.blob_store,
        graphs=application.graphs,
        curriculum=curriculum,
        catalog=application.catalog,
        # A getter, not the value: at this point in the ordering the value is
        # `None`. This mirrors `web.py` and is the line the fix is about.
        catalog_features=lambda: application.catalog_features,
        catalog_recorder=application.catalog_recorder,
    )
    transport = ASGITransport(app=api)
    # Starlette's own lifespan runner, not a hand-rolled `async with
    # lifespan(api)`: this is the call uvicorn makes, so a factory that
    # dropped the argument fails here too.
    async with (
        api.router.lifespan_context(api),
        AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        name = f"catalog-late-{uuid4()}"
        created = await client.post("/api/projects", json={"name": name})
        assert created.status_code == 200
        project_id = created.json()["id"]

        await _seed_two_categories(application, project_id)

        response = await client.get(f"/api/projects/{project_id}/catalog?unnamed=true")
        assert response.status_code == 200, response.text
        body = response.json()

    candidates = [
        *body["hero"],
        *body["highlights"],
        *(c for cat in body["filed"] for c in cat["candidates"]),
    ]
    assert len(candidates) > 0
    assert len(candidates[0]["anchors"]) > 0
    assert len(body["categories"]) >= 2
