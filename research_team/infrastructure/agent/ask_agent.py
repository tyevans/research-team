"""A deep agent that can read a project and change nothing about it.

The executor behind `AskService`. It reuses the project tools that
`build_application.open_graph` assembles, keeps only the readers, and gives
the built-in file tools a backend that refuses to write.
"""

from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Any
from uuid import UUID

from deepagents import FilesystemMiddleware, create_deep_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import BaseTool

from research_team.application.ask import AskAnswer, AskMessage, Citation
from research_team.application.corpus_read import (
    LIST_SOURCES_TOOL,
    READ_SOURCE_TOOL,
    REFERENCE_SYNTAX_PROMPT,
)
from research_team.application.knowledge import GRAPH_SEARCH_TOOL
from research_team.application.ports import ActivityReporter
from research_team.application.topics import LIST_TOPICS_TOOL
from research_team.infrastructure.agent.deep_agent import (
    to_activity_delta,
    to_activity_message,
)
from research_team.infrastructure.agent.messages import last_text
from research_team.infrastructure.agent.read_only_backend import ReadOnlyProjectBackend

READ_ONLY_TOOLS = frozenset(
    {
        LIST_SOURCES_TOOL,
        READ_SOURCE_TOOL,
        GRAPH_SEARCH_TOOL,
        LIST_TOPICS_TOOL,
    }
)
"""The tools the ask agent may hold.

An allowlist rather than a denylist so that a tool added to `open_graph`
later is excluded until someone names it here. `fetch` and `web_search` are
absent, which is also why this path wires no approval gate: there is nothing
to gate.

`open_topic` was named here when this was written, on the spec's description of
it as a reader. It is not: it runs an `OpenTopic` command and creates a `Topic`
aggregate, so a page whose whole contract is that it changes nothing cannot
hold it. Every other topic tool was already excluded for the same reason.

The names are imported from the application layer rather than retyped, so a
tool renamed at its definition cannot leave a stale string here silently
filtering it out.
"""

READ_ONLY_FILE_TOOLS = ["ls", "read_file", "glob", "grep"]
"""The built-in file tools the agent is offered at all.

`permissions=[FilesystemPermission(..., mode="deny")]` was tried first and is
not this: it leaves `write_file`, `edit_file` and `delete` on the model's tool
list and answers a call with a permission error, which costs a wasted turn and
contradicts a prompt that says the project cannot be changed. Only
`FilesystemMiddleware`'s own `tools` argument drops them before they are
advertised, and passing a replacement in `middleware` is how `create_deep_agent`
lets a caller reach it -- it merges by middleware name, so the default
filesystem stack is replaced rather than doubled, and the general-purpose
subagent inherits the replacement.

`ReadOnlyProjectBackend` still raises on a write. This list decides what is
offered; the backend decides what could ever land, and neither is trusted to
be the only one.
"""

CITED_BY_TOOL = {READ_SOURCE_TOOL: ("source", "source_id")}
"""Tool name -> (citation kind, the argument naming what was read).

`read_source` alone: it is the only admitted tool that opens one identified
thing. A search returns candidates the agent may never read, so it earns no
citation, and listing is not reading either.

`open_topic` was mapped here too, to `("topic", "topic_id")` -- an argument it
does not have, so no real call could ever have produced that citation. It is
gone from the allowlist above, and `Citation.kind` narrowed with it rather than
keeping a union member nothing can emit.
"""

ASK_PROMPT = (
    """You are answering questions about one research project's gathered material.

Use the tools to look things up before answering. You can read the project's
sources, its knowledge graph, its topics and its files. You cannot change any
of them, and you have no access to the web -- if the material does not answer
the question, say so plainly rather than filling the gap from memory.

Prefer quoting what a source actually says over paraphrasing it, and say which
source you got something from.

"""
    + REFERENCE_SYNTAX_PROMPT
)


def readable(tools: Iterable[BaseTool]) -> tuple[BaseTool, ...]:
    return tuple(tool for tool in tools if tool.name in READ_ONLY_TOOLS)


