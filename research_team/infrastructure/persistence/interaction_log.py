"""One flat table holding every interaction event.

Flat, with a JSON payload column, rather than a table per kind. The
vocabulary will churn, the database is droppable, and SQLite's JSON operators
are enough for the hand queries this feature exists to enable:

    sqlite3 ~/.research-team/interactions.db \\
      "select seq, kind, view, json_extract(payload,'$.dwell_ms')
         from interaction_events where browser_session_id = '...' order by seq"

Per-kind tables would be the right call once a consumer exists and its
queries are known. Today there is no consumer, and guessing at its shape is
what this design is arranged to avoid.
"""

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

import aiosqlite
from eventsource import DomainEvent, ReadModel
from eventsource.adapters.sqlite.readmodels import SQLiteReadModelRepository
from eventsource.ports.readmodels import Filter, Query, ReadModelRepository
from pydantic import Field, field_validator

from research_team.domain.interaction import InteractionEvent
from research_team.infrastructure.persistence.read_models import apply_schema

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
