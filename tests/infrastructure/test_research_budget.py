"""That a parent authoring turn cannot read forever.

The defect this guards is in the owner's log rather than in anyone's
imagination: three runs of the `mid-2000s` area spent eighteen model calls and
thirty tool calls on graph and corpus queries, twelve of them near-identical
rephrasings of one question, and then returned an empty message with no tool
calls and no file written. See `research_budget.py` for the full account.

**Every test here is parametrised over the number of rounds, and that is the
point rather than thoroughness.** A test run at one round count cannot tell the
budget from a hard-coded constant, and a test that only checks the budget
*eventually* bites cannot tell `rounds` from `rounds + 1` -- which is the whole
difference between the measured bound and one more spiral round than the
measurement justifies. The property that distinguishes a working budget from a
broken one is that the count of tool-bearing calls tracks `rounds` and nothing
else: not the size of the corpus, not the number of tools, not how long the
model keeps going.
"""

from dataclasses import dataclass, replace
from typing import Any

import pytest

from research_team.infrastructure.agent.research_budget import (
    BUDGET_NOTICE,
    DEFAULT_ROUNDS,
    RESEARCH_TOOLS,
    ResearchBudget,
)


@dataclass
class FakeRequest:
    """The two `ModelRequest` fields the middleware reads and overrides.

    A stand-in rather than the real `ModelRequest`, which needs a model, a
    runtime and a graph state to construct. The risk that carries is named
    plainly: this fixture cannot catch `override` changing its signature
    upstream. `test_the_middleware_overrides_a_real_model_request` is the one
    that drives the genuine article and is why that risk is bounded.
    """

    tools: list[Any]
    system_prompt: str = "system"

    def override(self, **changes: Any) -> "FakeRequest":
        return replace(self, **changes)


def tools_of(count: int) -> list[dict[str, str]]:
    """`count` research tools plus the three a bounded parent must keep.

    Dict-shaped on purpose: `ModelRequest.tools` carries already-structured
    tool definitions as well as `BaseTool`s, and a `_tool_name` that only knew
    about `.name` would keep every research tool while looking exactly like a
    budget that works.
    """
    research = sorted(RESEARCH_TOOLS)[:count]
    return [{"name": name} for name in [*research, "write_file", "edit_file", "task"]]


def names(request: FakeRequest) -> set[str]:
    return {tool["name"] for tool in request.tools}


async def drive(budget: ResearchBudget, calls: int, tools: list[Any]) -> list[FakeRequest]:
    """Run `calls` model calls through `budget`, returning what each one saw."""
    seen: list[FakeRequest] = []

    async def handler(request: FakeRequest) -> str:
        seen.append(request)
        return "answer"

    for _ in range(calls):
        await budget.awrap_model_call(FakeRequest(tools=list(tools)), handler)
    return seen


@pytest.mark.asyncio
@pytest.mark.parametrize("rounds", [1, 2, 5, 16, 40])
async def test_the_budget_covers_exactly_the_rounds_it_names(rounds):
    """Call `rounds` keeps its tools; call `rounds + 1` does not.

    Both halves, because each alone passes under an off-by-one in the other
    direction: asserting only that call `rounds + 1` is stripped passes a
    middleware that strips from call 1, and asserting only that call `rounds`
    is whole passes one that never strips at all.
    """
    tools = tools_of(3)
    seen = await drive(ResearchBudget(rounds=rounds), rounds + 1, tools)

    for request in seen[:rounds]:
        assert names(request) >= set(sorted(RESEARCH_TOOLS)[:3])
    assert not names(seen[rounds]) & RESEARCH_TOOLS


