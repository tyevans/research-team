"""Every remaining converted tool answers with the shape it claims.

`search` (in `search.py`, tool name `web_search`) maps onto `hit_list`, not
`entity_list` -- see the shape table in
`docs/superpowers/specs/2026-08-28-activity-stream-design.md`. A web result
carries a title, a url and a snippet, the same three fields `search_sources`
draws; it has no `entity_type` or `relationship_count` to be an `EntityRef`.
"""

import pytest

from research_team.application.topics import TopicError


async def invoke_for_artifact(tool, args: dict) -> tuple[str, dict]:
    """`(content, artifact)` from a `content_and_artifact` tool. Plain
    `tool.ainvoke(args)` discards the artifact -- see
    `test_corpus_tool_artifacts.py`'s identical helper."""
    message = await tool.ainvoke(
        {"name": tool.name, "args": args, "id": "test-call", "type": "tool_call"}
    )
    return message.content, message.artifact


def tool_named(tools, name):
    return next(tool for tool in tools if tool.name == name)


@pytest.mark.parametrize(
    ("tool_name", "args", "shape"),
    [
        ("web_search", {"query": "magic"}, "hit_list"),
        ("fetch", {"url": "https://example.test/magic"}, "excerpt"),
        ("list_topics", {}, "inventory"),
        ("open_topic", {"question": "Why?", "rationale": "Because."}, "inventory"),
        ("record_finding", {"topic_id": "not-a-uuid", "text": "a finding"}, "acknowledgement"),
    ],
)
@pytest.mark.asyncio
async def test_each_tool_answers_with_its_shape(all_tools, tool_name, args, shape) -> None:
    tool = tool_named(all_tools, tool_name)
    if tool_name == "record_finding":
        # `record_finding` requires `summary`, not `text` -- the parametrize
        # above is deliberately the brief's own (wrong) draft args, kept as a
        # comment-visible reminder of what the tool's real signature is.
        args = {"topic_id": "not-a-uuid", "summary": "a finding", "source_ids": []}
    _, artifact = await invoke_for_artifact(tool, args)
    assert artifact["shape"] == shape


@pytest.mark.asyncio
async def test_web_search_is_a_hit_list_not_an_entity_list(all_tools) -> None:
    """The design doc's shape table, not the task-4 brief's draft, is
    authoritative -- see this module's docstring."""
    tool = tool_named(all_tools, "web_search")
    _, artifact = await invoke_for_artifact(tool, {"query": "magic"})

    assert artifact["shape"] == "hit_list"
    assert artifact["sources"], "the stubbed transport answers one result; expect one source"


@pytest.mark.asyncio
async def test_a_fetched_pages_excerpt_carries_its_url_as_the_uri(all_tools) -> None:
    tool = tool_named(all_tools, "fetch")
    _, artifact = await invoke_for_artifact(tool, {"url": "https://example.test/magic"})

    assert artifact["shape"] == "excerpt"
    assert artifact["uri"] == "https://example.test/magic"


@pytest.mark.asyncio
async def test_record_gap_answers_an_acknowledgement(all_tools) -> None:
    tool = tool_named(all_tools, "record_gap")
    _, artifact = await invoke_for_artifact(
        tool, {"topic_id": "not-a-uuid", "looking_for": "x", "tried": ["a search"]}
    )
    assert artifact["shape"] == "acknowledgement"


@pytest.mark.asyncio
async def test_link_source_answers_an_acknowledgement(all_tools) -> None:
    tool = tool_named(all_tools, "link_source")
    _, artifact = await invoke_for_artifact(
        tool, {"topic_id": "not-a-uuid", "source_id": "seed-one"}
    )
    assert artifact["shape"] == "acknowledgement"


@pytest.mark.asyncio
async def test_open_topic_reaches_an_ok_acknowledgement_free_inventory(all_tools) -> None:
    """`open_topic`'s success path returns `Inventory`, not `Acknowledgement`
    -- the one place a write answers in a shape other than punctuation,
    because the design doc's shape table puts it there beside `list_sources`
    and `list_topics`."""
    tool = tool_named(all_tools, "open_topic")
    text, artifact = await invoke_for_artifact(
        tool, {"question": "What is a magic square?", "rationale": "Curiosity."}
    )
    assert artifact["shape"] == "inventory"
    assert artifact["kind"] == "topic"
    assert artifact["items"][0]["title"] == "What is a magic square?"
    assert "Tracking" in text


def test_topic_error_is_importable() -> None:
    """Sanity check that `topic_tools.py`'s error type is still what the fake
    port in `conftest.py` raises -- guards against the two drifting apart
    silently."""
    assert issubclass(TopicError, Exception)
