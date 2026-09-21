"""Attaching a project's knowledge graph to an executor already built.

The graph cannot be wired at construction, because which project a session
belongs to is decided at runtime -- long after the application is built. But
`TurnExecutorTools.set_tools` replaces what the next turn sees, so attaching
later is enough: no application rebuild, no dynamic tool binding.

Names no redstring, langchain, or infrastructure type: opening and closing a
graph is delegated to callables the composition root supplies, the same way
`KnowledgePort` keeps the vocabulary above it free of adapter details. That is
what lets this live in `application/` without naming an adapter.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any, Protocol
from uuid import UUID


def _compose(base: Sequence[Any], attached: Sequence[Any]) -> list[Any]:
    """`base` and `attached`, with an attached tool replacing a base one of
    the same name.

    `fetch` is the reason this exists. It is built once at composition with no
    project, and a corpus-aware version of it can only be built once a project
    is known -- which is here. Both are called `fetch`, so without shadowing
    the executor would hold two tools of one name and which one the model
    reached would be an accident of ordering.

    The alternative was handing the base tool a mutable slot for the current
    project's corpus. That fails on `detach`: nothing would clear the slot, so
    a session that left a project would keep reading its sources. Shadowing
    makes that impossible rather than merely discouraged, because restoring
    the base set is something `detach` already does.

    Anything without a `.name` cannot collide and is kept.
    """
    shadowed = {name for tool in attached if (name := getattr(tool, "name", None))}
    kept = [tool for tool in base if getattr(tool, "name", None) not in shadowed]
    return [*kept, *attached]


class TurnExecutorTools(Protocol):
    """The slice of a turn executor this needs: its tools, replaceable between turns."""

    @property
    def tools(self) -> tuple[Any, ...]: ...

    def set_tools(self, tools: Sequence[Any]) -> None: ...


#: Opens one project's graph and returns it alongside the tools it lends the
#: agent. Raises rather than returning a half-open graph -- `attach` relies on
#: that to stay atomic.
OpenGraph = Callable[[UUID], Awaitable[tuple[Any, Sequence[Any]]]]

#: Releases whatever `OpenGraph` returned as its first element.
CloseGraph = Callable[[Any], Awaitable[None]]


class KnowledgeAttachment:
    """Opens a project's graph on demand, and lends its tools to the executor.

    Holds the base tool set so `detach` can restore it exactly, rather than
    trying to subtract the knowledge tools back out -- subtraction would have
    to assume nothing else ever touches the executor's tool list between an
    attach and a detach, which is not a guarantee this class can make.
    """

    def __init__(
        self,
        executor: TurnExecutorTools,
        base_tools: Sequence[Any],
        *,
        open_graph: OpenGraph,
        close_graph: CloseGraph,
        on_attached: Callable[[UUID], Awaitable[None]] | None = None,
        on_detached: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._executor = executor
        self._base_tools = tuple(base_tools)
        self._open_graph = open_graph
        self._close_graph = close_graph
        self._on_attached = on_attached
        self._on_detached = on_detached
        self.current: Any | None = None
        """The attached graph, or None with no project attached."""

        self.attached_project_id: UUID | None = None
        """Which project `current` belongs to, or None with nothing attached."""
        self._attached_tools: tuple[Any, ...] = ()

    @property
    def is_attached(self) -> bool:
        """Whether a project's knowledge graph is currently attached."""
        return self.current is not None

    @property
    def attached_tools(self) -> tuple[Any, ...]:
        """The tools contributed by the knowledge attachment."""
        return self._attached_tools

    @asynccontextmanager
    async def session(self, project_id: UUID) -> AsyncIterator["KnowledgeAttachment"]:
        """Scoped attachment context manager that guarantees clean detachment."""
        await self.attach(project_id)
        try:
            yield self
        finally:
            await self.detach()

    async def refresh(self) -> None:
        """Re-attach the current project if one is currently attached."""
        if self.attached_project_id is not None:
            await self.attach(self.attached_project_id)

    async def attach(self, project_id: UUID) -> None:
        """Open `project_id`'s graph and swap its tools into the executor.

        Atomic in effect: if `open_graph` raises -- an unreachable Neo4j, a
        replay that refuses a partial graph -- nothing here has happened yet,
        so the executor's tools are untouched and `current` stays None. The
        session stays usable without knowledge rather than half-attached.
        """
        knowledge, tools = await self._open_graph(project_id)
        previous = self.current
        self._executor.set_tools(_compose(self._base_tools, tools))
        self.current = knowledge
        self.attached_project_id = project_id
        self._attached_tools = tuple(tools)
        if previous is not None:
            await self._close_graph(previous)
        if self._on_attached is not None:
            await self._on_attached(project_id)

    async def detach(self) -> None:
        """Close whatever is attached and restore the base tools exactly.

        A no-op past restoring the tools when nothing is attached, so every
        caller that is "leaving a project, if it was in one" can call this
        unconditionally.
        """
        if self.current is not None:
            await self._close_graph(self.current)
        self._executor.set_tools(self._base_tools)
        self.current = None
        self.attached_project_id = None
        self._attached_tools = ()
        if self._on_detached is not None:
            await self._on_detached()
