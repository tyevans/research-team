"""The Neo4j graph store, against a real server.

Deselected by default. Start the server and run it deliberately:

    docker compose -f docker-compose.test.yml up -d neo4j
    uv run pytest -m integration tests/integration/test_neo4j_graph_store.py
"""

import os
import pytest
from uuid import uuid4

from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.snapshots import SQLiteSnapshotStore
from redstring import FakeLlmProvider

from research_team.application.knowledge import SourceRef
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from research_team.infrastructure.knowledge.stores import build_graph_store

pytestmark = pytest.mark.integration


@pytest.fixture
def neo4j_env(monkeypatch):
    monkeypatch.setenv("AGENT_NEO4J_URI", os.getenv("AGENT_NEO4J_URI", "bolt://localhost:7688"))
    monkeypatch.setenv("AGENT_NEO4J_USER", os.getenv("AGENT_NEO4J_USER", "neo4j"))
    monkeypatch.setenv("AGENT_NEO4J_PASSWORD", os.getenv("AGENT_NEO4J_PASSWORD", "redstring"))


@pytest.mark.asyncio
async def test_ingest_and_search_against_a_real_neo4j(tmp_path, neo4j_env):
    project_id = uuid4()
    store = build_graph_store("neo4j")
    await store.ensure_schema()
    db_path = str(tmp_path / "sessions.db")
    try:
        adapter = RedstringKnowledge(
            project_id,
            store=store,
            event_store=SQLiteEventStore(db_path),
            snapshot_store=SQLiteSnapshotStore(db_path),
            provider=FakeLlmProvider(),
            domain="encyclopedia_wiki",
            adjudicate=False,
        )

        report = await adapter.ingest(
            SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
        )
        matches = await adapter.search("lovelace")

        assert report.entity_count >= 1
        assert any("lovelace" in match.name.lower() for match in matches)
    finally:
        # Leave no rows behind: the next run shares this database.
        await store.delete_by_tenant(project_id)
        await store.close()
