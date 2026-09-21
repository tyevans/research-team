"""Lazy async resources and cache/store wrappers for deferred loop-bound opening."""

import asyncio
import functools
from collections.abc import Awaitable, Callable
from datetime import datetime
from uuid import UUID

import aiosqlite

from research_team.application.curriculum.course_catalog import (
    CachedBlurb,
    CachedOutline,
)
from research_team.application.tenancy.project_summaries import ProjectSummary
from research_team.infrastructure.persistence.project_summaries import (
    SqliteProjectSummaries,
)
from research_team.infrastructure.persistence.read_models import (
    ArtRow,
    ArtStore,
    CandidateArtRow,
    CandidateArtStore,
    CourseBlurbStore,
    CourseOutlineStore,
)


class LazyAsyncResource[T]:
    """Coroutine-safe lazy async resource with double-checked locking.

    Defers opening the underlying resource until its first use, ensuring that
    resources requiring a running asyncio event loop (e.g. SQLite connections)
    can be composed synchronously. Two concurrent callers will safely await
    the same lock, and only one initialization will run.
    """

    def __init__(
        self,
        factory: Callable[[], Awaitable[T]] | Callable[[str], Awaitable[T]],
        db_path: str | None = None,
        close: Callable[[T], Awaitable[None]] | None = None,
    ) -> None:
        if db_path is not None:
            self._factory: Callable[[], Awaitable[T]] = functools.partial(factory, db_path)  # type: ignore[assignment]
        else:
            self._factory = factory  # type: ignore[assignment]
        self._close = close
        self._resource: T | None = None
        self._lock = asyncio.Lock()

    @classmethod
    def open_fn(
        cls,
        open_func: Callable[[str], Awaitable[T]],
        db_path: str,
        close: Callable[[T], Awaitable[None]] | None = None,
    ) -> "LazyAsyncResource[T]":
        """Build a `LazyAsyncResource` from an async opener taking a db_path."""
        return cls(functools.partial(open_func, db_path), close=close)

    async def get(self) -> T:
        """Return the opened resource, creating it on first call."""
        if self._resource is None:
            async with self._lock:
                if self._resource is None:
                    self._resource = await self._factory()
        return self._resource

    @property
    def is_opened(self) -> bool:
        """Whether the resource has been opened."""
        return self._resource is not None

    async def opened(self) -> T:
        """Alias for `get()`."""
        return await self.get()

    async def close(self) -> None:
        """Close the underlying resource if it was opened."""
        async with self._lock:
            if self._resource is not None:
                resource = self._resource
                self._resource = None
                if self._close is not None:
                    await self._close(resource)
                else:
                    close_method = getattr(resource, "close", None)
                    if callable(close_method):
                        res = close_method()
                        if isinstance(res, Awaitable):
                            await res


class _LazyBlurbCache:
    """`BlurbCachePort` over `CourseBlurbStore`, opened on first use.

    `CatalogService` is built inside `build_application`, before any event
    loop is running -- `start()`'s own docstring says why nothing here can
    open an aiosqlite connection until then. Unlike `catalog_features`, which
    is read through a property because `catalog` itself (not this cache) is
    what a route holds a reference to, this port is handed directly to
    `CatalogService` at construction, so it has to defer the open internally
    rather than being swapped in later. Guarded by a lock so two concurrent
    card renders do not each open their own connection to the same file.
    """

    def __init__(self, db_path: str) -> None:
        self._resource = LazyAsyncResource(CourseBlurbStore.open, db_path)

    async def _opened(self) -> CourseBlurbStore:
        return await self._resource.get()

    async def get(self, project_id: UUID, slug: str) -> CachedBlurb | None:
        store = await self._opened()
        row = await store.get(project_id, slug)
        if row is None:
            return None
        return CachedBlurb(
            text=row.text,
            title=row.title,
            membership_hash=row.membership_hash,
            model=row.model,
            generated_at=datetime.fromisoformat(row.generated_at),
        )

    async def all_for_project(self, project_id: UUID) -> dict[str, CachedBlurb]:
        store = await self._opened()
        rows = await store.all_for_project(project_id)
        return {
            slug: CachedBlurb(
                text=row.text,
                title=row.title,
                membership_hash=row.membership_hash,
                model=row.model,
                generated_at=datetime.fromisoformat(row.generated_at),
            )
            for slug, row in rows.items()
        }

    async def put(
        self,
        project_id: UUID,
        slug: str,
        title: str,
        text: str,
        membership_hash: str,
        model: str,
        generated_at: datetime,
    ) -> None:
        store = await self._opened()
        await store.put(project_id, slug, title, text, membership_hash, model, generated_at)

    async def close(self) -> None:
        await self._resource.close()


