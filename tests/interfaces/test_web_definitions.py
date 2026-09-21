"""Entity definition routes exercised over ASGI."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from redstring import Entity, ExtractionMethod, Provenance

from research_team.composition import build_application as _build_application
from research_team.interfaces.web import create_app
from research_team.knowledge.application.entity_definitions import (
    Definition,
    DefinitionService,
)
from research_team.knowledge.application.graph_read import (
    GraphEntity,
    GraphRelationship,
    Neighborhood,
)
from research_team.knowledge.application.usages import Usage


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
async def app_and_client(db_path, fake_model):
    application = await _started(model=fake_model, db_path=db_path)
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=application.blob_store,
        topics=application.topic_readers,
        graphs=application.graphs,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield application, client
    await application.close()


async def _project_with_graph(application, client) -> tuple[str, dict]:
    created = await client.post("/api/projects", json={"name": f"graph-{uuid4()}"})
    assert created.status_code == 200
    project_id = created.json()["id"]
    tenant_id = UUID(project_id)

    store = await application.graphs.open(tenant_id)
    prandtl_id = uuid4()
    await store.upsert_entities(
        [
            Entity(
                id=prandtl_id,
                tenant_id=tenant_id,
                name="Ludwig Prandtl",
                normalized_name="ludwig prandtl",
                entity_type="person",
                provenance=Provenance(
                    observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                    extraction_method=ExtractionMethod.MANUAL,
                    confidence=1.0,
                ),
            )
        ]
    )
    return project_id, {"prandtl_id": prandtl_id}


# ---------------- entity definition ----------------
#
# `DefinitionService` (Task 9) is exercised here through fakes matching
# `tests/application/test_entity_definitions.py`s own -- these tests are
# about the routes status codes and view shape, not about grounding, which
# that suite already covers. Built over fakes rather than through
# `application.definition_readers`, deliberately kept that way after the
# composition wiring landed: reaching the real factory would put a graph
# store, a chunk store and an LLM adapter between these tests and the status
# code they are about. That the *composed* app answers rather than 503ing is
# a different question, asserted in
# `tests/integration/test_definition_wiring.py`.


class _FakeDefinitionGraph:
    """`GraphReadPort.neighborhood`, keyed by `str(entity_id)` the way the
    real port is -- enough for the route under test, nothing else."""

    def __init__(self, neighborhoods: dict) -> None:
        self._neighborhoods = neighborhoods

    async def find_entities(self, **kwargs):  # pragma: no cover - unused here
        raise NotImplementedError

    async def whole(self, **kwargs):  # pragma: no cover - unused here
        raise NotImplementedError

    async def neighborhood(self, entity_id: str, *, depth: int = 1):
        return self._neighborhoods.get(entity_id)


class _FakeDefinitionUsages:
    def __init__(self, by_entity: dict) -> None:
        self._by_entity = by_entity

    async def usages(self, entity_id, *, limit: int = 20):
        return self._by_entity.get(entity_id, [])[:limit]


class _FakeDefinitionCache:
    def __init__(self) -> None:
        self.rows: dict = {}

    async def get(self, entity_id):
        return self.rows.get(entity_id)

    async def put(self, entity_id, definition) -> None:
        self.rows[entity_id] = definition


class _FakeDefinitionModel:
    """Canned text and citations -- no live model call, matching every other
    test in this suite (`fake_model` for the chat turns, `FakeDefinitionModel`
    in `test_entity_definitions.py` for this same port).

    `replies` is consumed in call order, one per `generate`; once exhausted,
    further calls repeat the last reply. The stale-fallback test uses this to
    make the *second* call (the regeneration triggered by a stale cache hit)
    come back citing nothing, so `DefinitionService.define`s fallback is
    exercised rather than its ordinary success path.
    """

    _OK = json.dumps(
        {
            "text": "Acme is a supplier of widgets.",
            "citations": [{"source_id": "doc-1", "start": 0, "end": 14}],
        }
    )

    def __init__(self, replies: list[str] | None = None) -> None:
        self._replies = list(replies) if replies else [self._OK]

    @property
    def model_name(self) -> str:
        return "fake-model"

    async def generate(self, prompt: str) -> str:
        if len(self._replies) > 1:
            return self._replies.pop(0)
        return self._replies[0]


async def _ready(value):
    """`value`, as something awaitable.

    `definitions` is `Callable[[UUID], Awaitable[...]]` because building a
    real service opens a graph store; a fake that needs no opening still has
    to satisfy the shape."""
    return value


def _definition_service_client(cache, model=None):
    """A `create_app` wired with a real `DefinitionService` over fakes, plus
    the one project + entity id it can answer for.

    Returns an async context manager yielding `(client, project_id, entity_id,
    bare_id)`: `entity_id` has a passage and an edge to ground a definition
    in, `bare_id` has neither, matching `ACME`/`BARE` in
    `test_entity_definitions.py`.
    """

    @asynccontextmanager
    async def _make():
        entity_id = uuid4()
        bare_id = uuid4()
        other_id = uuid4()
        root = GraphEntity(entity_id=str(entity_id), name="Acme", entity_type="Organization")
        other = GraphEntity(
            entity_id=str(other_id), name="Widget Co", entity_type="Organization"
        )
        graph = _FakeDefinitionGraph(
            {
                str(entity_id): Neighborhood(
                    root=root,
                    entities=(other,),
                    relationships=(
                        GraphRelationship(
                            source_id=root.entity_id,
                            target_id=other.entity_id,
                            relationship_type="supplies",
                        ),
                    ),
                ),
                str(bare_id): Neighborhood(
                    root=GraphEntity(
                        entity_id=str(bare_id), name="Nobody", entity_type="Person"
                    ),
                    entities=(),
                    relationships=(),
                ),
            }
        )
        usages = _FakeDefinitionUsages(
            {
                entity_id: [
                    Usage(
                        source_id="doc-1",
                        start=0,
                        end=40,
                        text="Acme supplies widgets.",
                        score=1.0,
                    )
                ]
            }
        )
        service = DefinitionService(
            graph=graph, usages=usages, cache=cache, model=model or _FakeDefinitionModel()
        )
        application = await _started()
        api = create_app(
            application.service,
            application.feed,
            application.turns,
            corpus=application.corpus,
            blob_store=application.blob_store,
            topics=application.topic_readers,
            # A factory, matching `Application.definition_readers`: the
            # route binds a project before it can reach a service. These
            # fakes are project-agnostic, so one service answers for the one
            # project this fixture makes.
            definitions=lambda _project_id: _ready(service),
        )
        transport = ASGITransport(app=api)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/projects", json={"name": f"definitions-{uuid4()}"}
            )
            assert created.status_code == 200
            project_id = created.json()["id"]
            try:
                yield client, project_id, entity_id, bare_id
            finally:
                pass
        await application.close()

    return _make()


async def test_a_definition_is_returned_with_its_citations():
    async with _definition_service_client(_FakeDefinitionCache()) as (
        client,
        project_id,
        entity_id,
        _bare,
    ):
        response = await client.get(
            f"/api/projects/{project_id}/graph/entities/{entity_id}/definition"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["text"]
    assert body["citations"][0]["source_id"] == "doc-1"
    assert body["stale"] is False


async def test_a_stale_definition_whose_regeneration_fails_is_still_served_and_says_so():
    """A GET on a stale row regenerates (Task 9s contract), so this pins the
    fallback rather than an accident of ordering: what the reader sees when
    that regeneration comes back with nothing usable. Losing a definition
    the reader already saw because *this* refresh attempt failed is worse
    than showing the older text labelled `stale` -- see
    `DefinitionService.define`s docstring on the fallback.

    The models second reply cites nothing verifiable (`FakeDefinitionModel`
    consumes replies in order), which is what a real model can do when an
    edit removed the passages the citation used to land in. Fails if the
    fallback is dropped: without it this test would see `text: None`.
    """
    cache = _FakeDefinitionCache()
    model = _FakeDefinitionModel(
        replies=[
            _FakeDefinitionModel._OK,
            json.dumps({"text": "Acme is a company.", "citations": []}),
        ]
    )
    async with _definition_service_client(cache, model=model) as (
        client,
        project_id,
        entity_id,
        _bare,
    ):
        first = await client.get(
            f"/api/projects/{project_id}/graph/entities/{entity_id}/definition"
        )
        assert first.status_code == 200
        cached = cache.rows[entity_id]
        cache.rows[entity_id] = Definition(
            text=cached.text,
            citations=cached.citations,
            model=cached.model,
            generated_at=cached.generated_at,
            stale=True,
        )

        response = await client.get(
            f"/api/projects/{project_id}/graph/entities/{entity_id}/definition"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == first.json()["text"]
    assert body["stale"] is True


async def test_an_undefinable_entity_returns_200_with_a_null_text_not_404():
    """The entity exists -- `bare_id` is a real node in the fake graph -- and
    is merely undefinable today because it has no passages and no edges. A
    404 here would tell the browser the entity itself is missing, which is a
    different and wrong statement; see the ruling recorded in
    `progress.md` and `DefinitionService.define`s docstring."""
    async with _definition_service_client(_FakeDefinitionCache()) as (
        client,
        project_id,
        _entity,
        bare_id,
    ):
        response = await client.get(
            f"/api/projects/{project_id}/graph/entities/{bare_id}/definition"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["text"] is None
    assert body["citations"] == []


async def test_definition_route_503s_when_no_definition_service_is_configured(app_and_client):
    """An app built without `definitions` still answers 503, not 500.

    No longer the shipping state -- `web.py` passes
    `Application.definition_readers` now -- but every fixture in this file
    except `_definition_service_client` builds an app without it, and the
    honest answer for those is "this build cannot do that", not a traceback.
    503, not 404: the project and entity may both be real."""
    application, client = app_and_client
    project_id, ids = await _project_with_graph(application, client)

    response = await client.get(
        f"/api/projects/{project_id}/graph/entities/{ids['prandtl_id']}/definition"
    )

    assert response.status_code == 503
