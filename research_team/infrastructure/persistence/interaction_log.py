"""One flat table holding every interaction event.

Flat, with a JSON payload column, rather than a table per kind. The
vocabulary will churn, the database is droppable, and SQLite's JSON operators
are enough for the hand queries this feature exists to enable:

    uv run python -c "
    import sqlite3
    con = sqlite3.connect('$HOME/.research-team/interactions.db')
    for row in con.execute(
        \"select seq, kind, view, json_extract(payload,'$.dwell_ms')\"
        \" from interaction_events where browser_session_id = ? order by seq\",
        ('...',),
    ):
        print(row)
    "

The `sqlite3` CLI is the more natural way to write this and is not assumed
present -- it is not installed on every machine this runs on, and the form
above needs nothing beyond the interpreter already in this project's venv.

Per-kind tables would be the right call once a consumer exists and its
queries are known. Today there is no consumer, and guessing at its shape is
what this design is arranged to avoid.
"""

import asyncio
import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

import aiosqlite
from eventsource import (
    DeclarativeProjection,
    DomainEvent,
    InMemoryEventBus,
    ReadModel,
    SQLCheckpointRepository,
    SQLDLQRepository,
    create_async_engine,
    handles,
)
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.readmodels import SQLiteReadModelRepository
from eventsource.application.subscriptions import SubscriptionConfig, SubscriptionManager
from eventsource.ports.dlq import DLQEntry
from eventsource.ports.readmodels import Filter, Query, ReadModelRepository
from pydantic import Field, field_validator
from sqlalchemy.ext.asyncio import AsyncEngine

from research_team.domain.interaction import (
    ActionRetried,
    ActionUndone,
    ApprovalDecided,
    AskSubmitted,
    AttentionLost,
    AttentionRegained,
    DispatchRequested,
    EmptyResultEncountered,
    EntityOpened,
    ExtractionCancelled,
    ExtractionQueued,
    InteractionEvent,
    ProjectSwitched,
    SearchPerformed,
    ViewEntered,
    ViewExited,
)
from research_team.infrastructure.persistence.read_models import (
    LOCAL_RETRY_POLICY,
    apply_schema,
)

INTERACTION_LOG_NAMESPACE = UUID("6f1d9b02-3e7c-4a58-9c31-0d5b7a8e4f12")


class InteractionEventRow(ReadModel):
    """One interaction, as stored.

    `id` is derived rather than random -- see `row_id`. No column is named
    after a SQLite keyword: the generated DDL does not quote identifiers, and
    `check_telemetry.py` records what that costs when you forget.
    """

    __table_name__ = "interaction_events"

    browser_session_id: UUID
    install_id: UUID
    seq: int
    kind: str
    view: str
    occurred_at: datetime
    received_at: datetime | None = None
    project_id: UUID | None = None
    session_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    """Everything specific to the kind. SQLite hands this back as JSON text,
    hence the decoder below."""

    @field_validator("payload", mode="before")
    @classmethod
    def _decode_payload(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def row_id(browser_session_id: UUID, seq: int) -> UUID:
        """Derived from the pair, so a duplicate delivery overwrites rather
        than duplicating.

        `sendBeacon` can deliver twice and a timer flush can race a page-hide
        flush, so duplicates are the expected case. A random id would store
        both, and every count over this table would be quietly wrong.

        The pair rather than `seq` alone: seq is monotonic within one browser
        session and collides freely across them.
        """
        return uuid5(INTERACTION_LOG_NAMESPACE, f"{browser_session_id}:{seq}")


# Every field the base `DomainEvent` and `InteractionEvent` envelopes supply,
# including `correlation_id`, `tenant_id` and `actor_id` -- not just the pair
# that happen to have their own row columns. A hand-picked exclusion set
# misses whichever envelope field nobody thought to name, and it would leak
# straight into `payload` with nothing to catch it.
_ENVELOPE_FIELDS = frozenset(DomainEvent.model_fields) | frozenset(
    InteractionEvent.model_fields
)


def row_for(event: InteractionEvent) -> InteractionEventRow:
    """The row one event becomes.

    Split out of the projection so the store can write a row without a
    subscription, which is what makes Task 3's tests independent of Task 4.
    """
    payload = {
        name: value
        for name, value in event.model_dump(mode="json").items()
        if name not in _ENVELOPE_FIELDS
    }
    return InteractionEventRow(
        id=InteractionEventRow.row_id(event.aggregate_id, event.seq),
        browser_session_id=event.aggregate_id,
        install_id=event.install_id,
        seq=event.seq,
        kind=type(event).__name__,
        view=event.view,
        occurred_at=event.occurred_at,
        received_at=event.received_at,
        project_id=event.project_id,
        session_id=event.session_id,
        payload=payload,
    )


class InteractionLogStore:
    """The table, and the few reads worth having before a consumer exists.

    No projection here, unlike `CheckTelemetryStore` -- this store is used
    standalone by its own tests and by Task 4's runner, which builds its own
    projection from `rows` directly. A projection this store never drives
    would be dead weight.
    """

    def __init__(
        self,
        connection: aiosqlite.Connection,
        rows: ReadModelRepository[InteractionEventRow],
    ) -> None:
        self._connection = connection
        self._rows = rows

    @classmethod
    async def open(
        cls,
        db_path: str,
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> "InteractionLogStore":
        connection = await aiosqlite.connect(db_path)
        await apply_schema(connection, InteractionEventRow)
        # Two indexes for the two reads this log is for: a stream read, which
        # is what prefix prediction needs, and an aggregate read by kind over
        # time, which is what friction counting needs.
        await connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_interaction_events_stream "
            f"ON {InteractionEventRow.table_name()}(browser_session_id, seq)"
        )
        await connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_interaction_events_kind "
            f"ON {InteractionEventRow.table_name()}(kind, occurred_at)"
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, InteractionEventRow, tracer)
        return cls(connection, rows)

    @property
    def rows(self) -> ReadModelRepository[InteractionEventRow]:
        return self._rows

    async def record(self, event: InteractionEvent) -> None:
        """Write one event's row, replacing any row already there for its
        (browser_session_id, seq)."""
        await self._rows.save(row_for(event))

    async def events(self, browser_session_id: UUID) -> list[InteractionEventRow]:
        found = await self._rows.find(
            Query(
                filters=[
                    Filter(
                        field="browser_session_id",
                        operator="eq",
                        # The real UUID, not `str(...)` -- `check_telemetry.py`
                        # records a stringified filter matching nothing in the
                        # in-memory repository, which compares the field's real
                        # value.
                        value=browser_session_id,
                    )
                ]
            )
        )
        return sorted(found, key=lambda row: row.seq)

    async def count(self) -> int:
        return len(await self._rows.find(None))

    async def truncate(self) -> None:
        await self._connection.execute(f"DELETE FROM {InteractionEventRow.table_name()}")
        await self._connection.commit()

    async def close(self) -> None:
        await self._connection.close()


