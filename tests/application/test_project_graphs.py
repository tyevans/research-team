"""`ProjectGraphs`: the single owner of an open `GraphStore` per project.

Two stores rebuilt separately for the same project are correct at the
instant each is built and wrong immediately after: extraction writes to
whichever one is attached, and the other keeps answering from a snapshot
of the past. That is the bug this class exists to make impossible -- there
is exactly one store per project, opened once and handed to every caller
that asks for it.

`_FakeStore` stands in for a real `GraphStore`; nothing here needs redstring
or a real replay, only the caching, locking and eviction behaviour around
whatever `build_store`/`rebuild` are given.
"""

import asyncio
from uuid import uuid4

import pytest

from research_team.application.project_graphs import ProjectGraphs


class _FakeStore:
    """Just enough of a `GraphStore` for the cache to hold and close."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _CountingRebuild:
    """A fake `rebuild` that counts calls instead of folding a real log.

    Standing in for `rebuild_graph`, which the brief's own tests never call
    -- what they assert on is how many times *whatever* rebuild step ran,
    not what it folded.
    """

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, store, project_id) -> None:
        self.calls += 1
        # A real rebuild would `await` on I/O; yielding here is what makes
        # the concurrency test meaningful -- without a suspension point,
        # `asyncio.gather` would never actually interleave the five calls,
        # and the lock would never be exercised.
        await asyncio.sleep(0)


def _graphs(rebuild=None):
    return ProjectGraphs(build_store=_FakeStore, rebuild=rebuild or _CountingRebuild())


async def test_opening_the_same_project_twice_returns_the_same_store():
    graphs = _graphs()
    project_id = uuid4()

    first = await graphs.open(project_id)
    second = await graphs.open(project_id)

    assert first is second


async def test_concurrent_opens_rebuild_only_once():
    counting_rebuild = _CountingRebuild()
    graphs = _graphs(counting_rebuild)
    project_id = uuid4()

    await asyncio.gather(*(graphs.open(project_id) for _ in range(5)))

    assert counting_rebuild.calls == 1


async def test_closing_evicts_so_a_later_open_rebuilds():
    counting_rebuild = _CountingRebuild()
    graphs = _graphs(counting_rebuild)
    project_id = uuid4()

    first = await graphs.open(project_id)
    await graphs.close(project_id)
    second = await graphs.open(project_id)

    assert counting_rebuild.calls == 2
    assert first is not second
    assert first.closed is True


async def test_close_all_closes_every_cached_store():
    graphs = _graphs()
    first_id, second_id = uuid4(), uuid4()

    first = await graphs.open(first_id)
    second = await graphs.open(second_id)
    await graphs.close_all()

    assert first.closed is True
    assert second.closed is True


class _SchemaVectorStore:
    """A vector store with DDL to run, like `PgVectorStore` and unlike the memory one."""

    def __init__(self) -> None:
        self.ensured = 0
        self.closed = False

    async def ensure_schema(self) -> None:
        self.ensured += 1

    async def close(self) -> None:
        self.closed = True


class _NoSchemaVectorStore:
    """`InMemoryVectorStore`'s shape: no schema, and nothing to close."""


class _CountingOpen:
    """An async `open_vector_store`, counting how many stores it was asked for.

    Async because the real one is: `build_vector_store` awaits
    `PgVectorStore.connect`, which awaits `asyncpg.create_pool`. A synchronous
    fake here would not exercise the thing that was broken.
    """

    def __init__(self, store) -> None:
        self.store = store
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        await asyncio.sleep(0)
        return self.store


def _graphs_with_vectors(store):
    return ProjectGraphs(
        build_store=_FakeStore,
        rebuild=_CountingRebuild(),
        open_vector_store=_CountingOpen(store),
    )


