"""SQLite-backed implementation of the `SessionRepository` port."""

import asyncio
from uuid import UUID

from eventsource import (
    DomainEvent,
    FeedReadOptions,
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

from research_team.infrastructure.persistence.aggregate_repositories import (
    SNAPSHOT_THRESHOLD as SNAPSHOT_THRESHOLD,
)
from research_team.infrastructure.persistence.aggregate_repositories import (
    build_aggregate_repository as build_aggregate_repository,
)
from research_team.infrastructure.persistence.aggregate_repositories import (
    build_ask_conversation_repository as build_ask_conversation_repository,
)
from research_team.infrastructure.persistence.aggregate_repositories import (
    build_corpus_repository as build_corpus_repository,
)
from research_team.infrastructure.persistence.aggregate_repositories import (
    build_course_authoring_run_repository as build_course_authoring_run_repository,
)
from research_team.infrastructure.persistence.aggregate_repositories import (
    build_course_repository as build_course_repository,
)
from research_team.infrastructure.persistence.aggregate_repositories import (
    build_judgements_repository as build_judgements_repository,
)
from research_team.infrastructure.persistence.aggregate_repositories import (
    build_learner_progress_repository as build_learner_progress_repository,
)
from research_team.infrastructure.persistence.aggregate_repositories import (
    build_project_repository as build_project_repository,
)
from research_team.infrastructure.persistence.aggregate_repositories import (
    build_research_run_repository as build_research_run_repository,
)
from research_team.infrastructure.persistence.aggregate_repositories import (
    build_socratic_dialogue_repository as build_socratic_dialogue_repository,
)
from research_team.infrastructure.persistence.aggregate_repositories import (
    build_topic_repository as build_topic_repository,
)
from research_team.infrastructure.persistence.event_feed_policy import (
    FEED_AGGREGATE_TYPES as FEED_AGGREGATE_TYPES,
)
from research_team.infrastructure.persistence.event_feed_policy import (
    KNOWLEDGE_CATEGORIES as KNOWLEDGE_CATEGORIES,
)
from research_team.infrastructure.persistence.event_feed_policy import (
    UNROUTED_AGGREGATE_TYPES as UNROUTED_AGGREGATE_TYPES,
)
from research_team.platform.shared.ports import FeedEntry
from research_team.session.domain import Session
from research_team.tenancy.domain import Project

__all__ = [
    "FEED_AGGREGATE_TYPES",
    "KNOWLEDGE_CATEGORIES",
    "SNAPSHOT_THRESHOLD",
    "UNROUTED_AGGREGATE_TYPES",
    "EventStoreSessionRepository",
    "build_aggregate_repository",
    "build_ask_conversation_repository",
    "build_corpus_repository",
    "build_course_authoring_run_repository",
    "build_course_repository",
    "build_judgements_repository",
    "build_learner_progress_repository",
    "build_project_repository",
    "build_research_run_repository",
    "build_socratic_dialogue_repository",
    "build_topic_repository",
]


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
        aggregates: AggregateRepository[Session],
        publisher: InMemoryEventBus | None = None,
        snapshot_store: SQLiteSnapshotStore | None = None,
    ) -> None:
        self._store = store
        self._aggregates = aggregates
        self._publisher = publisher
        self._snapshot_store = snapshot_store
        self._projects = build_project_repository(store, publisher, snapshot_store)
        self._appended = asyncio.Event()
        if publisher is not None:
            publisher.subscribe_to_all_events(self._on_published)

    @classmethod
    def open(cls, db_path: str) -> "EventStoreSessionRepository":
        store = SQLiteEventStore(db_path)
        publisher = InMemoryEventBus()
        snapshot_store = SQLiteSnapshotStore(db_path)
        aggregates = build_aggregate_repository(
            store, publisher, snapshot_store=snapshot_store
        )
        return cls(store, aggregates, publisher, snapshot_store=snapshot_store)

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
    def snapshot_store(self) -> SQLiteSnapshotStore | None:
        """The snapshot store this repository's aggregates use, if any.

        Exposed so a collaborator that needs one of its own -- the knowledge
        graph's consolidator, at composition -- reuses this one instead of
        opening a second `SQLiteSnapshotStore` against the same file. A second
        instance would spin up its own non-daemon aiosqlite worker thread that
        nothing closes (BACKLOG B5).

        Typed optional because the constructor accepts `None` -- a repository
        assembled by hand, as some tests do, need not supply one. `open()`,
        the only path composition uses, always builds and passes one, so for
        every repository composition sees this is never `None`; the type
        stays honest about the constructor rather than the narrower guarantee
        one particular factory happens to provide.
        """
        return self._snapshot_store

    @property
    def publisher(self) -> InMemoryEventBus | None:
        """The bus saves are announced on, for subscribers that want live events."""
        return self._publisher

    @property
    def projects(self) -> AggregateRepository[Project]:
        """The `Project` aggregate repository, over this same log and file.

        Exposed so a caller -- the REPL's `/project new` -- can `create_new`
        and `save` a project without opening a second connection or a second
        snapshot store against the same database.
        """
        return self._projects

    async def list_projects(self) -> list[tuple[UUID, str]]:
        """Every project's id and name, from the creation events.

        Reads the `Project` category directly rather than going through
        `read_since`/`read_all`: that path is filtered to the aggregate types
        a live subscriber can place (this store is shared with `Project` and
        redstring's own streams), so listing projects needs its own read
        rather than a weakened feed filter.

        Deleted projects are left out. Deletion is a tombstone event on the
        same stream rather than a removal, so the creation event is still
        there, and filtering here is what makes "deleted" mean "gone" to
        every caller that lists -- including the duplicate-name check, which
        is why a deleted project's name becomes free to reuse.
        """
        envelopes = await collect(self._store.read_category("Project"))
        deleted = {
            envelope.event.aggregate_id
            for envelope in envelopes
            if type(envelope.event).__name__ == "ProjectDeleted"
        }
        return [
            (envelope.event.aggregate_id, envelope.event.name)
            for envelope in envelopes
            if type(envelope.event).__name__ == "ProjectCreated"
            and envelope.event.aggregate_id not in deleted
        ]

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

    def create(self, session_id: UUID) -> Session:
        return self._aggregates.create_new(session_id)

    async def load(self, session_id: UUID) -> Session:
        return await self._aggregates.load(session_id)

    async def save(self, session: Session) -> None:
        await self._aggregates.save(session)

    async def events_for(self, session_id: UUID) -> list[DomainEvent]:
        stream = StreamId(session_id, Session.aggregate_type)
        return [envelope.event for envelope in await collect(self._store.read_stream(stream))]

    # ---- the EventFeed port ----

    async def latest_position(self) -> object | None:
        return await self._store.current_position()

    async def read_since(self, position: object | None) -> list[FeedEntry]:
        """What the research page and the session views watch, since `position`.

        Scoped by aggregate type rather than taking the whole feed. This store
        is shared, and it holds streams belonging to aggregates nothing
        subscribing here can place -- `ResearchRun` and `LearnerProgress`
        among them. Unscoped, every one of them would arrive as a `FeedEntry`
        addressed to something no subscriber knows how to route. What is
        admitted is `FEED_AGGREGATE_TYPES` and what is held back is
        `UNROUTED_AGGREGATE_TYPES`; both are named above, and a type in
        neither fails a test.

        This docstring named `Project` among the unplaceable until the fix
        below, and it
        was wrong twice over: the course page has always had a rail to move,
        and the docstring below already said a live subscriber could place
        one. A comment describing a live path that carries nothing is the
        recurring accompaniment to this bug, not an incidental detail.

        The scoping is `FeedReadOptions.aggregate_type` (eventsource 0.12),
        which the SQLite adapter pushes into the same query that already
        handles `from_position`. It used to be a comprehension filter here,
        which read the whole feed to discard most of it -- forced, because
        before 0.12 the filter had nowhere else to go.

        **Topics are read as well as sessions, and that is the fix for a
        research page that only showed new topics after a reload.** `open_topic`
        appends to this same log, and both `seeding.py` and `ResearchView`
        already say in their own comments that a client sees new topics by
        invalidating on those frames -- but the filter above admitted only
        `Session`, so no topic event has ever reached the SSE feed and
        neither claim held. A test that saves a `Topic` and asserts a feed
        entry for it is what would have failed.

        **redstring's two categories are read as well, and that is the fix for
        a graph pane that only showed new entities after a reload.** They are
        the same case as `Topic` one layer out: an extraction appends
        `DocumentExtracted` here, and the drawing on the research page *is*
        what that event added, so a feed that filtered them out left the only
        live signal the pane could have had unreachable. Their aggregate ids
        are a document's and a tenant's rather than a session's, which is why
        `_sse` addresses the resulting frame by `tenant_id` and never by
        `aggregate_id`.

        **`Corpus` is read for the documents pane, which had no live path at
        all.** It is a separate admission from the two above even though one
        ingest moves both, because a document is stored *before* it is
        extracted and an extraction that fails emits nothing on redstring's
        streams -- so a pane fed by graph frames would silently drop exactly
        the sources whose failure a reader needs to see listed.

        **`Project` is read for the project page, which had no live path at
        all.** Its events are appended here and the page is what they moved, so
        a change made while a tab was open reached the browser through nothing
        and the page only moved on a reload. It is the same shape as `Topic`,
        the graph and `Corpus` before it -- the fourth time -- which is why
        `FEED_AGGREGATE_TYPES` and `UNROUTED_AGGREGATE_TYPES` now exist instead
        of a literal here.

        One admission covers the whole aggregate rather than one event class,
        and that is deliberate: the lifecycle events (`ProjectSessionJoined`,
        `ProjectTipAdvanced`, `ProjectDeleted`) move the holding-session link
        and the project list. Filtering to whichever event was reported would
        have fixed that symptom and left its siblings invisible until the next
        report.

        The redstring category names come from redstring rather than being
        spelled out
        here. This is the one module outside `infrastructure/knowledge/` that
        imports it, and the import is the point: redstring is pre-1.0 with a
        no-shim policy, so a renamed category should be an `ImportError` at
        startup rather than a feed that silently reads nothing and a pane that
        silently stops updating -- which is exactly the failure this method
        already shipped once.

        One read per type rather than one unfiltered read, because the filter
        is what keeps the categories nobody can route out; merged by position
        afterwards, which is safe because positions are totally ordered within
        one store and every read starts from the same cursor. Five indexed
        queries per poll is the price, up from two, against an unfiltered read
        that would carry the same document events plus everything else.

        The cost that is not the query count: `DocumentExtracted` carries every
        entity and relationship the run found, so this deserialises a whole
        extraction's payload in order to emit a frame that says only "the graph
        moved". Measured against nothing -- it is reasoned, not benchmarked --
        and it is the price of the log being the signal. See the commit for the
        projection-into-our-own-event alternative and why it was not taken.
        """
        envelopes = [
            envelope
            for aggregate_type in FEED_AGGREGATE_TYPES
            for envelope in await collect(
                self._store.read_all(
                    from_position=position,
                    options=FeedReadOptions(aggregate_type=aggregate_type),
                )
            )
        ]
        return [
            FeedEntry(
                aggregate_id=envelope.event.aggregate_id,
                aggregate_type=envelope.event.aggregate_type,
                event=envelope.event,
                position=envelope.position,
            )
            for envelope in sorted(envelopes, key=lambda envelope: envelope.position)
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
        if self._snapshot_store is not None:
            # Required since eventsource 0.12: the snapshot store holds one
            # connection for its lifetime, backed by a non-daemon aiosqlite
            # thread that keeps the interpreter alive until it is closed.
            # Nothing in the library closes it for us.
            await self._snapshot_store.close()
        await self._store.close()
