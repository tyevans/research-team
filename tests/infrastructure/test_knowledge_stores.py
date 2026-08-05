import pytest

from research_team.infrastructure.knowledge.stores import build_graph_store


def test_memory_is_the_default_store():
    store = build_graph_store("memory")

    assert type(store).__name__ == "InMemoryGraphStore"


def test_neo4j_builds_a_neo4j_store(monkeypatch):
    """Constructing the driver does not connect; the first query does."""
    monkeypatch.setenv("AGENT_NEO4J_URI", "bolt://localhost:7688")
    monkeypatch.setenv("AGENT_NEO4J_PASSWORD", "redstring")

    store = build_graph_store("neo4j")

    assert type(store).__name__ == "Neo4jGraphStore"


def test_neo4j_without_a_password_is_refused(monkeypatch):
    monkeypatch.delenv("AGENT_NEO4J_PASSWORD", raising=False)

    with pytest.raises(ValueError, match="AGENT_NEO4J_PASSWORD"):
        build_graph_store("neo4j")


def test_an_unknown_store_is_rejected_by_name():
    with pytest.raises(ValueError, match="postgres"):
        build_graph_store("postgres")
