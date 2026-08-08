"""The single owner of an open knowledge-graph store per project.

A `GraphStore` used to exist only inside `open_graph`, for as long as a
project stayed attached to a turn executor: built, folded from the log, and
handed to the executor's tools. That was enough while the only reader was
the agent mid-turn. It stops being enough the moment something else wants to
read the same graph -- a browser route, in particular -- because a second
store rebuilt independently is correct at the instant it is built and wrong
immediately after: extraction writes to the one attached to the turn, and
the independent copy keeps answering from a snapshot of the past. Ingest a
document, open the graph browser, see nothing new.

So there is exactly one store per project, and this is what owns it. Every
caller that wants a project's graph -- attachment, a read route, anything
else that shows up later -- asks `open` and gets the same object, which is
what makes "the graph extraction just wrote to" and "the graph the browser
just read" the same graph rather than two that happen to agree by luck.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

# Names no redstring type, the way `knowledge_attachment.py`'s `OpenGraph`
# and `CloseGraph` do not: what a store actually is is composition-root and
# adapter knowledge, and this module only ever calls `ensure_schema` and
# `close` on one through `hasattr`, never anything that requires the real
# type to type-check.

#: Builds a fresh, unopened store. A callable rather than a store instance
#: because one store cannot serve two projects -- each `open` that actually
#: rebuilds needs its own.
BuildStore = Callable[[], Any]

#: Folds one project's knowledge events into a store that was just built.
#: Takes the store and the project id; closes over whatever feed it reads
#: from, the way `open_graph` used to close over `repository.store` directly.
Rebuild = Callable[[Any, UUID], Awaitable[None]]


class ProjectGraphs:
    """Opens, caches, and closes one `GraphStore` per project.

    `open` is idempotent: the same project returns the same store object for
    as long as it stays open, so attachment and a read route see one graph,
    not two that can drift apart. Concurrent callers opening the same
    project for the first time must still only rebuild once -- a naive
    "check the dict, then build" races five callers into five rebuilds -- so
    the build is guarded by a lock kept per project. A single lock shared by
    every project would serialise unrelated projects' first opens against
    each other for no reason; a lock per id only ever contends with itself.
    """

    def __init__(self, *, build_store: BuildStore, rebuild: Rebuild) -> None:
        self._build_store = build_store
        self._rebuild = rebuild
        self._stores: dict[UUID, Any] = {}
        self._locks: dict[UUID, asyncio.Lock] = {}

    def _lock_for(self, project_id: UUID) -> asyncio.Lock:
        # `dict.setdefault` is synchronous and this coroutine has not
        # suspended since entering `open`, so there is no window for two
        # callers to each believe they created the lock for this id.
        return self._locks.setdefault(project_id, asyncio.Lock())

    async def open(self, project_id: UUID) -> Any:
        """This project's store, building and folding it in on first ask.

        Every caller passes through the per-project lock, including ones
        that will find the store already cached -- the lock is cheap to
        acquire when uncontended, and re-checking the cache first (outside
        the lock) would just be a second place for the same race to hide.
        """
        async with self._lock_for(project_id):
            store = self._stores.get(project_id)
            if store is not None:
                return store
            store = self._build_store()
            # `ensure_schema` is the first call that actually talks to a
            # Neo4j server; a no-op for the in-memory store, which has none.
            if hasattr(store, "ensure_schema"):
                await store.ensure_schema()
            await self._rebuild(store, project_id)
            self._stores[project_id] = store
            return store

    async def close(self, project_id: UUID) -> None:
        """Evict this project's store, closing it if it has a close to run.

        A later `open` rebuilds from scratch rather than resuming: this is
        the only path that removes a project from the cache, so the cache
        cannot hold a closed handle by accident, and the lock stays in the
        dict rather than being torn down out from under a caller that is
        still waiting on it.
        """
        store = self._stores.pop(project_id, None)
        if store is not None and hasattr(store, "close"):
            await store.close()

    async def close_all(self) -> None:
        """Close every cached store. For process shutdown."""
        for project_id in list(self._stores):
            await self.close(project_id)
