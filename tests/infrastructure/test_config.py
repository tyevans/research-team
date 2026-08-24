"""The environment knobs, and that they say what the README says."""

import pytest

from research_team.infrastructure import config

CONTEXT_VARS = (
    "AGENT_CONTEXT",
    "AGENT_CONTEXT_TRIGGER",
    "AGENT_CONTEXT_KEEP_MESSAGES",
    "AGENT_CONTEXT_KEEP_RESULTS",
    "AGENT_CONTEXT_CLEAR_OVER",
)


@pytest.fixture
def unset(monkeypatch):
    for name in CONTEXT_VARS:
        monkeypatch.delenv(name, raising=False)


def test_the_defaults_are_the_documented_ones(unset):
    """These four numbers appear in the README; drift makes it a lie."""
    assert config.context_mode() == "full"
    assert config.context_trigger_tokens() == 120_000
    assert config.context_keep_messages() == 20
    assert config.context_keep_results() == 6
    assert config.context_clear_over_chars() == 2_000


def test_the_two_keep_settings_are_independent(monkeypatch):
    """They count different things -- messages and tool results -- so one knob
    for both was a value tuned for neither."""
    monkeypatch.setenv("AGENT_CONTEXT_KEEP_MESSAGES", "12")
    monkeypatch.setenv("AGENT_CONTEXT_KEEP_RESULTS", "3")

    assert config.context_keep_messages() == 12
    assert config.context_keep_results() == 3


@pytest.mark.parametrize("mode", config.CONTEXT_MODES)
def test_every_advertised_mode_is_accepted(mode, monkeypatch):
    monkeypatch.setenv("AGENT_CONTEXT", mode)
    assert config.context_mode() == mode


def test_a_mode_that_does_not_exist_says_what_does(monkeypatch):
    monkeypatch.setenv("AGENT_CONTEXT", "clever")

    with pytest.raises(ValueError, match="full, elide, compact, delegate"):
        config.context_mode()


def test_a_mode_is_read_forgivingly(monkeypatch):
    """Operators type into a shell, not into a parser."""
    monkeypatch.setenv("AGENT_CONTEXT", "  Elide \n")
    assert config.context_mode() == "elide"


def test_the_web_binding_defaults_to_this_machine(monkeypatch):
    """A coding agent with a virtual filesystem still should not be public
    by default."""
    monkeypatch.delenv("AGENT_WEB_HOST", raising=False)
    assert config.web_host() == "127.0.0.1"


def test_tracing_is_off_by_default(monkeypatch):
    monkeypatch.delenv("AGENT_TRACING", raising=False)
    assert config.tracing_enabled() is False


def test_tracing_accepts_the_usual_spellings(monkeypatch):
    for value in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("AGENT_TRACING", value)
        assert config.tracing_enabled() is True, value


def test_a_falsey_looking_value_does_not_enable_tracing(monkeypatch):
    """`AGENT_TRACING=0` must mean off, not "the variable is set"."""
    for value in ("0", "false", "no", ""):
        monkeypatch.setenv("AGENT_TRACING", value)
        assert config.tracing_enabled() is False, value


def test_no_searxng_url_means_no_search_tool(monkeypatch):
    monkeypatch.delenv("AGENT_SEARXNG_URL", raising=False)
    assert config.searxng_url() is None


def test_a_blank_searxng_url_reads_as_unset(monkeypatch):
    monkeypatch.setenv("AGENT_SEARXNG_URL", "   ")
    assert config.searxng_url() is None


def test_curation_model_defaults_to_the_chat_model(monkeypatch):
    monkeypatch.delenv("AGENT_CURATION_MODEL", raising=False)
    monkeypatch.setenv("AGENT_MODEL", "qwen-chat")
    assert config.curation_model() == "qwen-chat"


def test_curation_model_is_overridable(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "qwen-chat")
    monkeypatch.setenv("AGENT_CURATION_MODEL", "qwen-curation")
    assert config.curation_model() == "qwen-curation"


def test_a_blank_curation_model_reads_as_unset(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "qwen-chat")
    monkeypatch.setenv("AGENT_CURATION_MODEL", "   ")
    assert config.curation_model() == "qwen-chat"


