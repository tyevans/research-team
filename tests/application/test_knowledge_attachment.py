"""`KnowledgeAttachment`: opening and closing a project's graph mid-session.

Uses the real `RedstringKnowledge` over an in-memory graph store and
`fake_provider()` -- the redstring wiring this exercises is genuine, only the
executor is a stand-in. Shares the `repository` fixture's event store rather
than constructing a second `SQLiteSnapshotStore` (BACKLOG B5: a second one
leaks a non-daemon thread).
"""

from uuid import uuid4

import pytest
from redstring import InMemoryGraphStore

from research_team.application.knowledge_attachment import KnowledgeAttachment
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from tests.conftest import fake_provider


class _FakeTool:
    """Stands in for a `BaseTool`: only `.name` is ever read here."""

    def __init__(self, name: str) -> None:
        self.name = name


class _FakeExecutor:
    """A `TurnExecutorTools` that just remembers the last tool list."""

    def __init__(self, tools):
        self._tools = tuple(tools)

    @property
    def tools(self):
        return self._tools

    def set_tools(self, tools):
        self._tools = tuple(tools)


BASE_TOOLS = (_FakeTool("search"),)
KNOWLEDGE_TOOL_NAMES = {"remember", "graph_search", "unmerge"}


def _build(repository, *, fails: bool = False):
    """One `KnowledgeAttachment` wired the way composition wires it, minus
    the real store/model choices -- `open_graph` builds a real
    `RedstringKnowledge` over an in-memory store; `fails` makes it raise
    instead, to exercise the atomic-failure path."""

    async def open_graph(project_id):
        if fails:
            raise RuntimeError("graph store unreachable")
        knowledge = RedstringKnowledge(
            project_id,
            store=InMemoryGraphStore(),
            event_store=repository.store,
            snapshot_store=repository.snapshot_store,
            provider=fake_provider(),
            domain="auto",
        )
        tools = tuple(_FakeTool(name) for name in KNOWLEDGE_TOOL_NAMES)
        return knowledge, tools

    closed = []

    async def close_graph(knowledge):
        closed.append(knowledge)

    executor = _FakeExecutor(BASE_TOOLS)
    attachment = KnowledgeAttachment(
        executor, BASE_TOOLS, open_graph=open_graph, close_graph=close_graph
    )
    return attachment, executor, closed


def _tool_names(executor) -> set[str]:
    return {tool.name for tool in executor.tools}


async def test_before_attach_nothing_is_current_and_no_knowledge_tools(repository):
    attachment, executor, _ = _build(repository)

    assert attachment.current is None
    # Equality with the base tuple, read off the executor's own (mutable)
    # `tools` property -- not `"remember" not in BASE_TOOLS`, which would
    # hold no matter what `KnowledgeAttachment.__init__` did, since nothing
    # in `BASE_TOOLS` was ever going to contain it. This would fail if
    # construction ever pre-attached something onto the executor.
    assert executor.tools == BASE_TOOLS


async def test_attach_registers_current_and_all_three_knowledge_tools(repository):
    attachment, executor, _ = _build(repository)

    await attachment.attach(uuid4())

    assert attachment.current is not None
    assert _tool_names(executor) >= KNOWLEDGE_TOOL_NAMES


async def test_detach_restores_exactly_the_base_tools(repository):
    attachment, executor, _ = _build(repository)
    await attachment.attach(uuid4())

    await attachment.detach()

    # Equality with the base tuple, not merely "remember is gone" -- a
    # detach that left some other tool behind would still pass a weaker
    # assertion.
    assert executor.tools == BASE_TOOLS
    assert attachment.current is None


async def test_a_failed_open_leaves_nothing_attached(repository):
    """An unreachable graph store must not half-attach.

    If `open_graph` raises, the executor's tools must be untouched and
    `current` must stay None -- the session stays usable without knowledge
    rather than ending up in a state where some but not all of the attach
    happened.
    """
    attachment, executor, _ = _build(repository, fails=True)

    with pytest.raises(RuntimeError):
        await attachment.attach(uuid4())

    assert attachment.current is None
    assert executor.tools == BASE_TOOLS


async def test_attaching_twice_leaves_exactly_one_graph_for_the_second_project(repository):
    attachment, executor, closed = _build(repository)
    first_project = uuid4()
    second_project = uuid4()

    await attachment.attach(first_project)
    first_knowledge = attachment.current
    await attachment.attach(second_project)

    assert attachment.current.project_id == second_project
    # Exactly one graph's tools are on the executor -- attaching again did
    # not append a second copy of the three knowledge tools.
    assert _tool_names(executor) == KNOWLEDGE_TOOL_NAMES | {"search"}
    assert len(executor.tools) == len(BASE_TOOLS) + len(KNOWLEDGE_TOOL_NAMES)
    # The graph attaching over replaced was actually closed, not leaked --
    # the branch `attach` takes to avoid leaking a store when re-attaching.
    assert closed == [first_knowledge]