class _LazyArtStore:
    """`ArtStore`, opened on first use -- `_LazyBlurbCache`'s exact shape and
    reason, but exposing the store's own methods directly rather than a
    narrower port. Nothing in this increment builds an `ArtGeneratorPort`
    adapter yet (that is a sibling task's job), so there is no port to defer
    behind; this exists solely so `create_app`'s `art_store` parameter has
    something to serve `/api/art/{art_id}.svg` from without opening a
    connection before uvicorn's event loop exists -- see `_LazyBlurbCache`'s
    docstring for why that ordering matters.

    **Every public method of `ArtStore` has to be forwarded, and that is not a
    style rule.** This wrapper mirrors a concrete class rather than standing
    behind a `Protocol`, so nothing declares what its surface should be: a
    method added to `ArtStore` and used through this is an `AttributeError` at
    the call, in a background task, on the one code path that reaches it.
    `decrement_uses` shipped that way and ran in production. It is only called
    when a candidate already *has* an assignment to drop -- the sweep's
    membership-changed arm and every reroll -- so a fresh project sweeps clean
    and the failure appears the first time somebody redoes art they already
    have:

        AttributeError: '_LazyArtStore' object has no attribute
        'decrement_uses'. Did you mean: 'increment_uses'?

    Nothing caught it. There is no Python typechecker in this repository's
    gates, `ArtSweep.__init__` annotates `art_store: ArtStore` while
    composition passes this, and every test of the sweep supplies its own fake
    store rather than the wrapper. The three sibling wrappers were audited at
    the same time and are complete -- the other two mirror `Protocol`s in
    `application/course_catalog.py`, which is the difference.
    `test_composition.py` now pins the surface against `ArtStore`'s own, so the
    next method lands as a failing test rather than as a broken reroll.
    """

    def __init__(self, db_path: str) -> None:
        self._resource = LazyAsyncResource(ArtStore.open, db_path)

    async def _opened(self) -> ArtStore:
        return await self._resource.get()

    async def get(self, art_id: UUID) -> ArtRow | None:
        store = await self._opened()
        return await store.get(art_id)

    async def put(
        self,
        art_id: UUID,
        svg: str,
        description: str,
        tags: list[str],
        palette: str,
        created_at: datetime,
        source: str,
        uses: int = 0,
    ) -> None:
        store = await self._opened()
        await store.put(art_id, svg, description, tags, palette, created_at, source, uses)

    async def all(self) -> list[ArtRow]:
        store = await self._opened()
        return await store.all()

    async def increment_uses(self, art_id: UUID) -> None:
        store = await self._opened()
        await store.increment_uses(art_id)

    async def decrement_uses(self, art_id: UUID) -> None:
        store = await self._opened()
        await store.decrement_uses(art_id)

    async def close(self) -> None:
        await self._resource.close()


