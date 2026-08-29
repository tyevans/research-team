"""Real tools, real stores, real artifacts.

This is the *port with one adapter* rule from CLAUDE.md. The co-mention channel
shipped fully unit-tested from both sides and produced nothing for a whole
feature, because nothing drove the real writer into the real reader. A renderer
test fed a hand-written literal cannot see a tool that never populates its
artifact.
"""

import pytest

from research_team.application.tool_artifacts import SHAPES

PRODUCED_BY_TOOLS = {
    "hit_list",
    "entity_list",
    "excerpt",
    "inventory",
    "acknowledgement",
}
NOT_TOOL_PRODUCED = {"file_change", "delegation"}


def test_the_registry_covers_every_shape_a_tool_can_produce() -> None:
    """Fails at collection-adjacent time if an eighth shape is added and left
    unclaimed by either set -- documentation would not."""
    assert set(SHAPES) == PRODUCED_BY_TOOLS | NOT_TOOL_PRODUCED


async def _invoke(tool, args: dict) -> tuple[str, dict | None]:
    """`(content, artifact)`, using a `ToolCall`-shaped input.

    Plain `tool.ainvoke(args)` -- the shape the task-5 brief's own draft of
    this test used -- discards the artifact: in the installed langchain-core,
    `BaseTool._format_output` returns bare `content` whenever `tool_call_id`
    is `None`, and a plain-dict `ainvoke` never supplies one. A test written
    the brief's way would pass regardless of whether any tool populated an
    artifact at all, which is exactly the false-positive this contract test
    exists to rule out.
    """
    message = await tool.ainvoke(
        {"name": tool.name, "args": args, "id": "test-call", "type": "tool_call"}
    )
    return message.content, message.artifact


@pytest.mark.parametrize("shape", sorted(PRODUCED_BY_TOOLS))
@pytest.mark.asyncio
async def test_every_shape_is_produced_by_a_real_tool_call(live_tools, shape) -> None:
    produced = set()
    for tool, args in live_tools:
        _, artifact = await _invoke(tool, args)
        if artifact:
            produced.add(artifact["shape"])
    assert shape in produced, f"no real tool call produced a {shape} artifact"


@pytest.mark.asyncio
async def test_no_live_tool_call_answers_with_a_none_artifact(live_tools) -> None:
    """Every converted tool -- error path or not -- carries a shape. `None`
    is reserved for a message written before this feature, or a tool nobody
    has converted; a converted tool answering `None` looks identical to
    either from the console and hides which one it actually is."""
    for tool, args in live_tools:
        _, artifact = await _invoke(tool, args)
        assert artifact is not None, f"{tool.name} answered with no artifact at all"
