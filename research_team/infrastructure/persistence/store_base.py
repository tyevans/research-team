"""Base classes, schema management, and runner infrastructure for read model stores."""

from __future__ import annotations

import asyncio
import inspect
import sys
from typing import Any
from uuid import UUID

import aiosqlite
from eventsource import (
    FeedReadOptions,
    InMemoryEventBus,
    ReadModel,
    SQLCheckpointRepository,
    SQLDLQRepository,
    collect,
    create_async_engine,
)
from eventsource.adapters.sql.readmodel_schema import (
    generate_additive_migration,
    generate_full_schema,
)
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.application.projections.retry import ExponentialBackoffRetryPolicy
from eventsource.application.subscriptions import (
    SubscriptionConfig,
    SubscriptionManager,
)
from eventsource.application.subscriptions.retry import RetryConfig
from eventsource.ports.dlq import DLQEntry
from eventsource.ports.readmodels import (
    ReadModelSchemaMismatchError,
)
from sqlalchemy.ext.asyncio import AsyncEngine

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

CATALOG_NAMESPACE = UUID("c5e8a017-3d62-5f94-8b21-6a0d4e97c318")
"""A literal, not a derived `uuid5(NAMESPACE_URL, ...)`, matching every other
namespace in this file. A computed namespace would silently remap every row
id the moment its input string is edited; this one is also consumed by the
blurb cache (Task 4), which builds its own ids as
`uuid5(CATALOG_NAMESPACE, f"blurb:{{project_id}}:{{slug}}")`, so it stays at
module level rather than nested in a class."""


def model_schema(model: type[ReadModel]) -> str:
    return generate_full_schema(model, dialect="sqlite")


async def apply_schema(connection: aiosqlite.Connection, model: type[ReadModel]) -> None:
    """Create the table, and add any column the model has grown since.

    `CREATE TABLE IF NOT EXISTS` is the whole of the DDL, which is exactly
    right until a field is *added* to a read model: the table already exists,
    so nothing happens, and the next read fails against a table missing a
    column the row type now declares. That is not a hypothetical -- adding
    `project_id` to `SessionSummaryRow` broke every existing database this way,
    with `/sessions` and `/tree` answering 500 while a fresh database was fine
    and every test passed.

    A read model is derived data, so widening it is always safe: the column is
    added empty and `/rebuild` re-derives it from the log. That is what makes
    this an idempotent reconcile rather than a migration to write and version.
    Only additions are handled -- a *renamed* or *retyped* column is a rebuild
    from scratch, and one that silently dropped data here would be worse than
    an error nobody can miss.

    The additions come from `generate_additive_migration`, which is pure and
    raises `ReadModelSchemaMismatchError` before returning any statement. So a
    model carrying one addable column and one impossible one (`NOT NULL` with
    no default, which has no honest value for the rows already stored) leaves
    the table as it was rather than half-widened. The loop this replaced read
    the column definitions back out of the generated DDL by regex and issued
    one `ALTER` each, so SQLite refused the impossible column *after* the
    addable ones had landed.

    The generator refuses a required column with no default outright, where
    SQLite refuses it only on a table that has rows. That difference matters
    here: `project_id` is exactly such a column, and the incident above is
    repaired by adding it to a database whose table is usually empty. So an
    empty table takes the recreate path instead -- there is no data to lose,
    which is the only reason it is honest.
    """
    await connection.executescript(model_schema(model))
    existing = {
        row[1]
        for row in await (
            await connection.execute(f"PRAGMA table_info({model.table_name()})")
        ).fetchall()
    }
    # Not the library's `reconcile_read_model_schema`, which does this whole
    # function: it takes a SQLAlchemy `AsyncConnection | AsyncEngine`, and
    # every store here owns a raw aiosqlite one. Threading an engine through
    # two `open()` classmethods buys behaviour these few lines already have.
    try:
        statements = generate_additive_migration(model, existing, dialect="sqlite")
    except ReadModelSchemaMismatchError:
        rows = await (
            await connection.execute(f"SELECT 1 FROM {model.table_name()} LIMIT 1")
        ).fetchone()
        if rows is not None:
            # Rows exist and one of the new columns has no honest value for
            # them. `/rebuild` is the answer, and an error nobody can miss is
            # how they find out -- filling the column with a guess would be
            # worse. `test_a_refused_reconcile_leaves_the_table_untouched`
            # fails if any of the addable columns lands anyway.
            raise
        await connection.executescript(
            f"DROP TABLE {model.table_name()};\n{model_schema(model)}"
        )
        await connection.commit()
        return
    for statement in statements:
        await connection.execute(statement)
    await connection.commit()