class InteractionLogProjection(DeclarativeProjection):
    """Every interaction event becomes one row.

    One handler per kind rather than a single catch-all, because
    `DeclarativeProjection` routes by declared type and derives
    `subscribed_to()` from these decorators -- which is also what the live
    subscription uses to decide which bus events wake it. A kind absent from
    here is a kind that neither wakes the runner nor lands in the table, and
    nothing reports it.

    The handlers are identical because the row shape is uniform; `row_for`
    holds the one implementation.
    """

    def __init__(
        self,
        rows: ReadModelRepository[InteractionEventRow],
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._rows = rows
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    async def _record(self, event: InteractionEvent) -> None:
        await self._rows.save(row_for(event))

    @handles(ViewEntered)
    async def _on_view_entered(self, event: ViewEntered) -> None:
        await self._record(event)

    @handles(ViewExited)
    async def _on_view_exited(self, event: ViewExited) -> None:
        await self._record(event)

    @handles(AttentionLost)
    async def _on_attention_lost(self, event: AttentionLost) -> None:
        await self._record(event)

    @handles(AttentionRegained)
    async def _on_attention_regained(self, event: AttentionRegained) -> None:
        await self._record(event)

    @handles(EntityOpened)
    async def _on_entity_opened(self, event: EntityOpened) -> None:
        await self._record(event)

    @handles(ProjectSwitched)
    async def _on_project_switched(self, event: ProjectSwitched) -> None:
        await self._record(event)

    @handles(ExtractionQueued)
    async def _on_extraction_queued(self, event: ExtractionQueued) -> None:
        await self._record(event)

    @handles(ExtractionCancelled)
    async def _on_extraction_cancelled(self, event: ExtractionCancelled) -> None:
        await self._record(event)

    @handles(DispatchRequested)
    async def _on_dispatch_requested(self, event: DispatchRequested) -> None:
        await self._record(event)

    @handles(SearchPerformed)
    async def _on_search_performed(self, event: SearchPerformed) -> None:
        await self._record(event)

    @handles(AskSubmitted)
    async def _on_ask_submitted(self, event: AskSubmitted) -> None:
        await self._record(event)

    @handles(ApprovalDecided)
    async def _on_approval_decided(self, event: ApprovalDecided) -> None:
        await self._record(event)

    @handles(ActionUndone)
    async def _on_action_undone(self, event: ActionUndone) -> None:
        await self._record(event)

    @handles(ActionRetried)
    async def _on_action_retried(self, event: ActionRetried) -> None:
        await self._record(event)

    @handles(EmptyResultEncountered)
    async def _on_empty_result_encountered(self, event: EmptyResultEncountered) -> None:
        await self._record(event)


class InteractionLogRunner:
    """Keeps `interaction_events` following the interaction log.

    Takes its own store and its own bus. Passing the sessions store's bus
    here would give the subscription wake-ups about a log it is not reading,
    which fails as silence rather than as an error.

    Builds its own `InteractionLogProjection` from `InteractionLogStore.rows`
    inside `start()` -- the store deliberately holds no projection of its own
    (see `InteractionLogStore`'s docstring), because a projection the store
    never drives on its own would be dead weight for Task 3's tests, which use
    the store standalone.
    """

    def __init__(
        self,
        store: SQLiteEventStore,
        db_path: str,
        bus: InMemoryEventBus,
        tracer=None,
    ) -> None:
        self._store = store
        self._db_path = db_path
        self._bus = bus
        self._tracer = tracer
        self._log: InteractionLogStore | None = None
        self._manager: SubscriptionManager | None = None
        self._subscription = None
        self._checkpoints: SQLCheckpointRepository | None = None
        self._dlq: SQLDLQRepository | None = None
        self._engine: AsyncEngine | None = None

    @property
    def projection_name(self) -> str:
        """The subscription's name, which is also its checkpoint and DLQ key."""
        return InteractionLogProjection.__name__

    async def start(self) -> None:
        """Open the table and start following the log.

        Touches the event store first for the reason the other runners do: it
        creates `projection_checkpoints` on first connection rather than at
        construction, so reaching for checkpoints before anything has used the
        store finds no table at all.
        """
        if self._manager is not None:
            return
        await self._store.current_position()
        engine = create_async_engine(f"sqlite+aiosqlite:///{self._db_path}")
        # Held so `stop()` can dispose it -- see `CheckTelemetryRunner.start`.
        self._engine = engine
        self._checkpoints = SQLCheckpointRepository(engine)
        self._dlq = SQLDLQRepository(engine)
        self._log = await InteractionLogStore.open(
            self._db_path, self._checkpoints, self._dlq, self._tracer
        )
        projection = InteractionLogProjection(
            self._log.rows, self._checkpoints, self._dlq, self._tracer
        )
        self._manager = SubscriptionManager(
            self._store, self._bus, self._checkpoints, dlq_repo=self._dlq, tracer=self._tracer
        )
        self._subscription = await self._manager.subscribe(
            projection, SubscriptionConfig(start_from="checkpoint")
        )
        results = await self._manager.start()
        failures = {name: err for name, err in results.items() if err is not None}
        if failures:
            raise RuntimeError(f"the interaction log projection failed to start: {failures}")

    async def failures(self, limit: int = 100) -> list[DLQEntry]:
        """Events this projection could not process.

        A non-empty list means interactions the browser reported are missing
        from the table, with nothing else surfacing that -- an instrument that
        under-reports quietly is the failure worth surfacing here.
        """
        if self._dlq is None:
            return []
        return await self._dlq.get_failed_events(
            projection_name=self.projection_name, limit=limit
        )

    async def events(self, browser_session_id: UUID) -> list[InteractionEventRow]:
        if self._log is None:
            raise RuntimeError("the interaction log projection has not been started")
        return await self._log.events(browser_session_id)

    async def count(self) -> int:
        if self._log is None:
            raise RuntimeError("the interaction log projection has not been started")
        return await self._log.count()

    async def caught_up(self, timeout: float = 10.0) -> None:
        """Wait until every appended event has reached the table.

        Compares global positions rather than filtering the feed by aggregate
        type, and that is only correct because of a precondition: this store
        holds `browser_session` and nothing else. The scoped variants
        elsewhere in this repository exist because `sessions.db` is shared by
        eight aggregate types, and a global wait there never drains.

        **The moment a second category lands in this store, this must become
        the scoped form** -- see `CheckTelemetryRunner.caught_up`, which
        filters by event type because aggregate type alone was not fine
        enough there. The failure mode of getting it wrong is a 10s
        `TimeoutError` naming nothing about the cause.
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
            f"the interaction log projection did not reach {target} within {timeout}s"
        )

    async def rebuild(self) -> None:
        """Throw the table away and derive it again from the log.

        Safe because the table holds no original information: every row comes
        from an event that is still there. Dropping the checkpoint alongside
        the rows is the part that matters -- rows without the checkpoint would
        leave the subscription resuming over an empty table, which is worse
        than the drift being repaired.
        """
        if self._manager is None or self._log is None:
            raise RuntimeError("the interaction log projection has not been started")
        await self._manager.stop()
        for entry in await self.failures(limit=1000):
            await self._dlq.mark_resolved(entry.id, resolved_by="rebuild")
        await self._log.truncate()
        await self._checkpoints.reset_checkpoint(self.projection_name)
        self._manager = None
        self._subscription = None
        await self._log.close()
        self._log = None
        await self.start()
        await self.caught_up()

    async def stop(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
            self._manager = None
        if self._log is not None:
            await self._log.close()
            self._log = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
