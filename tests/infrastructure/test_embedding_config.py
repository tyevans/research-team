"""The embedding knobs, and the one thing they must not do by default.

Embeddings are the first thing this project has added that costs a model call
per *entity* rather than per document, against an endpoint that may not exist.
So the tests that matter most here are the ones about being switched off.
"""

import pytest

from research_team.infrastructure import config

EMBEDDING_VARS = (
    "AGENT_VECTOR_STORE",
    "AGENT_EMBEDDING_MODEL",
    "AGENT_EMBEDDING_DIMENSION",
    "AGENT_EMBEDDING_BASE_URL",
    "AGENT_PGVECTOR_DSN",
)


@pytest.fixture
def unset(monkeypatch):
    for name in EMBEDDING_VARS:
        monkeypatch.delenv(name, raising=False)


def test_a_default_install_has_no_vector_store(unset):
    """Off unless asked, which is the whole safety property of this change.

    An install that had embeddings switched on by default would, on its first
    ingest, make one embedding call per extracted entity against an endpoint
    nobody configured -- and `AGENT_BASE_URL`'s default points at a local
    server that serves a chat model and need not serve an embedding one. The
    failure would land in the middle of an ingest the user had already paid to
    fetch.

    This test would pass with `DEFAULT_VECTOR_STORE` set to `"memory"` only if
    someone also changed the constant it reads, which is the point.
    """
    assert config.vector_store() == "none"
    assert config.embeddings_enabled() is False


def test_asking_for_a_vector_store_is_what_turns_embeddings_on(monkeypatch, unset):
    """One switch, not two. Two would allow a store with nothing writing to it."""
    monkeypatch.setenv("AGENT_VECTOR_STORE", "memory")

    assert config.vector_store() == "memory"
    assert config.embeddings_enabled() is True


def test_a_vector_store_that_does_not_exist_says_what_does(monkeypatch, unset):
    """Named-and-refused rather than silently falling back to `none`.

    `build_graph_store` made this choice first and for the same reason: a
    deployment that asked for pgvector and silently got no embeddings at all
    would consolidate worse than it asked to and say nothing about it.
    """
    monkeypatch.setenv("AGENT_VECTOR_STORE", "chroma")

    with pytest.raises(ValueError, match=r"none.*memory.*pgvector"):
        config.vector_store()


def test_the_embedding_model_has_no_default(monkeypatch, unset):
    """A chat model and an embedding model are not the same model.

    `AGENT_MODEL` defaults to a chat model, and defaulting the embedding model
    to it would send embedding requests to a name that answers chat -- which
    most OpenAI-compatible servers answer with a 400 and some answer with
    something shaped like an embedding and numerically meaningless. There is no
    name that is right for every install, so there is no default.
    """
    monkeypatch.setenv("AGENT_VECTOR_STORE", "memory")

    with pytest.raises(ValueError, match="AGENT_EMBEDDING_MODEL"):
        config.embedding_model()


def test_the_embedding_dimension_has_no_default(monkeypatch, unset):
    """The store's width is fixed at construction and cannot be discovered.

    redstring refuses to wire a provider to a store whose dimension disagrees,
    *before* any text is embedded. That check is only worth having if the
    number came from the deployment rather than from a guess here -- a wrong
    default would make every install that forgot to set it fail identically
    and late.
    """
    monkeypatch.setenv("AGENT_VECTOR_STORE", "memory")
    monkeypatch.setenv("AGENT_EMBEDDING_MODEL", "nomic-embed-text")

    with pytest.raises(ValueError, match="AGENT_EMBEDDING_DIMENSION"):
        config.embedding_dimension()


def test_the_embedding_endpoint_defaults_to_the_one_everything_else_uses(monkeypatch, unset):
    """Same local server unless told otherwise; separable because it often is not.

    llama.cpp serves one model per process, so an install running a chat model
    locally serves its embeddings from a second port -- or from a hosted
    provider entirely. Reusing `AGENT_BASE_URL` is the right default and a
    wrong requirement.
    """
    monkeypatch.setenv("AGENT_BASE_URL", "http://localhost:9999/v1/")

    assert config.embedding_base_url() == "http://localhost:9999/v1/"

    monkeypatch.setenv("AGENT_EMBEDDING_BASE_URL", "http://localhost:8081/v1/")

    assert config.embedding_base_url() == "http://localhost:8081/v1/"


def test_pgvector_refuses_to_start_without_a_dsn(monkeypatch, unset):
    """No default DSN, for `neo4j_auth`'s reason: no silent connection anywhere."""
    monkeypatch.setenv("AGENT_VECTOR_STORE", "pgvector")

    with pytest.raises(ValueError, match="AGENT_PGVECTOR_DSN"):
        config.pgvector_dsn()