async def test_the_vector_store_gets_its_schema_before_any_project_opens():
    """`ensure_schema` runs on the vector store, which nothing used to do.

    The gap: `ProjectGraphs.open` ensured the *graph* store's schema and no
    caller anywhere ensured the vector store's, so `AGENT_VECTOR_STORE=pgvector`
    produced a `PgVectorStore` against a table that did not exist and raised
    `UndefinedTableError` on the first entity it tried to write -- mid-ingest,
    after the fetch and the extraction model call had already been paid for.

    Fails with the change reverted: `ensured` stays 0.
    """
    vectors = _SchemaVectorStore()

    await _graphs_with_vectors(vectors).open(uuid4())

    assert vectors.ensured == 1


async def test_the_vector_store_is_opened_once_across_projects():
    """One process-wide store: opened once, not once per project.

    A pool per project is the cost this pins. `PgVectorStore.connect` awaits
    `asyncpg.create_pool`, which opens `min_size` connections before it
    returns, so a second open is real sockets rather than a wasted call.
    """
    opener = _CountingOpen(_SchemaVectorStore())
    graphs = ProjectGraphs(
        build_store=_FakeStore, rebuild=_CountingRebuild(), open_vector_store=opener
    )

    await graphs.open(uuid4())
    await graphs.open(uuid4())
    await graphs.open(uuid4())

    assert opener.calls == 1
    assert opener.store.ensured == 1


async def test_concurrent_opens_build_one_vector_store():
    """Five projects opening at once must not open five pools.

    The per-project locks never contend with each other by design, so without a
    lock of its own the latch is checked by five coroutines before any of them
    sets it -- and four pools are opened and dropped with their connections
    still held. A leak that needs two projects at once to appear.
    """
    opener = _CountingOpen(_SchemaVectorStore())
    graphs = ProjectGraphs(
        build_store=_FakeStore, rebuild=_CountingRebuild(), open_vector_store=opener
    )

    await asyncio.gather(*(graphs.open(uuid4()) for _ in range(5)))

    assert opener.calls == 1


async def test_the_opened_vector_store_is_the_one_handed_out():
    """`vectors()` returns what `open_vector_store` produced, not a rebuild.

    `open_graph` reaches for this to wire `RedstringKnowledge`, so "the store
    whose schema was ensured" and "the store the adapter writes to" have to be
    the same object.
    """
    vectors = _SchemaVectorStore()
    graphs = _graphs_with_vectors(vectors)

    assert await graphs.vectors() is vectors


async def test_a_vector_store_with_no_schema_is_left_alone():
    """`InMemoryVectorStore` has no `ensure_schema`, and must not be required to.

    `hasattr` rather than a type check, matching how this class already treats
    the graph store. Reverting the guard turns this into an `AttributeError`.
    """
    graphs = _graphs_with_vectors(_NoSchemaVectorStore())

    assert await graphs.open(uuid4()) is not None


async def test_no_vector_store_opens_a_project_as_before():
    """`AGENT_VECTOR_STORE=none` builds nothing, and must stay openable."""
    graphs = ProjectGraphs(build_store=_FakeStore, rebuild=_CountingRebuild())

    assert await graphs.open(uuid4()) is not None
    assert await graphs.vectors() is None


async def test_closing_everything_closes_the_vector_store():
    """The pool is released at shutdown, and only by `close_all`.

    Not by `close(project_id)`: the store is shared, and closing it when one
    project is evicted would take the pool out from under every other open
    project.
    """
    vectors = _SchemaVectorStore()
    graphs = _graphs_with_vectors(vectors)
    project_id = uuid4()
    await graphs.open(project_id)

    await graphs.close(project_id)
    assert not vectors.closed, "one project closing must not close a shared store"

    await graphs.close_all()
    assert vectors.closed


async def test_a_failed_open_is_retried_rather_than_latched():
    """A server down at the first open must not be remembered as absent.

    Latching before the open succeeded would turn one unreachable-at-startup
    moment into embeddings being off for the life of the process, silently.
    """
    attempts = []

    async def _flaky():
        attempts.append(None)
        if len(attempts) == 1:
            raise ConnectionError("server not up yet")
        return _SchemaVectorStore()

    graphs = ProjectGraphs(
        build_store=_FakeStore, rebuild=_CountingRebuild(), open_vector_store=_flaky
    )

    with pytest.raises(ConnectionError):
        await graphs.open(uuid4())

    assert await graphs.vectors() is not None
    assert len(attempts) == 2


