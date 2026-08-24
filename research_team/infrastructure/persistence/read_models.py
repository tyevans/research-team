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
from eventsource.adapters.sql.readmodel_schema import (
    generate_additive_migration,
    generate_full_schema,
)
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.readmodels import SQLiteReadModelRepository
from eventsource.application.projections.retry import ExponentialBackoffRetryPolicy
from eventsource.application.subscriptions import (
    SubscriptionConfig,
    SubscriptionManager,
)
from eventsource.application.subscriptions.retry import RetryConfig
from eventsource.ports.dlq import DLQEntry
from eventsource.ports.readmodels import (
    Filter,
    Query,
    ReadModelRepository,
    ReadModelSchemaMismatchError,
)
from pydantic import Field, field_validator

# The public name, not `redstring.events.document`: reaching through a dotted
# path opts out of the only compatibility promise the library makes, which is
# how 0.8.0 broke six imports here. See PR #180.
from redstring import DocumentExtracted, EntitiesMerged
from redstring.events.streams import DOCUMENT_CATEGORY
from sqlalchemy.ext.asyncio import AsyncEngine

from research_team.application import SessionSummary, SummaryHealth
from research_team.application.media_acquisition import AcceptedProposal
from research_team.domain import (
    UNREADABLE_DEGRADATIONS,
    CorpusDerivedTextStored,
    CorpusDocumentDropped,
    CorpusDocumentStored,
    CorpusMediaStored,
    FileDeleted,
    FileEdited,
    FileWritten,
    MediaRecord,
    Session,
    SessionForkedFrom,
    SessionPurpose,
    SessionStarted,
    SourceRecord,
    TextRecord,
    TurnCompleted,
    TurnFailed,
    UserMessageSent,
)
from research_team.domain.ask_conversation import (
    AskConversation,
    AskConversationStarted,
    AskTurnRecorded,
)
from research_team.domain.catalog_curation import CourseFeatured, CourseUnfeatured
from research_team.domain.course import CourseAbandoned, CourseRealized
from research_team.domain.course_authoring_run import (
    COURSE_AUTHORING_RUN_AGGREGATE_TYPE,
    CourseAuthored,
    CourseAuthoringFailed,
    CourseAuthoringRunSettled,
    CourseAuthoringRunStarted,
)
from research_team.domain.media_proposals import (
    MediaAssetIgnored,
    MediaAssetUnignored,
    MediaHostIgnored,
    MediaHostUnignored,
    MediaNeedsIdentified,
    MediaProposalAccepted,
    MediaProposalFailed,
    MediaProposalRejected,
    MediaProposalStored,
    MediaProposed,
)
from research_team.domain.ontology import (
    ONTOLOGY_AGGREGATE_TYPE,
    DiscoveredClass,
    OntologyDiscovered,
)
from research_team.domain.socratic_dialogue import (
    SocraticDialogue,
    SocraticDialogueConcluded,
    SocraticDialogueStarted,
    SocraticProgressObserved,
    SocraticTurnRecorded,
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
        `Session`. Any append of another type moves the global end to a
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
                    options=FeedReadOptions(aggregate_type=Session.aggregate_type),
                )
            )
            if not remaining:
                return
            await asyncio.sleep(0.01)
        raise TimeoutError(
            f"the /sessions projection did not consume every {Session.aggregate_type} "
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
    derived_from: str | None = None
    """The media source this was perceived from, or None for a fetched
    document -- mirrors `TextRecord.derived_from` exactly; see its docstring
    for why this is not a third kind of row."""
    locator_map: str | None = None
    """JSON, read whole and never queried into. The locator union
    (`TimeSpan | PageRef | BBox | CharSpan | ByteRange`) belongs to
    `readeverything` and will grow arms there; a structured column here would
    make every arm it adds a schema change in this repository, for a query
    nobody makes -- resolving one offset needs every segment in the map, so
    there is no partial read that would justify decomposing it. Nullable
    because a fetched document has no map at all, not an empty one."""
    perceived_with: str | None = None
    """The capability fingerprint that produced this transcript, or None for
    a fetched document. Mirrors `TextRecord.perceived_with`."""
    degradations: str | None = None
    """JSON list of strings, or the JSON encoding of `UNREADABLE_DEGRADATIONS`
    if the event's own field could not be read -- see `_on_derived_text` for
    why null is not used for that case. None (not `"[]"`) for a fetched
    document, which is a different fact from "perception was complete"."""
    extracted_at: str | None = None
    """When this document's text was last folded into the graph, or None.

    The one field here the corpus aggregate cannot supply: extraction happens
    on redstring's `Document` stream, not the `Corpus` one, so this is written
    by `_on_extracted` from an event the fold never sees. That is also why it
    is not on `TextRecord` -- a domain record that claimed to know this
    would be claiming knowledge of another aggregate's stream.

    A timestamp rather than a flag, because "when" is free here (the event
    carries it) and answers the question a flag cannot: whether the graph
    predates a revision of the text.

    **A database written before this column reads every document as
    unextracted, and a rebuild is the only thing that fixes it.** `apply_schema`
    adds the column as NULL and the projection resumes from its checkpoint, so
    the `DocumentExtracted` events that would fill it have already gone by.
    Measured on a copy of a real database on 2026-08-14, not reasoned: three
    documents with graphs, all three reading `extracted=False` on the resume
    path and all three correct after `CorpusRunner.rebuild()`.

    Not migrated, deliberately -- this project is pre-release with no users to
    break, so the rebuild is the answer rather than a backfill nobody will need
    twice.
    """

    @staticmethod
    def row_id(project_id: UUID, source_id: str) -> UUID:
        """The row id for a source in a project.

        Source ids are chosen per project -- `"s1"`, a URL, a filename -- and
        will collide across them. Keying on the pair means one project's
        re-ingest cannot overwrite another's document.
        """
        return uuid5(CORPUS_NAMESPACE, f"{project_id}:{source_id}")


class CorpusMediaRow(ReadModel):
    """One media source: everything but its bytes.

    A separate table rather than columns on `corpus_documents`, for two
    reasons. `corpus_documents.text` is NOT NULL and every media row would have
    to lie about it -- and making it nullable would then let a text row lie
    too, which is the failure mode where a document silently loses its content
    and still lists. Second, `apply_schema` refuses a required column with no
    default outright, so widening is also the more expensive path.

    No `extracted_at`. Nothing extracts media yet, and a column whose only
    value is NULL is a promise the perception slice may not want to keep.
    """

    __table_name__ = "corpus_media"

    project_id: UUID
    source_id: str
    sha256: str
    """Where the bytes are. A row whose blob is gone is a dangling reference,
    which the read path reports as 410 rather than 404 -- see
    `CorpusReadPort.read_media`."""
    media_type: str
    byte_count: int
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    fetched_at: str | None = None
    dropped_reason: str | None = None

    @staticmethod
    def row_id(project_id: UUID, source_id: str) -> UUID:
        """Mirrors `CorpusDocumentRow.row_id` exactly.

        Deliberately the same derivation over the same inputs: the two tables
        share one `source_id` namespace, so a row id that differed between them
        would let one id name two rows. Source ids are chosen per project --
        `"s1"`, a URL, a filename -- and will collide across them. Keying on
        the pair means one project's re-ingest cannot overwrite another's.
        """
        return uuid5(CORPUS_NAMESPACE, f"{project_id}:{source_id}")


def _decode_degradations(value: str) -> tuple[str, ...] | None:
    """Parse a `degradations` JSON string, or say the shape is wrong.

    Shared by the write side (`_on_derived_text`, deciding what to store) and
    the read side (`to_record`, deciding what to hand back), so there is one
    place that knows what "a JSON list of strings" means rather than two that
    could drift. `None` means the value did not parse to that shape --
    callers decide what to do about it, since a writer wants to fall back to
    `UNREADABLE_DEGRADATIONS` and a reader wants the same, for the identical
    reason `_degradations_from` gives in `corpus.py`: an empty tuple already
    means "perception was complete", so silently producing `()` -- or, worse,
    `tuple(json.loads(...))`'s own failure modes, a `ValueError` on bad JSON
    or a tuple of dict keys on well-formed JSON of the wrong shape -- would
    misreport a value that could not be read as one that was fine.
    """
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        return None
    return tuple(parsed)


def _degradations_of(stored: str | None) -> tuple[str, ...]:
    """A row's `degradations` column as a tuple, keeping `[]` distinct from junk.

    Three cases, and the middle one is the one a `or` collapses: no column at
    all (a fetched document -- `()`), a column holding `[]` (a perception that
    missed nothing -- also `()`, and it must not be reported as unreadable),
    and a column that will not parse (`UNREADABLE_DEGRADATIONS`).
    """
    if not stored:
        return ()
    decoded = _decode_degradations(stored)
    return decoded if decoded is not None else UNREADABLE_DEGRADATIONS


def to_record(row: CorpusDocumentRow | CorpusMediaRow) -> SourceRecord:
    """Present a stored row as the aggregate's own no-bytes shape.

    Reusing `TextRecord`/`MediaRecord` rather than defining listing types here
    makes the no-content guarantee structural: there is no field for text or
    bytes to arrive in, so a listing cannot start carrying a corpus by
    accident. It also keeps the tables and the fold saying the same thing
    about a source, which is the property a rebuild depends on.
    """
    if isinstance(row, CorpusMediaRow):
        return MediaRecord(
            source_id=row.source_id,
            sha256=row.sha256,
            media_type=row.media_type,
            byte_count=row.byte_count,
            uri=row.uri,
            title=row.title,
            published_at=row.published_at,
            note=row.note,
            fetched_at=row.fetched_at,
            dropped_reason=row.dropped_reason,
        )
    return TextRecord(
        source_id=row.source_id,
        sha256=row.sha256,
        char_count=row.char_count,
        uri=row.uri,
        title=row.title,
        published_at=row.published_at,
        note=row.note,
        fetched_at=row.fetched_at,
        dropped_reason=row.dropped_reason,
        derived_from=row.derived_from,
        perceived_with=row.perceived_with,
        # Stored as JSON, wanted as a tuple. `row.degradations` is None for a
        # fetched document (no field to decode) and JSON otherwise -- either
        # the producer's list or `UNREADABLE_DEGRADATIONS` re-encoded by
        # `_on_derived_text`. Routed through `_decode_degradations` rather than
        # a bare `tuple(json.loads(...))`: this build never writes a row whose
        # `degradations` fails that shape check, but a row is not an event --
        # nothing here refuses on write the way `decide` does, so a row from a
        # direct edit or an earlier build's bug is not this build's problem to
        # rule out. `UNREADABLE_DEGRADATIONS` is the honest answer for that
        # case too, for the same reason it is the answer for a malformed
        # event.
        # `is None` and not `or`, and the distinction is a shipped bug rather
        # than a style point. `_decode_degradations("[]")` returns `()`, which
        # is falsy, so `or UNREADABLE_DEGRADATIONS` fired on the *ordinary*
        # case -- a complete perception, nothing missed -- and every clean
        # transcript listed one degradation reading "<degradations could not be
        # read from the event>". Measured on 2026-08-16 by the end-to-end test
        # in `tests/integration/test_media_reaches_the_graph.py`, which is the
        # first thing to look at a derived row that degraded nothing; the write
        # side below (`_on_derived_text`) already used `is not None` and was
        # right. The comment above this one explains why the marker exists at
        # all, and it stays true -- it just must not be reached from `[]`.
        degradations=_degradations_of(row.degradations),
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
        media_rows: ReadModelRepository[CorpusMediaRow],
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._rows = rows
        self._media_rows = media_rows
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(CorpusDocumentStored)
    async def _on_stored(self, event: CorpusDocumentStored) -> None:
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
            # Cleared, deliberately. A store event means *new bytes* -- the
            # digest check in `_store_document` swallows a re-store of
            # identical text without appending anything -- so any graph that
            # exists describes text this document no longer has. Reading as
            # unextracted is the honest answer and puts it back in front of
            # the person who can requeue it. Ordering makes this safe rather
            # than lucky: `ingest` stores before it extracts, so the
            # `DocumentExtracted` that follows sets the field again.
            "extracted_at": None,
        }
        existing = await self._rows.get(row_id)
        if existing is None:
            await self._rows.save(CorpusDocumentRow(id=row_id, **fields))
            return
        for name, value in fields.items():
            setattr(existing, name, value)
        await self._rows.save(existing)

    @handles(CorpusDerivedTextStored)
    async def _on_derived_text(self, event: CorpusDerivedTextStored) -> None:
        """Write a transcript into `corpus_documents`, not a new table.

        A derived source *is* a text source -- it chunks, it quotes, it
        extracts -- so every existing text reader has to find it here, not in
        a parallel place that would need its own `get`/`list_all`/extraction
        wiring to match. Load-and-mutate, matching `_on_stored` and
        `_on_media_stored`: the version counter climbs on a re-perception
        rather than resetting.

        **`degradations` is stored as the marker, not as null, when the
        event's own field will not parse.** The two candidates were: null
        the column, or store `UNREADABLE_DEGRADATIONS` (JSON-encoded, since
        the column is JSON text). Null loses the distinction `TextRecord`
        depends on -- its docstring says an *empty* `degradations` means "a
        complete perception", so a NULL that `to_record` decoded as `()`
        would read back as a clean transcript when the truth is that this
        column could not be read at all. Storing the marker instead means
        `to_record` decodes it to the same tuple the aggregate's own
        `_degradations_from` returns for the identical failure in `evolve` --
        one string, one meaning, whichever side reads it, and `to_record`
        reads through the identical `_decode_degradations` check this handler
        writes through, so that parity is enforced by sharing the check
        rather than by two call sites agreeing to write the same logic twice.
        This branch is not reachable through `decide`, which refuses a
        malformed payload before an event is ever written; it exists for the
        same reason `_degradations_from` does, for an event this build did
        not write -- an earlier build, a repair script, or a direct append.
        """
        row_id = CorpusDocumentRow.row_id(event.aggregate_id, event.source_id)
        degradations = (
            event.degradations
            if _decode_degradations(event.degradations) is not None
            else json.dumps(list(UNREADABLE_DEGRADATIONS))
        )
        fields = {
            "project_id": event.aggregate_id,
            "source_id": event.source_id,
            "text": event.text,
            "sha256": event.sha256,
            "char_count": len(event.text),
            "title": event.title,
            # Written on every store, including when it is `None`. A
            # re-perception or a revise that cleared the note has to clear the
            # column too -- this handler load-and-mutates, so a field left out
            # of `fields` keeps whatever the previous store put there, which
            # would make a removed note reappear.
            "note": event.note,
            "dropped_reason": None,
            "derived_from": event.derived_from,
            "locator_map": event.locator_map,
            "perceived_with": event.perceived_with,
            "degradations": degradations,
            # Same reasoning as `_on_stored`: new bytes mean any existing
            # graph describes text this source no longer has.
            "extracted_at": None,
        }
        existing = await self._rows.get(row_id)
        if existing is None:
            await self._rows.save(CorpusDocumentRow(id=row_id, **fields))
            return
        for name, value in fields.items():
            setattr(existing, name, value)
        await self._rows.save(existing)

    @handles(DocumentExtracted)
    async def _on_extracted(self, event: DocumentExtracted) -> None:
        """Note that this source now has a graph.

        The one handler here fed by a stream the corpus does not own.
        `CorpusRunner` subscribes to the whole store rather than one category,
        and dispatch is by event type, so redstring's own event arrives here
        without any new wiring -- `tenant_id` is the project, which is what
        makes the row addressable.

        **A missing row is skipped rather than raised**, which is the opposite
        of `_on_dropped`'s rule and deliberately so. `_require` treats a
        missing row as drift because the corpus aggregate refuses to drop what
        it does not hold, so the event could not legitimately exist. Nothing
        makes that true here: extraction is a different aggregate, redstring
        will happily extract a document this corpus never stored, and every
        `DocumentExtracted` written before the corpus table existed is exactly
        that. Raising would put ordinary history in the DLQ and report drift
        that is not there.
        """
        row = await self._rows.get(CorpusDocumentRow.row_id(event.tenant_id, event.source_id))
        if row is None:
            return
        row.extracted_at = event.occurred_at.isoformat()
        await self._rows.save(row)

    @handles(CorpusMediaStored)
    async def _on_media_stored(self, event: CorpusMediaStored) -> None:
        """Write the media source, superseding whatever it held before.

        Load-and-mutate, matching `_on_stored`: the version counter keeps
        climbing on a re-store rather than resetting, and `dropped_reason` is
        cleared explicitly for the same reason it is there -- storing asserts
        presence.
        """
        row_id = CorpusMediaRow.row_id(event.aggregate_id, event.source_id)
        fields = {
            "project_id": event.aggregate_id,
            "source_id": event.source_id,
            "sha256": event.sha256,
            "media_type": event.media_type,
            "byte_count": event.byte_count,
            "uri": event.uri,
            "title": event.title,
            "published_at": event.published_at,
            "note": event.note,
            "fetched_at": event.fetched_at,
            "dropped_reason": None,
        }
        existing = await self._media_rows.get(row_id)
        if existing is None:
            await self._media_rows.save(CorpusMediaRow(id=row_id, **fields))
            return
        for name, value in fields.items():
            setattr(existing, name, value)
        await self._media_rows.save(existing)

    @handles(CorpusDocumentDropped)
    async def _on_dropped(self, event: CorpusDocumentDropped) -> None:
        """Mark whichever table holds the id, never both.

        Task 2's kind-collision guard makes an id held in both tables
        impossible -- `decide` refuses a store that would change what an
        existing source id means. A handler that updated both tables
        unconditionally would not merely tolerate that guard being violated,
        it would hide the violation: the drop would "succeed" against a row
        that should not exist, instead of surfacing the id collision as
        drift. Trying the document row first and falling back to the media
        row is the same distinction `_kind_of` makes in the domain, made
        again here because the read side cannot ask the aggregate.
        """
        row_id = CorpusDocumentRow.row_id(event.aggregate_id, event.source_id)
        row = await self._rows.get(row_id)
        if row is not None:
            row.dropped_reason = event.reason
            await self._rows.save(row)
            return
        media_row = await self._require_media(event.aggregate_id, event.source_id)
        media_row.dropped_reason = event.reason
        await self._media_rows.save(media_row)

    async def _require_media(self, project_id: UUID, source_id: str) -> CorpusMediaRow:
        """The media row for a source, which must already exist.

        Reached only once `_on_dropped` has ruled out a document row, so a
        miss here means the id is in neither table: the aggregate rejects
        dropping a source it does not hold, so that cannot come from a
        legitimate stream. Inventing a row would hide exactly the drift worth
        knowing about, matching `_require`'s reasoning for the document side.
        """
        row = await self._media_rows.get(CorpusMediaRow.row_id(project_id, source_id))
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
        media_rows: ReadModelRepository[CorpusMediaRow],
        projection: CorpusProjection,
    ) -> None:
        self._connection = connection
        self._rows = rows
        self._media_rows = media_rows
        self.projection = projection

    @classmethod
    async def open(
        cls, db_path: str, checkpoint_repo=None, dlq_repo=None, tracer=None
    ) -> "CorpusStore":
        connection = await aiosqlite.connect(db_path)
        await apply_schema(connection, CorpusDocumentRow)
        await apply_schema(connection, CorpusMediaRow)
        # `apply_schema` reconciles columns and not indexes, so this stays: it
        # is not made redundant by the line above and deleting it would put
        # every project's reads back on a full scan.
        #
        # The generated schema indexes `deleted_at` and nothing else. Every
        # read here is by project, and a corpus is the one table expected to
        # grow into the millions of characters, so the scan is worth avoiding.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_corpus_documents_project "
            f"ON {CorpusDocumentRow.table_name()}(project_id)"
        )
        # Mirrors the index above, and for the same reason: every read of
        # this table is scoped to one project.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_corpus_media_project "
            f"ON {CorpusMediaRow.table_name()}(project_id)"
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, CorpusDocumentRow, tracer)
        media_rows = SQLiteReadModelRepository(connection, CorpusMediaRow, tracer)
        return cls(
            connection,
            rows,
            media_rows,
            CorpusProjection(rows, media_rows, checkpoint_repo, dlq_repo, tracer),
        )

    async def get(
        self, project_id: UUID, source_id: str, *, include_dropped: bool = False
    ) -> CorpusDocumentRow | None:
        """One document with its text, or None if it is unknown -- or dropped,
        unless `include_dropped` says otherwise.

        Returns the row rather than a separate shape. `/sessions` converts
        because `SessionSummary` already existed as the application's own
        vocabulary; nothing here predates the row, and inventing a twin of it
        would be a second thing to keep in sync for no gain.

        A dropped source answers None by default: it is a document somebody
        excluded, and the caller asking for it wants to hear that it is not
        available, not to handle an exception for an ordinary state. That is
        wrong for exactly one caller -- `CorpusEditor.restore`, which exists
        to put a dropped document back and needs its text to do so, and which
        is the only caller whose job is to un-exclude what this method would
        otherwise hide. `include_dropped` is keyword-only and defaults False
        so every other caller keeps seeing what it always has.
        """
        row = await self._rows.get(CorpusDocumentRow.row_id(project_id, source_id))
        if row is None or row.project_id != project_id:
            return None
        if row.dropped_reason is not None and not include_dropped:
            return None
        return row

    async def get_media(
        self, project_id: UUID, source_id: str, *, include_dropped: bool = False
    ) -> CorpusMediaRow | None:
        """One media source, or None if it is unknown -- or dropped, unless
        `include_dropped` says otherwise. Mirrors `get` exactly, over the
        other table.
        """
        row = await self._media_rows.get(CorpusMediaRow.row_id(project_id, source_id))
        if row is None or row.project_id != project_id:
            return None
        if row.dropped_reason is not None and not include_dropped:
            return None
        return row

    async def list_all(
        self, project_id: UUID, *, include_dropped: bool = False
    ) -> "list[CorpusDocumentRow | CorpusMediaRow]":
        """Every source in a project, text and media together, whole rows.

        The only listing method. There used to be a second one, `list`, which
        selected columns explicitly and queried the documents table alone; it
        was deleted with `CorpusReadPort.list_documents` and for the same
        reason. A caller holding a `CorpusRunner` could reach it, its return
        type said `SourceListing`, and what it returned was half a corpus --
        which renders exactly like a whole one.

        The cost of that deletion is real and is not paid back here: `list`
        projected nine columns and this loads whole rows, `text` included, so
        listing a corpus of a hundred papers now pulls every one of them
        through memory to render a table of titles. Measured on
        2026-08-16 rather than reasoned about: 34.4 ms and 22.0 MB peak for a
        corpus of 500 documents of 40,000 characters, 140.7 ms and 102 MB at
        500 documents near `MAX_DOCUMENT_CHARS`. Still accepted, because every
        caller left on this path is a person pressing something once -- the one
        caller that ran it in a loop, `fetch.stored_page`, was moved to
        `list_text_uris` below. Nothing above this sees the text:
        `SourceListing.record` is a `TextRecord`/`MediaRecord` and has no field
        for it.

        The fix, when a listing is felt (about 1,500 documents of 40,000
        characters), is two column-projected queries that both have to feed
        `to_record` -- which reads `char_count` on one kind and
        `media_type`/`byte_count` on the other, so unlike `list_text_uris` they
        cannot share a column tuple. `BACKLOG.md` B84 carries the full numbers,
        including why the narrower row model it once suspected would have saved
        nothing: peak memory is entirely the bytes, and the per-row pydantic
        cost scales with the size of `text` rather than with the row count.

        Two tables, one query each, held to the same
        `dropped_reason`/`deleted_at` filter as `get` and `get_media`.
        """
        project_filter = [Filter.eq("project_id", str(project_id))]
        by_project = Query(filters=project_filter, order_by="source_id")
        documents = await self._rows.find(by_project)
        media = await self._media_rows.find(by_project)
        return sorted(
            (
                row
                for row in (*documents, *media)
                if row.deleted_at is None and (include_dropped or row.dropped_reason is None)
            ),
            key=lambda row: row.source_id,
        )

    async def list_text_uris(self, project_id: UUID) -> list[tuple[str, str]]:
        """`(source_id, uri)` for every live text source that has a URI.

        Raw SQL and two columns, deliberately, where every other read here
        goes through the repository and gets whole pydantic rows. That is the
        entire point of this method: `fetch.stored_page` needs exactly these
        two strings on every `fetch` tool call, and answering it through
        `list_all` loads every document's text. Measured on 2026-08-16 on a
        fixture corpus of 500 documents x 40,000 characters -- 48.1 ms and
        22.5 MB peak per call through `list_sources`, 5.7 ms and 0.16 MB
        through this. `CorpusReadPort.list_text_uris` carries the attribution
        and `BACKLOG.md` B84 the rest.

        Documents only, and this is *not* the half-corpus hazard `list` was
        deleted over: nothing renders this, and its caller wants text sources
        specifically. It is also why it is a separate method rather than a
        flag on `list_all` -- a listing that answered for one table would read
        downstream as a whole corpus, and this cannot, because it answers with
        strings.

        The filter matches `list_all`'s exactly, minus the `include_dropped`
        opt-in nobody on this path wants. Kept as literal SQL against the
        generated column names, which is the cost: a rename of `dropped_reason`
        or `uri` on `CorpusDocumentRow` breaks this at runtime rather than at
        type-check time. `test_the_uri_listing_matches_what_a_full_listing_says`
        is what fails if it drifts.
        """
        async with self._connection.execute(
            f"SELECT source_id, uri FROM {CorpusDocumentRow.table_name()} "
            "WHERE project_id = ? AND uri IS NOT NULL "
            "AND deleted_at IS NULL AND dropped_reason IS NULL "
            "ORDER BY source_id",
            (str(project_id),),
        ) as cursor:
            return [(row[0], row[1]) for row in await cursor.fetchall()]

    async def truncate(self) -> None:
        """Empty both tables, for a rebuild to fill again.

        Deletes rather than soft-deletes, for the reason `SessionSummaryStore`
        gives: a soft-deleted row would linger invisibly and collide with the
        row the replay is about to write for the same source. Both tables,
        because one rebuild replays both `CorpusDocumentStored` and
        `CorpusMediaStored` -- truncating only the document table would leave
        stale media rows the replay never revisits.
        """
        await self._connection.execute(f"DELETE FROM {CorpusDocumentRow.table_name()}")
        await self._connection.execute(f"DELETE FROM {CorpusMediaRow.table_name()}")
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

    async def get(
        self, project_id: UUID, source_id: str, *, include_dropped: bool = False
    ) -> CorpusDocumentRow | None:
        if self._corpus is None:
            raise RuntimeError("the corpus projection has not been started")
        return await self._corpus.get(project_id, source_id, include_dropped=include_dropped)

    async def get_media(
        self, project_id: UUID, source_id: str, *, include_dropped: bool = False
    ) -> CorpusMediaRow | None:
        if self._corpus is None:
            raise RuntimeError("the corpus projection has not been started")
        return await self._corpus.get_media(
            project_id, source_id, include_dropped=include_dropped
        )

    async def list_all(
        self, project_id: UUID, *, include_dropped: bool = False
    ) -> "list[CorpusDocumentRow | CorpusMediaRow]":
        if self._corpus is None:
            raise RuntimeError("the corpus projection has not been started")
        return await self._corpus.list_all(project_id, include_dropped=include_dropped)

    async def list_text_uris(self, project_id: UUID) -> list[tuple[str, str]]:
        if self._corpus is None:
            raise RuntimeError("the corpus projection has not been started")
        return await self._corpus.list_text_uris(project_id)

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


