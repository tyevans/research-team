"""Everything the process reads from its environment, in one place.

Kept at the edge on purpose: no layer below this one asks the environment
anything, so tests configure the application by passing arguments rather than
by setting variables.
"""

import os
from pathlib import Path

DEFAULT_MODEL = "qwen3.6-27b-mtp"
DEFAULT_BASE_URL = "http://localhost:8080/v1/"
DEFAULT_API_KEY = "not-needed"

CONTEXT_MODES = ("full", "elide", "compact", "delegate")
DEFAULT_CONTEXT_MODE = "full"

DEFAULT_CONTEXT_TRIGGER_TOKENS = 120_000
DEFAULT_CONTEXT_KEEP_MESSAGES = 20
DEFAULT_CONTEXT_KEEP_RESULTS = 6
DEFAULT_CONTEXT_CLEAR_OVER_CHARS = 2_000

DEFAULT_OTLP_ENDPOINT = "http://localhost:4318/v1/traces"
DEFAULT_SERVICE_NAME = "research-team"

DEFAULT_SEARXNG_RESULTS = 5


def default_db_path() -> str:
    """Where sessions live. Sessions persist across runs and are resumable."""
    configured = os.getenv("AGENT_DB")
    if configured:
        return configured
    path = Path.home() / ".research-team" / "sessions.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def model_name() -> str:
    return os.getenv("AGENT_MODEL", DEFAULT_MODEL)


def base_url() -> str:
    return os.getenv("AGENT_BASE_URL", DEFAULT_BASE_URL)


def api_key() -> str:
    return os.getenv("AGENT_API_KEY", DEFAULT_API_KEY)


def web_host() -> str:
    return os.getenv("AGENT_WEB_HOST", "127.0.0.1")


def web_port() -> int:
    return int(os.getenv("AGENT_WEB_PORT", "8000"))


def context_mode() -> str:
    """How this instance manages a conversation that outgrows the window.

    One instance, one mode: the choice shapes what every session on it sends
    to the model, and mixing them within a process would make "why did this
    turn see that?" unanswerable.
    """
    configured = os.getenv("AGENT_CONTEXT", DEFAULT_CONTEXT_MODE).strip().lower()
    if configured not in CONTEXT_MODES:
        raise ValueError(
            f"AGENT_CONTEXT={configured!r} is not one of {', '.join(CONTEXT_MODES)}"
        )
    return configured


def context_trigger_tokens() -> int:
    """How much conversation `compact` tolerates before summarizing.

    Approximate tokens, not characters: the threshold has to mean something
    against a model's window, and every published trigger is quoted in tokens.
    """
    return int(os.getenv("AGENT_CONTEXT_TRIGGER", DEFAULT_CONTEXT_TRIGGER_TOKENS))


def context_keep_messages() -> int:
    """How many recent messages `compact` leaves out of the summary.

    Separate from the tool-result count below because they are different
    quantities: six messages might be one exchange or six, while six tool
    results is six tool results. LangChain's summarizer keeps twenty by
    default, and a thin tail is where summarization does most of its damage --
    recent detail is what the agent is actively using.
    """
    return int(os.getenv("AGENT_CONTEXT_KEEP_MESSAGES", DEFAULT_CONTEXT_KEEP_MESSAGES))


def context_keep_results() -> int:
    """How many recent tool results `elide` leaves whole.

    Counted in results rather than messages so the retained volume does not
    swing with the shape of the conversation; Anthropic's tool-result clearing
    counts the same way.
    """
    return int(os.getenv("AGENT_CONTEXT_KEEP_RESULTS", DEFAULT_CONTEXT_KEEP_RESULTS))


def context_clear_over_chars() -> int:
    """How long an older tool result may be before `elide` clears it.

    Not a truncation length -- a result over this size is replaced outright,
    because a partial result reads as a whole one.
    """
    return int(os.getenv("AGENT_CONTEXT_CLEAR_OVER", DEFAULT_CONTEXT_CLEAR_OVER_CHARS))


def tracing_enabled() -> bool:
    """Whether this process should export traces. Off unless asked.

    Opt-in rather than opt-out because tracing is only useful if something is
    collecting it, and a developer running this locally has nothing listening.
    """
    return os.getenv("AGENT_TRACING", "").strip().lower() in {"1", "true", "yes", "on"}


def otlp_endpoint() -> str:
    """Where traces are sent. The OTLP/HTTP default collector address."""
    return os.getenv("AGENT_OTLP_ENDPOINT", DEFAULT_OTLP_ENDPOINT)


def tracing_service_name() -> str:
    """What this process calls itself in a trace."""
    return os.getenv("AGENT_SERVICE_NAME", DEFAULT_SERVICE_NAME)


def searxng_url() -> str | None:
    """The SearXNG instance to search, or None if this install has no search.

    Unset is the default and means the agent gets no network tool at all --
    which is what keeps the sandbox claim true for anyone who has not opted in.
    """
    configured = os.getenv("AGENT_SEARXNG_URL", "").strip()
    return configured.rstrip("/") or None


def searxng_results() -> int:
    """How many results reach the model. Capped because context is the cost."""
    return int(os.getenv("AGENT_SEARXNG_RESULTS", str(DEFAULT_SEARXNG_RESULTS)))
