"""What the checks were asked at each gate, and what was decided about it.

One table, `check_outcomes`, one row per bound check per review. A review
writes its rows with the decision columns empty; the `ToolCallDecided` that
answers it arrives later and fills them. **That fold is the whole feature** --
it is what turns "how often is this check overridden" into a query rather than
a join across two event types nobody has correlated.

One table rather than two, and one projection rather than two, for two reasons.
The rows and the decision that completes them are read together on every query,
so splitting them would put a join in front of every read for no storage saved.
More decisively, a projection handling only one of the two event types would
never advance its checkpoint past the other -- each subscription has a single
checkpoint, and events it does not handle still have to be consumed for it to
move.

`CorpusProjection` / `CorpusStore` / `CorpusRunner` in `read_models.py` are the
template this follows. Two things diverge from them deliberately and both are
noted where they happen: `caught_up` is scoped by aggregate type rather than
comparing global positions, and the store applies its schema through
`apply_schema` rather than a bare `executescript`.
"""

import asyncio
from datetime import datetime
from uuid import UUID, uuid5

import aiosqlite
from eventsource import (
    DeclarativeProjection,
    FeedReadOptions,
    InMemoryEventBus,
    ReadModel,
    SQLCheckpointRepository,
    SQLDLQRepository,
    collect,
    create_async_engine,
    handles,
)
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.readmodels import SQLiteReadModelRepository
from eventsource.application.subscriptions import SubscriptionConfig, SubscriptionManager
from eventsource.ports.dlq import DLQEntry
from eventsource.ports.readmodels import Query, ReadModelRepository
from eventsource.ports.readmodels.query import Filter
from sqlalchemy.ext.asyncio import AsyncEngine

from research_team.domain import CodingSession, StageChecksEvaluated, ToolCallDecided
from research_team.infrastructure.persistence.read_models import (
    LOCAL_RETRY_POLICY,
    apply_schema,
)

CHECK_TELEMETRY_NAMESPACE = UUID("c36dd14c-6c08-42d7-8d09-239d5cb0e440")
"""Namespace for deriving a row id from `(review_id, check)`.

Derived rather than random for `CORPUS_NAMESPACE`'s reason: the decision
handler and every replay have to find a row this process may not have written,
and looking it up by a random id it would first have to store is circular.
"""


class CheckOutcomeRow(ReadModel):
    """One bound check at one gate, and what happened to the gate afterwards.

    `check_name`, not `check`. The name is forced and it is worth stating why,
    because `check` is what the spec, the event payload and every reader call
    it: `CHECK` is a SQLite keyword, the library's schema generator does not
    quote identifiers, and a field called `check` produces
    `sqlite3.OperationalError: near "TEXT": syntax error` from the generated
    `CREATE TABLE` -- before any index DDL is reached. Quoting the index alone
    does not help; the table itself cannot be created. Measured, not reasoned:
    a `ReadModel` with that field was built and opened against SQLite.

    The decision columns are nullable because a row is written when the review
    lands and completed when the decision arrives. A row with them still null
    is not an error: it is a gate that was posed and never answered, which
    happens when a process dies mid-review and when a review is open right now.
    Task 5 counts those in `evaluated` and excludes them from `decided`, so the
    absence has to survive as an absence.
    """

    __table_name__ = "check_outcomes"

    review_id: UUID
    project_id: UUID
    session_id: UUID
    """The stream this was recorded on.

    Carried rather than inferred because the telemetry is keyed by project and
    this projection reads a session stream: the project id is on the event,
    and the session id would otherwise be the one fact the table loses.
    """
    stage: str
    preset: str
    preset_version: str
    check_name: str
    severity: str
    findings: int
    """0 means the check ran and found nothing -- only readable that way
    alongside `status`, which is what separates it from a check that never ran."""
    status: str
    """`ran` or `unimplemented`."""
    posed_by: str
    """`runner` or `tool`. Decides whether the two timestamps mean anything."""
    evaluated_at: datetime
    decision: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None

    @staticmethod
    def row_id(review_id: UUID, check: str) -> UUID:
        """The row id for one check within one review.

        Keyed on the pair because a review writes a row per check and a check
        recurs in every later review; either half alone collides.
        """
        return uuid5(CHECK_TELEMETRY_NAMESPACE, f"{review_id}:{check}")


