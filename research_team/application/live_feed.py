"""Following the log as it grows.

The store gives us a cursor and "everything after it". Turning that into a
stream a UI can subscribe to is orchestration, so it lives here rather than in
the adapter -- and staying at this layer means a live view works over any
store that can answer the two feed questions.
"""

from collections.abc import AsyncIterator

from research_team.application.ports import EventFeed, FeedEntry

POLL_INTERVAL_SECONDS = 0.4


class LiveFeed:
    """Yields events as they are appended, forever."""

    def __init__(
        self, feed: EventFeed, *, poll_interval: float = POLL_INTERVAL_SECONDS
    ) -> None:
        self._feed = feed
        self._poll_interval = poll_interval

    def encode_position(self, position: object) -> str:
        """Text form of a cursor, for a subscriber to keep and return."""
        return self._feed.encode_position(position)

    def decode_position(self, raw: str) -> object | None:
        """A returned cursor, or None if this store cannot place it."""
        return self._feed.decode_position(raw)

    async def position_now(self) -> object:
        """Where the log ends at this moment.

        `follow()` takes this itself when given neither a position nor
        `from_start`, so this exists for the one caller that needs to take it
        *earlier*: a subscriber cannot say "I am listening from here" until
        here has been decided, and inside `follow` that happens on the first
        turn of a task nobody can wait for. `_sse` takes the position, then
        announces itself.
        """
        return await self._feed.latest_position()

    async def follow(
        self, *, from_start: bool = False, from_position: object | None = None
    ) -> AsyncIterator[FeedEntry]:
        """Stream feed entries.

        Starts at the current end of the log, so a subscriber sees what happens
        *from now on* rather than a replay of everything -- pass
        `from_start=True` when the whole history is what you want, or
        `from_position` to pick up immediately after a position you already
        have. That last one is what a reconnecting subscriber wants: starting
        at the end again would silently drop whatever landed while it was away,
        and starting from the beginning would repeat everything it has.

        Always reads through the store, never off a bus: positions and ordering
        come from the log, so a subscriber sees exactly what was durably
        appended, in that order, with no chance of a delivered-but-unwritten
        event or a duplicate. What the feed *may* do is skip the wait --
        `wait_for_append` returns early when a writer signals one, and falls
        back to the interval when nothing can. So the cursor still makes each
        read cover only what is new, and the interval becomes a ceiling on
        latency rather than the latency itself.
        """
        if from_position is not None:
            cursor = from_position
        elif from_start:
            cursor = None
        else:
            cursor = await self._feed.latest_position()
        while True:
            entries = await self._feed.read_since(cursor)
            for entry in entries:
                cursor = entry.position
                yield entry
            if not entries:
                await self._feed.wait_for_append(self._poll_interval)
