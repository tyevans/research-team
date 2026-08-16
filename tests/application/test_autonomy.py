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
from research_team.application.autonomy import (
    ADVANCE_STAGE_TOOL,
    FETCH_MEDIA_TOOL,
    STAGE_GATE_TOOLS,
    TOOL_FLOORS,
)

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


def test_relax_all_leaves_the_stage_gate_alone():
    """`advance_stage`'s floor is the workflow review, not a hazard rating.

    "Stop asking me about fetch" must not quietly mean "and let the run cross
    every stage boundary unseen", which is the silent-progress failure the
    staging design exists to prevent.
    """
    policy = AutonomyPolicy()

    changed = policy.relax_all()

    assert ADVANCE_STAGE_TOOL not in changed
    assert policy.level_for(ADVANCE_STAGE_TOOL) == "ask"
    assert STAGE_GATE_TOOLS == (ADVANCE_STAGE_TOOL,)


def test_relax_all_can_be_asked_to_include_the_stage_gate():
    """A deliberate, separate act -- but a supported one."""
    policy = AutonomyPolicy()

    changed = policy.relax_all(include_stage_gates=True)

    assert changed[ADVANCE_STAGE_TOOL] == "auto"
    assert policy.level_for(ADVANCE_STAGE_TOOL) == "auto"


def test_relax_all_reports_only_the_levels_that_actually_moved():
    """What comes back is what a caller may record. A tool already `auto` was
    not a decision anybody made, and recording it would have the log claim
    changes that never happened.
    """
    policy = AutonomyPolicy()
    policy.set("write_file", "ask")

    changed = policy.relax_all()

    assert changed == {"write_file": "auto", "fetch": "auto", "fetch_media": "auto"}


def test_relax_all_relaxes_a_deny_too():
    """A relax-all, not a raise-only: a `deny` set earlier is a thing said
    earlier, and the later, more general "allow everything" wins. Keeping the
    deny would leave a switch that does not do what it says.
    """
    policy = AutonomyPolicy()
    policy.set("delete_file", "deny")

    changed = policy.relax_all()

    assert changed["delete_file"] == "auto"
    assert policy.level_for("delete_file") == "auto"


def test_relax_all_on_an_already_relaxed_policy_changes_and_reports_nothing():
    policy = AutonomyPolicy()
    policy.relax_all()

    assert policy.relax_all() == {}


def test_fetch_media_floors_at_ask():
    """A default-`auto` policy still asks before this tool leaves the process
    -- the same argument as `fetch`'s floor, with megabytes and a perception
    pass added to what a single unreviewed call can do.
    """
    assert AutonomyPolicy(default="auto").level_for(FETCH_MEDIA_TOOL) == "ask"


def test_an_explicit_setting_still_wins_in_both_directions():
    """A floor raises a default and never lowers it; someone who turns this
    to `auto` for a research session meant it."""
    policy = AutonomyPolicy(default="auto")
    policy.set(FETCH_MEDIA_TOOL, "auto")
    assert policy.level_for(FETCH_MEDIA_TOOL) == "auto"

    policy.set(FETCH_MEDIA_TOOL, "deny")
    assert policy.level_for(FETCH_MEDIA_TOOL) == "deny"


def test_relax_all_sweeps_it_in():
    """Intended, and stated rather than inherited: this is the first tool
    where "allow all" means megabytes and a perception pass."""
    assert FETCH_MEDIA_TOOL in AutonomyPolicy().relax_all()
