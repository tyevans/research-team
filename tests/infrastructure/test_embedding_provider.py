"""The embedding provider this project builds for itself.

`test_extraction_model.py` is the sibling: same shape, same reason to exist --
this project builds its own client rather than using redstring's
`openai_compatible` helper, so every default that helper applies has to be
applied here or it silently does not reach us.
"""

import pytest

from research_team.infrastructure.agent.deep_agent import build_embedding_provider


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("AGENT_VECTOR_STORE", "memory")
    monkeypatch.setenv("AGENT_EMBEDDING_MODEL", "nomic-embed-text")
    monkeypatch.setenv("AGENT_EMBEDDING_DIMENSION", "768")
    monkeypatch.delenv("AGENT_EMBEDDING_BASE_URL", raising=False)


def test_it_reports_the_model_and_dimension_it_was_configured_with(configured):
    """Both are provenance, not decoration.

    `model` is the only thing that says which collection a stored vector
    belongs to, and `dimension` is what redstring checks against the store
    *before* embedding anything -- so a provider that reported either wrongly
    would pass construction and fail at the first write, or worse, not fail.
    """
    provider = build_embedding_provider()

    assert provider.model == "nomic-embed-text"
    assert provider.dimension == 768


def test_it_satisfies_redstrings_port(configured):
    """`EmbeddingProvider` is `runtime_checkable`, so this is a real check.

    It would pass with the change reverted only if `build_embedding_provider`
    existed at all, which is the point of asserting it here rather than
    trusting the type annotation: nothing type-checks the adapter redstring
    hands back.
    """
    from redstring import EmbeddingProvider

    assert isinstance(build_embedding_provider(), EmbeddingProvider)


def test_it_points_at_the_embedding_endpoint_not_the_chat_one(monkeypatch, configured):
    """A separate port is the normal case, not the exotic one -- llama.cpp
    serves one model per process."""
    monkeypatch.setenv("AGENT_BASE_URL", "http://localhost:8080/v1/")
    monkeypatch.setenv("AGENT_EMBEDDING_BASE_URL", "http://localhost:8081/v1/")

    provider = build_embedding_provider()

    assert "8081" in str(provider._embeddings.openai_api_base)


def test_no_model_configured_is_refused_before_any_request(monkeypatch):
    """Loud and early. The alternative is a 400 mid-ingest, after the fetch
    has been paid for -- which is the failure `config.extraction_thinking`
    documents and this one is shaped to avoid."""
    monkeypatch.setenv("AGENT_VECTOR_STORE", "memory")
    monkeypatch.delenv("AGENT_EMBEDDING_MODEL", raising=False)

    with pytest.raises(ValueError, match="AGENT_EMBEDDING_MODEL"):
        build_embedding_provider()
