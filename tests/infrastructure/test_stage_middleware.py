"""The stage gate, against a hand-built `ModelRequest` and once for real.

Most of these tests never build an agent. The middleware's whole job is a pure
function of one `ModelRequest`, and a stub request makes the interesting
assertions -- which tools survived, what the system message ends up saying --
direct rather than inferred from what a model happened to do with them.

The exception is deliberate: one test goes through `create_deep_agent` and
reads the tool list off the model's `bind_tools` call. A stub cannot prove the
middleware composes -- that langchain wires `awrap_model_call` at all, that the
built-ins are already in `request.tools` by the time we see them, that
filtering down survives the dynamic-tool validation. Those are exactly the
claims that would break silently on a langchain upgrade.
"""

import warnings
from dataclasses import dataclass
from typing import Any

import pytest
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool, tool

from research_team.infrastructure.agent.stage_middleware import (
    CORE_TOOLS,
    StageMiddleware,
    managed_tools_for,
)


@dataclass
class FakeStage:
    """The structural shape `StageMiddleware` needs, and nothing else.

    Mirrors the three fields the real `StageBase` declares under the same
    names, so the protocol is satisfied by both without adaptation --
    `test_the_real_domain_stage_satisfies_the_protocol` is what keeps that
    true as `workflow.py` changes.
    """

    id: str
    name: str
    tools: tuple[str, ...] = ()


def _tool(name: str) -> BaseTool:
    @tool(name)
    def _fn(text: str) -> str:
        """A tool that exists only to be named."""
        return text

    return _fn


def _request(*, tools: list[Any], system_message: SystemMessage | None = None) -> ModelRequest:
    return ModelRequest(
        model=RecordingModel(),
        messages=[HumanMessage("go")],
        system_message=system_message,
        tools=tools,
        state={"messages": []},
        runtime=None,
    )


class Capture:
    """A `handler` that records the request it was handed and returns nothing."""

    def __init__(self) -> None:
        self.request: ModelRequest | None = None

    async def __call__(self, request: ModelRequest) -> Any:
        self.request = request
        return AIMessage("ok")


class RecordingModel(BaseChatModel):
    """A chat model that answers once and remembers what was bound to it.

    `bind_tools` returning `self` rather than a `RunnableBinding` is the point:
    the agent then calls this same object, so the recorded list is what the
    graph actually reached the model with, not a copy made on the way.
    """

    bound: list[str] = []
    seen_messages: list[Any] = []

    @property
    def _llm_type(self) -> str:
        return "recording"

    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        self.bound = [getattr(t, "name", None) or t.get("name", "?") for t in tools]
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.seen_messages = messages
        return ChatResult(generations=[ChatGeneration(message=AIMessage("done"))])


def _middleware(
    stage: FakeStage, stages: list[FakeStage], instructions: str | None = None
) -> StageMiddleware:
    return StageMiddleware(
        stage, managed_tools=managed_tools_for(stages), instructions=instructions
    )


DRAFT = FakeStage(id="draft", name="Draft objectives", tools=("remember", "read_source"))
REVIEW = FakeStage(id="review", name="Screen", tools=("read_source", "advance_stage"))
STAGES = [DRAFT, REVIEW]
INSTRUCTIONS = "Write objectives that name their source."
"""Prompt text as composition would resolve it from `generator.prompt_ref`."""


async def test_a_tool_the_stage_does_not_allow_never_reaches_the_model() -> None:
    handler = Capture()
    request = _request(tools=[_tool("remember"), _tool("advance_stage")])

    await _middleware(DRAFT, STAGES).awrap_model_call(request, handler)

    assert handler.request is not None
    names = {t.name for t in handler.request.tools}
    assert names == {"remember"}


async def test_the_deepagents_builtins_survive_the_filter() -> None:
    handler = Capture()
    builtins = [_tool(name) for name in sorted(CORE_TOOLS)]
    request = _request(tools=[*builtins, _tool("advance_stage")])

    await _middleware(DRAFT, STAGES).awrap_model_call(request, handler)

    assert handler.request is not None
    assert {t.name for t in handler.request.tools} >= CORE_TOOLS


async def test_a_tool_no_stage_claims_is_left_alone() -> None:
    """The filter is a denylist, so an unmanaged tool is not the gate's business.

    A future tool wired into the executor without being named in any stage
    should keep working rather than silently vanish.
    """
    handler = Capture()
    request = _request(tools=[_tool("web_search")])

    await _middleware(DRAFT, STAGES).awrap_model_call(request, handler)

    assert handler.request is not None
    assert [t.name for t in handler.request.tools] == ["web_search"]


