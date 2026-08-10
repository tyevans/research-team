"""Choosing what holds the vectors, and refusing to choose wrong.

Shaped after `test_knowledge_stores.py`, because `build_vector_store` is
`build_graph_store` for the other half of consolidation's evidence and the two
should not need to be learned separately.
"""

import inspect

import pytest

from research_team.infrastructure.knowledge.stores import build_vector_store


def test_the_builder_is_a_coroutine_function():
    """`build_vector_store` must be awaited, and the reason is `PgVectorStore`.

    Its `connect` is `async` -- unlike `Neo4jGraphStore.connect`, which is not
    -- so a synchronous builder returned the un-awaited coroutine and
    `AGENT_VECTOR_STORE=pgvector` passed a coroutine object downstream as if it
    were a store. Nothing caught that, because the two backends this suite can
    build without a server are both synchronous to construct, and a coroutine
    is truthy and not None. Asserted on the signature for that reason: this is
    the one property of the builder no server-free test of its *return value*
    can see.
    """
    assert inspect.iscoroutinefunction(build_vector_store)


async def test_none_is_the_default_and_builds_nothing():
    """`None`, not an empty store.

    An empty `InMemoryVectorStore` and no vector store at all are different to
    `CandidateFinder`: it asks an empty store for the subject's vector, gets
    nothing back, and drops the embedding feature -- the same outcome, reached
    by holding an object and paying for a lookup per candidate. `None` is what
    says the feature is off, and it is what `RedstringKnowledge` can check.
    """
    assert await build_vector_store("none", dimension=768) is None


async def test_memory_builds_an_in_memory_store():
    store = await build_vector_store("memory", dimension=768)

    assert type(store).__name__ == "InMemoryVectorStore"
    assert store.dimension == 768


async def test_the_store_is_built_at_the_dimension_it_was_asked_for():
    """The width is the model's property, and a store built at the wrong one
    rejects every vector with `DimensionMismatchError` at the first write --
    which is a poison event, not a retryable failure."""
    store = await build_vector_store("memory", dimension=1024)

    assert store.dimension == 1024


async def test_pgvector_without_a_dsn_is_refused(monkeypatch):
    monkeypatch.delenv("AGENT_PGVECTOR_DSN", raising=False)

    with pytest.raises(ValueError, match="AGENT_PGVECTOR_DSN"):
        await build_vector_store("pgvector", dimension=768)


async def test_an_unknown_store_is_rejected_by_name():
    with pytest.raises(ValueError, match="chroma"):
        await build_vector_store("chroma", dimension=768)
