"""Telling the author what it just wrote wrong, in the result of the write.

The alternative -- a `validate_component` tool the model is asked to call
before writing -- depends on the model choosing to call it, which is exactly
the kind of instruction-following that degrades on a long run at the point
nobody is watching. Hooking the parse into the write path costs no new tool
surface and closes the loop whether or not the model was minded to.

What it must not do is be noisy. A write that produced nothing wrong returns
the string it always did, byte for byte, because a suffix on every successful
write is a suffix the model learns to skip.
"""

from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage

from research_team.infrastructure.agent.component_feedback import ComponentFeedback

GOOD = """\
```component:mcq
id: sev-1
prompt: What severity?
options:
  - text: "SEV-1"
    correct: false
  - text: "SEV-2"
    correct: true
```
"""

MISSING_OPTIONS = "```component:mcq\nid: sev-1\nprompt: What severity?\n```\n"
NO_ID = "```component:checklist\nitems:\n  - text: Go\n```\n"


def _request(tool="write_file", path="/course/01.md"):
    return SimpleNamespace(tool_call={"name": tool, "args": {"file_path": path}})


async def _run(files, request, content="Updated file /course/01.md", status="success"):
    middleware = ComponentFeedback(read=files.get)

    async def handler(_):
        return ToolMessage(
            content=content, name=request.tool_call["name"], tool_call_id="t1", status=status
        )

    return await middleware.awrap_tool_call(request, handler)


async def test_a_clean_write_returns_exactly_what_it_returned_before():
    result = await _run({"/course/01.md": GOOD}, _request())
    assert result.content == "Updated file /course/01.md"


async def test_a_broken_component_is_reported_in_the_write_result():
    result = await _run({"/course/01.md": MISSING_OPTIONS}, _request())
    assert result.content.startswith("Updated file /course/01.md")
    assert "error:" in result.content
    assert "'sev-1'" in result.content and "options" in result.content


async def test_a_warning_reaches_the_author_too():
    """A derived id renders fine today and detaches learner state tomorrow."""
    result = await _run({"/course/01.md": NO_ID}, _request())
    assert "warning:" in result.content
    assert "id" in result.content


async def test_an_edit_is_validated_against_the_file_it_produced():
    """`edit_file` carries a replacement, not a document, so the check has to
    read back what the edit actually left behind."""
    result = await _run({"/course/01.md": MISSING_OPTIONS}, _request(tool="edit_file"))
    assert "error:" in result.content


@pytest.mark.parametrize("tool", ["read_file", "ls", "grep", "task"])
async def test_tools_that_do_not_write_are_left_alone(tool):
    result = await _run({"/course/01.md": MISSING_OPTIONS}, _request(tool=tool))
    assert result.content == "Updated file /course/01.md"


async def test_a_failed_write_is_not_annotated():
    """The tool already said why it failed; a parse of the old file is noise."""
    result = await _run(
        {"/course/01.md": MISSING_OPTIONS}, _request(), content="nope", status="error"
    )
    assert result.content == "nope"


@pytest.mark.parametrize("path", ["/notes.py", "/data.json", "/README"])
async def test_files_that_are_not_markdown_are_not_parsed(path):
    result = await _run({path: MISSING_OPTIONS}, _request(path=path))
    assert result.content == "Updated file /course/01.md"


async def test_a_file_that_cannot_be_read_back_is_not_an_error():
    """A write to a path the aggregate does not hold is somebody else's bug,
    and failing the tool call over it would turn a mystery into an outage."""
    result = await _run({}, _request())
    assert result.content == "Updated file /course/01.md"


async def test_a_read_that_raises_does_not_take_the_turn_down():
    """Authoring feedback is a nicety. Losing a turn over it is not a trade
    anybody would make, so the whole hook is best-effort by construction."""

    def explode(_path):
        raise RuntimeError("the filesystem is on fire")

    middleware = ComponentFeedback(read=explode)

    async def handler(_):
        return ToolMessage(content="Updated file /x.md", name="write_file", tool_call_id="t")

    result = await middleware.awrap_tool_call(_request(), handler)
    assert result.content == "Updated file /x.md"


async def test_a_non_message_result_passes_straight_through():
    """Some tools return a `Command`. Appending a string to one is meaningless."""
    middleware = ComponentFeedback(read={"/course/01.md": MISSING_OPTIONS}.get)
    sentinel = object()

    async def handler(_):
        return sentinel

    assert await middleware.awrap_tool_call(_request(), handler) is sentinel
