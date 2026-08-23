"""The catalog routes, composed rather than faked.

Composed for `test_ontology_routes.py`'s reason: a build that never constructs
a `CatalogService` answers `GET .../catalog` with empty sections and no error,
and a fixture handing the route a hand-built service cannot tell that build
from a working one. Every assertion here is on the payload's contents.

**The composition below is not `Application.catalog`** -- that field does not
exist yet. Composition wiring is Task 10's job (`composition.py`), which also
registers `CatalogFeatureProjection` with the application's own projection
set. This module builds the same real objects (`TypePluralityGrouper`,
`SeededArtProvider`, `CatalogFeatureStore`, `CatalogFeatureProjection`,
`EventStoreCatalogFeatureRecorder`) directly over the composed application's
event store, following `CurriculumService`'s own precedent in
`test_curriculum_routes.py`: `curriculum` is built the same way, standalone,
because it composes nothing the application owns. When Task 10 lands, this
fixture's hand-assembly and `composition.py`'s should agree -- the whole point
of composing real objects here rather than fakes.
"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from eventsource import (
    InMemoryEventBus,
    SQLCheckpointRepository,
    SQLDLQRepository,
    create_async_engine,
)
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.application.subscriptions import SubscriptionConfig, SubscriptionManager
from httpx import ASGITransport, AsyncClient
from redstring import Entity, ExtractionMethod, Provenance, Relationship

from research_team.application.course_catalog import CatalogService
from research_team.application.curriculum import CurriculumService
from research_team.composition import build_application
from research_team.infrastructure.knowledge.catalog_recorder import (
    EventStoreCatalogFeatureRecorder,
)
from research_team.infrastructure.knowledge.seeded_art import SeededArtProvider
from research_team.infrastructure.knowledge.type_plurality_grouper import TypePluralityGrouper
from research_team.infrastructure.persistence.read_models import (
    CatalogFeatureProjection,
    CatalogFeatureStore,
)
from research_team.interfaces.web import create_app

pytestmark = pytest.mark.asyncio


class _NoBlurbs:
    """A `BlurbCachePort` that has never cached anything. Blurb generation
    is out of scope for this feature (task-14's own note: the trigger is a
    deliberate gap in this increment), so every route in this module renders
    candidates with `blurb: None`."""

    async def get(self, project_id, slug):
        return None

    async def put(self, *args, **kwargs) -> None:  # pragma: no cover -- never called here
        raise AssertionError("nothing in this module generates a blurb")


class _CatalogFeatures:
    """The read side (`CatalogFeatureStore`) and the write side
    (`EventStoreCatalogFeatureRecorder`) of one project's featuring, plus the
    projection that keeps them level with the log -- assembled the same way
    `OntologyRunner`/`MediaProposalRunner` are, scoped to
    `CatalogFeatureProjection`'s one aggregate type.
    """

    def __init__(self, store: SQLiteEventStore, bus, db_path: str) -> None:
        self._store = store
        self._bus = bus
        self._db_path = db_path
        self.features: CatalogFeatureStore | None = None
        self._manager: SubscriptionManager | None = None
        self._subscription = None

    async def start(self) -> None:
        await self._store.current_position()
        engine = create_async_engine(f"sqlite+aiosqlite:///{self._db_path}")
        checkpoints = SQLCheckpointRepository(engine)
        dlq = SQLDLQRepository(engine)
        self.features = await CatalogFeatureStore.open(self._db_path)
        projection = CatalogFeatureProjection(self.features, checkpoints, dlq)
        self._manager = SubscriptionManager(self._store, self._bus, checkpoints, dlq_repo=dlq)
        self._subscription = await self._manager.subscribe(
            projection, SubscriptionConfig(start_from="checkpoint")
        )
        results = await self._manager.start()
        failures = {name: err for name, err in results.items() if err is not None}
        if failures:
            raise RuntimeError(f"the catalog feature projection failed to start: {failures}")

    def recorder(self, project_id: UUID) -> EventStoreCatalogFeatureRecorder:
        return EventStoreCatalogFeatureRecorder(self._store, self._bus, project_id)

    async def caught_up(self, timeout: float = 10.0) -> None:
        if self._manager is None:
            return
        target = await self._store.current_position()
        if target is None:
            return
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if self._subscription.last_processed_position is not None and (
                self._subscription.last_processed_position >= target
            ):
                return
            await asyncio.sleep(0.01)
        raise TimeoutError("the catalog feature projection did not catch up in time")

    async def close(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
        if self.features is not None:
            await self.features.close()


@pytest.fixture
async def app_and_client(db_path, fake_model):
    application = build_application(model=fake_model, db_path=db_path)
    await application.start()
    curriculum = CurriculumService()
    catalog = CatalogService(
        grouper=TypePluralityGrouper(), art=SeededArtProvider(), blurbs=_NoBlurbs()
    )
    # Its own `SQLiteEventStore` and `InMemoryEventBus`, not the application's.
    # `Application` exposes no field for either -- both live inside
    # `composition.py`'s closure (`repository.store`/`.publisher`), reachable
    # only from inside that module. That is fine here: catalog events are
    # appended under their own aggregate type (`CATALOG_AGGREGATE_TYPE`) on
    # their own stream, so this recorder and this projection only ever need
    # to agree *with each other*, over the same sqlite file the rest of the
    # application already writes to. Task 10 will thread the application's
    # own store/bus through instead, once `composition.py` exposes them.
    store = SQLiteEventStore(db_path)
    bus = InMemoryEventBus()
    features = _CatalogFeatures(store, bus, db_path)
    await features.start()
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=application.blob_store,
        graphs=application.graphs,
        curriculum=curriculum,
        catalog=catalog,
        catalog_features=features.features,
        catalog_recorder=features.recorder,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(
            application=application, client=client, catalog=catalog, features=features
        )
    await features.close()
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
    created = await client.post("/api/projects", json={"name": f"catalog-{uuid4()}"})
    assert created.status_code == 200
    return created.json()["id"]


async def _seed_two_clusters(application, project_id: str) -> None:
    """Two four-cliques joined by nothing: an unambiguous two-area graph.

    Follows `test_curriculum_routes.py`'s `_seed_two_clusters` exactly -- what
    is under test here is the catalog route, not extraction, and seeding
    through `GraphStore.upsert_entities` is this repository's own shortcut for
    that split.
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


