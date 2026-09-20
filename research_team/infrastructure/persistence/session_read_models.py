"""Session summary read model, projection, store, and runner.

Houses the `/sessions` read-side state and projections.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

import aiosqlite
from eventsource import (
    DeclarativeProjection,
    ReadModel,
    handles,
)
from eventsource.adapters.sqlite.readmodels import SQLiteReadModelRepository
from eventsource.ports.readmodels import (
    Query,
    ReadModelRepository,
)
from pydantic import Field, field_validator

from research_team.application import SessionSummary, SummaryHealth
from research_team.domain import (
    FileDeleted,
    FileEdited,
    FileWritten,
    Session,
    SessionForkedFrom,
    SessionPurpose,
    SessionStarted,
    TurnCompleted,
    TurnFailed,
    UserMessageSent,
)
from research_team.infrastructure.persistence.store_base import (
    LOCAL_RETRY_POLICY,
    BaseProjectionRunner,
    BaseReadModelStore,
    open_readmodel_connection,
)

__all__ = [
    "SessionSummaryProjection",
    "SessionSummaryRow",
    "SessionSummaryRunner",
    "SessionSummaryStore",
    "to_summary",
]


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
    project_id: UUID
    """Required, matching `SessionStarted`. A row without one could only come
    from a database written before a project was compulsory, and this build
    does not load those: the event itself refuses to validate, so a rebuild
    raises rather than quietly reproducing the row."""
    purpose: SessionPurpose
    """Required, matching `SessionStarted`. A row without one could only come
    from a database written before purpose was compulsory, and this build
    does not load those: the event itself refuses to validate, so a rebuild
    raises rather than quietly reproducing the row."""

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
        project_id=row.project_id,
        purpose=row.purpose,
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
        tracer=None,
    ) -> None:
        self._rows = rows
        # Without a DLQ the library logs a permanent failure at CRITICAL and
        # moves on, so the only record of a corrupted row is a line in a log
        # nobody is reading. With one, the failure is queryable -- which is
        # what makes `rebuild()` something you know to reach for.
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(SessionStarted)
    async def _on_started(self, event: SessionStarted) -> None:
        await self._rows.save(
            SessionSummaryRow(
                id=event.aggregate_id,
                started_at=event.occurred_at,
                # Written here and nowhere else: this is the only event that
                # carries a project or a purpose, so no later handler can
                # change either and a replay from any checkpoint re-derives
                # the same values.
                project_id=event.project_id,
                purpose=event.purpose,
            )
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


class SessionSummaryStore(BaseReadModelStore):
    """The `/sessions` table, its projection, and the connection they share.

    Opening it applies the model's own DDL, so there is no migration step to
    run and forget -- the table either exists or is created on the way past,
    and a column the model has gained since is added on the way past too.
    """

    def __init__(
        self,
        connection: aiosqlite.Connection,
        rows: ReadModelRepository[SessionSummaryRow],
        projection: SessionSummaryProjection,
    ) -> None:
        super().__init__(connection)
        self._rows = rows
        self.projection = projection

    @classmethod
    async def open(
        cls, db_path: str, checkpoint_repo=None, dlq_repo=None, tracer=None
    ) -> SessionSummaryStore:
        connection = await open_readmodel_connection(db_path, SessionSummaryRow)
        rows = SQLiteReadModelRepository(connection, SessionSummaryRow, tracer)
        return cls(
            connection,
            rows,
            SessionSummaryProjection(rows, checkpoint_repo, dlq_repo, tracer),
        )

    async def list(self) -> list[SessionSummary]:
        """Every session, newest first -- one indexed query, not a full fold."""
        found = await self._rows.find(Query(order_by="started_at", order_direction="desc"))
        return [to_summary(row) for row in found]

    async def truncate(self) -> None:
        """Empty the table, for a rebuild to fill again.

        Deletes rather than soft-deletes: a rebuild is not a domain event, and
        a soft-deleted row would linger invisibly and collide with the row the
        replay is about to write for the same session.
        """
        await self._truncate_tables(SessionSummaryRow)


class SessionSummaryRunner(BaseProjectionRunner[SessionSummaryStore]):
    """Keeps the `/sessions` table following the log, and answers from it.

    Satisfies the `SessionSummaries` port, so the service can hold it from the
    moment it is constructed -- but the connection and the subscription behind
    it are opened in `start()`, inside the event loop that will use them.
    aiosqlite connections are bound to the loop that created them, so building
    one at import or construction time is a bug waiting for a different loop.
    """

    _label = "/sessions"
    _store_class = SessionSummaryStore
    _projection_class = SessionSummaryProjection
    _caught_up_aggregate_types = (Session.aggregate_type,)

    @property
    def _summaries(self) -> SessionSummaryStore | None:
        return self._store_instance

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

    async def list(self) -> list[SessionSummary]:
        return await self._started().list()