def test_searxng_url_loses_its_trailing_slash(monkeypatch):
    monkeypatch.setenv("AGENT_SEARXNG_URL", "http://searx.local/")
    assert config.searxng_url() == "http://searx.local"


def test_result_cap_defaults(monkeypatch):
    monkeypatch.delenv("AGENT_SEARXNG_RESULTS", raising=False)
    assert config.searxng_results() == 5


def test_graph_store_defaults_to_memory(monkeypatch):
    monkeypatch.delenv("AGENT_GRAPH_STORE", raising=False)
    assert config.graph_store() == "memory"


def test_knowledge_domain_defaults_to_the_projects_own_schema(monkeypatch):
    """Was `auto`, and the change is the point rather than an incidental.

    `auto` classifies per document and falls back to `encyclopedia_wiki`,
    whose `date` entity type is half of why nothing this project extracted
    ever carried a drawable date. See
    `infrastructure/knowledge/schemas/research_corpus.yaml`.
    """
    monkeypatch.delenv("AGENT_KNOWLEDGE_DOMAIN", raising=False)
    assert config.knowledge_domain() == "research_corpus"


def test_auto_is_still_reachable_through_the_environment(monkeypatch):
    """The way back to per-document classification, and the reason the
    resolver kept its `auto` arm."""
    monkeypatch.setenv("AGENT_KNOWLEDGE_DOMAIN", "auto")
    assert config.knowledge_domain() == "auto"


def test_extraction_does_not_think_by_default(monkeypatch):
    """Off is redstring's measured default for extraction, and ours too."""
    monkeypatch.delenv("AGENT_EXTRACTION_THINKING", raising=False)
    assert config.extraction_thinking() is False


def test_extraction_thinking_can_be_turned_back_on(monkeypatch):
    """The way out for a backend that rejects `chat_template_kwargs` with a 400."""
    for value in ("1", "true", "TRUE", "yes", "on"):
        monkeypatch.setenv("AGENT_EXTRACTION_THINKING", value)
        assert config.extraction_thinking() is True, value
    for value in ("0", "false", "no", ""):
        monkeypatch.setenv("AGENT_EXTRACTION_THINKING", value)
        assert config.extraction_thinking() is False, value


def test_the_extraction_throughput_defaults_are_the_documented_pair(monkeypatch):
    """8 and 2000 appear in `docs/configuration.md`, and were chosen together.

    Either alone is close to pointless: 8 in flight over 3000-character chunks
    is fewer chunks than slots on most documents, and 2000-character chunks
    run serially is roughly double the wall clock for the same result. The
    pair is the change.
    """
    monkeypatch.delenv("AGENT_EXTRACTION_CONCURRENCY", raising=False)
    monkeypatch.delenv("AGENT_EXTRACTION_CHUNK_SIZE", raising=False)
    assert config.extraction_concurrency() == 8
    assert config.extraction_chunk_size() == 2_000


def test_the_extraction_throughput_knobs_are_overridable(monkeypatch):
    """The way down for a hosted endpoint with a per-minute quota, where a
    per-document ceiling of 8 is the wrong shape of limit entirely."""
    monkeypatch.setenv("AGENT_EXTRACTION_CONCURRENCY", "1")
    monkeypatch.setenv("AGENT_EXTRACTION_CHUNK_SIZE", "3000")
    assert config.extraction_concurrency() == 1
    assert config.extraction_chunk_size() == 3_000


def test_the_catalog_sweep_defaults_to_one_candidate_at_a_time(monkeypatch):
    """1, and the number is the finding rather than a failure to finish.

    The sweeps can run candidates concurrently; measured interleaved against
    the live endpoint on 2026-08-24, ceiling 8 came back 1.1% faster than
    ceiling 1 over the same 24 candidates, with the opening and closing
    ceiling-1 runs 0.13% apart. This server serialises, so the default asks it
    for one thing at a time and the mechanism waits for an endpoint that
    batches. See `config.catalog_sweep_concurrency` for the full table.

    Pinned as a value and not merely as `<= extraction_concurrency()`: the
    point of this test is that somebody raising it has to come here, read the
    curve, and re-measure before changing the number.
    """
    monkeypatch.delenv("AGENT_CATALOG_SWEEP_CONCURRENCY", raising=False)
    assert config.catalog_sweep_concurrency() == 1