def citations(messages: Sequence[BaseMessage]) -> tuple[Citation, ...]:
    """What the agent opened, in the order it opened it.

    Derived from tool calls rather than from the answer's prose, so the agent
    cannot cite a document it never read. Ordered rather than a set, so two
    identical runs produce identical output.
    """
    found: list[Citation] = []
    seen: set[tuple[str, str]] = set()
    for message in messages:
        for call in getattr(message, "tool_calls", ()) or ():
            cited = CITED_BY_TOOL.get(call.get("name", ""))
            if cited is None:
                continue
            kind, argument = cited
            identifier = (call.get("args") or {}).get(argument)
            if not identifier or (kind, str(identifier)) in seen:
                continue
            seen.add((kind, str(identifier)))
            found.append(Citation(kind=kind, id=str(identifier)))
    return tuple(found)


def _history(history: Sequence[AskMessage], question: str) -> list[BaseMessage]:
    prior: list[BaseMessage] = [
        HumanMessage(content=message.text)
        if message.role == "user"
        else AIMessage(content=message.text)
        for message in history
    ]
    return [*prior, HumanMessage(content=question)]


class DeepAgentAskExecutor:
    """Runs one question. Builds a fresh agent per question, as the turn
    executor does per pass -- the tools are bound to a project and a stale
    agent would answer about the wrong one."""

    def __init__(
        self,
        *,
        model: BaseChatModel,
        open_graph: Callable[[UUID], Awaitable[tuple[Any, tuple[BaseTool, ...]]]],
        project_files: Callable[[UUID], Awaitable[dict[str, Any]]],
        system_prompt: str = ASK_PROMPT,
    ) -> None:
        self._model = model
        self._open_graph = open_graph
        self._project_files = project_files
        self._system_prompt = system_prompt

    async def run(
        self,
        *,
        project_id: UUID,
        history: Sequence[AskMessage],
        question: str,
        on_activity: ActivityReporter,
    ) -> AskAnswer:
        """Answer one question, reporting activity as it happens.

        Every `on_activity` call is made from inside this coroutine and none is
        deferred to a callback that could outlive it, which is the contract
        `AskExecutor` states and `AskService._drain` relies on for a final note
        to reach the reader.
        """
        _knowledge, project_tools = await self._open_graph(project_id)
        backend = ReadOnlyProjectBackend(await self._project_files(project_id))
        agent = create_deep_agent(
            model=self._model,
            tools=list(readable(project_tools)) or None,
            backend=backend,
            middleware=[FilesystemMiddleware(backend=backend, tools=READ_ONLY_FILE_TOOLS)],
            system_prompt=self._system_prompt,
            # No checkpointer. A `MemorySaver` was wired here on the turn
            # executor's pattern and was worse than useless: langgraph refuses
            # to run a checkpointed root graph without a `thread_id` in the
            # config, and `astream` below passes none, so *every* question
            # raised `ValueError`. Adding a thread id would have bought a
            # checkpoint nothing ever resumes -- the agent is fresh per
            # question and the transcript is carried in `history`.
            # `test_the_answer_is_the_models_last_text` is what fails if a
            # checkpointer comes back without a config.
        )

        messages = _history(history, question)
        final: list[BaseMessage] = list(messages)
        reported = len(messages)
        async for mode, chunk in agent.astream(
            {"messages": messages}, stream_mode=["values", "messages"]
        ):
            if mode == "values":
                final = chunk.get("messages", final)
                for message in final[reported:]:
                    note = to_activity_message(message)
                    if note is not None:
                        on_activity(note)
                reported = len(final)
            elif mode == "messages":
                delta = to_activity_delta(chunk)
                if delta is not None:
                    on_activity(delta)

        # `last_text` rather than reading the tail message directly: the final
        # state can end on a `ToolMessage`, and `AIMessage.text` is a property
        # in the pinned langchain-core, so calling it would raise.
        return AskAnswer(text=last_text(final), citations=citations(final))
