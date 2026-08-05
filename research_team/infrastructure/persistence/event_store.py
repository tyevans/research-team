"""SQLite-backed implementation of the `SessionRepository` port."""

import asyncio
from uuid import UUID

from eventsource import (
    DomainEvent,
    InMemoryEventBus,
    Position,
    PositionDecodeError,
    PositionForeignError,
    StreamId,
    collect,
)
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.snapshots import SQLiteSnapshotStore
from eventsource.application.aggregates.repository import AggregateRepository

from research_team.application import FeedEntry
from research_team.domain import CodingSession

SNAPSHOT_THRESHOLD = 50


def build_aggregate_repository(
    store: SQLiteEventStore,
    db_path: str,
    publisher: InMemoryEventBus | None = None,
) -> AggregateRepository[CodingSession]:
    return AggregateRepository(
        store,
        CodingSession,
        # Publishing is a notification, not a delivery mechanism: subscribers
        # are told that something landed and go read the log for themselves.
        # It fires after the append commits, so a signal never runs ahead of
        # the write it is announcing.
        event_publisher=publisher,
        # Same database file as the event store: the schema that creates the
        # `snapshots` table is applied by the store's connection, so a separate
        # path (or a second ":memory:") would leave the table missing.
        snapshot_store=SQLiteSnapshotStore(db_path),
        snapshot_threshold=SNAPSHOT_THRESHOLD,
        # A snapshot is an optimisation for a future read, and the turn that
        # triggers it is the one thing in this application a person is actually
        # waiting on. Scheduling it off the save path spends the latency where
        # nobody is watching. `await_pending_snapshots()` is how tests -- and
        # shutdown -- pin the timing back down when they need it.
        snapshot_mode="background",
    )


class EventStoreSessionRepository:
    """Adapts `eventsource`'s store and repository to the application's ports.

    Satisfies both `SessionRepository` and `EventFeed`: three access paths over
    one log -- the aggregate repository for command handling, raw stream reads
    for the log-as-read-model features, and the global feed for live views.
    They are separate ports because they answer separate questions; they share
    an implementation because they share a connection.

    There is deliberately no "every event in the store" read here. The one
    caller that wanted it was the `/sessions` fold, which is now a projection
    (`SessionSummaryStore`) fed event by event -- and an unbounded read left
    lying around is an invitation to put the full scan back.
    """

    def __init__(
        self,
        store: SQLiteEventStore,
        aggregates: AggregateRepository[CodingSession],
        publisher: InMemoryEventBus | None = None,
    ) -> None:
        self._store = store
        self._aggregates = aggregates
        self._publisher = publisher
        self._appended = asyncio.Event()
        if publisher is not None:
            publisher.subscribe_to_all_events(self._on_published)

    @classmethod
    def open(cls, db_path: str) -> "EventStoreSessionRepository":
        store = SQLiteEventStore(db_path)
        publisher = InMemoryEventBus()
        return cls(store, build_aggregate_repository(store, db_path, publisher), publisher)

    @property
    def store(self) -> SQLiteEventStore:
        """The underlying log, for collaborators that read it directly.

        A projection catching up needs the store itself, not this adapter's
        session-shaped reads -- it wants the global feed, in append order,
        from a position. Exposing it here keeps the composition root from
        having to open a second connection to the same file.
        """
        return self._store

    @property
    def publisher(self) -> InMemoryEventBus | None:
        """The bus saves are announced on, for subscribers that want live events."""
        return self._publisher

    def _on_published(self, event: DomainEvent) -> None:
        """Raise the flag. Deliberately ignores the event itself.

        Anything a reader needs is already in the log, and taking it from here
        instead would mean trusting bus ordering over store ordering.
        """
        self._appended.set()

    async def wait_for_append(self, timeout: float) -> None:
        """Wait for a local write, or give up after `timeout`.

        The timeout is what covers writes this process cannot see -- a second
        process appending to the same file signals nothing here, so the
        interval remains the bound on how stale a reader can get.
        """
        # Cleared before waiting, not after: the flag answers "has anything
        # happened *since I started waiting*", and a leftover set from an
        # earlier write would otherwise return instantly with nothing to read.
        self._appended.clear()
        try:
            await asyncio.wait_for(self._appended.wait(), timeout)
        except TimeoutError:
            return

    def create(self, session_id: UUID) -> CodingSession:
        return self._aggregates.create_new(session_id)

    async def load(self, session_id: UUID) -> CodingSession:
        return await self._aggregates.load(session_id)

    async def save(self, session: CodingSession) -> None:
        await self._aggregates.save(session)

    async def events_for(self, session_id: UUID) -> list[DomainEvent]:
        stream = StreamId(session_id, CodingSession.aggregate_type)
        return [envelope.event for envelope in await collect(self._store.read_stream(stream))]

    # ---- the EventFeed port ----

    async def latest_position(self) -> object | None:
        return await self._store.current_position()

    async def read_since(self, position: object | None) -> list[FeedEntry]:
        """Session events since `position`, in append order.

        Filtered by aggregate type rather than taking the whole feed. This
        store is shared: redstring's `Document` and `Consolidation` streams
        live in the same file, and their aggregate ids are document and tenant
        ids, not sessions. Unfiltered, every one of them would arrive here as a
        `FeedEntry` claiming to be a session that does not exist.
        """
        envelopes = await collect(self._store.read_all(from_position=position))
        return [
            FeedEntry(
                session_id=envelope.event.aggregate_id,
                event=envelope.event,
                position=envelope.position,
            )
            for envelope in envelopes
            if envelope.event.aggregate_type == CodingSession.aggregate_type
        ]

    def encode_position(self, position: object) -> str:
        """A position as text, for handing to a client that may hand it back."""
        return position.to_str()

    def decode_position(self, raw: str) -> object | None:
        """A position from text, or None if the text is not one of ours.

        Returns rather than raises because the input is untrusted -- it comes
        back from a browser, which may have kept it across a database being
        replaced. A cursor we cannot place is not an error; it just means the
        caller has to start somewhere else.
        """
        try:
            position = Position.from_str(raw)
        except (PositionDecodeError, PositionForeignError, ValueError):
            return None
        # `from_str` will parse any well-formed position, including one from a
        # different store. Comparing it to ours would raise later, deep in a
        # read; checking here keeps that from ever being reachable.
        current = self._store.store_id
        return position if position.store_id == current else None

    @property
    def pending_snapshot_count(self) -> int:
        """Snapshots scheduled but not yet written. Zero once drained."""
        return self._aggregates.pending_snapshot_count

    async def drain_snapshots(self) -> None:
        """Wait for scheduled snapshots to be written.

        Snapshots are taken off the save path, which leaves callers who care
        about *whether one exists* -- shutdown, and tests -- with nothing to
        wait on. This is that seam.
        """
        await self._aggregates.await_pending_snapshots()

    async def close(self) -> None:
        # Drain before releasing the connection: snapshots are written on
        # background tasks, and closing out from under one would fail a write
        # that nothing is awaiting -- so the error would surface as a missing
        # snapshot much later, if at all.
        await self.drain_snapshots()
        await self._store.close()