DEFINITION_NAMESPACE = UUID("8a2c1e6d-4b9f-5a71-9e3c-2d6f8b1a0c45")
"""Distinct from `CORPUS_NAMESPACE` so a definition and a document that
happened to share a `(project_id, entity_id)`-shaped key could never collide
on `id` -- the two tables are keyed on unrelated things (an entity, a source)
that are both just strings by the time `uuid5` sees them."""


class EntityDefinitionRow(ReadModel):
    """One generated definition, cached against the entity it describes.

    A cache and not a projection's own state: the definition service's `put`
    is the only writer of `text`/`citations`/`model`/`generated_at`, but the
    row also has to be *invalidated* by graph events this table never reads
    the payload of -- a merge or an edit changes what an entity is without
    itself carrying new definition text. Splitting "what the definition says"
    from "whether it's still trustworthy" into `mark_stale`/`delete` on the
    store, rather than folding invalidation events here too, keeps the one
    thing this table promises -- `stale=True` means *some* graph change
    invalidated this text -- true regardless of which event caused it,
    without this row's shape needing to grow a case per invalidating event.
    """

    __table_name__ = "entity_definitions"

    project_id: UUID
    entity_id: UUID
    text: str
    citations: str
    """JSON array of `{source_id, start, end}`. A string column and not a
    list, deliberately unlike `SessionSummaryRow.file_paths`: that field is
    read back into application code that iterates it, where a citation is
    only ever handed whole to the browser that renders spans against source
    text it also holds. Decoding here would be work with no reader."""
    model: str
    generated_at: str
    stale: bool = False

    @staticmethod
    def row_id(project_id: UUID, entity_id: UUID) -> UUID:
        """The row id for a definition, matching `CorpusDocumentRow.row_id`'s
        shape: keying on the pair means one project's entity ids -- which are
        graph-local, not global -- cannot collide with another project's."""
        return uuid5(DEFINITION_NAMESPACE, f"{project_id}:{entity_id}")


class EntityDefinitionStore:
    """The definition cache table and the connection it owns.

    No projection here, unlike `CorpusStore` and `SessionSummaryStore` --
    this store is written to directly by whatever generates a definition and
    by Task 8's invalidation projection, both through `put`/`mark_stale`/
    `delete`, rather than by this store reading events itself. A store with
    no projection is still a store: `open()` still owns reconciling the
    table's schema, which is the part every caller needs and none should
    duplicate.
    """

    def __init__(self, connection: aiosqlite.Connection, rows: ReadModelRepository) -> None:
        self._connection = connection
        self._rows = rows

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> "EntityDefinitionStore":
        connection = await aiosqlite.connect(db_path)
        await apply_schema(connection, EntityDefinitionRow)
        # `apply_schema` reconciles columns, not indexes -- see the identical
        # note on `CorpusStore.open`. Every read here is project-scoped
        # (`get`, and `mark_stale`/`delete` before it), so an unindexed table
        # would put every project's reads behind a scan of every other
        # project's cached definitions.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_entity_definitions_project "
            f"ON {EntityDefinitionRow.table_name()}(project_id)"
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, EntityDefinitionRow, tracer)
        return cls(connection, rows)

    async def get(self, project_id: UUID, entity_id: UUID) -> EntityDefinitionRow | None:
        """The cached definition, or None if there is none yet.

        `row.project_id != project_id` cannot happen through this class's own
        `row_id` -- the pair is baked into the id -- but is checked anyway for
        the same reason `CorpusStore.get` checks it: a row reached by id alone
        makes no claim about which project asked, and a bug elsewhere that
        looked one entity up under the wrong project should not read back
        another project's definition as if it were an answer.
        """
        row = await self._rows.get(EntityDefinitionRow.row_id(project_id, entity_id))
        if row is None or row.project_id != project_id:
            return None
        return row

    async def put(self, row: EntityDefinitionRow) -> None:
        """Store a definition, superseding whatever was cached before."""
        await self._rows.save(row)

    async def mark_stale(self, project_id: UUID, entity_id: UUID) -> None:
        """Flag a cached definition as no longer trustworthy, without
        discarding it -- Task 8 sets this from a graph event that changed the
        entity, and the stale text stays visible (labelled) until something
        regenerates it, rather than disappearing out from under a reader.

        A missing row is a no-op, not an error: this is called from an
        invalidation projection reacting to graph events, and "this entity
        has never had a definition generated" is the ordinary case for most
        entities, not drift the way a missing row is for `CorpusProjection`'s
        drop handler. Raising here would put routine graph activity in the
        DLQ for a store that was never asked to remember anything.
        """
        row = await self.get(project_id, entity_id)
        if row is None:
            return
        row.stale = True
        await self._rows.save(row)

    async def delete(self, project_id: UUID, entity_id: UUID) -> None:
        """Discard a cached definition outright -- for an entity that no
        longer exists, where marking it stale would leave a permanent orphan
        nothing will ever regenerate. A missing row is a no-op for the same
        reason `mark_stale`'s is."""
        await self._rows.delete(EntityDefinitionRow.row_id(project_id, entity_id))

    async def close(self) -> None:
        await self._connection.close()


