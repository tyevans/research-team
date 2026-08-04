"""The `/sessions` list, kept as a table instead of recomputed from the log.

`summarize_sessions` folds every event in the database into rows. That is the
clearest possible statement of what a summary *is*, and it stays where it is --
but running it per request costs the whole log every time, which grows without
bound while the answer barely changes.

So the same fold runs here instead, once per event, into a row that is written
down. The definition has not moved; only how often it is applied. The two are
held together by a test that feeds identical events through both and compares.
"""

import asyncio
import json
from datetime import datetime
from uuid import UUID

import aiosqlite
from eventsource import (
    DeclarativeProjection,
    InMemoryEventBus,
    ReadModel,
    SQLCheckpointRepository,
    SQLDLQRepository,
    create_async_engine,
    handles,
)
from eventsource.adapters.sql.readmodel_schema import generate_full_schema
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.readmodels import SQLiteReadModelRepository
from eventsource.application.projections.retry import ExponentialBackoffRetryPolicy
from eventsource.application.subscriptions import (
    SubscriptionConfig,
    SubscriptionManager,
)
from eventsource.application.subscriptions.retry import RetryConfig
from eventsource.ports.dlq import DLQEntry
from eventsource.ports.readmodels import Query, ReadModelRepository
from pydantic import Field, field_validator

from research_team.application import SessionSummary, SummaryHealth
from research_team.domain import (
    FileDeleted,
    FileEdited,
    FileWritten,
    SessionForkedFrom,
    SessionStarted,
    TurnCompleted,
    TurnFailed,
    UserMessageSent,
)

LOCAL_RETRY_POLICY = ExponentialBackoffRetryPolicy(
    config=RetryConfig(max_retries=2, initial_delay=0.05, max_delay=1.0)
)
"""How hard to retry a projection handler before giving up on an event.

The library's default backs off for seconds at a time, which is right for a
projection writing over a network -- a broker hiccup or a connection reset is
worth waiting out. This one writes to a SQLite file in the same process, where
the realistic transient failure is a briefly-locked database that clears in
milliseconds. Waiting seconds would not fix anything a fast retry misses; it
would just delay the DLQ entry that tells you something is actually wrong.
"""


class SessionSummaryRow(ReadModel):
    """One row of `/sessions`. `id` is the session id.

    Carries `file_paths` rather than a file count, because the count is of
    distinct live files: a rewrite of a path already seen must not raise it,
    and a delete must lower it. A fold can see the whole stream at once and
    take a set difference; an incremental projection sees one event and has to
    have kept the set.
    """

    started_at: datetime
    turns: int = 0
    failed_turns: int = 0
    first_message: str = ""
    file_paths: list[str] = Field(default_factory=list)
    forked_from: UUID | None = None
    forked_at: int | None = None

    @field_validator("file_paths", mode="before")
    @classmethod
    def _decode_json_list(cls, value: object) -> object:
        """Accept the JSON text SQLite hands back for a list column.

        The SQLite read model adapter serialises lists to TEXT on the way in
        but only converts ids and its own timestamps on the way out, so a list
        field returns as the JSON string it was stored as. Decoding here keeps
        that asymmetry from leaking into the projection, which has no reason to
        know which backend it is writing to.
        """
        if isinstance(value, str):
            return json.loads(value)
        return value


def to_summary(row: SessionSummaryRow) -> SessionSummary:
    """Present a stored row as the application's summary type.

    The application layer keeps its own shape: a row is how this is stored,
    which is not a decision the use cases should inherit.
    """
    return SessionSummary(
        session_id=row.id,
        started_at=row.started_at,
        turns=row.turns,
        files=len(row.file_paths),
        first_message=row.first_message,
        forked_from=row.forked_from,
        forked_at=row.forked_at,
        failed_turns=row.failed_turns,
    )