async def open_readmodel_connection(
    db_path: str,
    *row_classes: type[ReadModel],
) -> aiosqlite.Connection:
    connection = await aiosqlite.connect(db_path)
    for rc in row_classes:
        await apply_schema(connection, rc)
    return connection


class BaseReadModelStore:
    """Base class providing connection lifecycle and table truncation for read model stores."""

    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._connection = connection

    async def close(self) -> None:
        await self._connection.close()

    async def _truncate_tables(self, *row_classes: type[ReadModel]) -> None:
        for rc in row_classes:
            await self._connection.execute(f"DELETE FROM {rc.table_name()}")
        await self._connection.commit()


class BaseProjectionRunner[TStore]:
    """Base lifecycle manager for SQLite read model projections.

    Encapsulates database engine creation, checkpoint tracking, dead-letter queue (DLQ)
    handling, subscription manager lifecycle, caught-up synchronization, and full rebuild
    workflows across all read model runners.
    """

    _label: str = "projection"
    _store_class: type[Any] | None = None
    _projection_class: type[Any] | None = None
    _caught_up_aggregate_types: tuple[str, ...] | None = None
    _caught_up_event_types: tuple[str, ...] | None = None

    def __init__(
        self,
        store: SQLiteEventStore,
        db_path: str,
        bus: InMemoryEventBus,
        tracer: Any = None,
    ) -> None:
        self._store = store
        self._db_path = db_path
        self._bus = bus
        self._tracer = tracer
        self._store_instance: TStore | None = None
        self._manager: SubscriptionManager | None = None
        self._subscription: Any = None
        self._checkpoints: SQLCheckpointRepository | None = None
        self._dlq: SQLDLQRepository | None = None
        self._engine: AsyncEngine | None = None

    @property
    def projection_name(self) -> str:
        """The subscription's name, which is also its checkpoint and DLQ key."""
        cls = self._resolve_projection_class()
        if cls is not None:
            return cls.__name__
        raise NotImplementedError(
            f"{self.__class__.__name__} must define projection_name or _projection_class"
        )

    def _resolve_projection_class(self) -> type[Any] | None:
        if self._projection_class is not None:
            name = getattr(self._projection_class, "__name__", None)
            if name:
                # If a test monkeypatched the class on read_models,
                # prefer that override over the module-level definition.
                rm_mod = sys.modules.get(
                    "research_team.infrastructure.persistence.read_models"
                )
                if rm_mod and hasattr(rm_mod, name):
                    candidate = getattr(rm_mod, name)
                    if candidate is not self._projection_class:
                        return candidate
                mod = sys.modules.get(self._projection_class.__module__)
                if mod and hasattr(mod, name):
                    return getattr(mod, name)
            return self._projection_class
        return None

    def _started(self) -> TStore:
        """The open store, or a refusal naming what was not done."""
        if self._store_instance is None:
            raise RuntimeError(f"the {self._label} projection has not been started")
        return self._store_instance

    @property
    def store(self) -> TStore:
        """The open store, or a refusal naming what was not done."""
        return self._started()

    async def _open_store(
        self,
        db_path: str,
        checkpoints: SQLCheckpointRepository,
        dlq: SQLDLQRepository,
        tracer: Any,
    ) -> TStore:
        """Hook to open the underlying read model store."""
        if self._store_class is not None:
            sig = inspect.signature(self._store_class.open)
            params = sig.parameters
            kwargs: dict[str, Any] = {}
            if "checkpoints" in params:
                kwargs["checkpoints"] = checkpoints
            elif "checkpoint_repo" in params:
                kwargs["checkpoint_repo"] = checkpoints
            if "dlq" in params:
                kwargs["dlq"] = dlq
            elif "dlq_repo" in params:
                kwargs["dlq_repo"] = dlq
            if "tracer" in params:
                kwargs["tracer"] = tracer
            if "retry_policy" in params:
                kwargs["retry_policy"] = LOCAL_RETRY_POLICY
            return await self._store_class.open(db_path, **kwargs)
        raise NotImplementedError(
            f"{self.__class__.__name__} must define _store_class or override _open_store"
        )

    def _create_projection(
        self,
        store: TStore,
        checkpoints: SQLCheckpointRepository,
        dlq: SQLDLQRepository,
        tracer: Any,
    ) -> Any:
        """Hook to construct the projection instance."""
        if hasattr(store, "projection"):
            return store.projection
        cls = self._resolve_projection_class()
        if cls is not None:
            sig = inspect.signature(cls.__init__)
            params = sig.parameters
            kwargs: dict[str, Any] = {}
            if "checkpoint_repo" in params:
                kwargs["checkpoint_repo"] = checkpoints
            elif "checkpoints" in params:
                kwargs["checkpoints"] = checkpoints
            if "dlq_repo" in params:
                kwargs["dlq_repo"] = dlq
            elif "dlq" in params:
                kwargs["dlq"] = dlq
            if "tracer" in params:
                kwargs["tracer"] = tracer
            return cls(store, **kwargs)
        raise NotImplementedError(
            f"{self.__class__.__name__} must define _projection_class "
            "or override _create_projection"
        )

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
        # Held so `stop()` can dispose it. An engine keeps a connection pool,
        # and each pooled aiosqlite connection is backed by a non-daemon
        # thread; closing the store's own connection does not touch them.
        self._engine = engine
        self._checkpoints = SQLCheckpointRepository(engine)
        self._dlq = SQLDLQRepository(engine)
        self._store_instance = await self._open_store(
            self._db_path, self._checkpoints, self._dlq, self._tracer
        )
        projection = self._create_projection(
            self._store_instance, self._checkpoints, self._dlq, self._tracer
        )
        self._manager = SubscriptionManager(
            self._store,
            self._bus,
            self._checkpoints,
            dlq_repo=self._dlq,
            tracer=self._tracer,
        )
        self._subscription = await self._manager.subscribe(
            projection, SubscriptionConfig(start_from="checkpoint")
        )
        results = await self._manager.start()
        failures = {name: err for name, err in results.items() if err is not None}
        if failures:
            raise RuntimeError(f"the {self._label} projection failed to start: {failures}")

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

    async def _truncate_store(self) -> None:
        """Hook to clear table(s) on rebuild. Subclasses can override."""
        if hasattr(self._store_instance, "truncate"):
            await self._store_instance.truncate()

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
        if self._manager is None or self._store_instance is None:
            raise RuntimeError(f"the {self._label} projection has not been started")
        await self._manager.stop()
        # Resolve the outstanding failures first. They record events that were
        # never applied *to the table being discarded*, so once it is gone they
        # describe nothing -- and a health check that stays red after a
        # successful repair is one people learn to ignore. Marked resolved
        # rather than deleted, so the record that it happened survives. If the
        # underlying bug is still there, the replay below files fresh entries.
        for entry in await self.failures(limit=1000):
            await self._dlq.mark_resolved(entry.id, resolved_by="rebuild")
        await self._truncate_store()
        await self._checkpoints.reset_checkpoint(self.projection_name)
        self._manager = None
        self._subscription = None
        if self._store_instance is not None:
            await self._store_instance.close()
            self._store_instance = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
        await self.start()
        await self.caught_up()

    def _caught_up_timeout_message(self, target: int | None, timeout: float) -> str:
        if self._caught_up_aggregate_types is not None:
            types_str = " and ".join(self._caught_up_aggregate_types)
            return (
                f"the {self._label} projection did not consume every {types_str} "
                f"event within {timeout}s"
            )
        return f"the {self._label} projection did not reach {target} within {timeout}s"

    async def caught_up(self, timeout: float = 10.0) -> None:
        """Block until the projection has seen everything appended so far."""
        if self._manager is None:
            return
        if self._caught_up_aggregate_types is not None:
            deadline = asyncio.get_running_loop().time() + timeout
            while asyncio.get_running_loop().time() < deadline:
                remaining: list[Any] = []
                for agg_type in self._caught_up_aggregate_types:
                    envelopes = await collect(
                        self._store.read_all(
                            from_position=self._subscription.last_processed_position,
                            options=FeedReadOptions(aggregate_type=agg_type),
                        )
                    )
                    if self._caught_up_event_types is not None:
                        envelopes = [
                            e
                            for e in envelopes
                            if type(e.event).__name__ in self._caught_up_event_types
                        ]
                    remaining.extend(envelopes)
                if not remaining:
                    return
                await asyncio.sleep(0.01)
            raise TimeoutError(self._caught_up_timeout_message(None, timeout))
        else:
            target = await self._store.current_position()
            if target is None:
                return
            deadline = asyncio.get_running_loop().time() + timeout
            while asyncio.get_running_loop().time() < deadline:
                reached = self._subscription.last_processed_position
                if reached is not None and not reached < target:
                    return
                await asyncio.sleep(0.01)
            raise TimeoutError(self._caught_up_timeout_message(target, timeout))

    async def stop(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
            self._manager = None
            self._subscription = None
        if self._store_instance is not None:
            await self._store_instance.close()
            self._store_instance = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None


__all__ = [
    "CATALOG_NAMESPACE",
    "LOCAL_RETRY_POLICY",
    "BaseProjectionRunner",
    "BaseReadModelStore",
    "apply_schema",
    "model_schema",
    "open_readmodel_connection",
]
