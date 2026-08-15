import pytest

from research_team.infrastructure.knowledge.stores import build_chunk_store, build_graph_store


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


def test_an_unknown_chunk_store_kind_is_refused_by_name():
    """A deployment that asked for postgres must not silently get memory."""
    with pytest.raises(ValueError, match="nonsense"):
        build_chunk_store("nonsense", dimension=1536)


def test_chunk_store_none_means_the_feature_is_off():
    assert build_chunk_store("none", dimension=1536) is None


def test_a_memory_chunk_store_takes_the_dimension_it_is_given():
    """Inert under lexical-only retrieval, but wrong here means a corpus that
    cannot be embedded later without rebuilding it."""
    store = build_chunk_store("memory", dimension=1536)
    assert store is not None
    assert store.dimension == 1536


def test_postgres_chunk_store_is_refused_as_unwired():
    """Nobody has asked for a postgres-backed chunk store; the ValueError
    still names it as a real setting so an operator sees it is unwired,
    not typo'd."""
    with pytest.raises(ValueError, match="postgres"):
        build_chunk_store("postgres", dimension=1536)