class _FakeChunkStore:
    """Just enough of a `ChunkStore` for the cache to hold and close."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _RecordingRebuild:
    """A fake `rebuild` that records whether it was called with `chunks`.

    Standing in for `rebuild_graph`'s own keyword-only `chunks` parameter --
    what these tests assert on is whether `ProjectGraphs` passes it through
    (and only when a chunk store actually exists), not what folding a chunk
    store does.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, store, project_id, **kwargs) -> None:
        self.calls.append(kwargs)
        await asyncio.sleep(0)


async def test_a_chunk_store_is_built_once_per_project_and_handed_to_rebuild():
    """`build_chunk_store` runs per project, like `build_store`, not once for the process.

    Unlike the vector store: a corpus is this project's data derived from
    this project's log, not a process-wide index, so sharing one across
    projects the way `_vector_store` is shared would leak one project's
    chunks into another's BM25 candidates.

    The co-mention index comes from its own builder, not from this one -- it
    holds no passage text and has no backend to choose -- so a build that
    confused the two would hand `rebuild` the same object under both keywords.
    That is asserted below rather than left to the type checker, of which there
    is none.
    """
    chunk_store = _FakeChunkStore()
    index = object()
    rebuild = _RecordingRebuild()
    graphs = ProjectGraphs(
        build_store=_FakeStore,
        rebuild=rebuild,
        build_chunk_store=lambda: chunk_store,
        build_co_mentions=lambda: index,
    )
    project_id = uuid4()

    await graphs.open(project_id)

    assert graphs.chunks(project_id) is chunk_store
    assert graphs.co_mentions(project_id) is index
    assert rebuild.calls == [{"chunks": chunk_store, "co_mentions": index}]


async def test_no_co_mention_builder_rebuilds_without_the_keyword():
    """`build_co_mentions` omitted must not add a `co_mentions=` kwarg.

    Same contract as `chunks`, and the same failure if it is broken: a
    `rebuild` that predates the co-mention channel raises `TypeError` on an
    unexpected keyword. Every test in this file that does not name the builder
    is that caller.

    **Proved red on 2026-08-22** by building the index unconditionally: **12
    failed** in this file, every test whose `rebuild` or store assertions did
    not expect a `co_mentions` key. That breadth is the point -- an
    unconditional keyword is not a local mistake, it changes what every caller
    of `rebuild` is handed.
    """
    rebuild = _RecordingRebuild()
    graphs = ProjectGraphs(build_store=_FakeStore, rebuild=rebuild)

    await graphs.open(uuid4())

    assert rebuild.calls == [{}]
    assert graphs.co_mentions(uuid4()) is None


async def test_closing_a_project_evicts_its_co_mention_index():
    """The index is dropped on close, so a later open folds a fresh one.

    **Evicted, not closed**, unlike the two chunk stores beside it: it holds no
    connection and no file, so there is nothing to release. What matters is
    that a reopened project does not keep answering from an index folded before
    whatever made the caller close it.

    **Proved red on 2026-08-22** by deleting the `_co_mentions.pop` line from
    `close`: **1 failed, this one**, 19 passed.
    """
    index = object()
    graphs = ProjectGraphs(
        build_store=_FakeStore,
        rebuild=_RecordingRebuild(),
        build_co_mentions=lambda: index,
    )
    project_id = uuid4()
    await graphs.open(project_id)
    assert graphs.co_mentions(project_id) is index

    await graphs.close(project_id)

    assert graphs.co_mentions(project_id) is None