@pytest.mark.asyncio
@pytest.mark.parametrize("corpus_tools", [1, 3, 7])
@pytest.mark.parametrize("model_calls", [20, 60, 200])
async def test_the_reading_a_parent_may_do_is_flat_in_the_corpus_and_in_persistence(
    corpus_tools, model_calls
):
    """The bound is on what the parent accumulates, not on what it finished.

    This is the assertion the whole change exists for. A model that keeps
    asking gets no further, and a corpus that offers more to read does not buy
    more reading: the number of calls that carried a research tool is exactly
    `rounds` across every combination below. A test that only asserted the run
    terminated would pass against the spiral itself, which also terminated --
    after eighteen rounds and with no file.
    """
    rounds = 4
    seen = await drive(ResearchBudget(rounds=rounds), model_calls, tools_of(corpus_tools))

    with_research = [request for request in seen if names(request) & RESEARCH_TOOLS]
    assert len(with_research) == rounds


@pytest.mark.asyncio
@pytest.mark.parametrize("rounds", [1, 4])
async def test_a_bounded_parent_keeps_the_tools_it_needs_to_finish(rounds):
    """Withdrawing `write_file` or `task` would turn a bounded run into a
    stopped one -- the failure being fixed, wearing a different cause."""
    seen = await drive(ResearchBudget(rounds=rounds), rounds + 2, tools_of(7))

    for request in seen[rounds:]:
        assert {"write_file", "edit_file", "task"} <= names(request)


@pytest.mark.asyncio
async def test_a_stripped_call_is_told_why():
    """A model whose tools vanish with no explanation reports that it cannot
    continue. The notice is reasoned rather than measured -- see the comment at
    the override -- and this pins that it is actually attached, which is the
    part that would rot silently."""
    seen = await drive(ResearchBudget(rounds=1), 2, tools_of(7))

    assert BUDGET_NOTICE not in seen[0].system_prompt
    assert seen[1].system_prompt.endswith(BUDGET_NOTICE)


@pytest.mark.asyncio
async def test_each_instance_carries_its_own_count():
    """`composition.turn_middleware` builds one of these per turn, which is
    what resets the budget between phases. A shared count -- the shape
    `SearchAttempts` has, and the shape this deliberately does not copy --
    would leave phase 2 with whatever phase 1 spent, so phase 4 of a four-phase
    run would begin with no reading at all."""
    tools = tools_of(7)
    await drive(ResearchBudget(rounds=2), 5, tools)
    fresh = await drive(ResearchBudget(rounds=2), 1, tools)

    assert names(fresh[0]) & RESEARCH_TOOLS


def test_the_default_is_the_one_the_environment_reads():
    """`config.DEFAULT_AUTHORING_ROUNDS` and `research_budget.DEFAULT_ROUNDS`
    are one value by import. Pinned because the alternative -- two literals
    that agree today -- is the drift CLAUDE.md's marker-constant section is
    about, one layer over."""
    from research_team.infrastructure import config

    assert DEFAULT_ROUNDS == config.DEFAULT_AUTHORING_ROUNDS == 6


@pytest.mark.asyncio
async def test_the_middleware_overrides_a_real_model_request():
    """Drives the genuine `ModelRequest`, not `FakeRequest`.

    The one test here that would catch `override` changing shape upstream, or
    `tools`/`system_prompt` being renamed -- everything above would keep
    passing against a middleware that no longer works, because the fake
    implements whatever the middleware asks of it. This is CLAUDE.md's
    single-adapter rule applied to a library seam: a stub on one side proves
    nothing about the other.
    """
    from langchain.agents.middleware.types import ModelRequest

    request = ModelRequest(
        model=None,
        messages=[],
        system_prompt="system",
        tool_choice=None,
        tools=tools_of(7),
        response_format=None,
        state={},
        runtime=None,
    )
    seen: list[Any] = []

    async def handler(prepared: Any) -> str:
        seen.append(prepared)
        return "answer"

    budget = ResearchBudget(rounds=1)
    await budget.awrap_model_call(request, handler)
    await budget.awrap_model_call(request, handler)

    assert {tool["name"] for tool in seen[0].tools} & RESEARCH_TOOLS
    assert not {tool["name"] for tool in seen[1].tools} & RESEARCH_TOOLS
    assert seen[1].system_prompt.endswith(BUDGET_NOTICE)
