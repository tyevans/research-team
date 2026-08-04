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
