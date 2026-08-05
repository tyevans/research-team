"""The Neo4j graph store this project constructs, against a real server.

Deselected by default. Start the server and run it deliberately:

    docker compose -f docker-compose.test.yml up -d neo4j
    uv run pytest -m integration tests/integration/test_neo4j_graph_store.py

What this pins is narrow and worth pinning: that the URI, auth and database
this project reads from the environment produce a store redstring can write
to and read back. redstring's own suite covers the adapter's behaviour; this
covers our wiring of it.
"""

import os
import pytest
from uuid import uuid4

from redstring import SourceDocument, build_graph

from research_team.infrastructure.knowledge.stores import build_graph_store
from tests.conftest import fake_provider

pytestmark = pytest.mark.integration


@pytest.fixture
def neo4j_env(monkeypatch):
    monkeypatch.setenv(
        "AGENT_NEO4J_URI", os.getenv("AGENT_NEO4J_URI", "bolt://localhost:7688")
    )
    monkeypatch.setenv("AGENT_NEO4J_USER", os.getenv("AGENT_NEO4J_USER", "neo4j"))
    monkeypatch.setenv("AGENT_NEO4J_PASSWORD", os.getenv("AGENT_NEO4J_PASSWORD", "redstring"))


@pytest.mark.asyncio
async def test_the_configured_store_round_trips_against_a_real_neo4j(neo4j_env):
    tenant_id = uuid4()
    store = build_graph_store("neo4j")
    await store.ensure_schema()
    try:
        await build_graph(
            SourceDocument(id="notes", text="Ada Lovelace worked with Charles Babbage."),
            provider=fake_provider(),
            store=store,
            tenant_id=tenant_id,
            domain="encyclopedia_wiki",
        )

        entities = await store.find_entities(tenant_id)

        assert any("lovelace" in entity.name.lower() for entity in entities)
    finally:
        # Leave no rows behind: the next run shares this server.
        await store.delete_by_tenant(tenant_id)
        await store.close()