class SessionSummaryProjection(DeclarativeProjection):
    """Applies session events to their row, one event at a time.

    Every handler is idempotent in the sense that matters after a crash: the
    row is loaded, changed, and written back, so replaying from a checkpoint
    that is slightly behind re-derives the same values rather than accumulating
    them twice. The one counter that could drift -- `failed_turns` -- is the
    reason the checkpoint is written after each event rather than in batches.
    """

    def __init__(
        self,
        rows: ReadModelRepository[SessionSummaryRow],
        checkpoint_repo=None,
        dlq_repo=None,
    ) -> None:
        self._rows = rows
        # Without a DLQ the library logs a permanent failure at CRITICAL and
        # moves on, so the only record of a corrupted row is a line in a log
        # nobody is reading. With one, the failure is queryable -- which is
        # what makes `rebuild()` something you know to reach for.
        super().__init__(checkpoint_repo=checkpoint_repo, dlq_repo=dlq_repo)
        # Assigned rather than passed: `CheckpointTrackingProjection` accepts a
        # retry_policy, but `DeclarativeProjection` does not forward one, so
        # this attribute is the only seam a declarative projection has. If a
        # future eventsource release adds the parameter, pass it instead --
        # this line is a workaround for a gap, not a preference.
        self._retry_policy = LOCAL_RETRY_POLICY

    @handles(SessionStarted)
    async def _on_started(self, event: SessionStarted) -> None:
        await self._rows.save(
            SessionSummaryRow(id=event.aggregate_id, started_at=event.occurred_at)
        )

    @handles(UserMessageSent)
    async def _on_user_message(self, event: UserMessageSent) -> None:
        row = await self._require(event.aggregate_id)
        if row.first_message:
            return
        row.first_message = str(event.message.get("data", {}).get("content", ""))
        await self._rows.save(row)

    @handles(TurnCompleted)
    async def _on_turn_completed(self, event: TurnCompleted) -> None:
        row = await self._require(event.aggregate_id)
        row.turns = event.turn_index
        await self._rows.save(row)

    @handles(TurnFailed)
    async def _on_turn_failed(self, event: TurnFailed) -> None:
        row = await self._require(event.aggregate_id)
        row.failed_turns += 1
        await self._rows.save(row)

    @handles(FileWritten)
    async def _on_file_written(self, event: FileWritten) -> None:
        await self._touch_file(event.aggregate_id, event.path)

    @handles(FileEdited)
    async def _on_file_edited(self, event: FileEdited) -> None:
        await self._touch_file(event.aggregate_id, event.path)

    @handles(FileDeleted)
    async def _on_file_deleted(self, event: FileDeleted) -> None:
        row = await self._require(event.aggregate_id)
        row.file_paths = [path for path in row.file_paths if path != event.path]
        await self._rows.save(row)

    @handles(SessionForkedFrom)
    async def _on_forked_from(self, event: SessionForkedFrom) -> None:
        row = await self._require(event.aggregate_id)
        row.forked_from = event.source_session_id
        row.forked_at = event.at_event
        await self._rows.save(row)

    async def _touch_file(self, session_id: UUID, path: str) -> None:
        row = await self._require(session_id)
        if path in row.file_paths:
            return
        row.file_paths = [*row.file_paths, path]
        await self._rows.save(row)

    async def _require(self, session_id: UUID) -> SessionSummaryRow:
        """The row for a session, which must already exist.

        `SessionStarted` is the creation event and cannot be preceded on its
        own stream, so a missing row means events arrived out of order or the
        table was truncated under a checkpoint that survived. Both are worth an
        error rather than a silently invented row.
        """
        row = await self._rows.get(session_id)
        if row is None:
            raise LookupError(f"no summary row for session {session_id}")
        return row


class SessionSummaryStore:
    """The `/sessions` table, its projection, and the connection they share.

    Opening it applies the model's own DDL, so there is no migration step to
    run and forget -- the table either exists or is created on the way past.
    """

    def __init__(
        self,
        connection: aiosqlite.Connection,
        rows: ReadModelRepository[SessionSummaryRow],
        projection: SessionSummaryProjection,
    ) -> None:
        self._connection = connection
        self._rows = rows
        self.projection = projection

    @classmethod
    async def open(
        cls, db_path: str, checkpoint_repo=None, dlq_repo=None
    ) -> "SessionSummaryStore":
        connection = await aiosqlite.connect(db_path)
        await connection.executescript(
            generate_full_schema(SessionSummaryRow, dialect="sqlite")
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, SessionSummaryRow)
        return cls(
            connection,
            rows,
            SessionSummaryProjection(rows, checkpoint_repo, dlq_repo),
        )

    async def list(self) -> list[SessionSummary]:
        """Every session, newest first -- one indexed query, not a full fold."""
        found = await self._rows.find(
            Query(order_by="started_at", order_direction="desc")
        )
        return [to_summary(row) for row in found]

    async def truncate(self) -> None:
        """Empty the table, for a rebuild to fill again.

        Deletes rather than soft-deletes: a rebuild is not a domain event, and
        a soft-deleted row would linger invisibly and collide with the row the
        replay is about to write for the same session.
        """
        await self._connection.execute(f"DELETE FROM {SessionSummaryRow.table_name()}")
        await self._connection.commit()

    async def close(self) -> None:
        await self._connection.close()


