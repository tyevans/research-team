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


def test_a_default_install_embeds(unset):
    """On, and this test is the record of that being deliberate.

    It was `none` when the provider first landed, because an install whose
    endpoint does not serve embeddings would meet a 400 mid-ingest. That
    hazard is unchanged and is now handled where it belongs -- the adapter
    probes once and degrades to two-feature scoring with a warning, rather
    than the whole feature being withheld from everyone to spare the
    misconfigured.

    What the default buys: a cross-document duplicate scores 0.8000 instead of
    0.7143 and clears `LOW_SIMILARITY` on evidence, which is what let the
    `low=` override be deleted. What it costs: an embedding call per extracted
    entity per ingest, and one adjudicator call per duplicate, because 0.8 is
    below `HIGH_SIMILARITY` 0.92.
    """
    assert config.vector_store() == "memory"
    assert config.vector_store() != config.NO_VECTOR_STORE


def test_asking_for_a_vector_store_is_what_turns_embeddings_on(monkeypatch, unset):
    """One switch, not two. Two would allow a store with nothing writing to it."""
    monkeypatch.setenv("AGENT_VECTOR_STORE", "memory")

    assert config.vector_store() == "memory"
    assert config.vector_store() != config.NO_VECTOR_STORE


def test_a_vector_store_that_does_not_exist_says_what_does(monkeypatch, unset):
    """Named-and-refused rather than silently falling back to `none`.

    `build_graph_store` made this choice first and for the same reason: a
    deployment that asked for pgvector and silently got no embeddings at all
    would consolidate worse than it asked to and say nothing about it.
    """
    monkeypatch.setenv("AGENT_VECTOR_STORE", "chroma")

    with pytest.raises(ValueError, match=r"none.*memory.*pgvector"):
        config.vector_store()


def test_the_embedding_model_is_never_the_chat_model(monkeypatch, unset):
    """A chat model and an embedding model are not the same model.

    This is the property worth pinning, and it survived the default flipping
    on. `AGENT_MODEL` names a chat model; pointing embeddings at it would send
    embedding requests to a name that answers chat -- a 400 from most
    OpenAI-compatible servers, and from the dangerous ones something
    vector-shaped and numerically meaningless.

    The model now has a default, because a default-on feature whose required
    variables have none does not start. `AGENT_MODEL` is emphatically not that
    default, and this test fails if anyone makes it one.
    """
    monkeypatch.setenv("AGENT_MODEL", "some-chat-model")

    assert config.embedding_model() == config.DEFAULT_EMBEDDING_MODEL
    assert config.embedding_model() != config.model_name()


def test_the_model_and_its_width_default_together(unset):
    """The two defaults are one decision, and 768 is `nomic-embed-text`'s width.

    They have to agree or the provider declares one number while the server
    returns another, which reaches `VectorProjection` as a
    `DimensionMismatchError` -- a poison event, unrecoverable rather than
    retryable. Overriding the model and leaving the width alone is exactly how
    someone gets there, which is why both docstrings say "set both or
    neither" and why the adapter's probe checks the width as well as the call.
    """
    assert config.embedding_model() == "nomic-embed-text"
    assert config.embedding_dimension() == 768


def test_an_explicit_dimension_still_wins(monkeypatch, unset):
    monkeypatch.setenv("AGENT_EMBEDDING_DIMENSION", "1024")

    assert config.embedding_dimension() == 1024


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
