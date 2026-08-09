"""Following the log, over a fake feed with no store and no clock to wait on."""

import asyncio

import pytest

from research_team.application import FeedEntry, LiveFeed


class FakeFeed:
    """An `EventFeed` whose contents a test can push to."""

    def __init__(self) -> None:
        self.entries: list[FeedEntry] = []
        self.reads = 0
        self._appended = asyncio.Event()

    def push(self, name: str) -> None:
        position = len(self.entries) + 1
        self.entries.append(
            FeedEntry(
                aggregate_id=name,
                aggregate_type="CodingSession",
                event=name,
                position=position,
            )
        )
        self._appended.set()

    async def wait_for_append(self, timeout: float) -> None:
        try:
            await asyncio.wait_for(self._appended.wait(), timeout)
        except TimeoutError:
            return
        finally:
            self._appended.clear()

    async def latest_position(self) -> object | None:
        return self.entries[-1].position if self.entries else None

    async def read_since(self, position: object | None) -> list[FeedEntry]:
        self.reads += 1
        if position is None:
            return list(self.entries)
        return [entry for entry in self.entries if entry.position > position]


async def _take(feed: LiveFeed, count: int, **kwargs) -> list[FeedEntry]:
    taken: list[FeedEntry] = []
    stream = feed.follow(**kwargs)
    async for entry in stream:
        taken.append(entry)
        if len(taken) == count:
            await stream.aclose()
            return taken
    return taken


async def test_follow_starts_at_the_end_by_default():
    """A subscriber wants what happens next, not a replay of the whole log."""
    fake = FakeFeed()
    fake.push("old")
    feed = LiveFeed(fake, poll_interval=0.01)

    async def push_soon() -> None:
        await asyncio.sleep(0.05)
        fake.push("new")

    pusher = asyncio.create_task(push_soon())
    taken = await asyncio.wait_for(_take(feed, 1), timeout=5)
    await pusher

    assert [entry.event for entry in taken] == ["new"]


async def test_follow_from_start_replays_everything():
    fake = FakeFeed()
    fake.push("first")
    fake.push("second")
    feed = LiveFeed(fake, poll_interval=0.01)

    taken = await asyncio.wait_for(_take(feed, 2, from_start=True), timeout=5)

    assert [entry.event for entry in taken] == ["first", "second"]


async def test_the_cursor_advances_so_events_arrive_once():
    fake = FakeFeed()
    fake.push("a")
    fake.push("b")
    fake.push("c")
    feed = LiveFeed(fake, poll_interval=0.01)

    taken = await asyncio.wait_for(_take(feed, 3, from_start=True), timeout=5)

    assert [entry.event for entry in taken] == ["a", "b", "c"]


async def test_an_append_wakes_the_feed_without_waiting_out_the_interval():
    """The poll interval is a ceiling on latency, not the latency itself.

    With a 30-second interval, a purely time-driven loop cannot deliver
    anything inside this test's timeout. Arriving quickly is only possible if
    the append itself woke the loop.
    """
    fake = FakeFeed()
    feed = LiveFeed(fake, poll_interval=30.0)

    async def push_soon() -> None:
        await asyncio.sleep(0.05)
        fake.push("pushed")

    pusher = asyncio.create_task(push_soon())
    taken = await asyncio.wait_for(_take(feed, 1), timeout=2)
    await pusher

    assert [entry.event for entry in taken] == ["pushed"]


async def test_following_from_a_position_resumes_after_it():
    """What a reconnecting subscriber needs: neither a replay nor a gap."""
    fake = FakeFeed()
    fake.push("before")
    fake.push("cutoff")
    resume_from = fake.entries[-1].position
    fake.push("after")
    feed = LiveFeed(fake, poll_interval=0.01)

    taken = await asyncio.wait_for(_take(feed, 1, from_position=resume_from), timeout=5)

    assert [entry.event for entry in taken] == ["after"]


async def test_an_idle_log_polls_rather_than_spins():
    """No events must not mean a busy loop."""
    fake = FakeFeed()
    feed = LiveFeed(fake, poll_interval=0.05)

    stream = feed.follow()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(stream), timeout=0.3)
    await stream.aclose()

    # ~6 polls in 0.3s at a 0.05s interval; the point is that it slept at all.
    assert fake.reads < 20
