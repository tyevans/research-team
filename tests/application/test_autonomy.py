"""The autonomy policy: what the agent may do without being asked.

Mutable on purpose. It is read once per tool call rather than once per turn,
so raising or lowering autonomy lands on the next tool call -- including
partway through a turn already running.
"""

from inspect import signature

import pytest
from hypothesis import given
from hypothesis import strategies as st

from research_team.knowledge.application import (
    GRAPH_SEARCH_TOOL,
    REMEMBER_TOOL,
    UNMERGE_TOOL,
)
from research_team.session.application.autonomy import (
    FETCH_MEDIA_TOOL,
    GATED_TOOLS,
    TOOL_FLOORS,
    AutonomyPolicy,
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


def test_relax_all_exempts_nothing():
    """It swept every gated tool but `advance_stage`, which was a review gate
    rather than a hazard and needed asking for by name. Both are gone, and
    what remains in `GATED_TOOLS` is hazards only -- so a relax-all that
    withheld one would be withholding it for being dangerous.

    Red against any surviving exemption, and against `relax_all` taking a
    keyword to grant one.
    """
    policy = AutonomyPolicy(default="deny")

    changed = policy.relax_all()

    assert set(changed) == set(GATED_TOOLS)
    assert all(policy.level_for(tool) == "auto" for tool in GATED_TOOLS)
    assert not signature(policy.relax_all).parameters


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


def test_restrict_all_moves_tools_to_ask_and_reports_changes():
    policy = AutonomyPolicy(default="auto")
    policy.relax_all()
    # Now all are auto
    changed = policy.restrict_all(level="ask")
    assert len(changed) == len(GATED_TOOLS)
    for tool in GATED_TOOLS:
        assert policy.level_for(tool) == "ask"

    # Calling restrict_all again with same level reports nothing
    assert policy.restrict_all(level="ask") == {}

    # Can restrict to deny
    changed_deny = policy.restrict_all(level="deny")
    assert len(changed_deny) == len(GATED_TOOLS)
    for tool in GATED_TOOLS:
        assert policy.level_for(tool) == "deny"

    with pytest.raises(ValueError, match="unknown autonomy level"):
        policy.restrict_all(level="invalid")  # type: ignore[arg-type]


def test_reset_clears_explicit_levels():
    policy = AutonomyPolicy(default="auto")
    policy.set("write_file", "deny")
    policy.set("edit_file", "ask")

    # Reset single tool
    changed = policy.reset("write_file")
    assert changed == {"write_file": "auto"}
    assert policy.level_for("write_file") == "auto"

    # Reset all
    changed_all = policy.reset()
    assert changed_all == {"edit_file": "auto"}

    with pytest.raises(ValueError, match="not a gated tool"):
        policy.reset("read_file")


def test_is_gated_predicate():
    policy = AutonomyPolicy()
    assert policy.is_gated("write_file") is True
    assert policy.is_gated("read_file") is False
    assert AutonomyPolicy.is_gated("delete_file") is True
    assert AutonomyPolicy.is_gated("unknown_tool") is False


def test_explain_autonomy_level():
    policy = AutonomyPolicy(default="auto")
    # Ungated tool
    exp_ungated = policy.explain("read_file")
    assert exp_ungated["gated"] is False
    assert exp_ungated["level"] == "auto"

    # Gated tool without override
    exp_fetch = policy.explain("fetch")
    assert exp_fetch["gated"] is True
    assert exp_fetch["explicit"] is False
    assert exp_fetch["floor"] == "ask"
    assert exp_fetch["level"] == "ask"

    # Gated tool with override
    policy.set("fetch", "auto")
    exp_fetch_override = policy.explain("fetch")
    assert exp_fetch_override["explicit"] is True
    assert exp_fetch_override["level"] == "auto"


def test_copy_policy():
    policy = AutonomyPolicy(default="ask")
    policy.set("write_file", "deny")

    cloned = policy.copy()
    assert cloned.level_for("write_file") == "deny"
    assert cloned.level_for("delete_file") == "ask"

    # Mutations to clone do not touch original
    cloned.set("write_file", "auto")
    assert cloned.level_for("write_file") == "auto"
    assert policy.level_for("write_file") == "deny"


def test_scoped_autonomy_policy():
    from research_team.session.application.autonomy import ScopedAutonomyPolicy

    parent = AutonomyPolicy(default="auto")
    scoped = ScopedAutonomyPolicy(parent)

    # Initially matches parent
    assert scoped.level_for("write_file") == "auto"
    assert scoped.level_for("fetch") == "ask"

    # Local override in scope
    scoped.set("write_file", "deny")
    assert scoped.level_for("write_file") == "deny"
    assert parent.level_for("write_file") == "auto"

    # Parent change reflected in scope if not locally overridden
    parent.set("delete_file", "deny")
    assert scoped.level_for("delete_file") == "deny"

    # Scope levels() reflects combined view
    levels = scoped.levels()
    assert levels["write_file"] == "deny"
    assert levels["delete_file"] == "deny"
