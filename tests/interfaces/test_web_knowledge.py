"""Knowledge graph, usages, and entity definition routes exercised over ASGI."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from redstring import (
    DatePrecision,
    Entity,
    ExtractionMethod,
    Provenance,
    Relationship,
    StoredChunk,
    TemporalExtent,
)

from research_team.application.entity_definitions import Definition, DefinitionService
from research_team.application.graph_read import (
    MAX_GRAPH_NODES,
    GraphEntity,
    GraphRelationship,
    Neighborhood,
)
from research_team.application.usages import Usage
from research_team.composition import build_application as _build_application
from research_team.interfaces.web import create_app


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


@pytest.fixture
def client(app_and_client):
    return app_and_client[1]


# ---------------- graph ----------------


def _graph_entity(
    entity_id,
    tenant_id,
    name: str,
    entity_type: str = "person",
    *,
    temporal: TemporalExtent | None = None,
):
    return Entity(
        id=entity_id,
        tenant_id=tenant_id,
        name=name,
        normalized_name=name.lower(),
        entity_type=entity_type,
        # Fixed rather than `datetime.now`: no route under test reads
        # `observed_at`, and a moving value in a fixture is a difference that
        # shows up in a failure diff without meaning anything.
        provenance=Provenance(
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            extraction_method=ExtractionMethod.MANUAL,
            confidence=1.0,
        ),
        temporal=temporal,
    )


def _year(year: int) -> TemporalExtent:
    return TemporalExtent(
        start_date=datetime(year, 1, 1, tzinfo=UTC),
        end_date=datetime(year, 12, 31, tzinfo=UTC),
        precision=DatePrecision.YEAR,
    )


def _month(year: int, month: int) -> TemporalExtent:
    return TemporalExtent(
        start_date=datetime(year, month, 1, tzinfo=UTC),
        precision=DatePrecision.MONTH,
    )


def _graph_relationship(
    relationship_id, tenant_id, source_id, target_id, relationship_type: str
):
    return Relationship(
        id=relationship_id,
        tenant_id=tenant_id,
        source_entity_id=source_id,
        target_entity_id=target_id,
        relationship_type=relationship_type,
        confidence=1.0,
    )


async def _project_with_graph(application, client) -> tuple[str, dict]:
    """A project holding two linked entities in its graph store, seeded directly.

    Seeded through `GraphStore.upsert_entities`/`upsert_relationships` --
    the same shortcut `test_graph_read.py` takes -- rather than through
    `remember`, because what is under test is the read route, not extraction.
    """
    created = await client.post("/api/projects", json={"name": f"graph-{uuid4()}"})
    assert created.status_code == 200
    project_id = created.json()["id"]
    tenant_id = UUID(project_id)

    store = await application.graphs.open(tenant_id)
    prandtl_id, karman_id = uuid4(), uuid4()
    await store.upsert_entities(
        [
            _graph_entity(prandtl_id, tenant_id, "Ludwig Prandtl"),
            _graph_entity(karman_id, tenant_id, "Theodore von Kármán"),
        ]
    )
    await store.upsert_relationships(
        [_graph_relationship(uuid4(), tenant_id, prandtl_id, karman_id, "advised")]
    )
    return project_id, {"prandtl_id": prandtl_id, "karman_id": karman_id}


async def test_listing_graph_entities_finds_what_was_seeded(app_and_client):
    application, client = app_and_client
    project_id, ids = await _project_with_graph(application, client)

    response = await client.get(f"/api/projects/{project_id}/graph/entities")

    assert response.status_code == 200
    body = response.json()
    assert {row["name"] for row in body["entities"]} == {
        "Ludwig Prandtl",
        "Theodore von Kármán",
    }
    assert {row["entity_id"] for row in body["entities"]} == {
        str(ids["prandtl_id"]),
        str(ids["karman_id"]),
    }
    assert body["next_after"] is None


async def test_listing_graph_entities_filters_by_name(app_and_client):
    """`name` matches case-insensitively as a substring of the entity's
    display name -- the same give `RedstringKnowledge.search` gives an
    agent's free text, because a human typing a partial name into a search
    box needs no less. `GraphStore.find_entities(name=...)` alone would
    require the full normalized name; the route must not be held to that.
    """
    application, client = app_and_client
    project_id, ids = await _project_with_graph(application, client)

    response = await client.get(
        f"/api/projects/{project_id}/graph/entities", params={"name": "prandtl"}
    )

    assert response.status_code == 200
    body = response.json()
    assert [row["entity_id"] for row in body["entities"]] == [str(ids["prandtl_id"])]


async def test_the_first_graph_entity_listing_for_an_untouched_project_works(client):
    """`_project_with_graph` seeds through `graphs.open`, so nothing here can.

    CLAUDE.md's fixture rule: a fixture that seeds through the same call the
    code under test depends on cannot see that dependency go missing. Every
    other test in this section arranges through `_project_with_graph`, which
    calls `application.graphs.open` -- the very call `_graph_reader` is
    responsible for making. From those tests' point of view the project is
    always open, so a route that stopped opening it would keep passing.

    The failure this guards against is not a wrong answer, it is a 503 on the
    *first* request for any newly-touched project and a 200 on every request
    after it, in the same process. `CLAUDE.md` records that shipping once, on
    the entity-definitions work, and it reads as flakiness.

    Three sibling route families already carry this guard --
    `tests/interfaces/test_curriculum_routes.py`
    (`test_the_first_request_for_an_untouched_project_works`),
    `test_document_routes.py:650`, and
    `test_reading_the_whole_graph_of_an_empty_project_is_not_an_error` below.
    The two graph-entity families never got theirs.

    **This one cannot be proved red against today's tree, and saying so is
    the honest version.** `_graph_reader` reads exactly one per-project
    resource -- the store `graphs.open` returns -- so there is no "fetched
    before open" ordering available to get wrong in it, unlike `_usage_reader`
    below. The guard is here for the next resource `ProjectGraphs.open` builds
    (`chunks`, `co_mentions`, `card_vectors` and `cards` are all already in
    that set) reaching this route ahead of the open, which is the change that
    would otherwise ship silently.
    """
    created = await client.post("/api/projects", json={"name": f"graph-{uuid4()}"})
    project_id = created.json()["id"]

    response = await client.get(f"/api/projects/{project_id}/graph/entities")

    assert response.status_code == 200, "a 503 here is the route reading before it opens"
    assert response.json()["entities"] == []


async def test_the_first_neighborhood_request_for_an_untouched_project_works(client):
    """The neighborhood route, from a project nothing has opened.

    404 rather than 200 is the right answer -- the entity asked for does not
    exist -- and 404 rather than **503** is what this asserts. The distinction
    matters because 503 is what a route that reached for a per-project store
    before `graphs.open` built it would answer, and only on the first request
    for that project.

    Asked with a random entity id deliberately: seeding one would need
    `graphs.open`, which is the call being tested for.

    Not provable red today, for the reason the listing guard above states.
    """
    created = await client.post("/api/projects", json={"name": f"graph-{uuid4()}"})
    project_id = created.json()["id"]

    response = await client.get(
        f"/api/projects/{project_id}/graph/entities/{uuid4()}/neighborhood"
    )

    assert response.status_code == 404, "a 503 here is the route reading before it opens"


async def test_a_neighborhood_carries_root_entities_and_relationships(app_and_client):
    application, client = app_and_client
    project_id, ids = await _project_with_graph(application, client)

    response = await client.get(
        f"/api/projects/{project_id}/graph/entities/{ids['prandtl_id']}/neighborhood"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["root"]["entity_id"] == str(ids["prandtl_id"])
    assert [row["entity_id"] for row in body["entities"]] == [str(ids["karman_id"])]
    assert body["relationships"] == [
        {
            "source_id": str(ids["prandtl_id"]),
            "target_id": str(ids["karman_id"]),
            "relationship_type": "advised",
            "inferred": False,
            "derivation": None,
        }
    ]
    assert "inferred_truncated" not in body


async def test_asking_past_the_depth_cap_is_refused(app_and_client):
    """A caller asking for depth 5 has misunderstood the API; quietly handing
    back depth `MAX_NEIGHBORHOOD_DEPTH` would hide that from them. The port
    underneath still clamps -- see `test_depth_is_clamped_by_the_port_not_only_the_route`
    -- but that is a different guarantee for a different caller: the port
    protects any future in-process caller, this 422 tells an HTTP client it
    was wrong.
    """
    application, client = app_and_client
    project_id, ids = await _project_with_graph(application, client)

    response = await client.get(
        f"/api/projects/{project_id}/graph/entities/{ids['prandtl_id']}/neighborhood",
        params={"depth": 5},
    )

    assert response.status_code == 422
    assert "depth" in response.json()["detail"]


async def test_a_malformed_after_cursor_is_a_422_not_a_500(app_and_client):
    """`after` arrives straight off the query string. `neighborhood`'s
    `entity_id` handles the same kind of caller mistake with a 404; this
    route should not let an unparseable UUID reach `UUID(after)` inside the
    reader and blow up as an unhandled 500.
    """
    application, client = app_and_client
    project_id, _ids = await _project_with_graph(application, client)

    response = await client.get(
        f"/api/projects/{project_id}/graph/entities", params={"after": "not-a-uuid"}
    )

    assert response.status_code == 422


async def test_an_unknown_entity_is_a_404(app_and_client):
    application, client = app_and_client
    project_id, _ids = await _project_with_graph(application, client)

    response = await client.get(
        f"/api/projects/{project_id}/graph/entities/{uuid4()}/neighborhood"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == f"no such entity in project {project_id}"


async def test_reading_the_whole_graph_returns_every_entity_and_edge(app_and_client):
    """What the browser opens with, before a reader knows a name to search
    for: the graph entire, wired, in one response."""
    application, client = app_and_client
    project_id, ids = await _project_with_graph(application, client)

    response = await client.get(f"/api/projects/{project_id}/graph")

    assert response.status_code == 200
    body = response.json()
    assert {row["entity_id"] for row in body["entities"]} == {
        str(ids["prandtl_id"]),
        str(ids["karman_id"]),
    }
    assert body["relationships"] == [
        {
            "source_id": str(ids["prandtl_id"]),
            "target_id": str(ids["karman_id"]),
            "relationship_type": "advised",
            "inferred": False,
            "derivation": None,
        }
    ]
    assert body["truncated"] is False


async def test_a_dated_pair_in_the_graph_produces_a_temporal_edge(app_and_client):
    """The wire shape Task 7 onward depends on: `temporal` on entities that
    have it, `inferred`/`derivation` on the edge inference produced rather
    than a stored one, and `inferred_truncated` on the body -- all snake_case,
    all pass-through from the port so there is nothing here to disagree with
    `ProjectGraphReader` about."""
    application, client = app_and_client
    created = await client.post("/api/projects", json={"name": f"graph-{uuid4()}"})
    assert created.status_code == 200
    project_id = created.json()["id"]
    tenant_id = UUID(project_id)

    store = await application.graphs.open(tenant_id)
    era_id, event_id = uuid4(), uuid4()
    await store.upsert_entities(
        [
            _graph_entity(era_id, tenant_id, "The Weimar Republic", temporal=_year(1923)),
            _graph_entity(
                event_id, tenant_id, "Hyperinflation Peaks", temporal=_month(1923, 11)
            ),
        ]
    )

    response = await client.get(f"/api/projects/{project_id}/graph")

    assert response.status_code == 200
    body = response.json()
    entities_by_id = {row["entity_id"]: row for row in body["entities"]}
    assert entities_by_id[str(era_id)]["temporal"] is not None
    assert entities_by_id[str(event_id)]["temporal"] is not None
    assert len(body["relationships"]) == 1
    edge = body["relationships"][0]
    assert edge["inferred"] is True
    assert edge["derivation"] is not None
    assert body["inferred_truncated"] is False


async def test_reading_the_whole_graph_of_an_empty_project_is_not_an_error(
    app_and_client,
):
    """A project with nothing extracted yet is what most first visits to the
    research page hit; it answers with an empty graph, not a failure."""
    _application, client = app_and_client
    created = await client.post("/api/projects", json={"name": f"graph-{uuid4()}"})
    project_id = created.json()["id"]

    response = await client.get(f"/api/projects/{project_id}/graph")

    assert response.status_code == 200
    assert response.json() == {
        "entities": [],
        "relationships": [],
        "truncated": False,
        "inferred_truncated": False,
    }


async def test_an_oversized_limit_is_clamped_rather_than_refused(app_and_client):
    """The opposite of `neighborhood`'s treatment of `depth`, deliberately:
    "as much as possible" is a question this route can answer, and
    `truncated` in the body is how it reports what that came to."""
    application, client = app_and_client
    project_id, _ids = await _project_with_graph(application, client)

    response = await client.get(
        f"/api/projects/{project_id}/graph", params={"limit": MAX_GRAPH_NODES + 1_000}
    )

    assert response.status_code == 200
    assert len(response.json()["entities"]) == 2


async def test_a_truncated_graph_says_so(app_and_client):
    """A client cannot tell a complete graph from the first page of a bigger
    one by counting, so the flag has to travel with the body."""
    application, client = app_and_client
    project_id, _ids = await _project_with_graph(application, client)

    response = await client.get(f"/api/projects/{project_id}/graph", params={"limit": 1})

    assert response.status_code == 200
    body = response.json()
    assert len(body["entities"]) == 1
    assert body["truncated"] is True
    # The one surviving entity's edge had its other end cut off, so there is
    # nothing left to draw a line between.
    assert body["relationships"] == []


async def test_an_unknown_project_is_a_404_on_every_graph_route(client):
    missing = uuid4()

    whole = await client.get(f"/api/projects/{missing}/graph")
    listing = await client.get(f"/api/projects/{missing}/graph/entities")
    neighborhood = await client.get(
        f"/api/projects/{missing}/graph/entities/{uuid4()}/neighborhood"
    )

    assert whole.status_code == 404
    assert whole.json()["detail"] == f"no project {missing}"
    assert listing.status_code == 404
    assert listing.json()["detail"] == f"no project {missing}"
    assert neighborhood.status_code == 404
    assert neighborhood.json()["detail"] == f"no project {missing}"


async def test_a_404_on_an_unknown_project_does_not_cache_a_graph_store(app_and_client):
    """`_graph_reader` opens and caches a store as a side effect of building
    a reader -- `graphs.open` is the first call that talks to Neo4j and
    `ProjectGraphs` never evicts except on `close`/`close_all`. Calling it
    for a project that turns out not to exist would grow `graphs._stores`
    without bound for every caller that walks unknown ids, and would pay a
    schema round trip per garbage id behind Neo4j. The 404 must be decided
    before the reader is ever built.
    """
    application, client = app_and_client
    missing = uuid4()

    response = await client.get(f"/api/projects/{missing}/graph/entities")

    assert response.status_code == 404
    assert missing not in application.graphs._stores


async def test_graph_routes_503_when_no_graph_reader_is_configured(app_and_client):
    """A build with no graph read model configured is a valid thing to serve
    -- see `_reader`'s own docstring for the reasoning -- so the caller needs
    to know the server cannot answer, not that the project has no graph.
    """
    application, client = app_and_client
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=application.blob_store,
        topics=application.topic_readers,
        graphs=None,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as unwired:
        project_id, ids = await _project_with_graph(application, client)

        listing = await unwired.get(f"/api/projects/{project_id}/graph/entities")
        neighborhood = await unwired.get(
            f"/api/projects/{project_id}/graph/entities/{ids['prandtl_id']}/neighborhood"
        )

    assert listing.status_code == 503
    assert neighborhood.status_code == 503


# ---------------- graph usages ----------------


async def _project_with_a_usage(application, client) -> tuple[str, UUID]:
    """A project holding one entity and one chunk that names it.

    Seeded straight through `GraphStore.upsert_entities` and
    `ChunkStore.upsert_many`, the same shortcut `_project_with_graph` and
    `test_usage_reader.py` take -- what is under test is the route, not
    chunking or extraction.
    """
    created = await client.post("/api/projects", json={"name": f"usages-{uuid4()}"})
    assert created.status_code == 200
    project_id = created.json()["id"]
    tenant_id = UUID(project_id)

    store = await application.graphs.open(tenant_id)
    entity_id = uuid4()
    await store.upsert_entities([_graph_entity(entity_id, tenant_id, "Acme Corp")])

    chunk_store = application.graphs.chunks(tenant_id)
    text = "Acme Corp builds rockets in Texas."
    await chunk_store.upsert_many(
        [
            StoredChunk(
                tenant_id=tenant_id,
                source_id="doc-1",
                text=text,
                chunk_index=0,
                start_char=0,
                end_char=len(text),
            )
        ]
    )
    return project_id, entity_id


async def test_usages_returns_passages_with_offsets(app_and_client):
    application, client = app_and_client
    project_id, entity_id = await _project_with_a_usage(application, client)

    response = await client.get(
        f"/api/projects/{project_id}/graph/entities/{entity_id}/usages"
    )

    assert response.status_code == 200
    first = response.json()["usages"][0]
    assert first["source_id"] and first["end"] > first["start"]


async def test_the_first_usages_request_for_an_untouched_project_works(client):
    """The usages route, from a project nothing has opened.

    This is the closest of the three to the incident CLAUDE.md records, and
    `_usage_reader`'s own docstring names it: the chunk store this route reads
    is *built inside* `graphs.open`, so asking `graphs.chunks` first gets
    `None` and a 503 that only means "nobody happened to ask for the graph
    yet". `_project_with_a_usage` opens the project to seed it, which is
    exactly why no test in this section could see that.

    An untouched project has no passages, so an empty list is the answer; the
    assertion that carries the weight is the status code.

    **Proved red on 2026-08-29** by swapping the two lines in `_usage_reader`
    so `graphs.chunks` is called before `graphs.open` -- 1 failed, 5 passed
    over `-k "untouched or usages"`. The one that failed is this one; every
    other usages test stayed green, which is the whole of CLAUDE.md's fixture
    rule in one run.
    """
    created = await client.post("/api/projects", json={"name": f"usages-{uuid4()}"})
    project_id = created.json()["id"]

    response = await client.get(f"/api/projects/{project_id}/graph/entities/{uuid4()}/usages")

    assert response.status_code == 200, "a 503 here is the route reading before it opens"
    assert response.json()["usages"] == []


async def test_usages_for_an_unknown_project_is_a_404(client):
    response = await client.get(f"/api/projects/{uuid4()}/graph/entities/{uuid4()}/usages")

    assert response.status_code == 404


async def test_a_usages_limit_above_the_cap_is_refused_rather_than_clamped(app_and_client):
    """A caller asking for 10,000 passages has misunderstood the endpoint,
    and silently handing back `MAX_USAGES` would teach them it worked."""
    application, client = app_and_client
    project_id, entity_id = await _project_with_a_usage(application, client)

    response = await client.get(
        f"/api/projects/{project_id}/graph/entities/{entity_id}/usages?limit=10000"
    )

    assert response.status_code == 422


# ---------------- entity definition ----------------
#
# `DefinitionService` (Task 9) is exercised here through fakes matching
# `tests/application/test_entity_definitions.py`'s own -- these tests are
# about the route's status codes and view shape, not about grounding, which
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
    come back citing nothing, so `DefinitionService.define`'s fallback is
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
    """A GET on a stale row regenerates (Task 9's contract), so this pins the
    fallback rather than an accident of ordering: what the reader sees when
    that regeneration comes back with nothing usable. Losing a definition
    the reader already saw because *this* refresh attempt failed is worse
    than showing the older text labelled `stale` -- see
    `DefinitionService.define`'s docstring on the fallback.

    The model's second reply cites nothing verifiable (`FakeDefinitionModel`
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
    `progress.md` and `DefinitionService.define`'s docstring."""
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
