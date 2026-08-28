"""Validation of interactive components, delivered in the write that caused it.

`components.py` can say precisely what is wrong with a component. This is the
part that makes the model hear it.

**Why a middleware rather than a tool.** The obvious design is a
`validate_component` tool the model calls before writing. It is also the design
that fails quietly: it depends on the model choosing to call it, on a long
autonomous run, at the point where nobody is reading the transcript. Hooking
the parse into the write path instead closes the loop whether or not the model
was minded to, and costs no new tool surface.

**Why not the backend.** `EventSourcedBackend` is where a write becomes an
event, so it looks like the natural home -- but deepagents' `write_file` tool
builds its own result string (`f"Updated file {res.path}"`) from a
`WriteResult` that carries only a path and an error. There is no slot for a
message, and the two ways to fake one -- smuggling the report through `path`,
or reporting a successful write as an `error` -- are both worse than reaching
for the hook langchain provides for exactly this.

**Async, because the sync hook is never called here.** `DeepAgentTurnExecutor`
streams, so `awrap_tool_call` is the one that runs; the sync `wrap_tool_call`
is dead code here and a hook written into it never fires.

**Best-effort, always.** Every failure path returns the tool's own result
untouched: a file the aggregate cannot read back, a result that is a `Command`
rather than a message, a read that raises. Authoring feedback is worth having
and it is not worth a turn, and a hook that can fail a write is a hook that
will eventually fail one at the worst moment.
"""

from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from research_team.application.components import parse_document, validation_report

WRITE_TOOLS = frozenset({"write_file", "edit_file"})
"""The tools that leave a document behind. `delete` leaves nothing to check."""

MARKDOWN_SUFFIXES = (".md", ".markdown", ".mdown", ".mkd")
"""The same set the client's `isMarkdownPath` gates on. Components only mean
anything in a file something will render as markdown."""


class ComponentFeedback(AgentMiddleware):
    """Append component errors and warnings to the result of a write.

    Reads the file back rather than inspecting the tool's arguments, because
    `edit_file` carries a replacement and not a document -- only the file that
    the edit actually produced can be parsed. `read` is therefore called after
    the tool has run, when the aggregate already holds the new content.
    """

    def __init__(self, read: Callable[[str], str | None]) -> None:
        super().__init__()
        self._read = read

    async def awrap_tool_call(
        self,
        request,
        handler: Callable[[object], Awaitable[object]],
    ):
        result = await handler(request)

        call = getattr(request, "tool_call", None) or {}
        if call.get("name") not in WRITE_TOOLS:
            return result
        if not isinstance(result, ToolMessage) or result.status == "error":
            return result

        path = (call.get("args") or {}).get("file_path")
        if not isinstance(path, str) or not path.lower().endswith(MARKDOWN_SUFFIXES):
            return result

        try:
            content = self._read(path)
        except Exception:  # noqa: BLE001 -- see the module docstring: never a turn
            return result
        if not isinstance(content, str):
            return result

        report = validation_report(parse_document(content, path=path))
        if not report:
            # Silence on success is deliberate. A suffix appended to every
            # write is a suffix the model stops reading, which would cost us
            # the one case it exists for.
            return result

        return result.model_copy(update={"content": f"{result.content}\n\n{report}"})
