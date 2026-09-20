"""Entity usage passage routes exercised over ASGI."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from redstring import Entity, ExtractionMethod, Provenance, StoredChunk

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


def _graph_entity(
    entity_id,
    tenant_id,
    name: str,
    entity_type: str = "person",
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
    )


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