def test_the_catalog_sweep_ceiling_is_overridable(monkeypatch):
    """The whole reason the mechanism survives a default of 1: an endpoint
    that batches turns concurrency on for the cost of an environment
    variable, with no code change and no rediscovery."""
    monkeypatch.setenv("AGENT_CATALOG_SWEEP_CONCURRENCY", "8")
    assert config.catalog_sweep_concurrency() == 8


def test_transcription_is_off_until_a_url_is_set(monkeypatch):
    monkeypatch.delenv("AGENT_TRANSCRIBER_URL", raising=False)
    assert config.transcriber_url() is None


def test_a_transcriber_url_without_a_model_refuses_to_start(monkeypatch):
    """The server reports no model name -- measured against whisper.cpp on
    2026-08-15 -- so there is nothing to infer one from, and the name is the
    ASR revision inside the capability fingerprint. Defaulting it would let
    two models' output share one cache key."""
    monkeypatch.setenv("AGENT_TRANSCRIBER_URL", "http://localhost:8083")
    monkeypatch.delenv("AGENT_TRANSCRIBER_MODEL", raising=False)
    with pytest.raises(ValueError, match="AGENT_TRANSCRIBER_MODEL"):
        config.transcriber_model()


def test_perception_max_chars_matches_the_document_cap(monkeypatch):
    """The drift guard ruling R1 promised, and it used to be tautological.

    It asserted `perception_max_chars() == DEFAULT_PERCEPTION_MAX_CHARS` --
    the getter against the constant the getter returns -- and never mentioned
    `MAX_DOCUMENT_CHARS`, the other half of the pair whose drift is the only
    thing this test exists to catch. Setting `MAX_DOCUMENT_CHARS` to 100_000
    left it green while transcripts capped at twice the document cap.

    Importing `application.knowledge` from an `infrastructure` test inverts
    nothing: R1's rule is that `config.py` must not import upward, and this is
    a test, which sits above both layers and is the only place the two
    constants can be compared at all.
    """
    from research_team.application.knowledge import MAX_DOCUMENT_CHARS

    monkeypatch.delenv("AGENT_PERCEPTION_MAX_CHARS", raising=False)
    assert config.DEFAULT_PERCEPTION_MAX_CHARS == MAX_DOCUMENT_CHARS
    assert config.perception_max_chars() == MAX_DOCUMENT_CHARS


def test_the_interaction_database_sits_beside_the_session_one(monkeypatch, tmp_path):
    """Its own file, because it is its own store: positions from two stores
    cannot be ordered against each other."""
    monkeypatch.delenv("AGENT_INTERACTION_DB", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    path = config.interaction_db_path()

    assert path.endswith("/.research-team/interactions.db")
    assert "sessions.db" not in path


def test_the_interaction_database_honours_an_override(monkeypatch):
    monkeypatch.setenv("AGENT_INTERACTION_DB", "/tmp/probe-interactions.db")

    assert config.interaction_db_path() == "/tmp/probe-interactions.db"


def test_the_interaction_log_collects_unless_switched_off(monkeypatch):
    """Default-on, unlike every other boolean in this module. Fails if someone
    "fixes" the inversion to match the others."""
    monkeypatch.delenv("AGENT_INTERACTION_LOG", raising=False)

    assert config.interaction_log_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "OFF", " off "])
def test_the_interaction_log_switches_off(monkeypatch, value):
    monkeypatch.setenv("AGENT_INTERACTION_LOG", value)

    assert config.interaction_log_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", ""])
def test_anything_else_leaves_the_interaction_log_collecting(monkeypatch, value):
    """An empty string is the unset-but-present case and must not read as off."""
    monkeypatch.setenv("AGENT_INTERACTION_LOG", value)

    assert config.interaction_log_enabled() is True
