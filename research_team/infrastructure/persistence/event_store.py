"""SQLite-backed implementation of the `SessionRepository` port."""

from uuid import UUID

from eventsource import DomainEvent, StreamId, collect
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.snapshots import SQLiteSnapshotStore
from eventsource.application.aggregates.repository import AggregateRepository

from research_team.domain import CodingSession

SNAPSHOT_THRESHOLD = 50


def build_aggregate_repository(
    store: SQLiteEventStore, db_path: str
) -> AggregateRepository[CodingSession]:
    return AggregateRepository(
        store,
        CodingSession,
        # Same database file as the event store: the schema that creates the
        # `snapshots` table is applied by the store's connection, so a separate
        # path (or a second ":memory:") would leave the table missing.
        snapshot_store=SQLiteSnapshotStore(db_path),
        snapshot_threshold=SNAPSHOT_THRESHOLD,
        snapshot_mode="sync",
    )


class EventStoreSessionRepository:
    """Adapts `eventsource`'s store and repository to the application's port.

    Two access paths, both over the same log: the aggregate repository for
    command handling, and raw stream reads for the log-as-read-model features.
    """

    def __init__(
        self,
        store: SQLiteEventStore,
        aggregates: AggregateRepository[CodingSession],
    ) -> None:
        self._store = store
        self._aggregates = aggregates

    @classmethod
    def open(cls, db_path: str) -> "EventStoreSessionRepository":
        store = SQLiteEventStore(db_path)
        return cls(store, build_aggregate_repository(store, db_path))

    def create(self, session_id: UUID) -> CodingSession:
        return self._aggregates.create_new(session_id)

    async def load(self, session_id: UUID) -> CodingSession:
        return await self._aggregates.load(session_id)

    async def save(self, session: CodingSession) -> None:
        await self._aggregates.save(session)

    async def events_for(self, session_id: UUID) -> list[DomainEvent]:
        stream = StreamId(session_id, CodingSession.aggregate_type)
        return [envelope.event for envelope in await collect(self._store.read_stream(stream))]

    async def all_events(self) -> list[DomainEvent]:
        envelopes = await collect(
            self._store.read_category(CodingSession.aggregate_type)
        )
        return [envelope.event for envelope in envelopes]

    async def close(self) -> None:
        await self._store.close()