async def test_dict_shaped_builtins_pass_through_untouched() -> None:
    handler = Capture()
    server_side = {"type": "web_search_20250305", "name": "web_search"}
    request = _request(tools=[server_side])

    await _middleware(DRAFT, STAGES).awrap_model_call(request, handler)

    assert handler.request is not None
    assert handler.request.tools == [server_side]


async def test_the_stage_prompt_is_appended_not_substituted() -> None:
    handler = Capture()
    request = _request(tools=[], system_message=SystemMessage("HARNESS PREAMBLE"))

    await _middleware(DRAFT, STAGES, INSTRUCTIONS).awrap_model_call(request, handler)

    assert handler.request is not None
    text = handler.request.system_message.text
    assert text.startswith("HARNESS PREAMBLE")
    assert INSTRUCTIONS in text
    assert DRAFT.name in text


async def test_a_stage_with_no_instructions_still_names_itself() -> None:
    handler = Capture()
    request = _request(tools=[], system_message=SystemMessage("HARNESS PREAMBLE"))

    await _middleware(REVIEW, STAGES).awrap_model_call(request, handler)

    assert handler.request is not None
    text = handler.request.system_message.text
    assert text.startswith("HARNESS PREAMBLE")
    assert REVIEW.name in text


async def test_an_absent_system_message_becomes_the_stage_prompt_alone() -> None:
    handler = Capture()
    request = _request(tools=[], system_message=None)

    await _middleware(DRAFT, STAGES, INSTRUCTIONS).awrap_model_call(request, handler)

    assert handler.request is not None
    assert INSTRUCTIONS in handler.request.system_message.text


async def test_the_original_request_is_left_untouched() -> None:
    """`override` is immutable and in-place mutation is deprecated; prove we used it."""
    handler = Capture()
    request = _request(
        tools=[_tool("remember"), _tool("advance_stage")],
        system_message=SystemMessage("HARNESS PREAMBLE"),
    )

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        await _middleware(DRAFT, STAGES).awrap_model_call(request, handler)

    assert [t.name for t in request.tools] == ["remember", "advance_stage"]
    assert request.system_message.text == "HARNESS PREAMBLE"
    assert handler.request is not request


def test_the_async_hook_is_the_one_implemented() -> None:
    """A refactor to the sync hook would raise on the first turn, not in review.

    `DeepAgentTurnExecutor._invoke` streams, and `AgentMiddleware`'s default
    `awrap_model_call` raises `NotImplementedError` naming exactly that mistake.
    Pinning it here is cheaper than the debugging session it replaces.
    """
    assert StageMiddleware.awrap_model_call is not AgentMiddleware.awrap_model_call
    assert StageMiddleware.wrap_model_call is AgentMiddleware.wrap_model_call


def test_the_middleware_carries_a_name_of_its_own() -> None:
    """`factory.py` asserts middleware names are unique; a default is a landmine."""
    assert _middleware(DRAFT, STAGES).name == "stage_gate"


def test_the_real_domain_stage_satisfies_the_protocol() -> None:
    """The protocol is structural, so nothing else would notice it drifting.

    Asserting on `model_fields` rather than constructing a stage keeps this
    from needing every unrelated required field of a `ScreenStage`.
    """
    from research_team.domain.workflow import StageBase

    assert {"id", "name", "tools"} <= set(StageBase.model_fields)


def test_managed_tools_never_include_the_core() -> None:
    stages = [FakeStage(id="s", name="S", tools=("remember", "write_file"))]
    assert managed_tools_for(stages) == frozenset({"remember"})


async def test_it_composes_through_create_deep_agent() -> None:
    """The part a stub cannot prove: langchain actually wires this in.

    Asserting on `bind_tools` rather than on a tool call keeps the test
    independent of whether a fake model chooses to call anything.
    """
    from deepagents import create_deep_agent

    model = RecordingModel()
    agent = create_deep_agent(
        model=model,
        tools=[_tool("remember"), _tool("advance_stage")],
        system_prompt="HARNESS PREAMBLE",
        middleware=[_middleware(DRAFT, STAGES, INSTRUCTIONS)],
    )

    await agent.ainvoke({"messages": [HumanMessage("go")]})

    assert "remember" in model.bound
    assert "advance_stage" not in model.bound
    assert set(model.bound) >= CORE_TOOLS
    system = model.seen_messages[0]
    assert isinstance(system, SystemMessage)
    assert "HARNESS PREAMBLE" in system.text
    assert INSTRUCTIONS in system.text


@pytest.mark.parametrize("stage", [DRAFT, REVIEW])
async def test_every_stage_keeps_the_core_available(stage: FakeStage) -> None:
    handler = Capture()
    request = _request(tools=[_tool(name) for name in sorted(CORE_TOOLS)])

    await _middleware(stage, STAGES).awrap_model_call(request, handler)

    assert handler.request is not None
    assert {t.name for t in handler.request.tools} == CORE_TOOLS
