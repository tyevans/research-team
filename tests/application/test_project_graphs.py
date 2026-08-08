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
