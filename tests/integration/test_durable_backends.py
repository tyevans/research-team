"""Both durable backends, wired the way `composition.py` wires them.

Deselected by default. Start the servers and run it deliberately:

    docker compose -f docker-compose.test.yml up -d
    uv run pytest -m integration tests/integration/test_durable_backends.py

`test_neo4j_graph_store.py` and `test_pgvector_store.py` each prove one adapter
answers. This proves the thing neither of them can: that `ProjectGraphs` --
the object `build_application` actually constructs, and the only caller that
opens either store in production -- drives them both correctly.

That distinction earned its place. Every defect this module was written to
catch lived in the gap between "the adapter works" and "we call it right":
`build_vector_store` returned an un-awaited coroutine, and nothing called
`ensure_schema` on the result. Both adapters passed their own tests throughout.
"""

import os
from uuid import uuid4

import pytest
from redstring import FakeEmbeddingProvider, SourceDocument, build_graph

from research_team.application.project_graphs import ProjectGraphs
from research_team.infrastructure.knowledge.stores import build_graph_store, build_vector_store
from tests.conftest import fake_provider

pytestmark = pytest.mark.integration

DIMENSION = 8
DEFAULT_DSN = "postgresql://redstring:redstring@localhost:55432/redstring"


@pytest.fixture
def backend_env(monkeypatch):
    """The variables a developer following the README would export."""
    monkeypatch.setenv("AGENT_PGVECTOR_DSN", os.getenv("AGENT_PGVECTOR_DSN", DEFAULT_DSN))
    monkeypatch.setenv(
        "AGENT_NEO4J_URI", os.getenv("AGENT_NEO4J_URI", "bolt://localhost:7688")
    )
    monkeypatch.setenv("AGENT_NEO4J_USER", os.getenv("AGENT_NEO4J_USER", "neo4j"))
    monkeypatch.setenv("AGENT_NEO4J_PASSWORD", os.getenv("AGENT_NEO4J_PASSWORD", "redstring"))


@pytest.fixture
async def graphs(backend_env):
    """A `ProjectGraphs` over both real backends, shaped as `composition.py` shapes it.

    The two callables are the same two expressions `build_application` passes:
    a `build_graph_store` per project, and one `build_vector_store` for the
    process. Divergence here would make this test agree with a wiring nobody
    ships, which is the failure mode a hand-rolled fixture invites.
    """
    opened = ProjectGraphs(
        build_store=lambda: build_graph_store("neo4j"),
        rebuild=_no_events,
        open_vector_store=lambda: build_vector_store("pgvector", dimension=DIMENSION),
    )
    yield opened
    await opened.close_all()


async def _no_events(_store, _project_id) -> None:
    """Stands in for `rebuild_graph`, which is not what this module is about.

    A real fold would need knowledge events already in a log; the wiring under
    test here is what happens to the stores before and around it.
    """


async def test_opening_a_project_readies_both_stores(graphs):
    """The vector store is opened *and* schema'd by the same call that opens the graph.

    Before this PR, `await graphs.vectors()` did not exist and the vector store
    was built synchronously in `build_application` -- yielding a coroutine, and
    one whose table was never created. This one assertion covers both: a
    coroutine has no `get`, and an unschema'd store raises `UndefinedTableError`
    on it.
    """
    project_id = uuid4()

    store = await graphs.open(project_id)
    vectors = await graphs.vectors()

    assert store is not None
    assert vectors is not None
    # A round trip, not `is not None` on the object: that is what separates
    # "constructed" from "usable", and constructed-but-unusable is exactly what
    # shipped.
    assert await vectors.get(uuid4(), project_id) is None


async def test_an_ingest_writes_to_neo4j_and_pgvector_together(graphs):
    """One `build_graph` over both stores, entities in one and vectors in the other.

    `FakeEmbeddingProvider` rather than a real endpoint: this is about where
    the vectors land, not what they contain, and an embedding model is exactly
    the dependency an integration runner does not have. It says nothing about
    similarity -- see `test_embedded_consolidation.py`'s docstring for why the
    fake's scores are not evidence about a real model.
    """
    project_id = uuid4()
    store = await graphs.open(project_id)
    vectors = await graphs.vectors()
    try:
        report = await build_graph(
            SourceDocument(id="notes", text="Ada Lovelace worked with Charles Babbage."),
            provider=fake_provider(),
            store=store,
            tenant_id=project_id,
            domain="encyclopedia_wiki",
            embedding_provider=FakeEmbeddingProvider(dimension=DIMENSION),
            vector_store=vectors,
        )

        entities = await store.find_entities(project_id)
        assert any("lovelace" in entity.name.lower() for entity in entities)

        assert report.event is not None
        assert report.embedded == len(report.event.entities)
        for entity in report.event.entities:
            assert await vectors.get(entity.id, project_id) is not None
    finally:
        # Leave no rows behind in either server: the next run shares both.
        await store.delete_by_tenant(project_id)
        await vectors.delete_by_tenant(project_id)


async def test_the_vector_store_is_shared_by_every_project(graphs):
    """One pool for the process, however many projects open.

    `PgVectorStore.connect` awaits `asyncpg.create_pool`, which opens
    connections before returning, so a store per project is real sockets. The
    graph stores are deliberately *not* shared -- one store cannot serve two
    tenants' rebuilds -- and this pins that the two are treated differently on
    purpose.
    """
    first_project, second_project = uuid4(), uuid4()

    first_graph = await graphs.open(first_project)
    second_graph = await graphs.open(second_project)

    assert first_graph is not second_graph
    assert await graphs.vectors() is await graphs.vectors()
