"""Which model extraction runs on, and whether it is allowed to think first.

redstring 0.4.0 turns thinking off for extraction by default, but only inside
`LangChainLlmProvider.openai_compatible`. This project builds its own
`ChatOpenAI` and uses `__init__`, so that default never arrived: extraction
kept reasoning, at roughly five times the wall clock and three times the
entity false positives redstring measured, for identical recall.

A test asserting only that `build_model()` returns a `ChatOpenAI` would have
passed throughout. What has to be asserted is the request body -- that the
model handed to the extraction provider carries `extra_body`, and that the
agent's own model does not, because whether *it* should reason is a separate
question nobody has measured.
"""

from langchain_core.messages import AIMessage
from redstring.llm.adapters.langchain import NO_THINKING

from research_team.composition import _extraction_model
from research_team.infrastructure.agent import build_extraction_model, build_model
from tests.conftest import ToolAwareFakeChatModel


def test_the_extraction_model_tells_the_server_not_to_think(monkeypatch):
    monkeypatch.delenv("AGENT_EXTRACTION_THINKING", raising=False)
    assert build_extraction_model().extra_body == NO_THINKING


def test_the_agents_own_model_is_left_thinking(monkeypatch):
    """The bug's fix must not spread to the conversational agent.

    The agent reasons across tool calls; extraction reads one document and
    reports what it says. Only the second was measured, so only the second
    changes.
    """
    monkeypatch.delenv("AGENT_EXTRACTION_THINKING", raising=False)
    assert build_model().extra_body is None


def test_an_env_override_restores_the_servers_own_behaviour(monkeypatch):
    """The escape hatch for a backend that has no chat template to pass kwargs to.

    OpenAI's hosted API is the one to expect: it rejects the unknown field
    with a 400 on the first extraction call.
    """
    monkeypatch.setenv("AGENT_EXTRACTION_THINKING", "1")
    assert build_extraction_model().extra_body is None


def test_extraction_gets_a_model_of_its_own_when_none_is_injected(monkeypatch):
    monkeypatch.delenv("AGENT_EXTRACTION_THINKING", raising=False)
    assert _extraction_model(None).extra_body == NO_THINKING


def test_an_injected_model_reaches_extraction_untouched():
    """`build_application(model=...)` is how tests inject fakes.

    A fake has no `extra_body` and cannot be given one; replacing it would
    point extraction at a real endpoint the test never asked for. Injected
    means injected.
    """
    fake = ToolAwareFakeChatModel(responses=[AIMessage(content="done", id="a1")])
    assert _extraction_model(fake) is fake