class SessionSummaryRunner:
    """Keeps the `/sessions` table following the log, and answers from it.

    Satisfies the `SessionSummaries` port, so the service can hold it from the
    moment it is constructed -- but the connection and the subscription behind
    it are opened in `start()`, inside the event loop that will use them.
    aiosqlite connections are bound to the loop that created them, so building
    one at import or construction time is a bug waiting for a different loop.
    """

    def __init__(self, store: SQLiteEventStore, db_path: str, bus: InMemoryEventBus):
        self._store = store
        self._db_path = db_path
        self._bus = bus
        self._summaries: SessionSummaryStore | None = None
        self._manager: SubscriptionManager | None = None
        self._subscription = None
        self._checkpoints: SQLCheckpointRepository | None = None
        self._dlq: SQLDLQRepository | None = None

    @property
    def projection_name(self) -> str:
        """The subscription's name, which is also its checkpoint and DLQ key."""
        return SessionSummaryProjection.__name__

    async def start(self) -> None:
        """Open the table and start following the log.

        The subscription replays from its checkpoint and then transitions to
        live events off the bus, so a table that is empty, stale, or exactly
        current all converge to the same place -- which is what makes this
        derived data that can be deleted and rebuilt rather than a second
        source of truth.
        """
        if self._manager is not None:
            return
        # Touch the event store first. It creates its schema -- including the
        # `projection_checkpoints` table this repository is about to read, and
        # the additive columns a newer library version adds to it -- on first
        # connection, not at construction. Reaching for checkpoints before
        # anything has used the store finds no table at all.
        await self._store.current_position()
        engine = create_async_engine(f"sqlite+aiosqlite:///{self._db_path}")
        self._checkpoints = SQLCheckpointRepository(engine)
        self._dlq = SQLDLQRepository(engine)
        self._summaries = await SessionSummaryStore.open(
            self._db_path, self._checkpoints, self._dlq
        )
        self._manager = SubscriptionManager(
            self._store, self._bus, self._checkpoints, dlq_repo=self._dlq
        )
        self._subscription = await self._manager.subscribe(
            self._summaries.projection, SubscriptionConfig(start_from="checkpoint")
        )
        results = await self._manager.start()
        failures = {name: err for name, err in results.items() if err is not None}
        if failures:
            raise RuntimeError(f"the /sessions projection failed to start: {failures}")

    async def failures(self, limit: int = 100) -> list[DLQEntry]:
        """Events this projection could not process.

        A non-empty list means the table has drifted from the log: the
        subscription carried on past the failure, so the row those events would
        have updated is wrong and will stay wrong until `rebuild()`.
        """
        if self._dlq is None:
            return []
        return await self._dlq.get_failed_events(
            projection_name=self.projection_name, limit=limit
        )

    async def health(self) -> SummaryHealth:
        """Whether the table can currently be trusted.

        `failed_events` is the one that matters: each entry is an event the
        projection gave up on, so each is a row that is wrong and will stay
        wrong until a rebuild. The other two describe ordinary operation.
        """
        if self._manager is None or self._subscription is None:
            return SummaryHealth(failed_events=0, following=False, behind=False)
        target = await self._store.current_position()
        reached = self._subscription.last_processed_position
        return SummaryHealth(
            failed_events=len(await self.failures()),
            following=self._subscription.is_running,
            behind=target is not None and (reached is None or reached < target),
        )

    async def rebuild(self) -> None:
        """Throw the table away and derive it again from the log.

        This is the repair for drift, and the reason drift is survivable at
        all: the log is the only source of truth, so anything computed from it
        can be discarded. Dropping the checkpoint with the rows is the part
        that matters -- dropping the rows alone would leave the subscription
        resuming from its old position over an empty table, which is a far
        worse state than the one being repaired.

        Runs the replay through a stopped subscription and starts it again
        afterwards, so nothing is applying live events into a table that is
        halfway through being rebuilt.
        """
        if self._manager is None or self._summaries is None:
            raise RuntimeError("the /sessions projection has not been started")
        await self._manager.stop()
        # Resolve the outstanding failures first. They record events that were
        # never applied *to the table being discarded*, so once it is gone they
        # describe nothing -- and a health check that stays red after a
        # successful repair is one people learn to ignore. Marked resolved
        # rather than deleted, so the record that it happened survives. If the
        # underlying bug is still there, the replay below files fresh entries.
        for entry in await self.failures(limit=1000):
            await self._dlq.mark_resolved(entry.id, resolved_by="rebuild")
        await self._summaries.truncate()
        await self._checkpoints.reset_checkpoint(self.projection_name)
        self._manager = None
        self._subscription = None
        await self._summaries.close()
        self._summaries = None
        await self.start()
        await self.caught_up()

    async def list(self) -> list[SessionSummary]:
        if self._summaries is None:
            raise RuntimeError("the /sessions projection has not been started")
        return await self._summaries.list()

    async def caught_up(self, timeout: float = 10.0) -> None:
        """Block until the projection has seen everything appended so far.

        The read model is eventually consistent on purpose, which is invisible
        when a person clicks and maddening when a test asserts. Rather than
        sleep and hope, this compares the subscription's position against the
        log's own end -- so it waits exactly as long as it has to.
        """
        if self._manager is None:
            return
        target = await self._store.current_position()
        if target is None:
            return
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            reached = self._subscription.last_processed_position
            if reached is not None and not reached < target:
                return
            await asyncio.sleep(0.01)
        raise TimeoutError(
            f"the /sessions projection did not reach {target} within {timeout}s"
        )

    async def stop(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
            self._manager = None
        if self._summaries is not None:
            await self._summaries.close()
            self._summaries = None