class CheckTelemetryProjection(DeclarativeProjection):
    """Applies a review's rows, then the decision that completes them.

    Both handlers load-then-mutate-then-save rather than inserting, so a replay
    from a stale checkpoint re-derives the same rows instead of doubling them.
    That is what makes `rebuild()` safe to reach for.
    """

    def __init__(
        self,
        rows: ReadModelRepository[CheckOutcomeRow],
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

    @handles(StageChecksEvaluated)
    async def _on_evaluated(self, event: StageChecksEvaluated) -> None:
        """One row per bound check, including the ones that found nothing.

        The passing ones are the denominator and are the reason this event
        exists; a projection that stored only the firing ones would reproduce
        the findings file in a table.
        """
        for entry in event.evaluated:
            await self._upsert(
                event, entry["check"], entry["severity"], entry["findings"], "ran"
            )
        for entry in event.unimplemented:
            # `findings=0` here means "did not run", and only `status` says so.
            # Storing these as "ran" would make every unimplemented binding
            # indistinguishable from a check that passed -- which is exactly
            # the confusion B38 has been sitting in.
            await self._upsert(event, entry["check"], entry["severity"], 0, "unimplemented")

    @handles(ToolCallDecided)
    async def _on_decided(self, event: ToolCallDecided) -> None:
        if event.review_id is None:
            return
        # Not a poison event when it matches nothing: it is a decision whose
        # review a truncated rebuild has not replayed yet, or one recorded
        # before this projection existed. Raising would send it to the DLQ and
        # leave every later row un-updated too, which is a far larger wrong
        # answer than a decision nobody can attribute.
        # The UUID itself, not `str(...)`. The SQLite adapter accepts either --
        # it stores ids as TEXT -- but the in-memory repository compares the
        # field's real value, so a stringified filter silently matches nothing
        # there and every projection test would assert against an empty fold.
        # `topics.py` stringifies and is correct only because it is never run
        # against the in-memory repository.
        found = await self._rows.find(
            Query(filters=[Filter(field="review_id", operator="eq", value=event.review_id)])
        )
        for row in found:
            row.decision = event.decision
            row.decided_by = event.decided_by
            row.decided_at = event.occurred_at
            await self._rows.save(row)

    async def _upsert(
        self,
        event: StageChecksEvaluated,
        check: str,
        severity: str,
        findings: int,
        status: str,
    ) -> None:
        """Write the row, or bring an existing one up to date.

        Mutating an existing row rather than replacing it keeps the
        repository's version counter climbing instead of resetting, following
        `CorpusProjection._on_stored`. The decision columns are deliberately
        untouched: a replay rewrites the review's own facts, and the decision
        that already completed them is re-applied by its own event later in the
        same stream.
        """
        row_id = CheckOutcomeRow.row_id(event.review_id, check)
        fields = {
            "review_id": event.review_id,
            "project_id": event.project_id,
            "session_id": event.aggregate_id,
            "stage": event.stage,
            "preset": event.preset,
            "preset_version": event.preset_version,
            "check_name": check,
            "severity": severity,
            "findings": findings,
            "status": status,
            "posed_by": event.posed_by,
            "evaluated_at": event.occurred_at,
        }
        existing = await self._rows.get(row_id)
        if existing is None:
            await self._rows.save(CheckOutcomeRow(id=row_id, **fields))
            return
        for name, value in fields.items():
            setattr(existing, name, value)
        await self._rows.save(existing)


class CheckTelemetryStore:
    """The `check_outcomes` table, its projection, and the connection they share."""

    def __init__(
        self,
        connection: aiosqlite.Connection,
        rows: ReadModelRepository[CheckOutcomeRow],
        projection: CheckTelemetryProjection,
    ) -> None:
        self._connection = connection
        self._rows = rows
        self.projection = projection

    @classmethod
    async def open(
        cls, db_path: str, checkpoint_repo=None, dlq_repo=None, tracer=None
    ) -> "CheckTelemetryStore":
        connection = await aiosqlite.connect(db_path)
        # `apply_schema`, not a bare `executescript` -- `CREATE TABLE IF NOT
        # EXISTS` does nothing to a table that already exists, so a field added
        # to `CheckOutcomeRow` later would be silently missing from every
        # database opened before the change. `read_models.py` still uses the
        # raw form for the corpus table; that is the older path, not the one to
        # copy. See `apply_schema`'s docstring for the incident.
        await apply_schema(connection, CheckOutcomeRow)
        # The generated schema indexes `deleted_at` and nothing else. Every
        # read is by project; the decision handler reads by review on every
        # gate decision; Task 5's aggregation groups by check.
        #
        # `check_name` needs no quoting -- but only because it is not called
        # `check`. See `CheckOutcomeRow`'s docstring for what that cost.
        for column in ("project_id", "check_name", "review_id"):
            await connection.execute(
                f"CREATE INDEX IF NOT EXISTS idx_check_outcomes_{column} "
                f"ON {CheckOutcomeRow.table_name()}({column})"
            )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, CheckOutcomeRow, tracer)
        return cls(
            connection,
            rows,
            CheckTelemetryProjection(rows, checkpoint_repo, dlq_repo, tracer),
        )

    async def outcomes(self, project_id: UUID) -> list[CheckOutcomeRow]:
        """Every recorded outcome in a project, oldest review first.

        Returns whole rows rather than a summary shape: the aggregation that
        turns these into rates is Task 5's, lives in `application/`, and cannot
        name a `ReadModel`. Ordering is stable so that two runs over unchanged
        data produce the same table.
        """
        rows = await self._rows.find(
            Query(filters=[Filter(field="project_id", operator="eq", value=project_id)])
        )
        return sorted(rows, key=lambda row: (row.evaluated_at, row.check_name, str(row.id)))

    async def truncate(self) -> None:
        """Empty the table, for a rebuild to fill again.

        Deletes rather than soft-deletes, for `CorpusStore.truncate`'s reason: a
        soft-deleted row would linger invisibly and collide with the row the
        replay is about to write under the same derived id.
        """
        await self._connection.execute(f"DELETE FROM {CheckOutcomeRow.table_name()}")
        await self._connection.commit()

    async def close(self) -> None:
        await self._connection.close()