class EntityDefinitionProjection(DeclarativeProjection):
    """Marks cached definitions untrustworthy in reaction to graph events.

    Deliberately writes no definition text -- `put` is for whatever generates
    one, elsewhere. This projection only calls `mark_stale`/`delete`, both of
    which already tolerate a missing row, so the two handlers below never
    need their own existence check the way `CorpusProjection._on_dropped`
    does through `_require`: there is no aggregate invariant here that would
    make a missing row drift rather than the ordinary case of an entity
    nobody has read yet.

    **Marks, never regenerates.** A bulk re-extraction touching two hundred
    entities would otherwise fire two hundred LLM calls for definitions
    nobody asked to read -- `stale=True` is a label the next click resolves,
    not a queue this projection drains itself.

    **Does not subscribe to `MergeUndone`, on purpose.** Undoing a merge
    deletes-then-restores the absorbed entities' rows via redstring's own
    projection, so on the next click they regenerate from scratch -- correct,
    with no help needed here. The canonical entity is left stale from the
    original `EntitiesMerged`, which is also correct: it is still the entity
    whose properties the merge touched, undo or not. No case a `MergeUndone`
    handler could catch actually yields a wrong answer today, so there is
    nothing here for one to do. If undo becomes routine enough that leaving
    the canonical stale (rather than restoring its pre-merge staleness) reads
    as surprising, that is the point to revisit this, not before.
    """

    def __init__(
        self,
        definitions: EntityDefinitionStore,
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._definitions = definitions
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(DocumentExtracted)
    async def _on_extracted(self, event: DocumentExtracted) -> None:
        """Stale every cached definition an extraction run touched.

        Entities never gain properties incrementally -- a property change
        arrives as a whole-entity payload inside `DocumentExtracted`, the way
        a new mention or a corrected name would -- so this one subscription
        is the entire "more properties were added" case; there is no second
        event to also watch for that.

        Keys on `event.tenant_id`, matching `CorpusProjection._on_extracted`:
        this subscribes to the whole store rather than one category, so
        redstring's own event arrives here without new wiring, and
        `tenant_id` is the project.
        """
        for entity in event.entities:
            await self._definitions.mark_stale(event.tenant_id, entity.id)

    @handles(EntitiesMerged)
    async def _on_merged(self, event: EntitiesMerged) -> None:
        """Stale the survivor, delete the absorbed.

        The canonical entity's definition may no longer describe it fully --
        a merge can bring in properties the cached text never saw -- so it is
        marked stale rather than left alone. An absorbed id, by contrast, is
        no longer clickable anywhere in the UI once merged away, so its
        cached definition is unreachable text; deleting it (not staling it)
        also keeps `/rebuild` producing the same row count as steady-state
        operation, where nothing ever generates a definition for an id that
        cannot be clicked. Leaving it would be a silent divergence nobody
        could later explain.
        """
        await self._definitions.mark_stale(event.tenant_id, event.canonical_entity_id)
        for merged_id in event.merged_entity_ids:
            await self._definitions.delete(event.tenant_id, merged_id)


class EntityDefinitionRunner:
    """Keeps the definition cache's staleness following the log.

    A third runner beside `CorpusRunner` and `SessionSummaryRunner`, for the
    same reasons `CorpusRunner`'s docstring gives for being a second one
    rather than sharing: a distinct port (`rebuild()` and `health()`-shaped
    surface for this table alone), and a `rebuild()` that must not be able to
    truncate a table it does not own.

    Unlike those two, this runner's `rebuild()` recomputes staleness rather
    than the rows themselves -- see `rebuild` below for why truncating here
    would be destructive rather than merely wasteful.
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
        self._definitions: EntityDefinitionStore | None = None
        self._manager: SubscriptionManager | None = None
        self._subscription = None
        self._checkpoints: SQLCheckpointRepository | None = None
        self._dlq: SQLDLQRepository | None = None
        self._engine: AsyncEngine | None = None

    @property
    def projection_name(self) -> str:
        return EntityDefinitionProjection.__name__

    async def start(self) -> None:
        """Open the table and start following the log.

        Same shape as `CorpusRunner.start`, including touching the event
        store first so `projection_checkpoints` exists before anything reads
        it.
        """
        if self._manager is not None:
            return
        await self._store.current_position()
        engine = create_async_engine(f"sqlite+aiosqlite:///{self._db_path}")
        self._engine = engine
        self._checkpoints = SQLCheckpointRepository(engine)
        self._dlq = SQLDLQRepository(engine)
        self._definitions = await EntityDefinitionStore.open(self._db_path, self._tracer)
        projection = EntityDefinitionProjection(
            self._definitions, self._checkpoints, self._dlq, self._tracer
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
            raise RuntimeError(f"the entity definition projection failed to start: {failures}")

    async def failures(self, limit: int = 100) -> list[DLQEntry]:
        if self._dlq is None:
            return []
        return await self._dlq.get_failed_events(
            projection_name=self.projection_name, limit=limit
        )

    async def get(self, project_id: UUID, entity_id: UUID) -> EntityDefinitionRow | None:
        """This project's cached definition of `entity_id`, if there is one.

        Delegated the way `CorpusRunner.get` is, rather than handing the
        `EntityDefinitionStore` out through a property, and the reason is
        `rebuild()`: it closes the store and opens another one. A caller
        holding the store would go on calling a closed connection, silently,
        after a repair -- where a caller holding the runner reaches whichever
        store is current on every call. That is also what keeps the route's
        cache and this projection's invalidation the *same* table: there is
        one owner of the connection, and it is this object.
        """
        if self._definitions is None:
            raise RuntimeError("the entity definition projection has not been started")
        return await self._definitions.get(project_id, entity_id)

    async def put(self, row: EntityDefinitionRow) -> None:
        """Store a generated definition, superseding whatever was cached.

        The write half of `get`, for the same one-owner reason. This
        projection never calls it -- see the class docstring on why
        generation and invalidation are split -- but the generating service
        reaches the table through here so that both halves go through one
        connection rather than two that would each cache the other's stale
        reads.
        """
        if self._definitions is None:
            raise RuntimeError("the entity definition projection has not been started")
        await self._definitions.put(row)

    async def rebuild(self) -> None:
        """Reset the checkpoint and replay, without truncating the table.

        `CorpusRunner.rebuild` and its `/sessions` counterpart both truncate
        first because their tables hold nothing that is not entirely derived
        from the log. This table is different: `text`/`citations`/`model`/
        `generated_at` come from the definition service's `put`, not from the
        event log this projection replays at all -- see the class
        docstring on why invalidation is split from generation. Truncating
        here would discard every generated definition and replace it with
        nothing, where a resubscribed replay would only re-derive
        `stale`. Resetting the checkpoint and replaying re-applies every
        `DocumentExtracted`/`EntitiesMerged` in the log, which correctly
        re-stales (and re-deletes) whatever the current rows say -- the same
        repair `CorpusRunner.rebuild` performs, minus the truncate that would
        make it destructive for this table.
        """
        if self._manager is None:
            raise RuntimeError("the entity definition projection has not been started")
        await self._manager.stop()
        for entry in await self.failures(limit=1000):
            await self._dlq.mark_resolved(entry.id, resolved_by="rebuild")
        await self._checkpoints.reset_checkpoint(self.projection_name)
        self._manager = None
        self._subscription = None
        await self._definitions.close()
        self._definitions = None
        await self.start()
        await self.caught_up()

    async def caught_up(self, timeout: float = 10.0) -> None:
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
            f"the entity definition projection did not reach {target} within {timeout}s"
        )

    async def stop(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
            self._manager = None
        if self._definitions is not None:
            await self._definitions.close()
            self._definitions = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None


ONTOLOGY_NAMESPACE = UUID("3f7b21c9-6d84-5e02-a1b7-9c4e0f83d216")
"""Distinct from `DEFINITION_NAMESPACE` and `CORPUS_NAMESPACE` for the reason
stated on those: three tables keyed on unrelated things that are all just
strings by the time `uuid5` sees them must not be able to collide on `id`."""


class OntologyClassRow(ReadModel):
    """One class discovered in one document, with what it was derived from.

    Entirely derived, unlike `EntityDefinitionRow`: every column here is
    rewritten by replaying the log, where a definition's `text` comes from a
    service's `put` and a replay could not restore it. That is why this
    table's rebuild may truncate and the definition runner's may not.

    Keyed on `(project_id, source_id, name)`. Two documents each stating "six
    difficulties" therefore produce two rows, deliberately -- merging them is
    the entity-identity problem redstring's `Consolidator` exists for and
    should reuse it, not grow a private version here.
    """

    __table_name__ = "ontology_classes"

    project_id: UUID
    source_id: str
    name: str
    kind: str
    """`ordered_scale` | `unordered_set` | `taxonomy`, as a plain string.

    Not the event's `Literal`: a column that refused an unknown value would
    put a replay in the DLQ over a payload the log has already accepted, and
    the log is not rewritable. Validation belongs at the point the value is
    believed -- `verify_classes` -- not at the point it is re-read.
    """
    declared_count: int | None = None
    member_count: int = 0
    """What was actually stored, recorded rather than counted from the
    membership table on read. A number derived by a join would always agree
    with itself, including after a half-finished write; two independently
    recorded numbers can disagree, which is the entire point of a checksum."""
    parent_class_id: UUID | None = None
    evidence_start: int = 0
    evidence_end: int = 0
    rejected_members: str = "[]"
    """JSON array of `{name, reason}`. A string column for the same reason
    `EntityDefinitionRow.citations` is one: it is handed whole to a browser
    that renders it, and decoding here would be work with no reader."""
    model: str = ""
    generated_at: str = ""
    stale: bool = False

    @staticmethod
    def row_id(project_id: UUID, source_id: str, name: str) -> UUID:
        return uuid5(ONTOLOGY_NAMESPACE, f"{project_id}:{source_id}:{name}")


class OntologyMembershipRow(ReadModel):
    """One member of one class, as the document spelled it.

    **No entity id, deliberately.** The first design stored one and it was
    wrong in the way redstring's ADR 0005 warns about: re-extraction remints
    entity ids with no invalidation event, so a stored id would name an entity
    that no longer exists, and nothing here would know. `ProjectGraphReader`
    resolves the name against the entities it is already holding, on every
    read -- which costs no extra query and cannot go stale.

    So the name is the whole record. A member that matches no entity today is
    still a member: its row keeps `member_count` honest against the class's
    `declared_count`, and the next read resolves it if extraction later
    produces the entity. Deleting it instead would make an unrelated
    re-extraction look like a discovery failure.
    """

    __table_name__ = "ontology_memberships"

    project_id: UUID
    class_id: UUID
    member_name: str
    ordinal: int | None = None

    @staticmethod
    def row_id(class_id: UUID, member_name: str) -> UUID:
        return uuid5(ONTOLOGY_NAMESPACE, f"{class_id}:{member_name}")


class OntologyExaminedRow(ReadModel):
    """That a discovery pass looked at this source, whatever it found.

    A separate row rather than a flag on a class, because the case it exists
    for is the one with *no* class: a document the pass read and found nothing
    in has nowhere else to record that it was read. Without this, "states no
    classes" and "never examined" are the same observation, and the `ungrouped`
    sweep re-runs every barren document on every pass, at model cost.
    """

    __table_name__ = "ontology_examined"

    project_id: UUID
    source_id: str

    @staticmethod
    def row_id(project_id: UUID, source_id: str) -> UUID:
        return uuid5(ONTOLOGY_NAMESPACE, f"examined:{project_id}:{source_id}")


class OntologyStore:
    """The three ontology tables and the connection they share.

    One store rather than one per table, unlike the rest of this module,
    because they are written and cleared together: replacing a source's classes
    must delete that source's memberships in the same breath. Two stores over
    two connections would make that two transactions with a window between them
    in which a class has no members and the canvas draws a bare hub.
    """

    def __init__(
        self,
        connection: aiosqlite.Connection,
        classes: ReadModelRepository[OntologyClassRow],
        members: ReadModelRepository[OntologyMembershipRow],
        examined: ReadModelRepository[OntologyExaminedRow],
    ) -> None:
        self._connection = connection
        self._classes = classes
        self._members = members
        self._examined = examined

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> "OntologyStore":
        connection = await aiosqlite.connect(db_path)
        await apply_schema(connection, OntologyClassRow)
        await apply_schema(connection, OntologyMembershipRow)
        await apply_schema(connection, OntologyExaminedRow)
        # `apply_schema` reconciles columns and not indexes -- the same note as
        # on `EntityDefinitionStore.open`. `members_for` runs once per class on
        # every graph read, so an unindexed membership table would put a
        # project's whole canvas behind one scan per class.
        for statement in (
            f"CREATE INDEX IF NOT EXISTS idx_ontology_classes_project "
            f"ON {OntologyClassRow.table_name()}(project_id, source_id)",
            f"CREATE INDEX IF NOT EXISTS idx_ontology_members_class "
            f"ON {OntologyMembershipRow.table_name()}(class_id)",
            f"CREATE INDEX IF NOT EXISTS idx_ontology_examined_project "
            f"ON {OntologyExaminedRow.table_name()}(project_id)",
        ):
            await connection.execute(statement)
        await connection.commit()
        return cls(
            connection,
            SQLiteReadModelRepository(connection, OntologyClassRow, tracer),
            SQLiteReadModelRepository(connection, OntologyMembershipRow, tracer),
            SQLiteReadModelRepository(connection, OntologyExaminedRow, tracer),
        )

    async def replace_for_source(
        self,
        project_id: UUID,
        source_id: str,
        classes: list[DiscoveredClass],
        *,
        model: str,
        generated_at: str,
    ) -> None:
        """Store this source's classes, discarding whatever it held before.

        Replacement rather than upsert: the pass is re-run whenever its prompt
        changes, and a re-run that no longer finds a class has to remove it. An
        upsert would leave behind every class any past prompt ever produced,
        and the canvas would accumulate one hub per attempt.

        An empty `classes` still clears and still records the source as
        examined -- see `OntologyExaminedRow`.
        """
        await self._forget_source(project_id, source_id)
        for klass in classes:
            class_id = OntologyClassRow.row_id(project_id, source_id, klass.name)
            await self._classes.save(
                OntologyClassRow(
                    id=class_id,
                    project_id=project_id,
                    source_id=source_id,
                    name=klass.name,
                    kind=klass.kind,
                    declared_count=klass.declared_count,
                    member_count=len(klass.members),
                    parent_class_id=(
                        OntologyClassRow.row_id(project_id, source_id, klass.parent_name)
                        if klass.parent_name
                        else None
                    ),
                    evidence_start=klass.evidence.start,
                    evidence_end=klass.evidence.end,
                    rejected_members=json.dumps(
                        [rejected.model_dump() for rejected in klass.rejected_members]
                    ),
                    model=model,
                    generated_at=generated_at,
                )
            )
            for member in klass.members:
                await self._members.save(
                    OntologyMembershipRow(
                        id=OntologyMembershipRow.row_id(class_id, member.name),
                        project_id=project_id,
                        class_id=class_id,
                        member_name=member.name,
                        ordinal=member.ordinal,
                    )
                )
        await self._examined.save(
            OntologyExaminedRow(
                id=OntologyExaminedRow.row_id(project_id, source_id),
                project_id=project_id,
                source_id=source_id,
            )
        )

    async def _forget_source(self, project_id: UUID, source_id: str) -> None:
        """Delete one source's classes and their memberships.

        Memberships are found through their classes rather than by a
        `source_id` of their own: a membership belongs to a class, and giving
        it a second copy of the class's source would be a second thing that can
        disagree. The cost is one extra query, on a table indexed for it.
        """
        for row in await self._classes_for_source(project_id, source_id):
            for member in await self.members_for(row.id):
                await self._members.delete(member.id)
            await self._classes.delete(row.id)

    async def _classes_for_source(
        self, project_id: UUID, source_id: str
    ) -> list[OntologyClassRow]:
        return [
            row for row in await self.classes_for(project_id) if row.source_id == source_id
        ]

    async def classes_for(self, project_id: UUID) -> list[OntologyClassRow]:
        """Every class in a project, newest table order.

        Goes through the repository rather than a projected SELECT, unlike
        `CorpusStore.list`: a class row is a few short strings, where a corpus
        row is an entire document, so there is nothing here worth the extra
        column list to avoid loading.
        """
        cursor = await self._connection.execute(
            f"SELECT id FROM {OntologyClassRow.table_name()} "
            "WHERE project_id = ? AND deleted_at IS NULL ORDER BY name",
            (str(project_id),),
        )
        try:
            ids = [UUID(row[0]) for row in await cursor.fetchall()]
        finally:
            await cursor.close()
        rows = [await self._classes.get(row_id) for row_id in ids]
        return [row for row in rows if row is not None]

    async def members_for(self, class_id: UUID) -> list[OntologyMembershipRow]:
        """One class's members, in the order the text gave them.

        Ordered by `ordinal` with nulls last, so an ordered scale reads as the
        document stated it and an unordered set keeps a stable arrival order
        rather than an arbitrary one. Sorting an unordered set by name here
        would read a sequence into a bag.
        """
        cursor = await self._connection.execute(
            f"SELECT id FROM {OntologyMembershipRow.table_name()} "
            "WHERE class_id = ? AND deleted_at IS NULL "
            "ORDER BY ordinal IS NULL, ordinal, member_name",
            (str(class_id),),
        )
        try:
            ids = [UUID(row[0]) for row in await cursor.fetchall()]
        finally:
            await cursor.close()
        rows = [await self._members.get(row_id) for row_id in ids]
        return [row for row in rows if row is not None]

    async def sources_with_classes(self, project_id: UUID) -> set[str]:
        """Every source a pass has examined, whatever it found.

        Named for what callers ask it -- "which sources are done" -- and
        deliberately answering from `ontology_examined` rather than from the
        class table, which would answer a different and wrong question. See
        `OntologyExaminedRow`.
        """
        cursor = await self._connection.execute(
            f"SELECT source_id FROM {OntologyExaminedRow.table_name()} "
            "WHERE project_id = ? AND deleted_at IS NULL",
            (str(project_id),),
        )
        try:
            return {row[0] for row in await cursor.fetchall()}
        finally:
            await cursor.close()

    async def mark_stale_for_source(self, project_id: UUID, source_id: str) -> None:
        """Flag a source's classes as no longer trustworthy, without discarding
        them -- the same contract `EntityDefinitionStore.mark_stale` keeps, and
        for the same reason: stale text stays visible, labelled, until
        something replaces it.

        A source with no classes is a no-op, not an error. This is called from
        a projection reacting to every extraction in the log, and most
        documents have never been examined; raising here would put routine
        extraction in the DLQ.
        """
        for row in await self._classes_for_source(project_id, source_id):
            row.stale = True
            await self._classes.save(row)

    async def close(self) -> None:
        await self._connection.close()


class OntologyProjection(DeclarativeProjection):
    """Writes discovered classes, and stales them when extraction moves under them.

    **Marks, never regenerates**, exactly as `EntityDefinitionProjection` does
    and for the identical measured reason: a bulk re-extraction touching two
    hundred documents would otherwise fire two hundred paid model calls for
    classes nobody asked to look at. `stale=True` is a label the next discovery
    run resolves, not a queue this projection drains. It is handed no model, so
    it could not call one even by mistake.
    """

    def __init__(
        self,
        ontology: OntologyStore,
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._ontology = ontology
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(OntologyDiscovered)
    async def _on_discovered(self, event: OntologyDiscovered) -> None:
        """Replace this source's classes with what the pass found.

        `event.occurred_at` rather than a clock read here: a replay has to
        reproduce the same `generated_at` it produced the first time, or a
        rebuild would rewrite every row with today's date and lose when the
        classes were actually derived.
        """
        await self._ontology.replace_for_source(
            event.project_id,
            event.source_id,
            event.classes,
            model=event.model_version,
            generated_at=event.occurred_at.isoformat(),
        )

    @handles(DocumentExtracted)
    async def _on_extracted(self, event: DocumentExtracted) -> None:
        """Stale this source's classes: the entities its memberships name have
        just been reminted, so every resolved id is suspect.

        Keys on `event.tenant_id`, matching `EntityDefinitionProjection` --
        redstring's own event arrives here without new wiring, and `tenant_id`
        is the project.
        """
        await self._ontology.mark_stale_for_source(event.tenant_id, str(event.source_id))


CATALOG_NAMESPACE = UUID("c5e8a017-3d62-5f94-8b21-6a0d4e97c318")
"""A literal, not a derived `uuid5(NAMESPACE_URL, ...)`, matching every other
namespace in this file. A computed namespace would silently remap every row
id the moment its input string is edited; this one is also consumed by the
blurb cache (Task 4), which builds its own ids as
`uuid5(CATALOG_NAMESPACE, f"blurb:{project_id}:{slug}")`, so it stays at
module level rather than nested in a class."""


class CatalogFeatureRow(ReadModel):
    """One candidate somebody put on the front page.

    Keyed by `(project_id, slug)` through `row_id`, so featuring the same slug
    twice moves its rank rather than adding a second row. That idempotence is
    what lets the route be a plain POST with no read-modify-write.
    """

    __table_name__ = "catalog_features"

    project_id: UUID
    slug: str
    rank: int = 0

    @staticmethod
    def row_id(project_id: UUID, slug: str) -> UUID:
        return uuid5(CATALOG_NAMESPACE, f"{project_id}:{slug}")


class CourseBlurbRow(ReadModel):
    """One generated blurb, cached against the cluster it describes.

    A cache and not a projection's own state, exactly like
    `EntityDefinitionRow`: the catalog service's `put` is the only writer.

    Unlike that row there is no `stale` flag, and the difference is
    deliberate. A definition is invalidated by graph events this table never
    reads, so it needs a flag something else can set. A blurb carries
    `membership_hash`, which answers the same question *by comparison* -- the
    caller already holds the current hash and can see the disagreement
    itself. A flag would be a second answer to one question, and the two
    would drift.
    """

    __table_name__ = "course_blurbs"

    project_id: UUID
    slug: str
    text: str
    membership_hash: str
    model: str
    generated_at: str
    title: str = ""
    """A generated course title, not the anchor entity's name -- Task 15.

    Defaulted, not required: `apply_schema` reconciles an added column onto a
    table that already has rows, but it leaves the column empty in every row
    that predates it. A required column with no default is refused outright
    on a populated table -- see CLAUDE.md's "Read models" section, which
    records this project shipping exactly that bug once. `""` is the honest
    value for "generated before this field existed", and
    `CatalogService.build`'s `cached.title or area.display_name()` is the
    fallback that covers it."""

    @staticmethod
    def row_id(project_id: UUID, slug: str) -> UUID:
        # The `blurb:` prefix keeps this id from colliding with
        # `CatalogFeatureRow.row_id`, which shares `CATALOG_NAMESPACE` and
        # hashes the same `{project_id}:{slug}` pair with no prefix of its
        # own.
        return uuid5(CATALOG_NAMESPACE, f"blurb:{project_id}:{slug}")


class CourseBlurbStore:
    """The blurb cache table and the connection it owns.

    No projection here, matching `EntityDefinitionStore`: nothing on the
    event log describes a blurb, so there is nothing for a projection to
    replay. The catalog service calls `put` directly after generating one.
    """

    def __init__(self, connection: aiosqlite.Connection, rows: ReadModelRepository) -> None:
        self._connection = connection
        self._rows = rows

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> "CourseBlurbStore":
        connection = await aiosqlite.connect(db_path)
        await apply_schema(connection, CourseBlurbRow)
        # `apply_schema` reconciles columns, not indexes -- the same note
        # `EntityDefinitionStore.open` carries, for the same reason: every
        # read here is project-scoped.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_course_blurbs_project "
            f"ON {CourseBlurbRow.table_name()}(project_id)"
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, CourseBlurbRow, tracer)
        return cls(connection, rows)

    async def get(self, project_id: UUID, slug: str) -> CourseBlurbRow | None:
        """The cached blurb, or None if none has been generated yet.

        `row.project_id != project_id` cannot happen through this class's
        own `row_id` -- the pair is baked into the id -- but is checked
        anyway for the same reason `EntityDefinitionStore.get` checks it: a
        row reached by id alone makes no claim about which project asked.
        """
        row = await self._rows.get(CourseBlurbRow.row_id(project_id, slug))
        if row is None or row.project_id != project_id:
            return None
        return row

    async def put(
        self,
        project_id: UUID,
        slug: str,
        title: str,
        text: str,
        membership_hash: str,
        model: str,
        generated_at: datetime,
    ) -> None:
        """Cache a blurb, superseding whatever was cached before for this
        slug -- `save` writes by id, and `row_id` is stable per
        `(project_id, slug)`, so a rewrite replaces rather than duplicates.
        """
        await self._rows.save(
            CourseBlurbRow(
                id=CourseBlurbRow.row_id(project_id, slug),
                project_id=project_id,
                slug=slug,
                text=text,
                membership_hash=membership_hash,
                model=model,
                generated_at=generated_at.isoformat(),
                title=title,
            )
        )

    async def close(self) -> None:
        await self._connection.close()


class CourseOutlineRow(ReadModel):
    """One generated outline, cached against the cluster it describes.

    Its own table rather than a `kind` column beside `CourseBlurbRow`. A blurb's
    payload is one `text` column and this one's is a structured list, so a
    shared table needs a JSON column that only half its rows ever fill -- and
    then the two row types share nothing but a primary key and a namespace. Two
    stores of the same shape are duplication a reader can see; one store with a
    column meaningful for half its rows is a schema that has to be explained.

    No `stale` flag, for `CourseBlurbRow`'s reason: `membership_hash` answers
    the same question by comparison, and a flag would be a second answer that
    can disagree with the first.
    """

    __table_name__ = "course_outlines"

    project_id: UUID
    slug: str
    promise: str
    sections: list[dict] = Field(default_factory=list)
    """`[{"heading": ..., "summary": ...}]`, in reading order."""
    membership_hash: str
    model: str
    generated_at: str

    @field_validator("sections", mode="before")
    @classmethod
    def _decode_json_list(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def row_id(project_id: UUID, slug: str) -> UUID:
        # The `outline:` prefix keeps this id from colliding with
        # `CourseBlurbRow.row_id` and `CatalogFeatureRow.row_id`, which share
        # `CATALOG_NAMESPACE` and hash the same `{project_id}:{slug}` pair
        # with their own (or no) prefix.
        return uuid5(CATALOG_NAMESPACE, f"outline:{project_id}:{slug}")


class CourseOutlineStore:
    """The outline cache table and the connection it owns.

    No projection here, matching `CourseBlurbStore`: nothing on the event log
    describes an outline, so there is nothing for a projection to replay. The
    catalog service calls `put` directly after generating one.
    """

    def __init__(self, connection: aiosqlite.Connection, rows: ReadModelRepository) -> None:
        self._connection = connection
        self._rows = rows

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> "CourseOutlineStore":
        connection = await aiosqlite.connect(db_path)
        await apply_schema(connection, CourseOutlineRow)
        # `apply_schema` reconciles columns, not indexes -- the same note
        # `CourseBlurbStore.open` carries, for the same reason: every read
        # here is project-scoped.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_course_outlines_project "
            f"ON {CourseOutlineRow.table_name()}(project_id)"
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, CourseOutlineRow, tracer)
        return cls(connection, rows)

    async def get(self, project_id: UUID, slug: str) -> CourseOutlineRow | None:
        """The cached outline, or None if none has been generated yet.

        `row.project_id != project_id` cannot happen through this class's
        own `row_id` -- the pair is baked into the id -- but is checked
        anyway for the same reason `CourseBlurbStore.get` checks it: a row
        reached by id alone makes no claim about which project asked.
        """
        row = await self._rows.get(CourseOutlineRow.row_id(project_id, slug))
        if row is None or row.project_id != project_id:
            return None
        return row

    async def put(
        self,
        project_id: UUID,
        slug: str,
        promise: str,
        sections: list[dict],
        membership_hash: str,
        model: str,
        generated_at: datetime,
    ) -> None:
        """Cache an outline, superseding whatever was cached before for this
        slug -- `save` writes by id, and `row_id` is stable per
        `(project_id, slug)`, so a rewrite replaces rather than duplicates.
        """
        await self._rows.save(
            CourseOutlineRow(
                id=CourseOutlineRow.row_id(project_id, slug),
                project_id=project_id,
                slug=slug,
                promise=promise,
                sections=sections,
                membership_hash=membership_hash,
                model=model,
                generated_at=generated_at.isoformat(),
            )
        )

    async def close(self) -> None:
        await self._connection.close()


class CatalogFeatureStore:
    """The featured table and the connection it owns."""

    def __init__(self, connection: aiosqlite.Connection, rows: ReadModelRepository) -> None:
        self._connection = connection
        self._rows = rows

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> "CatalogFeatureStore":
        connection = await aiosqlite.connect(db_path)
        await apply_schema(connection, CatalogFeatureRow)
        # `apply_schema` reconciles columns, not indexes -- the same note
        # `EntityDefinitionStore.open` carries, for the same reason: every
        # read here is project-scoped.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_catalog_features_project "
            f"ON {CatalogFeatureRow.table_name()}(project_id)"
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, CatalogFeatureRow, tracer)
        return cls(connection, rows)

    async def feature(self, project_id: UUID, slug: str, rank: int) -> None:
        await self._rows.save(
            CatalogFeatureRow(
                id=CatalogFeatureRow.row_id(project_id, slug),
                project_id=project_id,
                slug=slug,
                rank=rank,
            )
        )

    async def unfeature(self, project_id: UUID, slug: str) -> None:
        """Deleting something absent is a no-op, not an error.

        This is driven by a projection over a log that may hold an unfeature
        for a slug whose feature was never projected -- a rebuild from an
        arbitrary checkpoint does exactly that -- and raising here would put a
        routine replay in the dead-letter queue.
        """
        await self._rows.delete(CatalogFeatureRow.row_id(project_id, slug))

    async def featured_for(self, project_id: UUID) -> dict[str, int]:
        cursor = await self._connection.execute(
            f"SELECT slug, rank FROM {CatalogFeatureRow.table_name()} "
            "WHERE project_id = ? AND deleted_at IS NULL",
            (str(project_id),),
        )
        try:
            return {row[0]: row[1] for row in await cursor.fetchall()}
        finally:
            await cursor.close()

    async def close(self) -> None:
        await self._connection.close()


class CatalogFeatureProjection(DeclarativeProjection):
    """Keeps `catalog_features` level with the curation events."""

    def __init__(
        self,
        store: CatalogFeatureStore,
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._store = store
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(CourseFeatured)
    async def _featured(self, event: CourseFeatured) -> None:
        await self._store.feature(event.project_id, event.slug, event.rank)

    @handles(CourseUnfeatured)
    async def _unfeatured(self, event: CourseUnfeatured) -> None:
        await self._store.unfeature(event.project_id, event.slug)


class CourseRow(ReadModel):
    """A realized course: the frozen membership `CourseRealized` carried,
    kept so it survives a restart without folding the log.

    Keyed by `(project_id, slug)` through `row_id`, exactly like
    `CourseBlurbRow` and `CatalogFeatureRow` -- all three share
    `CATALOG_NAMESPACE` and hash the same pair, so the `course:` prefix below
    is what keeps this row's id from colliding with theirs.
    """

    __table_name__ = "courses"

    project_id: UUID
    slug: str
    title: str
    member_entity_ids: list[str] = Field(default_factory=list)
    membership_hash: str
    realized_at: datetime
    abandoned: bool = False
    """Marked rather than deleted, so a rebuild replaying `CourseRealized`
    then `CourseAbandoned` lands where a rebuild replaying only the first
    does not. A delete would make abandonment invisible to the replay that
    follows it: a rebuild that stops (or starts) between the two events
    would resurrect a course whose row was removed rather than flagged."""

    @field_validator("member_entity_ids", mode="before")
    @classmethod
    def _decode_json_list(cls, value: object) -> object:
        # `AuthoringRunRow._decode_json_list`'s pattern: SQLite has no list
        # column, so `member_entity_ids` round-trips through this table as a
        # JSON string and needs decoding back on the way out.
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def row_id(project_id: UUID, slug: str) -> UUID:
        # `course:` for the reason `CourseBlurbRow` gives for `blurb:` --
        # three row types now share CATALOG_NAMESPACE over the same
        # {project}:{slug} pair.
        return uuid5(CATALOG_NAMESPACE, f"course:{project_id}:{slug}")


class CourseStore:
    """The courses table and the connection it owns."""

    def __init__(self, connection: aiosqlite.Connection, rows: ReadModelRepository) -> None:
        self._connection = connection
        self._rows = rows

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> "CourseStore":
        connection = await aiosqlite.connect(db_path)
        await apply_schema(connection, CourseRow)
        # `apply_schema` reconciles columns, not indexes -- the same note
        # `CourseBlurbStore.open` carries, for the same reason: every read
        # here is project-scoped.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_courses_project "
            f"ON {CourseRow.table_name()}(project_id)"
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, CourseRow, tracer)
        return cls(connection, rows)

    async def get(self, project_id: UUID, slug: str) -> CourseRow | None:
        """The row for this slug, regardless of `abandoned`, or None if it
        has never been realized.

        `row.project_id != project_id` cannot happen through this class's
        own `row_id` -- the pair is baked into the id -- but is checked
        anyway for the reason `CourseBlurbStore.get` checks it: a row reached
        by id alone makes no claim about which project asked.
        """
        row = await self._rows.get(CourseRow.row_id(project_id, slug))
        if row is None or row.project_id != project_id:
            return None
        return row

    async def for_project(self, project_id: UUID) -> list[CourseRow]:
        """Every non-abandoned course in this project. `abandoned` rows are
        omitted here rather than absent from the table -- see `CourseRow`."""
        return await self._rows.find(
            Query(
                filters=[
                    Filter.eq("project_id", str(project_id)),
                    Filter.eq("abandoned", False),
                ]
            )
        )

    async def realize(
        self,
        project_id: UUID,
        slug: str,
        title: str,
        member_entity_ids: list[str],
        membership_hash: str,
        realized_at: datetime,
    ) -> None:
        """Write (or rewrite) the row -- `save` writes by id, and `row_id`
        is stable per `(project_id, slug)`, so a second `CourseRealized` for
        an already-abandoned slug reinstates it rather than duplicating."""
        await self._rows.save(
            CourseRow(
                id=CourseRow.row_id(project_id, slug),
                project_id=project_id,
                slug=slug,
                title=title,
                member_entity_ids=member_entity_ids,
                membership_hash=membership_hash,
                realized_at=realized_at,
                abandoned=False,
            )
        )

    async def abandon(self, project_id: UUID, slug: str) -> None:
        """Mark the row abandoned rather than deleting it -- see `CourseRow`
        for why. A no-op if the slug was never realized: a rebuild from an
        arbitrary checkpoint may replay an abandon whose realize predates the
        checkpoint, and raising here would put a routine replay in the
        dead-letter queue (the same reasoning `CatalogFeatureStore.unfeature`
        gives for tolerating a delete of something absent)."""
        row = await self.get(project_id, slug)
        if row is None:
            return
        await self._rows.save(row.model_copy(update={"abandoned": True}))

    async def close(self) -> None:
        await self._connection.close()


class CourseProjection(DeclarativeProjection):
    """Keeps `courses` level with the realization events."""

    def __init__(
        self,
        store: CourseStore,
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._store = store
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(CourseRealized)
    async def _realized(self, event: CourseRealized) -> None:
        await self._store.realize(
            event.project_id,
            event.slug,
            event.title,
            event.member_entity_ids,
            event.membership_hash,
            event.realized_at,
        )

    @handles(CourseAbandoned)
    async def _abandoned(self, event: CourseAbandoned) -> None:
        await self._store.abandon(event.project_id, event.slug)


class OntologyRunner:
    """Keeps the ontology tables following the log.

    A sixth runner, for the reasons `CorpusRunner`'s docstring gives for being
    a second: a distinct `rebuild()`/`health()`-shaped surface for these tables
    alone, and a `rebuild()` that must not be able to truncate tables it does
    not own.
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
        self._ontology: OntologyStore | None = None
        self._manager: SubscriptionManager | None = None
        self._subscription = None
        self._checkpoints: SQLCheckpointRepository | None = None
        self._dlq: SQLDLQRepository | None = None
        self._engine: AsyncEngine | None = None

    @property
    def projection_name(self) -> str:
        return OntologyProjection.__name__

    async def start(self) -> None:
        """Open the tables and start following the log.

        Same shape as `CorpusRunner.start`, including touching the event store
        first so `projection_checkpoints` exists before anything reads it.
        """
        if self._manager is not None:
            return
        await self._store.current_position()
        engine = create_async_engine(f"sqlite+aiosqlite:///{self._db_path}")
        self._engine = engine
        self._checkpoints = SQLCheckpointRepository(engine)
        self._dlq = SQLDLQRepository(engine)
        self._ontology = await OntologyStore.open(self._db_path, self._tracer)
        projection = OntologyProjection(
            self._ontology, self._checkpoints, self._dlq, self._tracer
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
            raise RuntimeError(f"the ontology projection failed to start: {failures}")

    async def failures(self, limit: int = 100) -> list[DLQEntry]:
        if self._dlq is None:
            return []
        return await self._dlq.get_failed_events(
            projection_name=self.projection_name, limit=limit
        )

    def _started(self) -> OntologyStore:
        """The open store, or a refusal naming what was not done.

        Delegated the way `CorpusRunner.get` is rather than handing the store
        out through a property, and for the same reason: `rebuild()` closes one
        store and opens another, so a caller holding the store would go on
        calling a closed connection, silently, after a repair.
        """
        if self._ontology is None:
            raise RuntimeError("the ontology projection has not been started")
        return self._ontology

    async def classes_for(self, project_id: UUID) -> list[OntologyClassRow]:
        return await self._started().classes_for(project_id)

    async def members_for(self, class_id: UUID) -> list[OntologyMembershipRow]:
        return await self._started().members_for(class_id)

    async def sources_with_classes(self, project_id: UUID) -> set[str]:
        return await self._started().sources_with_classes(project_id)

    async def rebuild(self) -> None:
        """Truncate and replay.

        The opposite of `EntityDefinitionRunner.rebuild`, which must not
        truncate, and the difference is which columns come from the log. A
        definition's `text` comes from a service's `put`, so replaying would
        not restore it. Every column in these three tables is written by
        `_on_discovered` from an event payload, so a replay reproduces them
        exactly -- and the truncate is what removes rows for a class a
        superseded event no longer carries, which a replay alone would leave
        behind.
        """
        if self._manager is None:
            raise RuntimeError("the ontology projection has not been started")
        await self._manager.stop()
        for entry in await self.failures(limit=1000):
            await self._dlq.mark_resolved(entry.id, resolved_by="rebuild")
        await self._checkpoints.reset_checkpoint(self.projection_name)
        async with aiosqlite.connect(self._db_path) as connection:
            for table in (
                OntologyClassRow.table_name(),
                OntologyMembershipRow.table_name(),
                OntologyExaminedRow.table_name(),
            ):
                await connection.execute(f"DELETE FROM {table}")
            await connection.commit()
        self._manager = None
        self._subscription = None
        await self._ontology.close()
        self._ontology = None
        await self.start()
        await self.caught_up()

    async def caught_up(self, timeout: float = 10.0) -> None:
        """Block until this projection has consumed every event it subscribes to.

        **Not a comparison against `current_position()`, the store's global
        end**, which is what an earlier draft of this method did and what
        `SessionSummaryRunner.caught_up` documents at length as wrong for a
        scoped subscription: any append of a type this projection ignores moves
        the end to a position it will never reach, and the wait then runs its
        full timeout every time.

        That draft justified the global comparison by arguing this projection
        consumes both of the event types that move the store in ordinary use.
        **It does not.** Storing a document appends `CorpusDocumentStored` and
        redstring's `DocumentChunked`, neither of them subscribed here -- and
        storing a document is the ordinary prelude to discovering an ontology
        in it, so the mistake was on the main path rather than in a corner.
        `tests/integration/test_ontology_wiring.py` caught it, because it
        stores a document before running a pass; no unit test could, because
        each builds its own store holding only the events it appended.

        So this reads the remaining work per aggregate type instead, scoped and
        starting from what the subscription has already processed -- empty in
        the common case rather than a scan of the log. Two reads, because this
        projection subscribes to two streams: its own `Ontology` events and
        redstring's document category.

        Filtered by event *type* as well, because the aggregate type is not
        fine enough on its own: `DocumentChunked` shares the document category
        with `DocumentExtracted` and is not handled here, so a scope-only read
        would never drain and every wait would still time out -- the same
        failure one level down, and the reason this is a filter rather than the
        two-line version `SessionSummaryRunner` gets away with.
        """
        if self._manager is None:
            return
        handled = (OntologyDiscovered.__name__, DocumentExtracted.__name__)
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            remaining = []
            for aggregate_type in (ONTOLOGY_AGGREGATE_TYPE, DOCUMENT_CATEGORY):
                remaining += [
                    envelope
                    for envelope in await collect(
                        self._store.read_all(
                            from_position=self._subscription.last_processed_position,
                            options=FeedReadOptions(aggregate_type=aggregate_type),
                        )
                    )
                    if type(envelope.event).__name__ in handled
                ]
            if not remaining:
                return
            await asyncio.sleep(0.01)
        raise TimeoutError(
            f"the ontology projection did not consume every {ONTOLOGY_AGGREGATE_TYPE} "
            f"and {DOCUMENT_CATEGORY} event within {timeout}s"
        )

    async def stop(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
            self._manager = None
            self._subscription = None
        if self._ontology is not None:
            await self._ontology.close()
            self._ontology = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None


MEDIA_PROPOSAL_NAMESPACE = UUID("d4a1c6e2-8f3b-5a90-9e7c-1b4d3f6a8c2e")
"""Distinct from every other namespace in this module, for the reason each of
theirs gives: two tables sharing one derivation could let an id chosen in one
collide with an id chosen in the other."""


class MediaNeedRow(ReadModel):
    """One need from a `MediaNeedsIdentified` payload, kept only so
    `MediaProposalProjection` can look a description up by `need_id` when a
    later `MediaProposed` names it.

    Not exposed through `MediaProposalStore` -- nothing reads this table
    directly. It exists purely to survive past the event that filled it, so
    the denormalization onto `MediaProposalRow` works whether a proposal
    arrives in the same process run that saw the needs event or a later one
    resuming from a checkpoint.
    """

    __table_name__ = "media_needs"

    project_id: UUID
    need_id: str
    description: str

    @staticmethod
    def row_id(project_id: UUID, need_id: str) -> UUID:
        """Keyed on the pair: `need_id` is chosen per stage-1 run and a
        second project's need with the same id must not overwrite this one.
        """
        return uuid5(MEDIA_PROPOSAL_NAMESPACE, f"need:{project_id}:{need_id}")


class MediaIgnoredAssetRow(ReadModel):
    """One asset a person has told the chain never to propose again.

    A row's existence is the fact; nothing on it varies. `MediaAssetUnignored`
    deletes the row outright rather than flagging it, because "currently
    ignored" is exactly what `for_project`-style listing over this table
    would otherwise have to filter for, and there is no reader that wants a
    history of past ignores.
    """

    __table_name__ = "media_ignored_assets"

    project_id: UUID
    asset_key: str

    @staticmethod
    def row_id(project_id: UUID, asset_key: str) -> UUID:
        return uuid5(MEDIA_PROPOSAL_NAMESPACE, f"ignored-asset:{project_id}:{asset_key}")


class MediaIgnoredHostRow(ReadModel):
    """Mirrors `MediaIgnoredAssetRow` exactly, at the host grain."""

    __table_name__ = "media_ignored_hosts"

    project_id: UUID
    host: str

    @staticmethod
    def row_id(project_id: UUID, host: str) -> UUID:
        return uuid5(MEDIA_PROPOSAL_NAMESPACE, f"ignored-host:{project_id}:{host}")


class MediaProposalRow(ReadModel):
    """One proposal, project/proposal/topic/need/reason/asset/thumbnail and
    the state it has reached.

    `need_description` is denormalized from `MediaNeedsIdentified` rather
    than joined at read time: the projection already sees both events on the
    same stream, in order, and a join across `MediaNeedRow` (or worse, a
    JSON `needs` column) is the more expensive way to answer a question this
    handler can answer once and write down. See the controller ruling in the
    task-7 brief -- without it the pane can group proposals by need but
    cannot label the groups.

    `source_id` and `error` are mutually exclusive outcomes of the same
    lifecycle step (`stored` vs `failed`) and both nullable, mirroring how
    `CorpusDocumentRow.dropped_reason` stays None until the fact it records
    happens -- the two are never both set on this build's own writes, but
    nothing enforces that here; the domain aggregate is where that guard
    lives, on `decide`'s lifecycle cases.
    """

    __table_name__ = "media_proposals"

    project_id: UUID
    proposal_id: str
    need_id: str
    need_description: str = ""
    topic_id: str
    page_url: str
    asset_url: str
    thumbnail_url: str = ""
    kind: str
    title: str
    reason: str
    query: str
    status: str = "proposed"
    note: str = ""
    source_id: str | None = None
    error: str | None = None

    @staticmethod
    def row_id(proposal_id: str) -> UUID:
        """Keyed on `proposal_id` alone, not the `(project_id, id)` pair
        `CorpusDocumentRow` uses. Every event after `MediaProposed` --
        `MediaProposalAccepted`, `Rejected`, `Stored`, `Failed` -- carries
        only `proposal_id`, not `project_id`; a key that needed both could
        not be derived from those events without a lookup this method exists
        to avoid. `decide`'s own guard makes `proposal_id` a domain-wide
        unique choice already: `AcceptMediaProposal` and friends are rejected
        with "unknown proposal" unless a record for that id already exists in
        *this project's* fold, so a `MediaProposalStore`'s own aggregate never
        mistakes another project's id for its own.
        """
        return uuid5(MEDIA_PROPOSAL_NAMESPACE, f"proposal:{proposal_id}")


class MediaProposalProjection(DeclarativeProjection):
    """Writes proposals, and the needs they are denormalized against.

    Every handler loads, changes and saves back, the same idempotent-on-
    replay shape `SessionSummaryProjection` uses -- so resuming from a
    slightly-behind checkpoint re-derives the same row rather than
    accumulating state twice.
    """

    def __init__(
        self,
        rows: ReadModelRepository[MediaProposalRow],
        needs: ReadModelRepository[MediaNeedRow],
        ignored_assets: ReadModelRepository[MediaIgnoredAssetRow],
        ignored_hosts: ReadModelRepository[MediaIgnoredHostRow],
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._rows = rows
        self._needs = needs
        self._ignored_assets = ignored_assets
        self._ignored_hosts = ignored_hosts
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(MediaNeedsIdentified)
    async def _on_needs_identified(self, event: MediaNeedsIdentified) -> None:
        """Record every need's description, keyed for `_on_proposed` to find.

        `needs` is JSON by design -- see the field's own docstring in
        `domain/media_proposals.py` -- so this is the one place that parses
        it. A need missing `description` or `need_id` is skipped rather than
        raising: stage 1's prompt is what shapes this payload and a malformed
        entry here must not put an otherwise-good discovery pass in the DLQ.
        """
        for need in json.loads(event.needs):
            need_id = need.get("need_id")
            if not need_id:
                continue
            await self._needs.save(
                MediaNeedRow(
                    id=MediaNeedRow.row_id(event.aggregate_id, need_id),
                    project_id=event.aggregate_id,
                    need_id=need_id,
                    description=need.get("description", ""),
                )
            )

    @handles(MediaProposed)
    async def _on_proposed(self, event: MediaProposed) -> None:
        """Create the row, denormalizing the need's description if one has
        been recorded. `event.project_id` is text on the event -- see its
        docstring -- and `aggregate_id` is the same value already parsed, so
        this reads from `aggregate_id` rather than re-parsing it.
        """
        need_row = await self._needs.get(
            MediaNeedRow.row_id(event.aggregate_id, event.need_id)
        )
        await self._rows.save(
            MediaProposalRow(
                id=MediaProposalRow.row_id(event.proposal_id),
                project_id=event.aggregate_id,
                proposal_id=event.proposal_id,
                need_id=event.need_id,
                need_description=need_row.description if need_row is not None else "",
                topic_id=event.topic_id,
                page_url=event.page_url,
                asset_url=event.asset_url,
                thumbnail_url=event.thumbnail_url,
                kind=event.kind,
                title=event.title,
                reason=event.reason,
                query=event.query,
            )
        )

    @handles(MediaProposalAccepted)
    async def _on_accepted(self, event: MediaProposalAccepted) -> None:
        row = await self._require(event.proposal_id)
        row.status = "accepted"
        await self._rows.save(row)

    @handles(MediaProposalRejected)
    async def _on_rejected(self, event: MediaProposalRejected) -> None:
        row = await self._require(event.proposal_id)
        row.status = "rejected"
        row.note = event.note
        await self._rows.save(row)

    @handles(MediaProposalStored)
    async def _on_stored(self, event: MediaProposalStored) -> None:
        row = await self._require(event.proposal_id)
        row.status = "stored"
        row.source_id = event.source_id
        await self._rows.save(row)

    @handles(MediaProposalFailed)
    async def _on_failed(self, event: MediaProposalFailed) -> None:
        """A failure stays visible rather than disappearing -- the design
        doc's own point: a judged candidate that turned out to serve an HTML
        interstitial is a failure, not a source, and the pane has to be able
        to say why a proposal never became one.
        """
        row = await self._require(event.proposal_id)
        row.status = "failed"
        row.error = event.error
        await self._rows.save(row)

    @handles(MediaAssetIgnored)
    async def _on_asset_ignored(self, event: MediaAssetIgnored) -> None:
        await self._ignored_assets.save(
            MediaIgnoredAssetRow(
                id=MediaIgnoredAssetRow.row_id(event.aggregate_id, event.asset_key),
                project_id=event.aggregate_id,
                asset_key=event.asset_key,
            )
        )

    @handles(MediaAssetUnignored)
    async def _on_asset_unignored(self, event: MediaAssetUnignored) -> None:
        """Reversible, per the module's own docstring -- a blacklist with no
        way back is a trap a single misclick sets permanently. `delete`
        answering False (nothing to remove) is not an error here: the same
        state an already-unignored asset would leave behind.
        """
        await self._ignored_assets.delete(
            MediaIgnoredAssetRow.row_id(event.aggregate_id, event.asset_key)
        )

    @handles(MediaHostIgnored)
    async def _on_host_ignored(self, event: MediaHostIgnored) -> None:
        await self._ignored_hosts.save(
            MediaIgnoredHostRow(
                id=MediaIgnoredHostRow.row_id(event.aggregate_id, event.host),
                project_id=event.aggregate_id,
                host=event.host,
            )
        )

    @handles(MediaHostUnignored)
    async def _on_host_unignored(self, event: MediaHostUnignored) -> None:
        await self._ignored_hosts.delete(
            MediaIgnoredHostRow.row_id(event.aggregate_id, event.host)
        )

    async def _require(self, proposal_id: str) -> MediaProposalRow:
        """The row for a proposal, which must already exist.

        `MediaProposed` is the creation event and cannot be preceded by
        `MediaProposalAccepted`/`Rejected`/`Stored`/`Failed` on a well-formed
        stream -- `decide`'s own unknown-id guard refuses those commands
        before this projection ever sees the events they would produce. A
        missing row here means events arrived out of order or the table was
        truncated under a checkpoint that survived, both worth an error
        rather than a silently invented row -- mirrors
        `SessionSummaryProjection._require`.
        """
        row = await self._rows.get(MediaProposalRow.row_id(proposal_id))
        if row is None:
            raise LookupError(f"no proposal row for {proposal_id}")
        return row


class MediaProposalStore:
    """The proposal table, its supporting tables, and the connection they
    share. Mirrors `OntologyStore`: one store over several tables that are
    written together, opened with `apply_schema` so there is no migration
    step to run and forget.
    """

    def __init__(
        self,
        connection: aiosqlite.Connection,
        rows: ReadModelRepository[MediaProposalRow],
        needs: ReadModelRepository[MediaNeedRow],
        ignored_assets: ReadModelRepository[MediaIgnoredAssetRow],
        ignored_hosts: ReadModelRepository[MediaIgnoredHostRow],
        projection: MediaProposalProjection,
    ) -> None:
        self._connection = connection
        self._rows = rows
        self._needs = needs
        self._ignored_assets = ignored_assets
        self._ignored_hosts = ignored_hosts
        self.projection = projection

    @classmethod
    async def open(
        cls, db_path: str, checkpoint_repo=None, dlq_repo=None, tracer=None
    ) -> "MediaProposalStore":
        connection = await aiosqlite.connect(db_path)
        await apply_schema(connection, MediaProposalRow)
        await apply_schema(connection, MediaNeedRow)
        await apply_schema(connection, MediaIgnoredAssetRow)
        await apply_schema(connection, MediaIgnoredHostRow)
        # `apply_schema` reconciles columns and not indexes, so this stays --
        # the same note as `CorpusStore.open`. Every read here is by project.
        for statement in (
            f"CREATE INDEX IF NOT EXISTS idx_media_proposals_project "
            f"ON {MediaProposalRow.table_name()}(project_id)",
            f"CREATE INDEX IF NOT EXISTS idx_media_needs_project "
            f"ON {MediaNeedRow.table_name()}(project_id)",
            f"CREATE INDEX IF NOT EXISTS idx_media_ignored_assets_project "
            f"ON {MediaIgnoredAssetRow.table_name()}(project_id)",
            f"CREATE INDEX IF NOT EXISTS idx_media_ignored_hosts_project "
            f"ON {MediaIgnoredHostRow.table_name()}(project_id)",
        ):
            await connection.execute(statement)
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, MediaProposalRow, tracer)
        needs = SQLiteReadModelRepository(connection, MediaNeedRow, tracer)
        ignored_assets = SQLiteReadModelRepository(connection, MediaIgnoredAssetRow, tracer)
        ignored_hosts = SQLiteReadModelRepository(connection, MediaIgnoredHostRow, tracer)
        return cls(
            connection,
            rows,
            needs,
            ignored_assets,
            ignored_hosts,
            MediaProposalProjection(
                rows, needs, ignored_assets, ignored_hosts, checkpoint_repo, dlq_repo, tracer
            ),
        )

    async def for_project(self, project_id: UUID) -> list[MediaProposalRow]:
        """Every proposal in a project, newest table order -- mirrors
        `OntologyStore.classes_for`'s shape: a repository `get` per id rather
        than a projected SELECT, because a proposal row is a handful of short
        strings, nothing worth a column list to avoid loading.
        """
        cursor = await self._connection.execute(
            f"SELECT id FROM {MediaProposalRow.table_name()} "
            "WHERE project_id = ? AND deleted_at IS NULL",
            (str(project_id),),
        )
        try:
            ids = [UUID(row[0]) for row in await cursor.fetchall()]
        finally:
            await cursor.close()
        rows = [await self._rows.get(row_id) for row_id in ids]
        return [row for row in rows if row is not None]

    async def get_by_proposal_id(self, proposal_id: str) -> MediaProposalRow | None:
        """One proposal, keyed the way `AcceptMediaProposal`/`StoreMediaProposal`
        name it -- by `proposal_id` alone, not `(project_id, id)`.
        `MediaProposalRow.row_id` already derives the storage key from just
        `proposal_id` for this reason (see its docstring); this is the direct
        `self._rows.get` that reasoning exists to enable, with no scan.
        """
        return await self._rows.get(MediaProposalRow.row_id(proposal_id))

    async def accepted(self) -> list[MediaProposalRow]:
        """Every `accepted` proposal, across every project -- ordered by
        `proposal_id`, not scoped by `WHERE project_id = ?` the way every
        other read on this store is. Deliberately: reconciliation runs once
        per process, before anything has asked about a particular project,
        and an accepted proposal in a project nobody opens this session is
        exactly the one most likely to have been abandoned.
        """
        cursor = await self._connection.execute(
            f"SELECT id FROM {MediaProposalRow.table_name()} "
            "WHERE status = 'accepted' AND deleted_at IS NULL "
            "ORDER BY proposal_id",
            (),
        )
        try:
            ids = [UUID(row[0]) for row in await cursor.fetchall()]
        finally:
            await cursor.close()
        rows = [await self._rows.get(row_id) for row_id in ids]
        return [row for row in rows if row is not None]

    async def ignored_assets(self, project_id: UUID) -> set[str]:
        cursor = await self._connection.execute(
            f"SELECT asset_key FROM {MediaIgnoredAssetRow.table_name()} "
            "WHERE project_id = ? AND deleted_at IS NULL",
            (str(project_id),),
        )
        try:
            return {row[0] for row in await cursor.fetchall()}
        finally:
            await cursor.close()

    async def ignored_hosts(self, project_id: UUID) -> set[str]:
        cursor = await self._connection.execute(
            f"SELECT host FROM {MediaIgnoredHostRow.table_name()} "
            "WHERE project_id = ? AND deleted_at IS NULL",
            (str(project_id),),
        )
        try:
            return {row[0] for row in await cursor.fetchall()}
        finally:
            await cursor.close()

    async def close(self) -> None:
        await self._connection.close()


class MediaProposalRunner:
    """Keeps the proposal tables following the log, and answers from them.

    A distinct runner rather than another projection sharing an existing
    manager, for `CorpusRunner`'s own reason: `rebuild()` truncates tables
    and resets a checkpoint, and sharing a manager would mean repairing one
    projection's drift also interrupted an unrelated one's reads.
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
        self._proposals: MediaProposalStore | None = None
        self._manager: SubscriptionManager | None = None
        self._subscription = None
        self._checkpoints: SQLCheckpointRepository | None = None
        self._dlq: SQLDLQRepository | None = None
        self._engine: AsyncEngine | None = None

    @property
    def projection_name(self) -> str:
        return MediaProposalProjection.__name__

    async def start(self) -> None:
        """Open the tables and start following the log.

        Same shape as `OntologyRunner.start`, including touching the event
        store first so `projection_checkpoints` exists before anything reads
        it.
        """
        if self._manager is not None:
            return
        await self._store.current_position()
        engine = create_async_engine(f"sqlite+aiosqlite:///{self._db_path}")
        self._engine = engine
        self._checkpoints = SQLCheckpointRepository(engine)
        self._dlq = SQLDLQRepository(engine)
        self._proposals = await MediaProposalStore.open(
            self._db_path, self._checkpoints, self._dlq, self._tracer
        )
        self._manager = SubscriptionManager(
            self._store, self._bus, self._checkpoints, dlq_repo=self._dlq, tracer=self._tracer
        )
        self._subscription = await self._manager.subscribe(
            self._proposals.projection, SubscriptionConfig(start_from="checkpoint")
        )
        results = await self._manager.start()
        failures = {name: err for name, err in results.items() if err is not None}
        if failures:
            raise RuntimeError(f"the media-proposal projection failed to start: {failures}")

    async def failures(self, limit: int = 100) -> list[DLQEntry]:
        if self._dlq is None:
            return []
        return await self._dlq.get_failed_events(
            projection_name=self.projection_name, limit=limit
        )

    def _started(self) -> MediaProposalStore:
        if self._proposals is None:
            raise RuntimeError("the media-proposal projection has not been started")
        return self._proposals

    async def for_project(self, project_id: UUID) -> list[MediaProposalRow]:
        return await self._started().for_project(project_id)

    async def get(self, proposal_id: str) -> AcceptedProposal | None:
        """Satisfies `MediaAcceptWorker`'s `MediaProposalReadPort` directly off
        this projection, rather than through a separate adapter -- this runner
        is already handed to routes as the read side of proposals
        (`list_media_proposals` reads `for_project` off it the same way), so
        composition hands the accept worker this same instance for `reads`.

        Returns whatever the row currently says regardless of `status`: the
        worker is only ever invoked after `AcceptMediaProposal` has already
        landed, and re-deriving that check here would be a second place for
        the two to disagree about what "accepted" means.
        """
        row = await self._started().get_by_proposal_id(proposal_id)
        if row is None:
            return None
        return AcceptedProposal(
            project_id=str(row.project_id),
            page_url=row.page_url,
            asset_url=row.asset_url,
            title=row.title,
        )

    async def accepted_proposal_ids(self) -> list[str]:
        """The accepted-but-unfinished set, across every project -- what
        `MediaAcceptReconciler` loops over. See `MediaProposalStore.accepted`
        for why this is not scoped to one project.
        """
        rows = await self._started().accepted()
        return [row.proposal_id for row in rows]

    async def ignored_assets(self, project_id: UUID) -> set[str]:
        return await self._started().ignored_assets(project_id)

    async def ignored_hosts(self, project_id: UUID) -> set[str]:
        return await self._started().ignored_hosts(project_id)

    async def rebuild(self) -> None:
        """Truncate and replay -- mirrors `OntologyRunner.rebuild` exactly,
        including why a truncate is needed and a replay alone would not be
        enough: every column here comes from an event payload, so replaying
        reproduces them, but a proposal whose stream no later event touches
        again would otherwise never lose a row nothing still asserts.
        """
        if self._manager is None:
            raise RuntimeError("the media-proposal projection has not been started")
        await self._manager.stop()
        for entry in await self.failures(limit=1000):
            await self._dlq.mark_resolved(entry.id, resolved_by="rebuild")
        await self._checkpoints.reset_checkpoint(self.projection_name)
        async with aiosqlite.connect(self._db_path) as connection:
            for table in (
                MediaProposalRow.table_name(),
                MediaNeedRow.table_name(),
                MediaIgnoredAssetRow.table_name(),
                MediaIgnoredHostRow.table_name(),
            ):
                await connection.execute(f"DELETE FROM {table}")
            await connection.commit()
        self._manager = None
        self._subscription = None
        await self._proposals.close()
        self._proposals = None
        await self.start()
        await self.caught_up()

    async def caught_up(self, timeout: float = 10.0) -> None:
        """Block until this projection has consumed every event on its own
        stream type. Scoped by aggregate type alone, unlike
        `OntologyRunner.caught_up` -- this projection subscribes to exactly
        one stream category (`MediaProposals`) and every event on it is
        handled, so there is no second, unhandled event type sharing the
        category the way `DocumentChunked` shares `DOCUMENT_CATEGORY` with
        `DocumentExtracted`. Mirrors `SessionSummaryRunner.caught_up`'s
        simpler shape for exactly that reason.
        """
        if self._manager is None:
            return
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            remaining = await collect(
                self._store.read_all(
                    from_position=self._subscription.last_processed_position,
                    options=FeedReadOptions(aggregate_type="MediaProposals"),
                )
            )
            if not remaining:
                return
            await asyncio.sleep(0.01)
        raise TimeoutError(
            "the media-proposal projection did not consume every MediaProposals "
            f"event within {timeout}s"
        )

    async def stop(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
            self._manager = None
            self._subscription = None
        if self._proposals is not None:
            await self._proposals.close()
            self._proposals = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None


ASK_NAMESPACE = UUID("b0d4f1a7-52c6-5f38-9d1e-7a3c806b45e9")
"""Distinct from the other namespaces here, for the reason stated on
`ONTOLOGY_NAMESPACE`: tables keyed on unrelated things that are all just
strings by the time `uuid5` sees them must not be able to collide on `id`."""


class AskConversationRow(ReadModel):
    """One persisted conversation. `id` is the conversation id.

    The aggregate id itself, with no `uuid5` over it, unlike every other row
    in this module: the id is minted by the server and handed to the client on
    the ask stream, so deriving a second one would give the history route a
    key nothing ever returned.

    Carries `first_question` and `turn_count` so a history list can be drawn
    from this table alone. The alternative -- listing conversations and then
    reading every turn of each to find its opening line -- is a query per row
    on a page whose whole job is to be a cheap index.
    """

    __table_name__ = "ask_conversations"

    project_id: UUID
    opened_at: datetime
    first_question: str = ""
    turn_count: int = 0


class AskTurnRow(ReadModel):
    """One question and its answer, with the citations that answer rested on.

    **`position` is stored, not inferred.** A read that leaned on insertion
    order would be correct until `rebuild()` truncated and replayed, which is
    a supported operation here and free to insert rows in a different physical
    order. The column is assigned from the conversation's `turn_count` as the
    event is applied, so a replay of the same log reproduces the same numbers.

    `citations` is a JSON list for `SessionSummaryRow.file_paths`' reason, and
    is decoded on the way out for the same asymmetry that field documents.
    """

    __table_name__ = "ask_turns"

    conversation_id: UUID
    project_id: UUID
    position: int
    question: str
    answer: str
    citations: list[dict] = Field(default_factory=list)
    recorded_at: datetime

    @field_validator("citations", mode="before")
    @classmethod
    def _decode_json_list(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def row_id(conversation_id: UUID, position: int) -> UUID:
        """Derived from the pair, so replaying one event twice rewrites a row
        rather than appending a second copy of the same turn."""
        return uuid5(ASK_NAMESPACE, f"{conversation_id}:{position}")


class AskConversationStore:
    """The two ask tables and the connection they share.

    One store rather than one per table, for `OntologyStore`'s reason: a turn
    and its conversation's `turn_count` are written together, and two stores
    over two connections would leave a window in which a conversation claims a
    turn that cannot be read yet.
    """

    def __init__(
        self,
        connection: aiosqlite.Connection,
        conversations: ReadModelRepository[AskConversationRow],
        turns: ReadModelRepository[AskTurnRow],
    ) -> None:
        self._connection = connection
        self._conversations = conversations
        self._turns = turns

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> "AskConversationStore":
        connection = await aiosqlite.connect(db_path)
        await apply_schema(connection, AskConversationRow)
        await apply_schema(connection, AskTurnRow)
        # `apply_schema` reconciles columns and not indexes -- the same note as
        # on `EntityDefinitionStore.open`. Both reads here are scoped: the
        # history list by project and one conversation's turns by conversation,
        # so without these every read scans every ask anyone ever made.
        for statement in (
            f"CREATE INDEX IF NOT EXISTS idx_ask_conversations_project "
            f"ON {AskConversationRow.table_name()}(project_id)",
            f"CREATE INDEX IF NOT EXISTS idx_ask_turns_conversation "
            f"ON {AskTurnRow.table_name()}(conversation_id, position)",
        ):
            await connection.execute(statement)
        await connection.commit()
        return cls(
            connection,
            SQLiteReadModelRepository(connection, AskConversationRow, tracer),
            SQLiteReadModelRepository(connection, AskTurnRow, tracer),
        )

    async def start(
        self, conversation_id: UUID, project_id: UUID, opened_at: datetime
    ) -> None:
        await self._conversations.save(
            AskConversationRow(id=conversation_id, project_id=project_id, opened_at=opened_at)
        )

    async def record(
        self,
        conversation_id: UUID,
        *,
        question: str,
        answer: str,
        citations: list[dict],
        recorded_at: datetime,
    ) -> None:
        """Store one turn at the next position, and move the conversation on.

        A turn against a conversation with no row is dropped rather than
        raised on: `AskConversation.decide` refuses a turn before a start, so
        the only way to arrive here is a log whose first event this projection
        never saw, and a DLQ entry per turn would bury a real failure under a
        stream that cannot be repaired anyway.
        """
        conversation = await self._conversations.get(conversation_id)
        if conversation is None:
            return
        position = conversation.turn_count
        await self._turns.save(
            AskTurnRow(
                id=AskTurnRow.row_id(conversation_id, position),
                conversation_id=conversation_id,
                project_id=conversation.project_id,
                position=position,
                question=question,
                answer=answer,
                citations=citations,
                recorded_at=recorded_at,
            )
        )
        conversation.turn_count = position + 1
        if position == 0:
            conversation.first_question = question
        await self._conversations.save(conversation)

    async def get(self, conversation_id: UUID) -> AskConversationRow | None:
        return await self._conversations.get(conversation_id)

    async def for_project(self, project_id: UUID) -> list[AskConversationRow]:
        """A project's conversations, most recently opened first."""
        return await self._conversations.find(
            Query(
                filters=[Filter(field="project_id", operator="eq", value=str(project_id))],
                order_by="opened_at",
                order_direction="desc",
            )
        )

    async def turns_for(self, conversation_id: UUID) -> list[AskTurnRow]:
        """One conversation's turns, in the order they were asked -- by the
        stored `position`, never by arrival. See `AskTurnRow`."""
        return await self._turns.find(
            Query(
                filters=[
                    Filter(field="conversation_id", operator="eq", value=str(conversation_id))
                ],
                order_by="position",
                order_direction="asc",
            )
        )

    async def truncate(self) -> None:
        """Empty both tables, for a rebuild to fill again -- a hard delete for
        `SessionSummaryStore.truncate`'s reason."""
        for table in (AskConversationRow.table_name(), AskTurnRow.table_name()):
            await self._connection.execute(f"DELETE FROM {table}")
        await self._connection.commit()

    async def close(self) -> None:
        await self._connection.close()


class AskConversationProjection(DeclarativeProjection):
    """Writes persisted asks into the two tables above.

    Nothing else writes them: unlike `EntityDefinitionStore`, every column
    here comes from an event payload, which is what lets `rebuild()` truncate.
    """

    def __init__(
        self,
        asks: AskConversationStore,
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._asks = asks
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(AskConversationStarted)
    async def _on_started(self, event: AskConversationStarted) -> None:
        await self._asks.start(event.aggregate_id, event.project_id, event.opened_at)

    @handles(AskTurnRecorded)
    async def _on_turn(self, event: AskTurnRecorded) -> None:
        """`event.occurred_at` rather than a clock read, for the reason
        `OntologyProjection._on_discovered` gives: a rebuild has to reproduce
        the timestamps it produced the first time, not today's."""
        await self._asks.record(
            event.aggregate_id,
            question=event.question,
            answer=event.answer,
            citations=[{"kind": kind, "id": cited} for kind, cited in event.citations],
            recorded_at=event.occurred_at,
        )


class AskConversationRunner:
    """Keeps the ask tables following the log.

    A seventh runner, for the reasons `CorpusRunner`'s docstring gives for
    being a second: a `rebuild()`/`failures()`-shaped surface for these tables
    alone, and a `rebuild()` that cannot truncate tables it does not own.
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
        self._asks: AskConversationStore | None = None
        self._manager: SubscriptionManager | None = None
        self._subscription = None
        self._checkpoints: SQLCheckpointRepository | None = None
        self._dlq: SQLDLQRepository | None = None
        self._engine: AsyncEngine | None = None

    @property
    def projection_name(self) -> str:
        return AskConversationProjection.__name__

    async def start(self) -> None:
        """Open the tables and start following the log.

        Same shape as `OntologyRunner.start`, including touching the event
        store first so `projection_checkpoints` exists before anything reads
        it.
        """
        if self._manager is not None:
            return
        await self._store.current_position()
        engine = create_async_engine(f"sqlite+aiosqlite:///{self._db_path}")
        self._engine = engine
        self._checkpoints = SQLCheckpointRepository(engine)
        self._dlq = SQLDLQRepository(engine)
        self._asks = await AskConversationStore.open(self._db_path, self._tracer)
        projection = AskConversationProjection(
            self._asks, self._checkpoints, self._dlq, self._tracer
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
            raise RuntimeError(f"the ask projection failed to start: {failures}")

    async def failures(self, limit: int = 100) -> list[DLQEntry]:
        if self._dlq is None:
            return []
        return await self._dlq.get_failed_events(
            projection_name=self.projection_name, limit=limit
        )

    def _started(self) -> AskConversationStore:
        """The open store, or a refusal naming what was not done -- delegated
        rather than handed out, for `OntologyRunner._started`'s reason."""
        if self._asks is None:
            raise RuntimeError("the ask projection has not been started")
        return self._asks

    async def get(self, conversation_id: UUID) -> AskConversationRow | None:
        return await self._started().get(conversation_id)

    async def for_project(self, project_id: UUID) -> list[AskConversationRow]:
        return await self._started().for_project(project_id)

    async def turns_for(self, conversation_id: UUID) -> list[AskTurnRow]:
        return await self._started().turns_for(conversation_id)

    async def rebuild(self) -> None:
        """Truncate and replay.

        Allowed here, unlike `EntityDefinitionRunner.rebuild`, because every
        column in both tables is written from an event payload -- including
        `position`, which the projection derives in log order and therefore
        reproduces.
        """
        if self._manager is None:
            raise RuntimeError("the ask projection has not been started")
        await self._manager.stop()
        for entry in await self.failures(limit=1000):
            await self._dlq.mark_resolved(entry.id, resolved_by="rebuild")
        await self._checkpoints.reset_checkpoint(self.projection_name)
        await self._started().truncate()
        self._manager = None
        self._subscription = None
        await self._asks.close()
        self._asks = None
        await self.start()
        await self.caught_up()

    async def caught_up(self, timeout: float = 10.0) -> None:
        """Block until every `AskConversation` event appended so far is in the
        tables.

        Scoped by aggregate type and started from what the subscription has
        already processed, **not** compared against the store's global end --
        `SessionSummaryRunner.caught_up` documents at length why that
        comparison runs its full timeout for a scoped subscription, and asks
        share a store with sessions, the corpus and redstring's documents, any
        of which moves the end to a position this projection never reaches.

        No event-type filter, unlike `OntologyRunner.caught_up`: this
        projection handles *both* event types on its aggregate, so the scope is
        already exact.
        """
        if self._manager is None:
            return
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            remaining = await collect(
                self._store.read_all(
                    from_position=self._subscription.last_processed_position,
                    options=FeedReadOptions(aggregate_type=AskConversation.aggregate_type),
                )
            )
            if not remaining:
                return
            await asyncio.sleep(0.01)
        raise TimeoutError(
            f"the ask projection did not consume every "
            f"{AskConversation.aggregate_type} event within {timeout}s"
        )

    async def stop(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
            self._manager = None
            self._subscription = None
        if self._asks is not None:
            await self._asks.close()
            self._asks = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None


SOCRATIC_NAMESPACE = UUID("e1c7a9d2-4b0f-4a6e-9c31-2f58d7b6e410")
"""Namespace for derived socratic row ids. A fresh uuid5 namespace rather than
reusing `ASK_NAMESPACE`: the two id spaces would otherwise collide on a
dialogue and a conversation that happened to share an id and a position, which
is astronomically unlikely and free to prevent."""


class SocraticDialogueRow(ReadModel):
    """One dialogue. `id` is the dialogue id.

    The aggregate id itself with no `uuid5` over it, for `AskConversationRow`'s
    reason: the id is minted by the server and handed to the client, so
    deriving a second one would give every read route a key nothing returned.

    **`goal` and `stopping_condition` are the resumption path's source of
    truth.** When the live registry has dropped a dialogue, this row is what it
    is rebuilt from -- so a projection that stored the topic and dropped these
    two would resume a dialogue aimed at nothing, and every request would still
    answer 200.

    `observations` is a JSON list for `AskTurnRow.citations`' reason. A third
    table was the alternative and buys a query nothing issues; the spec asks
    for the two-table pattern and this is what keeps it.
    """

    __table_name__ = "socratic_dialogues"

    project_id: UUID
    topic: str
    goal: str
    stopping_condition: str
    opening_prompt: str = ""
    pending_prompt: str = ""
    """The question the reader is currently looking at.

    **Derived, not a second copy.** It is the last turn's `prompt`, or
    `opening_prompt` when there are no turns -- the projection writes it on
    start and overwrites it on each turn, so the log still holds each utterance
    once and this column is the precomputation a read model exists to do. A
    client asking "what am I answering?" would otherwise have to fetch every
    turn to find out.

    `rebuild()` reproduces it, because it is written in log order from event
    payloads like every other column here."""

    opened_at: datetime
    status: str = "started"
    concluded_reason: str = ""
    turn_count: int = 0
    observations: list[dict] = Field(default_factory=list)

    @field_validator("observations", mode="before")
    @classmethod
    def _decode_json_list(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value


class SocraticTurnRow(ReadModel):
    """One exchange: what the reader said, and what the dialogue said back.

    **`position` is stored, not inferred**, for `AskTurnRow`'s reason: a read
    leaning on insertion order is correct until `rebuild()` truncates and
    replays, which is supported here and free to insert in a different physical
    order.

    `prompt` is the dialogue's utterance and `reply` is the reader's -- the
    inverse of `AskTurnRow`, because this surface runs in the opposite
    direction. See `test_the_speakers_are_not_swapped_on_the_way_into_the_table`
    for what a swap would look like: a transcript that still reads as a
    conversation, just one where the reader asks all the questions.

    **A row is one exchange, reader first.** The question this row's `reply`
    answers is the *previous* row's `prompt` -- or `opening_prompt` on the
    dialogue, for row 0. So a client rendering only this table draws a
    transcript that starts with the reader; the dialogue's `opening_prompt` is
    the missing first utterance.
    """

    __table_name__ = "socratic_turns"

    dialogue_id: UUID
    project_id: UUID
    position: int
    prompt: str
    reply: str
    citations: list[dict] = Field(default_factory=list)
    recorded_at: datetime

    @field_validator("citations", mode="before")
    @classmethod
    def _decode_json_list(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def row_id(dialogue_id: UUID, position: int) -> UUID:
        """Derived from the pair, so replaying one event twice rewrites a row
        rather than appending a second copy of the same turn."""
        return uuid5(SOCRATIC_NAMESPACE, f"{dialogue_id}:{position}")


class SocraticDialogueStore:
    """The two dialogue tables and the connection they share.

    One store rather than one per table, for `AskConversationStore`'s reason: a
    turn and its dialogue's `turn_count` and `pending_prompt` are written
    together, and two stores over two connections would leave a window in which
    a dialogue claims a turn that cannot be read yet.
    """

    def __init__(
        self,
        connection: aiosqlite.Connection,
        dialogues: ReadModelRepository[SocraticDialogueRow],
        turns: ReadModelRepository[SocraticTurnRow],
    ) -> None:
        self._connection = connection
        self._dialogues = dialogues
        self._turns = turns

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> "SocraticDialogueStore":
        connection = await aiosqlite.connect(db_path)
        await apply_schema(connection, SocraticDialogueRow)
        await apply_schema(connection, SocraticTurnRow)
        # `apply_schema` reconciles columns and not indexes -- the same note as
        # on `AskConversationStore.open`. Both reads here are scoped: the
        # history list by project and one dialogue's turns by dialogue, so
        # without these every read scans every dialogue anyone ever had.
        for statement in (
            f"CREATE INDEX IF NOT EXISTS idx_socratic_dialogues_project "
            f"ON {SocraticDialogueRow.table_name()}(project_id)",
            f"CREATE INDEX IF NOT EXISTS idx_socratic_turns_dialogue "
            f"ON {SocraticTurnRow.table_name()}(dialogue_id, position)",
        ):
            await connection.execute(statement)
        await connection.commit()
        return cls(
            connection,
            SQLiteReadModelRepository(connection, SocraticDialogueRow, tracer),
            SQLiteReadModelRepository(connection, SocraticTurnRow, tracer),
        )

    async def start(
        self,
        dialogue_id: UUID,
        project_id: UUID,
        *,
        topic: str,
        goal: str,
        stopping_condition: str,
        opening_prompt: str,
        opened_at: datetime,
    ) -> None:
        await self._dialogues.save(
            SocraticDialogueRow(
                id=dialogue_id,
                project_id=project_id,
                topic=topic,
                goal=goal,
                stopping_condition=stopping_condition,
                opening_prompt=opening_prompt,
                # With no turns yet, the opening question is the outstanding
                # one. `record` overwrites this on every turn.
                pending_prompt=opening_prompt,
                opened_at=opened_at,
            )
        )

    async def record(
        self,
        dialogue_id: UUID,
        *,
        reply: str,
        prompt: str,
        citations: list[dict],
        recorded_at: datetime,
    ) -> None:
        """Store one exchange at the next position, and move the dialogue on.

        A turn against a dialogue with no row is dropped rather than raised on,
        for `AskConversationStore.record`'s reason: `decide` refuses a turn
        before a start, so the only way to arrive here is a log whose head this
        projection never saw, and a DLQ entry per turn would bury a real
        failure under a stream that cannot be repaired anyway.
        """
        dialogue = await self._dialogues.get(dialogue_id)
        if dialogue is None:
            return
        position = dialogue.turn_count
        await self._turns.save(
            SocraticTurnRow(
                id=SocraticTurnRow.row_id(dialogue_id, position),
                dialogue_id=dialogue_id,
                project_id=dialogue.project_id,
                position=position,
                reply=reply,
                prompt=prompt,
                citations=citations,
                recorded_at=recorded_at,
            )
        )
        dialogue.turn_count = position + 1
        # Precomputed, not a second copy: this turn's `prompt` is the newest
        # thing the dialogue said, so it is what the reader is now answering.
        # Derivable from the turns table; kept here so a client does not have
        # to fetch every turn to learn it.
        dialogue.pending_prompt = prompt
        await self._dialogues.save(dialogue)

    async def observe(
        self, dialogue_id: UUID, *, observation: str, evidence: str, detail: str
    ) -> None:
        """Append one observation to the dialogue's list.

        Read-modify-write on a JSON column, which is only safe because this
        projection is the single writer of these tables and processes one event
        at a time -- the same assumption `record`'s position counter already
        makes.
        """
        dialogue = await self._dialogues.get(dialogue_id)
        if dialogue is None:
            return
        dialogue.observations = [
            *dialogue.observations,
            {"observation": observation, "evidence": evidence, "detail": detail},
        ]
        await self._dialogues.save(dialogue)

    async def conclude(self, dialogue_id: UUID, *, reason: str) -> None:
        dialogue = await self._dialogues.get(dialogue_id)
        if dialogue is None:
            return
        dialogue.status = "concluded"
        dialogue.concluded_reason = reason
        await self._dialogues.save(dialogue)

    async def get(self, dialogue_id: UUID) -> SocraticDialogueRow | None:
        return await self._dialogues.get(dialogue_id)

    async def for_project(self, project_id: UUID) -> list[SocraticDialogueRow]:
        """A project's dialogues, most recently opened first."""
        return await self._dialogues.find(
            Query(
                filters=[Filter(field="project_id", operator="eq", value=str(project_id))],
                order_by="opened_at",
                order_direction="desc",
            )
        )

    async def turns_for(self, dialogue_id: UUID) -> list[SocraticTurnRow]:
        """One dialogue's exchanges, in the order they happened -- by the
        stored `position`, never by arrival. See `SocraticTurnRow`."""
        return await self._turns.find(
            Query(
                filters=[Filter(field="dialogue_id", operator="eq", value=str(dialogue_id))],
                order_by="position",
                order_direction="asc",
            )
        )

    async def truncate(self) -> None:
        """Empty both tables, for a rebuild to fill again -- a hard delete for
        `SessionSummaryStore.truncate`'s reason."""
        for table in (SocraticDialogueRow.table_name(), SocraticTurnRow.table_name()):
            await self._connection.execute(f"DELETE FROM {table}")
        await self._connection.commit()

    async def close(self) -> None:
        await self._connection.close()


class SocraticDialogueProjection(DeclarativeProjection):
    """Writes dialogues into the two tables above.

    Nothing else writes them: every column comes from an event payload, which
    is what lets `rebuild()` truncate.
    """

    def __init__(
        self,
        dialogues: SocraticDialogueStore,
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._dialogues = dialogues
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(SocraticDialogueStarted)
    async def _on_started(self, event: SocraticDialogueStarted) -> None:
        await self._dialogues.start(
            event.aggregate_id,
            event.project_id,
            topic=event.topic,
            goal=event.goal,
            stopping_condition=event.stopping_condition,
            opening_prompt=event.opening_prompt,
            opened_at=event.opened_at,
        )

    @handles(SocraticTurnRecorded)
    async def _on_turn(self, event: SocraticTurnRecorded) -> None:
        """`event.occurred_at` rather than a clock read, for the reason
        `AskConversationProjection._on_turn` gives: a rebuild has to reproduce
        the timestamps it produced the first time, not today's."""
        await self._dialogues.record(
            event.aggregate_id,
            reply=event.reply,
            prompt=event.prompt,
            citations=[{"kind": kind, "id": cited} for kind, cited in event.citations],
            recorded_at=event.occurred_at,
        )

    @handles(SocraticProgressObserved)
    async def _on_observed(self, event: SocraticProgressObserved) -> None:
        await self._dialogues.observe(
            event.aggregate_id,
            observation=event.observation,
            evidence=event.evidence,
            detail=event.detail,
        )

    @handles(SocraticDialogueConcluded)
    async def _on_concluded(self, event: SocraticDialogueConcluded) -> None:
        await self._dialogues.conclude(event.aggregate_id, reason=event.reason)


class SocraticDialogueRunner:
    """Keeps the dialogue tables following the log.

    A ninth runner, for `AskConversationRunner`'s reason: a
    `rebuild()`/`failures()`-shaped surface for these tables alone, and a
    `rebuild()` that cannot truncate tables it does not own.

    **This is also the read side of resumption.** `get` and `turns_for` are
    what `SocraticDialogueService` reads through when the live registry has
    dropped a dialogue, so a build that never constructs this does not merely
    serve an empty history list -- it makes every resumed dialogue start over
    while telling the reader it continued.
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
        self._dialogues: SocraticDialogueStore | None = None
        self._manager: SubscriptionManager | None = None
        self._subscription = None
        self._checkpoints: SQLCheckpointRepository | None = None
        self._dlq: SQLDLQRepository | None = None
        self._engine: AsyncEngine | None = None

    @property
    def projection_name(self) -> str:
        return SocraticDialogueProjection.__name__

    async def start(self) -> None:
        """Open the tables and start following the log.

        Same shape as `AskConversationRunner.start`, including touching the
        event store first so `projection_checkpoints` exists before anything
        reads it.
        """
        if self._manager is not None:
            return
        await self._store.current_position()
        engine = create_async_engine(f"sqlite+aiosqlite:///{self._db_path}")
        self._engine = engine
        self._checkpoints = SQLCheckpointRepository(engine)
        self._dlq = SQLDLQRepository(engine)
        self._dialogues = await SocraticDialogueStore.open(self._db_path, self._tracer)
        projection = SocraticDialogueProjection(
            self._dialogues, self._checkpoints, self._dlq, self._tracer
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
            raise RuntimeError(f"the socratic projection failed to start: {failures}")

    async def failures(self, limit: int = 100) -> list[DLQEntry]:
        if self._dlq is None:
            return []
        return await self._dlq.get_failed_events(
            projection_name=self.projection_name, limit=limit
        )

    def _started(self) -> SocraticDialogueStore:
        """The open store, or a refusal naming what was not done -- delegated
        rather than handed out, for `AskConversationRunner._started`'s reason."""
        if self._dialogues is None:
            raise RuntimeError("the socratic projection has not been started")
        return self._dialogues

    async def get(self, dialogue_id: UUID) -> SocraticDialogueRow | None:
        return await self._started().get(dialogue_id)

    async def for_project(self, project_id: UUID) -> list[SocraticDialogueRow]:
        return await self._started().for_project(project_id)

    async def turns_for(self, dialogue_id: UUID) -> list[SocraticTurnRow]:
        return await self._started().turns_for(dialogue_id)

    async def rebuild(self) -> None:
        """Truncate and replay.

        Allowed here, as on `AskConversationRunner.rebuild`, because every
        column in both tables is written from an event payload -- including
        `position`, which the projection derives in log order and therefore
        reproduces, and `pending_prompt`, which is derived from the newest
        turn's `prompt` in that same order.
        """
        if self._manager is None:
            raise RuntimeError("the socratic projection has not been started")
        await self._manager.stop()
        for entry in await self.failures(limit=1000):
            await self._dlq.mark_resolved(entry.id, resolved_by="rebuild")
        await self._checkpoints.reset_checkpoint(self.projection_name)
        await self._started().truncate()
        self._manager = None
        self._subscription = None
        await self._dialogues.close()
        self._dialogues = None
        await self.start()
        await self.caught_up()

    async def caught_up(self, timeout: float = 10.0) -> None:
        """Block until every `SocraticDialogue` event appended so far is in the
        tables.

        Scoped by aggregate type and started from what the subscription has
        already processed, **not** compared against the store's global end --
        `SessionSummaryRunner.caught_up` documents at length why that
        comparison runs its full timeout for a scoped subscription, and
        dialogues share a store with sessions, asks, the corpus and redstring's
        documents, any of which moves the end to a position this projection
        never reaches.

        No event-type filter: this projection handles *all four* event types on
        its aggregate, so the scope is already exact.

        **A dropped `@handles` reports here as a timeout, not as a missing
        row.** `SubscriptionConfig` leaves `event_types=None`, so
        `EventFilter.from_subscriber` derives the filter from the projection's
        `@handles` set -- remove one and that event is never delivered, so
        `last_processed_position` never advances past it while this method
        keeps reading it back as remaining, for the full timeout. The
        diagnostic then names this method rather than the handler that went
        missing. Measured on 2026-08-17;
        `test_a_dialogue_whose_start_nothing_handles_is_silently_empty` is the
        test that had to work around it, and its docstring carries the detail.

        This shape is copied verbatim from `AskConversationRunner.caught_up`,
        so the sibling has the same property. Left alone deliberately:
        diverging one runner from the established shape for this alone buys
        a better error message and costs a difference nobody expects.
        """
        if self._manager is None:
            return
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            remaining = await collect(
                self._store.read_all(
                    from_position=self._subscription.last_processed_position,
                    options=FeedReadOptions(aggregate_type=SocraticDialogue.aggregate_type),
                )
            )
            if not remaining:
                return
            await asyncio.sleep(0.01)
        raise TimeoutError(
            f"the socratic projection did not consume every "
            f"{SocraticDialogue.aggregate_type} event within {timeout}s"
        )

    async def stop(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
            self._manager = None
            self._subscription = None
        if self._dialogues is not None:
            await self._dialogues.close()
            self._dialogues = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None


class AuthoringRunRow(ReadModel):
    """One course-authoring run. `id` is the run id.

    The aggregate id itself with no `uuid5` over it, for `AskConversationRow`'s
    reason: the run id is minted by the server and handed straight back on the
    202, so deriving a second one would give the catch-up route a key nothing
    ever returned.

    **One table, not two, and `authored` holds pairs.** The neighbouring
    two-table stores exist because something queries the child rows on their
    own -- a conversation's turns, a class's members. Nothing queries one
    authoring target: every read here is "the whole run", because the frame the
    browser renders is the whole run. So a target table would buy an index for
    a query nobody issues and cost a second write per target.

    Pairs rather than parallel `completed`/`sessions` lists, even though the
    wire frame carries them parallel: `courseLinks` in the browser has to
    defend against a length mismatch between those two, and a store that cannot
    produce one is better than a store that documents what to do about it. The
    frame is built by unzipping this, which makes the two arrays equal in
    length by construction rather than by care.

    **No `current` column, deliberately.** Which area is in hand right now is
    process state -- see `course_authoring_run.py` -- and a stored one would
    outlive the process driving it and assert that work is in progress when
    nothing is doing it.

    **No `settled_at` column either.** `last()` orders by `started_at`, and a
    nullable datetime that only three of five statuses ever fill would be a
    column read by nothing. The settling *time* is on the log if it is ever
    wanted; what a reader needs here is the settling *status*.
    """

    __table_name__ = "authoring_runs"

    project_id: UUID
    kind: str = ""
    status: str = "running"
    started_at: datetime
    targets: list[str] = Field(default_factory=list)
    authored: list[dict] = Field(default_factory=list)
    """`[{"target": ..., "session_id": ...}]`, in the order the run wrote them.

    `session_id` is the load-bearing half and the reason this table exists: the
    course markdown lives in that session's event-sourced workspace, and
    nothing else on the log records which session holds which area."""
    failures: list[dict] = Field(default_factory=list)
    """`[{"target": ..., "detail": ...}]`. Per target, because a run that wrote
    seven of eight is `done` with one failure listed."""

    @field_validator("targets", "authored", "failures", mode="before")
    @classmethod
    def _decode_json_list(cls, value: object) -> object:
        """Accept the JSON text SQLite hands back for a list column -- see
        `SessionSummaryRow._decode_json_list` on the asymmetry this hides."""
        if isinstance(value, str):
            return json.loads(value)
        return value


class AuthoringRunStore:
    """The `authoring_runs` table and the connection it owns.

    Every column is written from an event payload, so `rebuild()` may truncate
    -- unlike `EntityDefinitionStore`, nothing else writes here.
    """

    def __init__(
        self, connection: aiosqlite.Connection, rows: ReadModelRepository[AuthoringRunRow]
    ) -> None:
        self._connection = connection
        self._rows = rows

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> "AuthoringRunStore":
        connection = await aiosqlite.connect(db_path)
        await apply_schema(connection, AuthoringRunRow)
        # `apply_schema` reconciles columns and not indexes -- the same note as
        # on `EntityDefinitionStore.open`. The only read that is not by id is
        # `latest_for_project`, which runs on every open of the curriculum
        # pane; unindexed it would scan every run every project has ever made.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_authoring_runs_project "
            f"ON {AuthoringRunRow.table_name()}(project_id, started_at)"
        )
        await connection.commit()
        return cls(connection, SQLiteReadModelRepository(connection, AuthoringRunRow, tracer))

    async def start(
        self,
        run_id: UUID,
        project_id: UUID,
        *,
        kind: str,
        targets: list[str],
        started_at: datetime,
    ) -> None:
        await self._rows.save(
            AuthoringRunRow(
                id=run_id,
                project_id=project_id,
                kind=kind,
                started_at=started_at,
                targets=targets,
            )
        )

    async def record_authored(self, run_id: UUID, target: str, session_id: UUID) -> None:
        """Append one target's session, unless this target is already recorded.

        The existence check is what makes redelivery safe. A subscription that
        is restarted from a checkpoint written before its last handler returned
        replays that event, and an unconditional append would put the same
        course in the list twice -- which reads, on every surface, as a run that
        authored more targets than it had.
        """
        row = await self._rows.get(run_id)
        if row is None:
            return
        if any(entry.get("target") == target for entry in row.authored):
            return
        row.authored = [*row.authored, {"target": target, "session_id": str(session_id)}]
        await self._rows.save(row)

    async def record_failure(self, run_id: UUID, target: str, detail: str) -> None:
        """Append one target's failure, unless this target already has one.

        Deduplicated on `target` for `record_authored`'s reason. A target can
        only fail once per run -- the driving loop moves on after it -- so the
        target alone is the identity, and the detail of a redelivered event is
        by construction the same string.
        """
        row = await self._rows.get(run_id)
        if row is None:
            return
        if any(entry.get("target") == target for entry in row.failures):
            return
        row.failures = [*row.failures, {"target": target, "detail": detail}]
        await self._rows.save(row)

    async def settle(self, run_id: UUID, status: str) -> None:
        row = await self._rows.get(run_id)
        if row is None:
            return
        row.status = status
        await self._rows.save(row)

    async def get(self, run_id: UUID) -> AuthoringRunRow | None:
        return await self._rows.get(run_id)

    async def recent_for_project(
        self, project_id: UUID, limit: int = 2
    ) -> list[AuthoringRunRow]:
        """This project's runs, most recently started first.

        Ordered by `started_at` and not by insertion order, for
        `AskTurnRow.position`'s reason: a `rebuild()` truncates and replays and
        is free to insert rows in a different physical order, so a read that
        leaned on the table's order would answer correctly until the first
        rebuild and differently after it.

        The default limit is 2 because that is what the one caller needs:
        `AuthoringActivity.last` wants the newest run that is *not* the one it
        is currently driving, and at most one run per project is ever in
        flight -- so the second row is the deepest it can have to look.
        """
        return await self._rows.find(
            Query(
                filters=[Filter(field="project_id", operator="eq", value=str(project_id))],
                order_by="started_at",
                order_direction="desc",
                limit=limit,
            )
        )

    async def latest_for_project(self, project_id: UUID) -> AuthoringRunRow | None:
        """This project's most recently started run, or None if it has had none."""
        found = await self.recent_for_project(project_id, limit=1)
        return found[0] if found else None

    async def authored_session_for(self, project_id: UUID, target: str) -> UUID | None:
        """Which session holds `target`'s course markdown, or None if no run
        has ever authored it.

        Scans newest `started_at` first and returns the first match, so a
        target authored twice resolves to the session its *current* course
        actually lives in. `recent_for_project`'s own default `limit=2` is
        wrong here and is not reused: that default is tuned for
        `AuthoringActivity.last`, which only ever needs the run before the one
        in flight, but a course's session can have been written many runs
        ago -- inheriting 2 would make the link vanish the moment a third
        later run happens, indistinguishable from the course never having
        been authored. 200 is arbitrary but generous against any project's
        real run count.

        Filtered in Python, not SQL: `authored` is a JSON column, and a
        `json_each` query would tie this read to SQLite in a file whose other
        reads (`Query`/`Filter`) are backend-agnostic.
        """
        for row in await self.recent_for_project(project_id, limit=200):
            for entry in row.authored:
                if entry.get("target") == target:
                    return UUID(entry["session_id"])
        return None

    async def truncate(self) -> None:
        await self._connection.execute(f"DELETE FROM {AuthoringRunRow.table_name()}")
        await self._connection.commit()

    async def close(self) -> None:
        await self._connection.close()


class AuthoringRunProjection(DeclarativeProjection):
    """Writes course-authoring runs into the table above.

    Nothing else writes it, which is what lets `rebuild()` truncate.
    """

    def __init__(
        self,
        runs: AuthoringRunStore,
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._runs = runs
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(CourseAuthoringRunStarted)
    async def _on_started(self, event: CourseAuthoringRunStarted) -> None:
        await self._runs.start(
            event.aggregate_id,
            event.project_id,
            kind=event.kind,
            targets=list(event.targets),
            started_at=event.started_at,
        )

    @handles(CourseAuthored)
    async def _on_authored(self, event: CourseAuthored) -> None:
        await self._runs.record_authored(event.aggregate_id, event.target, event.session_id)

    @handles(CourseAuthoringFailed)
    async def _on_failed(self, event: CourseAuthoringFailed) -> None:
        await self._runs.record_failure(event.aggregate_id, event.target, event.detail)

    @handles(CourseAuthoringRunSettled)
    async def _on_settled(self, event: CourseAuthoringRunSettled) -> None:
        await self._runs.settle(event.aggregate_id, event.status)


class AuthoringRunRunner:
    """Keeps the authoring-run table following the log, and answers from it.

    A tenth runner, for the reasons `CorpusRunner`'s docstring gives for being
    a second: a `rebuild()`/`failures()`-shaped surface for this table alone,
    and a `rebuild()` that cannot truncate a table it does not own.

    Its failure mode if never constructed is `AskConversationRunner`'s and
    worse: an authoring run appends whether or not anything is following, so a
    build missing it answers every catch-up read with "no run has ever
    happened" while the courses sit on the log unfindable -- which is the exact
    bug this whole aggregate was added to fix, restored by an unwired line.
    `test_an_authoring_run_survives_a_restart.py` is what fails.
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
        self._runs: AuthoringRunStore | None = None
        self._manager: SubscriptionManager | None = None
        self._subscription = None
        self._checkpoints: SQLCheckpointRepository | None = None
        self._dlq: SQLDLQRepository | None = None
        self._engine: AsyncEngine | None = None

    @property
    def projection_name(self) -> str:
        return AuthoringRunProjection.__name__

    async def start(self) -> None:
        """Open the table and start following the log.

        Same shape as `AskConversationRunner.start`, including touching the
        event store first so `projection_checkpoints` exists before anything
        reads it.
        """
        if self._manager is not None:
            return
        await self._store.current_position()
        engine = create_async_engine(f"sqlite+aiosqlite:///{self._db_path}")
        self._engine = engine
        self._checkpoints = SQLCheckpointRepository(engine)
        self._dlq = SQLDLQRepository(engine)
        self._runs = await AuthoringRunStore.open(self._db_path, self._tracer)
        projection = AuthoringRunProjection(
            self._runs, self._checkpoints, self._dlq, self._tracer
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
            raise RuntimeError(f"the authoring projection failed to start: {failures}")

    async def failures(self, limit: int = 100) -> list[DLQEntry]:
        if self._dlq is None:
            return []
        return await self._dlq.get_failed_events(
            projection_name=self.projection_name, limit=limit
        )

    def _started(self) -> AuthoringRunStore:
        if self._runs is None:
            raise RuntimeError("the authoring projection has not been started")
        return self._runs

    async def get(self, run_id: UUID) -> AuthoringRunRow | None:
        return await self._started().get(run_id)

    async def latest_for_project(self, project_id: UUID) -> AuthoringRunRow | None:
        return await self._started().latest_for_project(project_id)

    async def recent_for_project(
        self, project_id: UUID, limit: int = 2
    ) -> list[AuthoringRunRow]:
        return await self._started().recent_for_project(project_id, limit)

    async def authored_session_for(self, project_id: UUID, target: str) -> UUID | None:
        return await self._started().authored_session_for(project_id, target)

    async def rebuild(self) -> None:
        """Truncate and replay. Allowed here for `AskConversationRunner`'s
        reason: every column comes from an event payload."""
        if self._manager is None:
            raise RuntimeError("the authoring projection has not been started")
        await self._manager.stop()
        for entry in await self.failures(limit=1000):
            await self._dlq.mark_resolved(entry.id, resolved_by="rebuild")
        await self._checkpoints.reset_checkpoint(self.projection_name)
        await self._started().truncate()
        self._manager = None
        self._subscription = None
        await self._runs.close()
        self._runs = None
        await self.start()
        await self.caught_up()

    async def caught_up(self, timeout: float = 10.0) -> None:
        """Block until every `CourseAuthoringRun` event appended so far is in
        the table.

        Scoped by aggregate type and started from what the subscription has
        already processed, **not** compared against the store's global end --
        `SessionSummaryRunner.caught_up` documents at length why that
        comparison runs its full timeout for a scoped subscription, and
        authoring runs share a store with sessions, the corpus and redstring's
        documents, any of which moves the end to a position this projection
        never reaches.

        No event-type filter: this projection handles every event type on its
        aggregate, so the scope is already exact.
        """
        if self._manager is None:
            return
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            remaining = await collect(
                self._store.read_all(
                    from_position=self._subscription.last_processed_position,
                    options=FeedReadOptions(
                        aggregate_type=COURSE_AUTHORING_RUN_AGGREGATE_TYPE
                    ),
                )
            )
            if not remaining:
                return
            await asyncio.sleep(0.01)
        raise TimeoutError(
            f"the authoring projection did not consume every "
            f"{COURSE_AUTHORING_RUN_AGGREGATE_TYPE} event within {timeout}s"
        )

    async def stop(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
            self._manager = None
            self._subscription = None
        if self._runs is not None:
            await self._runs.close()
            self._runs = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None


class ArtRow(ReadModel):
    """One piece of art in the global library.

    `art_id` is `uuid4`, minted once by the writer and never derived from a
    slug or any other input -- unlike every id in this module built through
    `uuid5(CATALOG_NAMESPACE, ...)`. Those are deliberately *derivable*, so
    that looking a row up again needs no index: give the same
    `(project_id, slug)` and you get the same id back. Art is the opposite
    case on purpose. The whole point of a library (increment 3's "Why") is
    that one picture is reusable across many candidates and many projects --
    a derived id would tie a picture to whichever slug happened to generate
    it first, and every other card that could reuse it would need its own
    copy of the same bytes with a different id instead of one row with
    `uses` counted up. `CandidateArtRow` below is the derivable mapping;
    this is the thing it points at.
    """

    __table_name__ = "art_library"

    svg: str
    """Sanitised before this is ever constructed -- see `ArtStore.put`'s
    docstring for why storage does not re-check it and the serving route
    does."""
    description: str
    """What the picture depicts, in words. This is the search key the
    sibling task's lexical search reads -- token overlap against a
    candidate's title and anchor names -- not a caption shown to a person."""
    tags: list[str] = Field(default_factory=list)
    palette: str = ""
    """The category key this was drawn for (`"work"`, `"person"`, ...), or
    `""` for a piece with no category affinity. Matches `SeededArtProvider`'s
    `CategoryKey` vocabulary but is stored as a plain string rather than that
    type -- this table outlives any one category scheme, and a string needs
    no migration if the scheme's vocabulary grows."""
    # `created_at` is not redeclared here -- `ReadModel` already carries it
    # as a `datetime` with a UTC default, and every other row in this module
    # that wants a distinctly-named generation timestamp (`generated_at` on
    # `CourseBlurbRow`/`CourseOutlineRow`) declares a second field rather
    # than fighting the base one. The spec's `created_at: datetime` is that
    # base field, not a second one.
    source: str
    """`"generated"` or `"seeded"` -- literal strings rather than an enum for
    the same reason similarly-shaped fields elsewhere in this module are
    plain strings: a read model's job is to be read by a query, and a query
    does not care whether Python enforces the vocabulary, only that the
    value on disk is one of the two."""
    uses: int = 0
    """How many `CandidateArtRow`s currently point at this. Bumped by
    `increment_uses`, not recomputed by counting -- see that method's
    docstring for why."""

    @field_validator("tags", mode="before")
    @classmethod
    def _decode_json_list(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value


class ArtStore:
    """The art library table and the connection it owns.

    A cache, not a projection, for `CourseBlurbStore`'s exact reason: nothing
    on the event log describes a piece of art -- there is no `ArtGenerated`
    event this table replays -- so there is nothing for a projection to
    fold. The generator (a sibling task) calls `put` directly after a
    sanitised SVG comes back from the model; `SeededArtProvider`'s
    placeholder never reaches this table at all, because it is computed
    per-request from the slug rather than stored.
    """

    def __init__(self, connection: aiosqlite.Connection, rows: ReadModelRepository) -> None:
        self._connection = connection
        self._rows = rows

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> "ArtStore":
        connection = await aiosqlite.connect(db_path)
        await apply_schema(connection, ArtRow)
        # `apply_schema` reconciles columns, not indexes -- the same note
        # every other store in this module carries. No index beyond the
        # primary key: `all()` is a full-table scan by design (the sibling
        # task's search scores every row; the library is small enough for
        # that to be fine, and the increment-3 spec's search section says why
        # an index meant to speed that up is premature before the corpus is
        # large enough to measure).
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, ArtRow, tracer)
        return cls(connection, rows)

    async def get(self, art_id: UUID) -> ArtRow | None:
        return await self._rows.get(art_id)

    async def put(
        self,
        art_id: UUID,
        svg: str,
        description: str,
        tags: list[str],
        palette: str,
        created_at: datetime,
        source: str,
        uses: int = 0,
    ) -> None:
        """Store a piece of art under an id the caller already minted --
        unlike every other `put` in this module, this does not compute the
        row's `id` itself, because it is `uuid4` and has no derivation to
        repeat (see `ArtRow`'s own docstring).

        Takes already-sanitised `svg`. Sanitising here as well would mean
        every caller pays the parse cost a second time for a value the
        generator already validated once before asking to store it; the
        route that serves this back out re-sanitises instead (see
        `app.py`), which is where the cost of *not* re-checking here would
        actually surface to a browser.
        """
        await self._rows.save(
            ArtRow(
                id=art_id,
                svg=svg,
                description=description,
                tags=tags,
                palette=palette,
                created_at=created_at,
                source=source,
                uses=uses,
            )
        )

    async def all(self) -> list[ArtRow]:
        """Every row, for the sibling task's search to score. `find()` with
        no query is the repository's own "everything" case. See `open`'s
        docstring for why this is a full scan rather than an indexed query."""
        return await self._rows.find()

    async def increment_uses(self, art_id: UUID) -> None:
        """Bumps `uses` by reading the current row and writing it back,
        rather than an atomic `UPDATE ... SET uses = uses + 1` the
        repository layer does not expose. `ReadModelRepository` here is a
        read/save abstraction over arbitrary rows, not a query builder, so
        this is the same read-modify-write shape `apply_schema`'s own
        column reconciliation uses. Fine for this table's write pattern:
        one assignment per candidate, never concurrent increments racing on
        the same row within a single sweep (increment 3's sweep is one
        candidate at a time, per the spec)."""
        row = await self._rows.get(art_id)
        if row is None:
            return
        row.uses += 1
        await self._rows.save(row)

    async def close(self) -> None:
        await self._connection.close()


class CandidateArtRow(ReadModel):
    """Which piece of art a candidate is assigned, keyed by `(project_id,
    slug)` exactly like `CourseBlurbRow`/`CourseOutlineRow` -- so that the
    decision (increment 3's "Assignment is a decision") is made once and
    read back the same way every subsequent request, rather than
    recomputed.
    """

    __table_name__ = "candidate_art"

    project_id: UUID
    slug: str
    art_id: UUID

    @staticmethod
    def row_id(project_id: UUID, slug: str) -> UUID:
        # The `art:` prefix keeps this id from colliding with
        # `CourseOutlineRow.row_id`, `CourseBlurbRow.row_id` and
        # `CatalogFeatureRow.row_id`, which share `CATALOG_NAMESPACE` and
        # hash the same `{project_id}:{slug}` pair with their own (or no)
        # prefix -- `outline:`, `blurb:`, `course:` and none, respectively.
        return uuid5(CATALOG_NAMESPACE, f"art:{project_id}:{slug}")


class CandidateArtStore:
    """The candidate-to-art assignment table and the connection it owns.

    No projection, for `CourseBlurbStore`'s reason: nothing on the event log
    describes an assignment. The sibling task's `LibraryArtProvider` calls
    `put` directly the first time it assigns a candidate a picture, whether
    by search match or by generation.
    """

    def __init__(self, connection: aiosqlite.Connection, rows: ReadModelRepository) -> None:
        self._connection = connection
        self._rows = rows

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> "CandidateArtStore":
        connection = await aiosqlite.connect(db_path)
        await apply_schema(connection, CandidateArtRow)
        # `apply_schema` reconciles columns, not indexes -- the same note
        # `CourseBlurbStore.open` carries, for the same reason: every read
        # here is project-scoped.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_candidate_art_project "
            f"ON {CandidateArtRow.table_name()}(project_id)"
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, CandidateArtRow, tracer)
        return cls(connection, rows)

    async def get(self, project_id: UUID, slug: str) -> CandidateArtRow | None:
        """The assigned art, or None if this candidate has never been
        assigned one. `row.project_id != project_id` is checked for
        `CourseBlurbStore.get`'s exact reason -- unreachable through this
        class's own `row_id`, but a row reached by id alone makes no claim
        about which project asked."""
        row = await self._rows.get(CandidateArtRow.row_id(project_id, slug))
        if row is None or row.project_id != project_id:
            return None
        return row

    async def put(self, project_id: UUID, slug: str, art_id: UUID) -> None:
        """Assign art to a candidate, superseding whatever was assigned
        before for this slug -- `save` writes by id, and `row_id` is stable
        per `(project_id, slug)`, so a rewrite replaces rather than
        duplicates."""
        await self._rows.save(
            CandidateArtRow(
                id=CandidateArtRow.row_id(project_id, slug),
                project_id=project_id,
                slug=slug,
                art_id=art_id,
            )
        )

    async def close(self) -> None:
        await self._connection.close()
