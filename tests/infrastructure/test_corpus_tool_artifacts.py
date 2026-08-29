"""Artifacts from the corpus tools, driven through the real tool objects."""

import re

from research_team.infrastructure.agent import corpus_tools
from research_team.infrastructure.agent.corpus_tools import build_corpus_tools


def tool_named(tools, name):
    return next(tool for tool in tools if tool.name == name)


async def invoke_for_artifact(tool, args: dict) -> tuple[str, dict]:
    """`(content, artifact)` from a `content_and_artifact` tool.

    Plain `tool.ainvoke(args)` -- what the brief's draft test wrote --
    discards the artifact: `BaseTool._format_output` returns bare `content`
    whenever `tool_call_id` is `None`, and a plain-dict `ainvoke` never
    supplies one (`langchain_core/tools/base.py`, `_format_output`). A
    `ToolCall`-shaped input carries an id, so the run wrapper hands back a
    `ToolMessage` with `.artifact` intact instead of silently dropping it.
    """
    message = await tool.ainvoke(
        {"name": tool.name, "args": args, "id": "test-call", "type": "tool_call"}
    )
    return message.content, message.artifact


async def test_search_sources_reports_every_hit_it_printed(seeded_corpus) -> None:
    tools = build_corpus_tools(seeded_corpus)
    text, artifact = await invoke_for_artifact(
        tool_named(tools, "search_sources"), {"pattern": "magic"}
    )

    assert artifact["shape"] == "hit_list"
    carried = sum(len(source["hits"]) for source in artifact["sources"])
    # Not `text.count(" | ")` -- a snippet can itself contain " | ", which
    # would silently over-count. Count match lines by their own leading
    # shape instead. The controller's binding ruling on this plan.
    printed = len(re.findall(r"^\s{2}\S+@\d+-\d+", text, flags=re.MULTILINE))
    assert carried == printed, "every line the model was shown is a hit the console can draw"
    assert artifact["total"] >= carried


async def test_the_string_the_model_reads_did_not_change(seeded_corpus) -> None:
    """The whole design rests on this: the artifact is additive, so no prompt,
    checkpoint or eval moves. Red if a tool starts formatting for the console."""
    tools = build_corpus_tools(seeded_corpus)
    text, _ = await invoke_for_artifact(
        tool_named(tools, "search_sources"), {"pattern": "magic"}
    )

    listings = await seeded_corpus.list_sources()
    expression = re.compile("magic", re.IGNORECASE)
    # `collect_matches` needs the corpus, not just its listings: `SourceListing`
    # is metadata only, and matching still has to read each source's text.
    hits, suppressed, _ = await corpus_tools.collect_matches(
        expression, seeded_corpus, listings
    )
    assert text == corpus_tools.format_matches("magic", hits, suppressed)


async def test_an_excerpt_carries_the_span_and_the_whole_length(seeded_corpus) -> None:
    """The ruler is the point of this card: 9% of a document read from near
    its start is a different claim than the whole of it."""
    tools = build_corpus_tools(seeded_corpus)
    _, artifact = await invoke_for_artifact(
        tool_named(tools, "read_source"),
        {"source_id": "seed-one", "start": 100, "end": 300},
    )

    assert artifact["shape"] == "excerpt"
    assert artifact["start"] == 100
    assert artifact["end"] <= 300
    assert artifact["char_count"] > artifact["end"] - artifact["start"]


async def test_an_empty_corpus_still_answers_with_a_shape(empty_corpus) -> None:
    """A miss is a rendering, not a fallback. `sources: []` draws "no matches
    for X"; a `None` artifact would silently drop to the text path and look
    identical to a tool nobody converted."""
    tools = build_corpus_tools(empty_corpus)
    _, artifact = await invoke_for_artifact(
        tool_named(tools, "search_sources"), {"pattern": "x"}
    )

    assert artifact["shape"] == "hit_list"
    assert artifact["sources"] == []


async def test_list_sources_reports_an_inventory(seeded_corpus) -> None:
    tools = build_corpus_tools(seeded_corpus)
    text, artifact = await invoke_for_artifact(tool_named(tools, "list_sources"), {})

    assert artifact["shape"] == "inventory"
    assert artifact["unit"] == "chars"
    assert {item["item_id"] for item in artifact["items"]} == {"seed-one", "seed-two"}
    assert text == corpus_tools.format_listing(await seeded_corpus.list_sources())


async def test_an_unknown_source_read_answers_a_failed_acknowledgement(
    seeded_corpus,
) -> None:
    tools = build_corpus_tools(seeded_corpus)
    text, artifact = await invoke_for_artifact(
        tool_named(tools, "read_source"), {"source_id": "does-not-exist"}
    )

    assert artifact["shape"] == "acknowledgement"
    assert artifact["ok"] is False
    assert artifact == {
        "shape": "acknowledgement",
        "version": 1,
        "action": "read_source",
        "subject": "does-not-exist",
        "detail": text,
        "ok": False,
    }
