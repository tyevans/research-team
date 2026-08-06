"""The autonomy policy: what the agent may do without being asked.

Mutable on purpose. It is read once per tool call rather than once per turn,
so raising or lowering autonomy lands on the next tool call -- including
partway through a turn already running.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from research_team.application import (
    GATED_TOOLS,
    GRAPH_SEARCH_TOOL,
    REMEMBER_TOOL,
    UNMERGE_TOOL,
    AutonomyPolicy,
)
from research_team.application.autonomy import TOOL_FLOORS

LEVELS = ("auto", "ask", "deny")


def test_defaults_to_auto_for_every_tool_that_declares_no_floor():
    """The baseline is still permissive, and the exceptions are exactly the
    tools that asked to be exceptions.

    Written against `TOOL_FLOORS` rather than against a hardcoded list so that
    adding a floor is a one-line change here too -- but deliberately not
    written as "whatever the floor says", which would pass no matter what the
    policy did. The floors themselves are pinned in `test_fetch.py`.
    """
    policy = AutonomyPolicy()
    for tool in GATED_TOOLS:
        if tool in TOOL_FLOORS:
            continue
        assert policy.level_for(tool) == "auto"


def test_an_ungated_tool_is_always_auto():
    policy = AutonomyPolicy(default="ask")
    policy.set("write_file", "deny")
    assert policy.level_for("read_file") == "auto"


def test_a_gated_tool_that_was_never_set_reads_the_constructor_default():
    """`level_for` falls back to whatever default the policy was built with,
    not hardcoded "auto" -- a session that opens more cautious (or looser)
    than the baseline should see that reflected for every tool it hasn't
    touched yet, and stay pinned to it for the ones it has.
    """
    policy = AutonomyPolicy(default="ask")
    assert policy.level_for("write_file") == "ask"
    policy.set("delete_file", "deny")
    assert policy.level_for("write_file") == "ask"
    assert policy.level_for("delete_file") == "deny"


def test_levels_reports_each_gated_tools_own_level_not_one_shared_answer():
    """`levels()` is the display path: it has to report per-tool state, not
    collapse every tool to whatever the first one happens to be.
    """
    policy = AutonomyPolicy()
    policy.set("write_file", "ask")
    policy.set("delete_file", "deny")

    seen = policy.levels()

    assert seen["write_file"] == "ask"
    assert seen["delete_file"] == "deny"
    assert seen["web_search"] == "auto"
    assert set(seen) == set(GATED_TOOLS)


def test_setting_a_level_takes_effect_immediately():
    policy = AutonomyPolicy()
    policy.set("web_search", "ask")
    assert policy.level_for("web_search") == "ask"
    policy.set("web_search", "deny")
    assert policy.level_for("web_search") == "deny"


def test_an_unknown_level_is_refused():
    policy = AutonomyPolicy()
    with pytest.raises(ValueError, match="sometimes"):
        policy.set("web_search", "sometimes")


def test_an_ungated_tool_cannot_be_set():
    policy = AutonomyPolicy()
    with pytest.raises(ValueError, match="read_file"):
        policy.set("read_file", "ask")


@given(
    st.lists(
        st.tuples(st.sampled_from(GATED_TOOLS), st.sampled_from(LEVELS)),
        min_size=1,
        max_size=30,
    )
)
def test_level_for_returns_the_last_level_set(writes):
    """For any sequence of sets, each tool reads back its own last write."""
    policy = AutonomyPolicy()
    expected = {}
    for tool, level in writes:
        policy.set(tool, level)
        expected[tool] = level
    for tool, level in expected.items():
        assert policy.level_for(tool) == level


@given(
    st.lists(
        st.tuples(st.sampled_from(GATED_TOOLS), st.sampled_from(LEVELS)),
        max_size=30,
    )
)
def test_levels_never_leak_between_tools(writes):
    """A tool nobody wrote to still reads its own default.

    The property under test is isolation, not the value: writing to any set of
    tools must leave every other tool exactly where it started, whether that
    is the policy default or a floor.
    """
    policy = AutonomyPolicy()
    untouched = set(GATED_TOOLS) - {tool for tool, _ in writes}
    before = {tool: policy.level_for(tool) for tool in untouched}
    for tool, level in writes:
        policy.set(tool, level)
    for tool in untouched:
        assert policy.level_for(tool) == before[tool]


def test_the_knowledge_writes_are_gated_but_the_read_is_not():
    """`remember` and `unmerge` write to the graph; `graph_search` only reads
    it. Gating the read too would make every lookup an interruption, so it
    must default to `auto` the way the file reads do -- and the writes must
    actually be settable, which is what distinguishes "gated" from "absent".
    """
    policy = AutonomyPolicy(default="ask")

    assert REMEMBER_TOOL in GATED_TOOLS
    assert UNMERGE_TOOL in GATED_TOOLS
    assert GRAPH_SEARCH_TOOL not in GATED_TOOLS

    assert policy.level_for(REMEMBER_TOOL) == "ask"
    assert policy.level_for(UNMERGE_TOOL) == "ask"
    assert policy.level_for(GRAPH_SEARCH_TOOL) == "auto"

    policy.set(REMEMBER_TOOL, "deny")
    assert policy.level_for(REMEMBER_TOOL) == "deny"
    assert policy.level_for(GRAPH_SEARCH_TOOL) == "auto"
