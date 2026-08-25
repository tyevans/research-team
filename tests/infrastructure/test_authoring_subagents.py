"""That the roster builds, and that no subagent can dispatch another.

The port-with-one-adapter shape from CLAUDE.md: the specs are data handed to a
library, and nothing else checks that the library accepts them. A malformed
entry surfaces only when an agent is constructed inside a turn, which means a
failed authoring run against a live endpoint, minutes in, naming nothing about
the roster.

A test that asserted the dicts have the right keys would look identical to this
one and would catch none of that -- it would be checking our own literal
against itself.
"""

import pytest
from deepagents import create_deep_agent
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from research_team.application.prose_rubric import critic_reporting_contract
from research_team.infrastructure.agent.authoring_subagents import (
    AUTHORING_DISPATCH_PROMPT,
    AUTHORING_SUBAGENTS,
)


def test_the_roster_has_six_subagents():
    assert len(AUTHORING_SUBAGENTS) == 6


def test_every_spec_builds_through_create_deep_agent():
    """Through `create_deep_agent`, not `SubAgentMiddleware`.

    deepagents 0.7.6 fills `model` and `tools` per spec in `graph.py` before
    compiling, so driving the middleware directly would demand fields
    production never supplies and fail on a roster that works. What production
    subscripts, and therefore raises on, is `name` and `system_prompt`.
    """
    agent = create_deep_agent(
        model=FakeListChatModel(responses=["ok"]),
        subagents=list(AUTHORING_SUBAGENTS),
    )
    assert agent is not None


def test_no_subagent_carries_orchestration_tools():
    """A subagent that could dispatch another would make the phase's fan-out
    unbounded and unobservable. deepagents builds subagents without
    SubAgentMiddleware, so this is the library's guarantee -- asserted here
    because the design depends on it and a future version could change it."""
    for spec in AUTHORING_SUBAGENTS:
        names = {getattr(tool, "name", "") for tool in spec.get("tools", ())}
        assert "task" not in names, spec["name"]


def test_every_spec_carries_a_name_and_a_system_prompt():
    """The two fields graph.py subscripts directly."""
    for spec in AUTHORING_SUBAGENTS:
        assert spec["name"]
        assert spec["system_prompt"]
        assert spec["description"]


def test_names_are_unique():
    names = [spec["name"] for spec in AUTHORING_SUBAGENTS]
    assert len(set(names)) == len(names)


@pytest.mark.parametrize(
    "name",
    [
        "unit-critic",
        "anecdote-hunter",
        "lesson-drafter",
        "prose-critic",
        "quiz-writer",
        "unit-reviewer",
    ],
)
def test_the_dispatch_prompt_names_every_subagent(name):
    """A subagent the primary agent is never told about is a subagent that is
    never called, and the run still settles -- so this is the assertion that
    stops a roster entry being dead weight."""
    assert name in AUTHORING_DISPATCH_PROMPT
    assert any(spec["name"] == name for spec in AUTHORING_SUBAGENTS)


def test_the_two_rubric_carrying_prompts_hold_the_rules_themselves():
    """Not that they mention a rubric -- that the six rules are in the text.

    The drafter and the critic are given the rubric inline because neither can
    read a file the caller did not name. An interpolation that silently
    produced an empty string would leave every other test in this file green:
    the spec still builds, the names are still unique, and the run still
    answers, having judged nothing.

    The counter is the second half of that: a filter inside a loop with no
    counter passes when the filter matches nothing, so renaming a spec or
    dropping one from the tuple would skip the body and stay green.
    """
    checked = 0
    for spec in AUTHORING_SUBAGENTS:
        if spec["name"] in {"lesson-drafter", "prose-critic"}:
            checked += 1
            assert "Opens with a problem, not a thesis" in spec["system_prompt"]
            assert "Varied section shape" in spec["system_prompt"]
    assert checked == 2


def test_only_the_critic_is_given_the_critics_reporting_contract():
    """The drafter gets the rules; it must not get the tail that follows them.

    The tail says to judge the lesson, to report nothing else, and not to
    rewrite it. In a drafter's prompt those fight the one instruction it has,
    and its OUTPUT clause competes with the real one below it -- the likely
    result being a critique where a lesson should be. Nothing else here would
    notice: a drafter handed the whole file still builds, still has a unique
    name, and still holds all six rules.
    """
    contract = critic_reporting_contract()
    assert contract.strip()
    drafter = next(s for s in AUTHORING_SUBAGENTS if s["name"] == "lesson-drafter")
    critic = next(s for s in AUTHORING_SUBAGENTS if s["name"] == "prose-critic")
    assert contract not in drafter["system_prompt"]
    assert "Report nothing else" not in drafter["system_prompt"]
    assert contract in critic["system_prompt"]


def test_neither_prompt_carries_the_rubrics_editors_note():
    """The HTML comment at the top of the rubric names both subagents and what
    each is given. A drafter told what the critic receives has been told
    something it can only act on wrongly, and it is maintenance prose either
    way -- tokens spent on nothing the subagent does."""
    for spec in AUTHORING_SUBAGENTS:
        assert "<!--" not in spec["system_prompt"], spec["name"]
        assert "whoever edits the file" not in spec["system_prompt"], spec["name"]