async def test_the_catalog_has_a_non_empty_hero_and_a_category(app_and_client):
    """The count is the assertion, not the status -- a build that never
    constructs `CatalogService` answers this route 200 with empty sections."""
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(application, project_id)

    body = (await client.get(f"/api/projects/{project_id}/catalog")).json()

    assert len(body["hero"]) > 0
    assert len(body["categories"]) >= 1


async def test_an_unwired_catalog_is_503(app_and_client):
    api = create_app(
        app_and_client.application.service,
        app_and_client.application.feed,
        app_and_client.application.turns,
        graphs=app_and_client.application.graphs,
    )
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        project_id = await _new_project(client)
        response = await client.get(f"/api/projects/{project_id}/catalog")

    assert response.status_code == 503


async def test_an_unknown_project_is_a_404(app_and_client):
    response = await app_and_client.client.get(f"/api/projects/{uuid4()}/catalog")

    assert response.status_code == 404


async def test_featuring_puts_a_candidate_first_in_hero(app_and_client):
    """The persisted decision, not merely the write's own status.

    Awaits `caught_up()` between the POST and the GET: the write appends an
    event and the read runs off the projection it feeds, so a GET issued
    before the projection has caught up would be racing its own write.
    """
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(application, project_id)
    before = (await client.get(f"/api/projects/{project_id}/catalog")).json()
    slug = before["hero"][-1]["slug"]

    response = await client.post(
        f"/api/projects/{project_id}/catalog/{slug}/feature", json={"rank": 0}
    )
    assert response.status_code == 200
    await app_and_client.features.caught_up()

    after = (await client.get(f"/api/projects/{project_id}/catalog")).json()
    assert after["hero"][0]["slug"] == slug


async def test_unfeaturing_restores_the_derived_order(app_and_client):
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(application, project_id)
    before = (await client.get(f"/api/projects/{project_id}/catalog")).json()
    original_order = [c["slug"] for c in before["hero"]]
    slug = original_order[-1]

    await client.post(f"/api/projects/{project_id}/catalog/{slug}/feature", json={"rank": 0})
    await app_and_client.features.caught_up()
    featured = (await client.get(f"/api/projects/{project_id}/catalog")).json()
    assert [c["slug"] for c in featured["hero"]] != original_order

    await client.post(f"/api/projects/{project_id}/catalog/{slug}/unfeature")
    await app_and_client.features.caught_up()

    restored = (await client.get(f"/api/projects/{project_id}/catalog")).json()
    assert [c["slug"] for c in restored["hero"]] == original_order


async def test_an_unknown_category_is_a_404(app_and_client):
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(application, project_id)

    response = await client.get(f"/api/projects/{project_id}/catalog/categories/nope")

    assert response.status_code == 404


async def test_a_category_page_lists_a_candidate_promoted_to_hero(app_and_client):
    """The R9 regression test.

    Built from `catalog.sections.filed` alone, this fails: `filed` holds only
    leftover candidates, and a category page built from it silently drops the
    exact candidate this test features -- the one prominent enough to have
    been promoted out of it. Built from `catalog.all_candidates`, as ruling R9
    requires, it passes.
    """
    application, client = app_and_client.application, app_and_client.client
    project_id = await _new_project(client)
    await _seed_two_clusters(application, project_id)
    before = (await client.get(f"/api/projects/{project_id}/catalog")).json()
    # Every seeded entity is `entity_type="concept"`, so `TypePluralityGrouper`
    # puts both areas in one category -- there is exactly one to assert on.
    (category_key,) = before["categories"]
    slug = before["hero"][0]["slug"]

    await client.post(f"/api/projects/{project_id}/catalog/{slug}/feature", json={"rank": 0})
    await app_and_client.features.caught_up()

    page = (
        await client.get(f"/api/projects/{project_id}/catalog/categories/{category_key}")
    ).json()

    assert slug in {c["slug"] for c in page["candidates"]}
