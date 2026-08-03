"""Following the log as it grows.

The store gives us a cursor and "everything after it". Turning that into a
stream a UI can subscribe to is orchestration, so it lives here rather than in
the adapter -- and staying at this layer means a live view works over any
store that can answer the two feed questions.
"""

import asyncio
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

    async def follow(self, *, from_start: bool = False) -> AsyncIterator[FeedEntry]:
        """Stream feed entries.

        Starts at the current end of the log, so a subscriber sees what happens
        *from now on* rather than a replay of everything -- pass
        `from_start=True` when the whole history is what you want.

        Polls rather than subscribes: SQLite has no push, and a fold this cheap
        does not justify a message bus. The cursor makes each poll a read of
        only what is new, so an idle log costs one empty query per interval.
        """
        cursor = None if from_start else await self._feed.latest_position()
        while True:
            entries = await self._feed.read_since(cursor)
            for entry in entries:
                cursor = entry.position
                yield entry
            if not entries:
                await asyncio.sleep(self._poll_interval)