class CheckTelemetryRunner:
    """Keeps `check_outcomes` following the log, and answers from it.

    A fourth runner rather than another subscription on an existing one, for
    the reason `CorpusRunner` sets out at length: `rebuild()` stops a manager,
    truncates a table and resets a checkpoint, and two tables that can fail
    independently have to be repairable independently. Repairing telemetry must
    not stop corpus reads, and repairing the corpus must not silently discard
    every measurement taken so far.
    """

    def __init__(
        self,
        store: SQLiteEventStore,
        db_path: str,
        bus: InMemoryEventBus,
        tracer=None,
    ):
        self._store = store
        self._db_path = db_path
        self._bus = bus
        self._tracer = tracer
        self._telemetry: CheckTelemetryStore | None = None
        self._manager: SubscriptionManager | None = None
        self._subscription = None
        self._checkpoints: SQLCheckpointRepository | None = None
        self._dlq: SQLDLQRepository | None = None
        self._engine: AsyncEngine | None = None

    @property
    def projection_name(self) -> str:
        """The subscription's name, which is also its checkpoint and DLQ key."""
        return CheckTelemetryProjection.__name__

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
        # Held so `stop()` can dispose it -- see `SessionSummaryRunner.start`.
        self._engine = engine
        self._checkpoints = SQLCheckpointRepository(engine)
        self._dlq = SQLDLQRepository(engine)
        self._telemetry = await CheckTelemetryStore.open(
            self._db_path, self._checkpoints, self._dlq, self._tracer
        )
        self._manager = SubscriptionManager(
            self._store, self._bus, self._checkpoints, dlq_repo=self._dlq, tracer=self._tracer
        )
        self._subscription = await self._manager.subscribe(
            self._telemetry.projection, SubscriptionConfig(start_from="checkpoint")
        )
        results = await self._manager.start()
        failures = {name: err for name, err in results.items() if err is not None}
        if failures:
            raise RuntimeError(f"the check telemetry projection failed to start: {failures}")

    async def failures(self, limit: int = 100) -> list[DLQEntry]:
        """Events this projection could not process.

        A non-empty list means the measurements are missing runs the log
        records -- which reads downstream as a check with a lower fire rate
        than it has, rather than as an error anybody sees. An instrument that
        under-reports quietly is the failure worth surfacing here.
        """
        if self._dlq is None:
            return []
        return await self._dlq.get_failed_events(
            projection_name=self.projection_name, limit=limit
        )

    async def outcomes(self, project_id: UUID) -> list[CheckOutcomeRow]:
        if self._telemetry is None:
            raise RuntimeError("the check telemetry projection has not been started")
        return await self._telemetry.outcomes(project_id)

    async def caught_up(self, timeout: float = 10.0) -> None:
        """Block until the projection has seen every session event so far.

        **Scoped by aggregate type, and not a comparison against the store's
        global position.** This is the one place this class diverges from
        `CorpusRunner`, and the divergence is not cosmetic: this subscription
        consumes `CodingSession` events in a store that also holds `Project`,
        `Corpus`, `Topic` and redstring's streams. Any append of another type
        moves the global end to a position this projection will never reach,
        and a wait on that position runs its full timeout and then raises a
        `TimeoutError` naming nothing about the cause.

        That is not a hypothetical here. Every gate this feature instruments
        sits inside a stage advance, and an advance writes to the `Project`
        stream -- so the event immediately after a review is routinely one this
        projection must ignore. `SessionSummaryRunner.caught_up` carries the
        same fix and the longer version of this story.

        The remaining-work read starts from what the subscription has already
        processed, so in the common case it is empty rather than a log scan.
        """
        if self._manager is None:
            return
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            remaining = await collect(
                self._store.read_all(
                    from_position=self._subscription.last_processed_position,
                    options=FeedReadOptions(aggregate_type=CodingSession.aggregate_type),
                )
            )
            if not remaining:
                return
            await asyncio.sleep(0.01)
        raise TimeoutError(
            f"the check telemetry projection did not consume every "
            f"{CodingSession.aggregate_type} event within {timeout}s"
        )

    async def rebuild(self) -> None:
        """Throw the table away and derive it again from the log.

        Safe because the table holds no original information: every count and
        every timestamp comes from an event that is still there. Dropping the
        checkpoint alongside the rows is the part that matters -- rows without
        the checkpoint would leave the subscription resuming over an empty
        table, which is worse than the drift being repaired.
        """
        if self._manager is None or self._telemetry is None:
            raise RuntimeError("the check telemetry projection has not been started")
        await self._manager.stop()
        for entry in await self.failures(limit=1000):
            await self._dlq.mark_resolved(entry.id, resolved_by="rebuild")
        await self._telemetry.truncate()
        await self._checkpoints.reset_checkpoint(self.projection_name)
        self._manager = None
        self._subscription = None
        await self._telemetry.close()
        self._telemetry = None
        await self.start()
        await self.caught_up()

    async def stop(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
            self._manager = None
        if self._telemetry is not None:
            await self._telemetry.close()
            self._telemetry = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
