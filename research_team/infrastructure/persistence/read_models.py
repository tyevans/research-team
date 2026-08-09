"""Tables kept alongside the log, because folding it per request does not scale.

Two of them, for two different reasons.

`/sessions` came first. `summarize_sessions` folds every event in the database
into rows, which is the clearest possible statement of what a summary *is*, and
it stays where it is -- but running it per request costs the whole log every
time, which grows without bound while the answer barely changes. So the same
fold runs here instead, once per event, into a row that is written down. The
definition has not moved; only how often it is applied. The two are held
together by a test that feeds identical events through both and compares.

The corpus table is the opposite case: there is no fold it replaces, because
`CorpusState` deliberately never holds document text. Snapshots are taken every
50 events and folding whole documents into aggregate state would put entire
corpora into each one, so the aggregate keeps an index and the text stays in
the event payload. That trade is only payable if something can read the payload
back, and this is that something.
"""

import asyncio
import json
import re
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
from sqlalchemy.ext.asyncio import AsyncEngine

from research_team.application import SessionSummary, SummaryHealth
from research_team.domain import (
    CodingSession,
    DocumentRecord,
    FileDeleted,
    FileEdited,
    FileWritten,
    SessionForkedFrom,
    SessionStarted,
    SourceDocumentDropped,
    SourceDocumentStored,
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
    project_id: UUID
    """Required, matching `SessionStarted`. A row without one could only come
    from a database written before a project was compulsory, and this build
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
                # carries a project, so no later handler can change it and a
                # replay from any checkpoint re-derives the same value.
                project_id=event.project_id,
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


def _column_definitions(model: type[ReadModel]) -> list[tuple[str, str]]:
    """The `(name, definition)` of every column in a model's generated DDL.

    Read back out of the DDL rather than off the model's fields so there is
    still one source of truth for how a field becomes a column -- the type
    mapping, the defaults and the constraints are the generator's business,
    and a second opinion here would drift from it silently.
    """
    body = re.search(r"CREATE TABLE[^(]*\((.*?)\n\);", model_schema(model), re.DOTALL)
    if not body:
        return []
    columns = []
    for line in body.group(1).splitlines():
        stripped = line.strip().rstrip(",")
        name, _, definition = stripped.partition(" ")
        if name and definition:
            columns.append((name, stripped))
    return columns


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
    """
    await connection.executescript(model_schema(model))
    existing = {
        row[1]
        for row in await (
            await connection.execute(f"PRAGMA table_info({model.table_name()})")
        ).fetchall()
    }
    for name, definition in _column_definitions(model):
        if name not in existing:
            # SQLite refuses `NOT NULL` with no default here, which is the
            # right refusal: such a column has no honest value for the rows
            # already stored. The error names the column, which is what a
            # developer who has just added a field needs to see.
            await connection.execute(
                f"ALTER TABLE {model.table_name()} ADD COLUMN {definition}"
            )
    await connection.commit()


class SessionSummaryStore:
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
        self._connection = connection
        self._rows = rows
        self.projection = projection

    @classmethod
    async def open(
        cls, db_path: str, checkpoint_repo=None, dlq_repo=None, tracer=None
    ) -> "SessionSummaryStore":
        connection = await aiosqlite.connect(db_path)
        await apply_schema(connection, SessionSummaryRow)
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
        self._summaries: SessionSummaryStore | None = None
        self._manager: SubscriptionManager | None = None
        self._subscription = None
        self._checkpoints: SQLCheckpointRepository | None = None
        self._dlq: SQLDLQRepository | None = None
        self._engine: AsyncEngine | None = None

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
        # Held so `stop()` can dispose it. An engine keeps a connection pool,
        # and each pooled aiosqlite connection is backed by a non-daemon
        # thread; closing the store's own connection does not touch them.
        self._engine = engine
        self._checkpoints = SQLCheckpointRepository(engine)
        self._dlq = SQLDLQRepository(engine)
        self._summaries = await SessionSummaryStore.open(
            self._db_path, self._checkpoints, self._dlq, self._tracer
        )
        self._manager = SubscriptionManager(
            self._store,
            self._bus,
            self._checkpoints,
            dlq_repo=self._dlq,
            tracer=self._tracer,
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
        sleep and hope, this waits until nothing this projection consumes is
        still unread -- so it waits exactly as long as it has to.

        **It used to compare against `current_position()`, the store's global
        end, and that was wrong in a way nothing could reach until now.** This
        store is shared: `Project`, `Corpus`, `Topic` and redstring's own
        streams live in it, while this subscription is scoped to
        `CodingSession`. Any append of another type moves the global end to a
        position this projection will never reach, and the wait runs its full
        timeout.

        Starting a session is exactly that case, every time: `start_in_project`
        ends with `JoinProject`, a `Project` append. So the last event in the
        store after any session starts is one this projection must ignore, and
        `caught_up` could only ever time out. It was survivable while sessions
        could be created without a project; it cannot be now, which is what
        turned an intermittent test failure into a certain one.

        The remaining-work read is scoped and starts from what the
        subscription has already processed, so it is empty in the common case
        rather than a scan of the log.
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
            f"the /sessions projection did not consume every {CodingSession.aggregate_type} "
            f"event within {timeout}s"
        )

    async def stop(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
            self._manager = None
        if self._summaries is not None:
            await self._summaries.close()
            self._summaries = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None


CORPUS_NAMESPACE = UUID("6f1f5f8e-0c4a-5c8f-9b3a-7d2f4c9e1a60")
"""Namespace for deriving a row id from `(project_id, source_id)`.

A read model has one `id` and a corpus document is keyed by two things, so the
id is a uuid5 of both rather than a surrogate. Derived rather than random
because the projection must be able to find the row for a source it has never
seen in this process -- after a restart, or halfway through a rebuild -- and
looking it up by a random id it would first have to store is circular.
"""


class CorpusDocumentRow(ReadModel):
    """One source document, text and all. `project_id` is the corpus's stream id.

    A `Corpus` shares its UUID with its `Project` and is a distinct stream by
    `StreamId(aggregate_id, "Corpus")`, so the event's `aggregate_id` is the
    project id and is stored under that name -- calling it `corpus_id` here
    would invent a second identifier for the thing callers already hold.

    This is the one place in the system that stores document text, which is
    the whole point: `CorpusState` gave it up so snapshots would stay small,
    and the text has to live somewhere readable or the trade bought nothing.

    `dropped_reason` is kept on the row rather than deleting it, mirroring the
    aggregate. A drop is a judgement someone made and the row is where that
    judgement stays legible; `get` and `list` filter it out, so a dropped
    document is unreadable without being unaccounted for.
    """

    __table_name__ = "corpus_documents"

    project_id: UUID
    source_id: str
    text: str
    sha256: str
    char_count: int
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    fetched_at: str | None = None
    dropped_reason: str | None = None

    @staticmethod
    def row_id(project_id: UUID, source_id: str) -> UUID:
        """The row id for a source in a project.

        Source ids are chosen per project -- `"s1"`, a URL, a filename -- and
        will collide across them. Keying on the pair means one project's
        re-ingest cannot overwrite another's document.
        """
        return uuid5(CORPUS_NAMESPACE, f"{project_id}:{source_id}")


def to_record(row: CorpusDocumentRow) -> DocumentRecord:
    """Present a stored row as the aggregate's own no-text shape.

    Reusing `DocumentRecord` rather than defining a listing type here makes the
    no-text guarantee structural: there is no field for text to arrive in, so a
    listing cannot start carrying corpora by accident. It also keeps the table
    and the fold saying the same thing about a document, which is the property
    a rebuild depends on.
    """
    return DocumentRecord(
        source_id=row.source_id,
        sha256=row.sha256,
        char_count=row.char_count,
        uri=row.uri,
        title=row.title,
        published_at=row.published_at,
        note=row.note,
        dropped_reason=row.dropped_reason,
    )


class CorpusProjection(DeclarativeProjection):
    """Applies corpus events to their row, one event at a time.

    Both handlers are idempotent by overwrite rather than by increment: there
    is no counter here, so replaying from a checkpoint that is behind
    re-derives exactly the same row instead of accumulating. That is why a
    rebuild is safe to reach for.
    """

    def __init__(
        self,
        rows: ReadModelRepository[CorpusDocumentRow],
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

    @handles(SourceDocumentStored)
    async def _on_stored(self, event: SourceDocumentStored) -> None:
        """Write the document, superseding whatever the source held before.

        The existing row is loaded and mutated rather than replaced wholesale,
        so the repository's version counter keeps climbing instead of resetting
        -- and `dropped_reason` is cleared explicitly, because storing asserts
        presence and a live document explaining why it is absent is nonsense.
        """
        row_id = CorpusDocumentRow.row_id(event.aggregate_id, event.source_id)
        fields = {
            "project_id": event.aggregate_id,
            "source_id": event.source_id,
            "text": event.text,
            "sha256": event.sha256,
            "char_count": len(event.text),
            "uri": event.uri,
            "title": event.title,
            "published_at": event.published_at,
            "note": event.note,
            "fetched_at": event.fetched_at,
            "dropped_reason": None,
        }
        existing = await self._rows.get(row_id)
        if existing is None:
            await self._rows.save(CorpusDocumentRow(id=row_id, **fields))
            return
        for name, value in fields.items():
            setattr(existing, name, value)
        await self._rows.save(existing)

    @handles(SourceDocumentDropped)
    async def _on_dropped(self, event: SourceDocumentDropped) -> None:
        row = await self._require(event.aggregate_id, event.source_id)
        row.dropped_reason = event.reason
        await self._rows.save(row)

    async def _require(self, project_id: UUID, source_id: str) -> CorpusDocumentRow:
        """The row for a source, which must already exist.

        The aggregate rejects dropping a source it does not hold, so a missing
        row cannot come from a legitimate stream: it means events arrived out
        of order or the table was truncated under a checkpoint that survived.
        Inventing a row would hide exactly the drift worth knowing about.
        """
        row = await self._rows.get(CorpusDocumentRow.row_id(project_id, source_id))
        if row is None:
            raise LookupError(f"no corpus row for {source_id!r} in project {project_id}")
        return row


class CorpusStore:
    """The corpus table, its projection, and the connection they share.

    Mirrors `SessionSummaryStore`: opening it applies the model's own DDL, so
    there is no migration step to run and forget.
    """

    def __init__(
        self,
        connection: aiosqlite.Connection,
        rows: ReadModelRepository[CorpusDocumentRow],
        projection: CorpusProjection,
    ) -> None:
        self._connection = connection
        self._rows = rows
        self.projection = projection

    @classmethod
    async def open(
        cls, db_path: str, checkpoint_repo=None, dlq_repo=None, tracer=None
    ) -> "CorpusStore":
        connection = await aiosqlite.connect(db_path)
        await connection.executescript(
            generate_full_schema(CorpusDocumentRow, dialect="sqlite")
        )
        # The generated schema indexes `deleted_at` and nothing else. Every
        # read here is by project, and a corpus is the one table expected to
        # grow into the millions of characters, so the scan is worth avoiding.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_corpus_documents_project "
            f"ON {CorpusDocumentRow.table_name()}(project_id)"
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, CorpusDocumentRow, tracer)
        return cls(connection, rows, CorpusProjection(rows, checkpoint_repo, dlq_repo, tracer))

    async def get(self, project_id: UUID, source_id: str) -> CorpusDocumentRow | None:
        """One document with its text, or None if it is unknown or dropped.

        Returns the row rather than a separate shape. `/sessions` converts
        because `SessionSummary` already existed as the application's own
        vocabulary; nothing here predates the row, and inventing a twin of it
        would be a second thing to keep in sync for no gain.

        A dropped source answers None rather than raising: it is a document
        somebody excluded, and the caller asking for it wants to hear that it
        is not available, not to handle an exception for an ordinary state.
        """
        row = await self._rows.get(CorpusDocumentRow.row_id(project_id, source_id))
        if row is None or row.project_id != project_id or row.dropped_reason is not None:
            return None
        return row

    async def list(
        self, project_id: UUID, *, include_dropped: bool = False
    ) -> list[DocumentRecord]:
        """Every document in a project, by source id, without their text.

        Selects columns explicitly instead of going through the repository,
        which would load whole rows -- and a row here is an entire document.
        Listing a corpus of a hundred papers would pull every one of them
        through memory to render a table of titles.

        `include_dropped` defaults to False so every existing caller -- the
        agent's own `list_sources` tool among them -- keeps seeing exactly
        the live corpus it always has. A caller that opts in gets dropped
        rows back too, `dropped_reason` and all, because the corpus keeps
        them on purpose and hiding them would misreport what it holds.
        """
        columns = (
            "source_id",
            "sha256",
            "char_count",
            "uri",
            "title",
            "published_at",
            "note",
            "dropped_reason",
        )
        drop_filter = "" if include_dropped else "AND dropped_reason IS NULL "
        cursor = await self._connection.execute(
            f"SELECT {', '.join(columns)} FROM {CorpusDocumentRow.table_name()} "
            f"WHERE project_id = ? {drop_filter}AND deleted_at IS NULL "
            "ORDER BY source_id",
            (str(project_id),),
        )
        try:
            return [
                DocumentRecord(**dict(zip(columns, row, strict=True)))
                for row in await cursor.fetchall()
            ]
        finally:
            await cursor.close()

    async def truncate(self) -> None:
        """Empty the table, for a rebuild to fill again.

        Deletes rather than soft-deletes, for the reason `SessionSummaryStore`
        gives: a soft-deleted row would linger invisibly and collide with the
        row the replay is about to write for the same document.
        """
        await self._connection.execute(f"DELETE FROM {CorpusDocumentRow.table_name()}")
        await self._connection.commit()

    async def close(self) -> None:
        await self._connection.close()


class CorpusRunner:
    """Keeps the corpus table following the log, and answers from it.

    A second runner rather than a second projection on `SessionSummaryRunner`,
    which was the first thing tried. That class can technically carry another
    subscription -- `SubscriptionManager` holds many, and `InMemoryEventBus`
    broadcasts to every subscriber, so there is no competing-consumer hazard --
    but two things make it the wrong home.

    The first is the port. `SessionSummaryRunner` satisfies `SessionSummaries`,
    whose documented subject is the `/sessions` list, and whose `health()`,
    `rebuild()` and `projection_name` are all singular. Making any of them
    answer for two projections is how a port stops meaning anything, and the
    web layer already calls all three.

    The second is `rebuild()`, and it is the one that decides it. Rebuilding is
    a manual repair that stops the manager, truncates a table, resets a
    checkpoint and starts again. Sharing a manager would mean repairing
    `/sessions` also stopped corpus reads, and would put the corpus table one
    editing mistake away from being truncated by a repair that had nothing to
    do with it. Two tables that can fail independently have to be repairable
    independently.

    What sharing would actually have bought is smaller than it looks: the two
    projections write to different tables through different connections either
    way, and SQLite serialises writers at the file level regardless, so the
    duplication avoided is an engine and two repositories that are keyed by
    projection name anyway.
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
        self._corpus: CorpusStore | None = None
        self._manager: SubscriptionManager | None = None
        self._subscription = None
        self._checkpoints: SQLCheckpointRepository | None = None
        self._dlq: SQLDLQRepository | None = None
        self._engine: AsyncEngine | None = None

    @property
    def projection_name(self) -> str:
        """The subscription's name, which is also its checkpoint and DLQ key."""
        return CorpusProjection.__name__

    async def start(self) -> None:
        """Open the table and start following the log.

        Same shape as `SessionSummaryRunner.start`, including touching the
        event store first: it creates the `projection_checkpoints` table on
        first connection rather than at construction, so reaching for
        checkpoints before anything has used the store finds no table at all.
        """
        if self._manager is not None:
            return
        await self._store.current_position()
        engine = create_async_engine(f"sqlite+aiosqlite:///{self._db_path}")
        # Held so `stop()` can dispose it -- see `SessionSummaryRunner.start`.
        self._engine = engine
        self._checkpoints = SQLCheckpointRepository(engine)
        self._dlq = SQLDLQRepository(engine)
        self._corpus = await CorpusStore.open(
            self._db_path, self._checkpoints, self._dlq, self._tracer
        )
        self._manager = SubscriptionManager(
            self._store, self._bus, self._checkpoints, dlq_repo=self._dlq, tracer=self._tracer
        )
        self._subscription = await self._manager.subscribe(
            self._corpus.projection, SubscriptionConfig(start_from="checkpoint")
        )
        results = await self._manager.start()
        failures = {name: err for name, err in results.items() if err is not None}
        if failures:
            raise RuntimeError(f"the corpus projection failed to start: {failures}")

    async def failures(self, limit: int = 100) -> list[DLQEntry]:
        """Events this projection could not process.

        A non-empty list means a document is missing or stale in the table
        while the log still holds it -- which reads downstream as a source that
        cannot be quoted, not as an error.
        """
        if self._dlq is None:
            return []
        return await self._dlq.get_failed_events(
            projection_name=self.projection_name, limit=limit
        )

    async def get(self, project_id: UUID, source_id: str) -> CorpusDocumentRow | None:
        if self._corpus is None:
            raise RuntimeError("the corpus projection has not been started")
        return await self._corpus.get(project_id, source_id)

    async def list(
        self, project_id: UUID, *, include_dropped: bool = False
    ) -> list[DocumentRecord]:
        if self._corpus is None:
            raise RuntimeError("the corpus projection has not been started")
        return await self._corpus.list(project_id, include_dropped=include_dropped)

    async def rebuild(self) -> None:
        """Throw the table away and derive it again from the log.

        Safe precisely because this table holds no original information: every
        byte of every document is in the event that put it there. Dropping the
        checkpoint alongside the rows is the part that matters -- rows without
        the checkpoint would leave the subscription resuming over an empty
        table, which is worse than the drift being repaired.
        """
        if self._manager is None or self._corpus is None:
            raise RuntimeError("the corpus projection has not been started")
        await self._manager.stop()
        for entry in await self.failures(limit=1000):
            await self._dlq.mark_resolved(entry.id, resolved_by="rebuild")
        await self._corpus.truncate()
        await self._checkpoints.reset_checkpoint(self.projection_name)
        self._manager = None
        self._subscription = None
        await self._corpus.close()
        self._corpus = None
        await self.start()
        await self.caught_up()

    async def caught_up(self, timeout: float = 10.0) -> None:
        """Block until the projection has seen everything appended so far.

        Load-bearing beyond tests, unlike the `/sessions` equivalent: `remember`
        stores a document and then wants to read it back to extract from it, and
        the gap between the append and the row is exactly where that would find
        nothing.
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
        raise TimeoutError(f"the corpus projection did not reach {target} within {timeout}s")

    async def stop(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
            self._manager = None
        if self._corpus is not None:
            await self._corpus.close()
            self._corpus = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
