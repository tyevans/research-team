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

#: Opens the one vector store this process shares, or returns None when
#: embeddings are off. A callable rather than a store because opening one is
#: asynchronous for pgvector and `build_application`, which builds this, is
#: not -- see `ProjectGraphs.vectors`.
OpenVectorStore = Callable[[], Awaitable[Any | None]]


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

    def __init__(
        self,
        *,
        build_store: BuildStore,
        rebuild: Rebuild,
        open_vector_store: OpenVectorStore | None = None,
    ) -> None:
        self._build_store = build_store
        self._rebuild = rebuild
        # One vector store for the process, not one per project: it scopes by
        # tenant internally, and a second would buy isolation redstring already
        # provides and pay for it in sockets. It is opened *here* rather than
        # in `build_application` because opening it is asynchronous --
        # `PgVectorStore.connect` is a coroutine that awaits `create_pool` --
        # and `build_application` is not. See `vectors`.
        self._open_vector_store = open_vector_store
        self._vector_store: Any | None = None
        self._vector_ready = False
        # Its own lock, not `_lock_for`'s: the per-project locks deliberately
        # never contend with each other, so two projects opening at once would
        # each see the latch unset and open a *second* connection pool. One of
        # them would then be dropped on the floor with its connections still
        # held -- a leak that only appears when two projects open at once, and
        # so not one a single-project test would ever show.
        self._vector_lock = asyncio.Lock()
        self._stores: dict[UUID, Any] = {}
        self._locks: dict[UUID, asyncio.Lock] = {}

    def _lock_for(self, project_id: UUID) -> asyncio.Lock:
        # `dict.setdefault` is synchronous and this coroutine has not
        # suspended since entering `open`, so there is no window for two
        # callers to each believe they created the lock for this id.
        return self._locks.setdefault(project_id, asyncio.Lock())

    async def vectors(self) -> Any | None:
        """The process's vector store, opened and schema'd on first ask.

        `None` when `AGENT_VECTOR_STORE=none`, which is the whole of switching
        embeddings off.

        **Two things were missing here, and both only failed against a real
        server.** `build_vector_store` was `def` while `PgVectorStore.connect`
        is `async` -- so `AGENT_VECTOR_STORE=pgvector` returned an un-awaited
        coroutine and handed it to `RedstringKnowledge` as a store. And nothing
        anywhere called `ensure_schema` on the vector store, though `open`
        calls it on the graph store two methods down, so even once awaited the
        store pointed at a table that did not exist and raised on the first
        entity of the first ingest -- after the fetch and the extraction call
        had been paid for. Constructible and unusable, twice over.

        This lives here because it is the earliest `await` on the path to the
        store being used: `build_application` is synchronous. It does not live
        in `rebuild_graph`, which folds the log, because the vector store is
        not part of that fold -- this project never appends `EntitiesEmbedded`,
        so a `VectorProjection` would have nothing to replay.

        `hasattr` rather than a type check, matching how `open` treats the
        graph store: only the pgvector adapter has DDL, and
        `InMemoryVectorStore` has no schema to ensure.
        """
        if self._open_vector_store is None or self._vector_ready:
            return self._vector_store
        async with self._vector_lock:
            if self._vector_ready:
                return self._vector_store
            store = await self._open_vector_store()
            if store is not None and hasattr(store, "ensure_schema"):
                await store.ensure_schema()
            self._vector_store = store
            # Latched only after both steps succeeded, so a server that was
            # down at the first open is retried at the next one rather than
            # remembered as absent for the life of the process.
            self._vector_ready = True
            return self._vector_store

    async def open(self, project_id: UUID) -> Any:
        """This project's store, building and folding it in on first ask.

        Every caller passes through the per-project lock, including ones
        that will find the store already cached -- the lock is cheap to
        acquire when uncontended, and re-checking the cache first (outside
        the lock) would just be a second place for the same race to hide.
        """
        # Before the per-project lock, not inside it: `vectors` takes its own
        # lock, and taking the two in one order here while a future caller
        # takes them in the other is how this grows a deadlock.
        await self.vectors()
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
        """Close every cached store, and the shared vector store. For shutdown.

        The vector store is closed here and nowhere else, because it is not
        per project and `close(project_id)` must not take it down while
        another project is still open. A `PgVectorStore` owns a connection
        pool; leaving it unclosed is how a process that has finished holds
        Postgres connections until it exits.
        """
        for project_id in list(self._stores):
            await self.close(project_id)
        store, self._vector_store = self._vector_store, None
        # Reset the latch too: a `vectors()` after `close_all` must open a new
        # store rather than hand back the closed one.
        self._vector_ready = False
        if store is not None and hasattr(store, "close"):
            await store.close()
