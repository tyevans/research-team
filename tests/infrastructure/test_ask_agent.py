"""The agent behind the ask page: what it may touch, and what it may cite.

The two assertions that carry the design are here -- the exact tool set, and
that a citation can only name something a tool actually opened.
"""

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from research_team.application.ask import Citation
from research_team.infrastructure.agent.ask_agent import (
    READ_ONLY_TOOLS,
    citations,
    readable,
)


def named(name: str):
    @tool(name)
    def _stub(argument: str = "") -> str:
        """A stand-in for a project tool."""
        return ""

    return _stub


def test_the_admitted_tools_are_exactly_the_five_readers():
    """This set is the security boundary; a change to it should be deliberate."""
    # Expected on the left because ruff's SIM300 reads an ALL_CAPS name as the
    # literal half of the comparison; the assertion is unchanged either way.
    assert (
        frozenset({"list_sources", "read_source", "graph_search", "list_topics", "open_topic"})
        == READ_ONLY_TOOLS
    )


def test_every_mutating_project_tool_is_filtered_out():
    """The ask page must not be a second way to edit a project's knowledge."""
    tools = [
        named(name)
        for name in (
            "remember",
            "remember_page",
            "unmerge",
            "record_finding",
            "record_gap",
            "link_source",
            "fetch",
            "web_search",
            "read_source",
        )
    ]

    assert [kept.name for kept in readable(tools)] == ["read_source"]


def test_a_tool_nobody_has_admitted_yet_is_excluded():
    """An allowlist so that a tool added to open_graph later cannot arrive here
    by default. This test is the one that fails when that happens."""
    assert readable([named("summarise_everything")]) == ()


def test_a_read_source_call_becomes_a_source_citation():
    """A citation records a read, and this is what reading a source looks like."""
    messages = [
        HumanMessage(content="what did we find?"),
        AIMessage(
            content="",
            tool_calls=[{"name": "read_source", "args": {"source_id": "s1"}, "id": "t1"}],
        ),
    ]

    assert citations(messages) == (Citation(kind="source", id="s1"),)


def test_an_open_topic_call_becomes_a_topic_citation():
    """The other tool that names one identified thing it opened."""
    messages = [
        AIMessage(
            content="",
            tool_calls=[{"name": "open_topic", "args": {"topic_id": "t-9"}, "id": "t1"}],
        )
    ]

    assert citations(messages) == (Citation(kind="topic", id="t-9"),)


def test_a_search_is_not_a_citation():
    """Searching is not reading. graph_search returns candidates the agent may
    never open, and citing them would overstate what it looked at."""
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "graph_search", "args": {"query": "boundary layer"}, "id": "t1"},
                {"name": "list_sources", "args": {}, "id": "t2"},
            ],
        )
    ]

    assert citations(messages) == ()


def test_the_same_source_read_twice_is_cited_once():
    """A citation list is a set of things read, not a tally of reads."""
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "read_source", "args": {"source_id": "s1"}, "id": "t1"},
                {"name": "read_source", "args": {"source_id": "s1"}, "id": "t2"},
            ],
        )
    ]

    assert citations(messages) == (Citation(kind="source", id="s1"),)


def test_citation_order_follows_the_order_things_were_read():
    """Stable output; a set would reorder the list between identical runs."""
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "read_source", "args": {"source_id": "b"}, "id": "t1"},
                {"name": "read_source", "args": {"source_id": "a"}, "id": "t2"},
            ],
        )
    ]

    assert citations(messages) == (
        Citation(kind="source", id="b"),
        Citation(kind="source", id="a"),
    )


def test_a_tool_call_without_its_identifying_argument_is_skipped():
    """A malformed call should not produce a citation to nothing."""
    messages = [
        AIMessage(content="", tool_calls=[{"name": "read_source", "args": {}, "id": "t1"}])
    ]

    assert citations(messages) == ()
