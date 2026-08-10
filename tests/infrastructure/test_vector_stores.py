"""Choosing what holds the vectors, and refusing to choose wrong.

Shaped after `test_knowledge_stores.py`, because `build_vector_store` is
`build_graph_store` for the other half of consolidation's evidence and the two
should not need to be learned separately.
"""

import pytest

from research_team.infrastructure.knowledge.stores import build_vector_store


def test_none_is_the_default_and_builds_nothing():
    """`None`, not an empty store.

    An empty `InMemoryVectorStore` and no vector store at all are different to
    `CandidateFinder`: it asks an empty store for the subject's vector, gets
    nothing back, and drops the embedding feature -- the same outcome, reached
    by holding an object and paying for a lookup per candidate. `None` is what
    says the feature is off, and it is what `RedstringKnowledge` can check.
    """
    assert build_vector_store("none", dimension=768) is None


def test_memory_builds_an_in_memory_store():
    store = build_vector_store("memory", dimension=768)

    assert type(store).__name__ == "InMemoryVectorStore"
    assert store.dimension == 768


def test_the_store_is_built_at_the_dimension_it_was_asked_for():
    """The width is the model's property, and a store built at the wrong one
    rejects every vector with `DimensionMismatchError` at the first write --
    which is a poison event, not a retryable failure."""
    store = build_vector_store("memory", dimension=1024)

    assert store.dimension == 1024


def test_pgvector_without_a_dsn_is_refused(monkeypatch):
    monkeypatch.delenv("AGENT_PGVECTOR_DSN", raising=False)

    with pytest.raises(ValueError, match="AGENT_PGVECTOR_DSN"):
        build_vector_store("pgvector", dimension=768)


def test_an_unknown_store_is_rejected_by_name():
    with pytest.raises(ValueError, match="chroma"):
        build_vector_store("chroma", dimension=768)
