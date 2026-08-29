"""Artifacts from the knowledge tools."""

import pytest

from research_team.infrastructure.agent.knowledge_tools import build_knowledge_tools


def tool_named(tools, name):
    return next(tool for tool in tools if tool.name == name)


async def invoke_for_artifact(tool, args: dict) -> tuple[str, dict]:
    """`(content, artifact)` from a `content_and_artifact` tool.

    Plain `tool.ainvoke(args)` discards the artifact -- see
    `test_corpus_tool_artifacts.py`'s identical helper for why a
    `ToolCall`-shaped input is required.
    """
    message = await tool.ainvoke(
        {"name": tool.name, "args": args, "id": "test-call", "type": "tool_call"}
    )
    return message.content, message.artifact


@pytest.mark.asyncio
async def test_an_unlinked_entity_survives_to_the_artifact(seeded_graph) -> None:
    """The graph's most actionable fact is an entity connected to nothing, and
    the current rendering makes it the least visible thing on the card."""
    tools = build_knowledge_tools(seeded_graph)
    _, artifact = await invoke_for_artifact(
        tool_named(tools, "graph_search"), {"query": "magic"}
    )

    counts = [entity["relationship_count"] for entity in artifact["entities"]]
    assert 0 in counts, "seed the fixture with an orphan or this proves nothing"
    assert artifact["shape"] == "entity_list"


@pytest.mark.asyncio
async def test_entities_are_sorted_by_descending_relationship_count(seeded_graph) -> None:
    """Sorted in the artifact builder, not the renderer -- see
    `entity_list_artifact`'s docstring. Ada and Charles each carry one
    relationship; the orphan carries none, so a query matching all three
    proves the ordering rather than assuming it."""
    tools = build_knowledge_tools(seeded_graph)
    _, artifact = await invoke_for_artifact(tool_named(tools, "graph_search"), {"query": "a"})

    counts = [entity["relationship_count"] for entity in artifact["entities"]]
    assert counts == sorted(counts, reverse=True)


@pytest.mark.asyncio
async def test_the_search_mode_reaches_the_console(seeded_graph) -> None:
    """`SearchOutcome.mode` exists to make a silent degradation visible. A
    console that drops it restores the silence."""
    tools = build_knowledge_tools(seeded_graph)
    _, artifact = await invoke_for_artifact(
        tool_named(tools, "graph_describe"), {"query": "magic"}
    )

    assert artifact["mode"] in {"fused", "cards", "unavailable"}
    assert artifact["shape"] == "entity_list"


@pytest.mark.asyncio
async def test_a_failed_unmerge_is_an_acknowledgement_that_says_so(seeded_graph) -> None:
    tools = build_knowledge_tools(seeded_graph)
    _, artifact = await invoke_for_artifact(
        tool_named(tools, "unmerge"),
        {"merge_id": "00000000-0000-0000-0000-000000000000"},
    )

    assert artifact["shape"] == "acknowledgement"
    assert artifact["ok"] is False


@pytest.mark.asyncio
async def test_an_invalid_merge_id_is_also_a_failed_acknowledgement(seeded_graph) -> None:
    """The other early return in `unmerge` -- a string that never parses as a
    UUID -- must not fall back to `None`."""
    tools = build_knowledge_tools(seeded_graph)
    _, artifact = await invoke_for_artifact(tool_named(tools, "unmerge"), {"merge_id": "nope"})

    assert artifact["shape"] == "acknowledgement"
    assert artifact["ok"] is False


@pytest.mark.asyncio
async def test_remember_answers_an_ok_acknowledgement(seeded_graph) -> None:
    tools = build_knowledge_tools(seeded_graph)
    _, artifact = await invoke_for_artifact(
        tool_named(tools, "remember"),
        {"text": "Grace Hopper worked on the Harvard Mark I.", "source_id": "grace"},
    )

    assert artifact["shape"] == "acknowledgement"
    assert artifact["ok"] is True