class _LazyProjectSummaries:
    """`ProjectSummaries`, over a connection opened on first use.

    `_LazyArtStore`'s shape, and the same reason for it: `build_application`
    is synchronous because `web.py` calls it before uvicorn has a loop, and an
    aiosqlite connection made on one loop cannot be used from another.

    **This one mirrors a `Protocol` rather than a concrete class**, which is
    the distinction `_LazyArtStore`'s docstring draws after forwarding an
    incomplete surface into production: `ProjectSummaries` declares exactly one
    method, so a method added to the adapter and not forwarded here is a method
    nothing is allowed to call through this type. There is no second surface to
    drift from.

    It opens its own connection rather than borrowing one of the runners',
    which costs a file handle and buys the thing this reader most needs to be:
    ignorant of the runners entirely. Every table it reads is owned by a
    different runner, so borrowing would mean choosing one of four to depend
    on, and the reader would then answer only while that one happened to be
    wired.
    """

    def __init__(self, db_path: str) -> None:
        self._resource = LazyAsyncResource(aiosqlite.connect, db_path)

    async def _opened(self) -> SqliteProjectSummaries:
        connection = await self._resource.get()
        return SqliteProjectSummaries(connection)

    async def all(self) -> dict[UUID, ProjectSummary]:
        reader = await self._opened()
        return await reader.all()

    async def close(self) -> None:
        await self._resource.close()


class _LazyCandidateArtStore:
    """`CandidateArtStore`, opened on first use -- `_LazyArtStore`'s exact
    shape and reason. A second small wrapper rather than one class managing
    both tables: `ArtStore` and `CandidateArtStore` are two different
    connections to two different tables in `read_models.py` already, and
    `_LazyOutlineCache`'s own docstring gives the precedent for keeping a
    lazy wrapper one store to one class."""

    def __init__(self, db_path: str) -> None:
        self._resource = LazyAsyncResource(CandidateArtStore.open, db_path)

    async def _opened(self) -> CandidateArtStore:
        return await self._resource.get()

    async def get(self, project_id: UUID, slug: str) -> CandidateArtRow | None:
        store = await self._opened()
        return await store.get(project_id, slug)

    async def put(
        self, project_id: UUID, slug: str, art_id: UUID, membership_hash: str
    ) -> None:
        # `membership_hash` is required here rather than defaulted, mirroring
        # `CandidateArtStore.put`. An assignment recorded without the hash it
        # was made against is exactly the row drift-detection can never
        # refresh -- it would compare against `""`, never match, and either
        # regenerate forever or never, depending on which way the comparison
        # falls. A default would make that unreachable-by-accident state
        # reachable by omission.
        store = await self._opened()
        await store.put(project_id, slug, art_id, membership_hash)

    async def close(self) -> None:
        await self._resource.close()


class _LazyOutlineCache:
    """`OutlineCachePort` over `CourseOutlineStore`, opened on first use.

    `_LazyBlurbCache`'s shape exactly, and for the same reason: `CourseService`
    is built inside `build_application`, before any event loop is running, so
    the port handed to it at construction has to defer opening its own
    connection rather than being swapped in once one exists. A separate class
    rather than a generic wrapper over both stores -- the two stores' `get`/
    `put` return different row shapes (`CourseOutlineRow.sections` is a list of
    dicts; `CachedOutline.sections` is a tuple of pairs), so the translation is
    the whole body of each method and sharing it would buy nothing.
    """

    def __init__(self, db_path: str) -> None:
        self._resource = LazyAsyncResource(CourseOutlineStore.open, db_path)

    async def _opened(self) -> CourseOutlineStore:
        return await self._resource.get()

    async def get(self, project_id: UUID, slug: str) -> CachedOutline | None:
        store = await self._opened()
        row = await store.get(project_id, slug)
        if row is None:
            return None
        return CachedOutline(
            promise=row.promise,
            sections=tuple((s["heading"], s["summary"]) for s in row.sections),
            membership_hash=row.membership_hash,
            model=row.model,
            generated_at=datetime.fromisoformat(row.generated_at),
        )

    async def put(
        self,
        project_id: UUID,
        slug: str,
        promise: str,
        sections: tuple[tuple[str, str], ...],
        membership_hash: str,
        model: str,
        generated_at: datetime,
    ) -> None:
        store = await self._opened()
        await store.put(
            project_id,
            slug,
            promise,
            [{"heading": heading, "summary": summary} for heading, summary in sections],
            membership_hash,
            model,
            generated_at,
        )

    async def close(self) -> None:
        await self._resource.close()
