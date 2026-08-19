"""The only place this feature appends.

No aggregate: nothing here enforces an invariant. The browser reports what
happened and there is no rule that could reject it, so events go straight to
the store with `ExpectedVersion.any_()` rather than through a
`DeciderAggregate`. `infrastructure/knowledge/ontology_recorder.py` made the
same call for the same reason and is worth reading alongside this.

**Appending is not delivering, and the difference is silent.** The store owns
ordering; the bus is only a wake-up telling a subscription that new work may
exist. An append nobody publishes reaches a running projection on the next
restart or rebuild and not before -- so `record` publishes, every time, and
the test that proves it is
`test_recording_publishes_every_event`. Every other writer in this codebase
gets this for free from `AggregateRepository(event_publisher=...)`; a recorder
with no aggregate has to do the publishing half itself.
"""

from collections import defaultdict
from collections.abc import Sequence

from eventsource import ExpectedVersion, InMemoryEventBus, StreamId
from eventsource.adapters.sqlite import SQLiteEventStore

from research_team.domain.interaction import (
    BROWSER_SESSION_AGGREGATE_TYPE,
    InteractionEvent,
)


class EventStoreInteractionRecorder:
    def __init__(self, store: SQLiteEventStore, publisher: InMemoryEventBus) -> None:
        self._store = store
        self._publisher = publisher

    async def record(self, events: Sequence[InteractionEvent]) -> int:
        """Append a batch and publish it. Returns how many were written.

        Grouped by browser session because `append` takes one `StreamId`, and
        one flush can carry events from more than one session -- rare, but a
        second tab plus a page-hide race produces it.

        An empty batch is a no-op rather than an error: `append` rejects an
        empty sequence, and a flush that carried only malformed events
        legitimately arrives with nothing left.
        """
        if not events:
            return 0

        by_session: dict[object, list[InteractionEvent]] = defaultdict(list)
        for event in events:
            by_session[event.aggregate_id].append(event)

        for browser_session_id, batch in by_session.items():
            await self._store.append(
                StreamId(browser_session_id, BROWSER_SESSION_AGGREGATE_TYPE),
                batch,
                # The stream protects no invariant, so there is no version to
                # expect. A concurrent second tab appending to its own stream
                # cannot conflict with this one anyway.
                ExpectedVersion.any_(),
            )

        await self._publisher.publish(list(events))
        return len(events)