async def test_no_chunk_store_configured_rebuilds_without_the_keyword():
    """`build_chunk_store` omitted (the default) must not add a `chunks=` kwarg.

    A `rebuild` that never expects chunking -- `rebuild_graph` itself, before
    this feature existed -- would raise `TypeError` on an unexpected keyword
    if this were passed unconditionally.
    """
    rebuild = _RecordingRebuild()
    graphs = ProjectGraphs(build_store=_FakeStore, rebuild=rebuild)

    await graphs.open(uuid4())

    assert rebuild.calls == [{}]
    assert graphs.chunks(uuid4()) is None


async def test_closing_a_project_closes_its_chunk_store_too():
    chunk_store = _FakeChunkStore()
    graphs = ProjectGraphs(
        build_store=_FakeStore,
        rebuild=_RecordingRebuild(),
        build_chunk_store=lambda: chunk_store,
    )
    project_id = uuid4()
    await graphs.open(project_id)

    await graphs.close(project_id)

    assert chunk_store.closed is True
    assert graphs.chunks(project_id) is None


# ---------------- entity cards ----------------


class _AnyRebuild:
    """A rebuild that accepts `chunks=`, which `_CountingRebuild` does not.

    These tests all configure a chunk store, and `open` passes `chunks=` only
    when one exists -- so the older double is not usable here and swapping it
    in would make every card test fail for a reason that has nothing to do
    with cards.
    """

    async def __call__(self, store, project_id, **kwargs):
        return None


async def test_the_card_store_is_not_the_chunk_store():
    """Two stores, so a card cannot reach a reader through `UsageReader`.

    `application/entity_definitions.py` enforces that every citation is
    `(source_id, start, end)` into a real document, because a claim a reader
    cannot check against its source is the failure that module exists to
    prevent. A card is synthesised text no source contains, so a citation into
    one would name a passage that does not exist while looking exactly as
    checked as a real one.

    **This passes trivially, and that is the argument for the design rather
    than a reason to skip it.** Filtering by a source-id convention would also
    work today and would stop working the first time somebody indexed cards
    without knowing the convention. Written down so that collapsing the two
    stores fails here, next to the reasoning, rather than in a reader's
    citation months later.
    """
    built: list[object] = []

    def build_chunk_store():
        store = object()
        built.append(store)
        return store

    async def index_cards(*, graph, cards, tenant_id):
        return 0

    graphs = ProjectGraphs(
        build_store=_FakeStore,
        rebuild=_AnyRebuild(),
        build_chunk_store=build_chunk_store,
        index_cards=index_cards,
    )
    project_id = uuid4()

    await graphs.open(project_id)

    assert graphs.chunks(project_id) is not None
    assert graphs.cards(project_id) is not None
    assert graphs.cards(project_id) is not graphs.chunks(project_id)


async def test_cards_are_indexed_from_the_folded_graph():
    """Card assembly runs after the replay, not during it.

    A card is a snapshot of a neighbourhood, so one taken before the last event
    is applied describes a graph that is still filling in -- and nothing would
    say so, because a partial neighbourhood is a well-formed card.
    """
    order: list[str] = []

    class _RecordingRebuild:
        async def __call__(self, store, project_id, **kwargs):
            order.append("rebuild")

    async def index_cards(*, graph, cards, tenant_id):
        order.append("cards")
        return 1

    graphs = ProjectGraphs(
        build_store=_FakeStore,
        rebuild=_RecordingRebuild(),
        build_chunk_store=lambda: object(),
        index_cards=index_cards,
    )

    await graphs.open(uuid4())

    assert order == ["rebuild", "cards"]


async def test_a_project_without_a_card_indexer_still_opens():
    """Cards are optional, the way chunking is.

    A build with no card indexer must open exactly as it did before this
    feature existed -- `cards()` answers `None` rather than raising, and
    nothing about the graph or the corpus changes.
    """
    graphs = ProjectGraphs(
        build_store=_FakeStore,
        rebuild=_AnyRebuild(),
        build_chunk_store=lambda: object(),
    )
    project_id = uuid4()

    await graphs.open(project_id)

    assert graphs.chunks(project_id) is not None
    assert graphs.cards(project_id) is None
