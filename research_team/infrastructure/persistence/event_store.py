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
from redstring.events.streams import CONSOLIDATION_CATEGORY, DOCUMENT_CATEGORY

from research_team.application import FeedEntry
from research_team.domain import Corpus, EntityJudgements, Project, Session
from research_team.domain.ask_conversation import AskConversation
from research_team.domain.learner import LearnerProgress
from research_team.domain.media_proposals import MediaProposals
from research_team.domain.ontology import ONTOLOGY_AGGREGATE_TYPE
from research_team.domain.research_run import ResearchRun
from research_team.domain.socratic_dialogue import SocraticDialogue
from research_team.domain.topic import Topic

SNAPSHOT_THRESHOLD = 50

KNOWLEDGE_CATEGORIES = (DOCUMENT_CATEGORY, CONSOLIDATION_CATEGORY)
"""redstring's stream categories, as they appear on this store's feed.

Named here rather than at each use because two places have to agree on it and
they are in different layers: `read_since` decides which categories reach the
feed, and `_sse` decides how a frame from one is addressed. Split, a third
category added upstream could be read and then rendered as a session -- which
is a mislabelled frame rather than an absent one, and the harder of the two to
notice.
"""

FEED_AGGREGATE_TYPES = (
    Session.aggregate_type,
    Project.aggregate_type,
    Topic.aggregate_type,
    Corpus.aggregate_type,
    MediaProposals.aggregate_type,
    *KNOWLEDGE_CATEGORIES,
)
"""Every aggregate type `read_since` admits to the live feed.

A module constant rather than a tuple literal inside `read_since` because it
is now read twice: by the query loop, and by
`test_every_aggregate_type_is_routed_or_deliberately_not`, which is the guard
against this list falling behind the domain a fourth time. The guard can only
compare against a list it can see.

Order is presentation, not behaviour -- `read_since` sorts by position after
merging -- so it is written to match the order `_sse` tests the types in.

`MediaProposals` is routed because a proposal's state changes without any
user action in the tab. Accepting one answers 202 immediately, and the
terminal state (`stored` or `failed`) arrives only after a download plus a
perception pass -- minutes, for an hour of audio. A pane that updated only on
reload would show an accepted proposal sitting in a working state forever,
which is precisely the defect BACKLOG.md B94 records for media rows during
transcription. Routing it is what makes the review pane's live state possible
at all.
"""

UNROUTED_AGGREGATE_TYPES = frozenset(
    {
        ResearchRun.aggregate_type,
        LearnerProgress.aggregate_type,
        EntityJudgements.aggregate_type,
        ONTOLOGY_AGGREGATE_TYPE,
        AskConversation.aggregate_type,
        SocraticDialogue.aggregate_type,
    }
)
"""Aggregate types deliberately kept off the feed, and the other half of the guard.

Being *absent* from `FEED_AGGREGATE_TYPES` is not a decision anybody wrote
down -- that is exactly how `Topic`, the graph, `Corpus` and `Project` each
went a release with a live path that carried nothing. Listing the exclusions
makes silence impossible: a new aggregate type is in one list or the other,
and the guard fails until somebody says which.

`ResearchRun` is off because the course page reads a run's state through
`/api/projects/{id}/run`, refreshed off the session frames a round already
emits -- its own frames would be a second signal for the same repaint. See
`useTreeRefresh`, which invalidates `allRuns` on log frames.

`LearnerProgress` is off because nothing renders it live: it is read on
opening a lesson and written by the reader who is already looking at it, so a
frame would arrive at the one client that does not need telling.

`EntityJudgements` is off because nothing renders a judgement. The events a
human's decision produces are consumed by consolidation, not by a view, and
what a viewer would actually want to see repaint is the *merge* that follows --
which is redstring's own event on the graph's stream, already routed. This is
the entry to revisit when the aliases panel lands (piece 3 of the entity-
judgements design): a panel listing what you have taught the project is a view
of these events, and then it belongs on the feed.

`Ontology` is off because the ontology view is a page a reader opens
deliberately and which reads its classes on open, not a pane that sits watching.
The pass that writes these events is queued through the same route a human just
pressed, so the one client that would be told is the one already waiting on the
202 it got back. The staleness this leaves is real and bounded: a pass finishing
while the view is open does not repaint it until a refresh. That is the same
trade `extraction_queue.py`'s docstring makes and states -- a frame type, a
pump, a `decodeFrame` case and a store cost more than they buy until somebody
is watching two tabs. Revisit when the ontology view becomes something left
open while a sweep runs across a project's documents, because then the missing
repaint is the whole point of having it open.

`AskConversation` is off for `LearnerProgress`'s exact reason: the asking
client is already receiving its answer through the ask's own stream -- the
generator that yields the turn back to the tab that asked it -- so a feed
frame would arrive at the one client that does not need telling. It costs a
second tab: a history pane open on the same project while another tab is
mid-conversation does not repaint, because nothing on that path reaches
`read_since`. Revisit when a history pane is actually built and is meant to
be left open while another tab asks -- the missing repaint only matters once
something is watching for it, the same condition `Ontology`'s paragraph
above names for its own pane.

`SocraticDialogue` is off for `AskConversation`'s reason and one more: the
only client that would repaint on a dialogue frame is the browser already
holding the SSE stream that produced it, so a feed frame would be a second
signal for a repaint that has already happened.

None is a *correctness* argument, and if any grows a pane the answer is
to move it into `FEED_AGGREGATE_TYPES` and give `_sse` a branch -- not to
widen this set.
"""


def build_project_repository(
    store: SQLiteEventStore,
    publisher: InMemoryEventBus | None = None,
    snapshot_store: SQLiteSnapshotStore | None = None,
) -> AggregateRepository[Project]:
    """Projects, over the same log and the same snapshot table as sessions.

    Unlike `build_aggregate_repository`, there is no fallback that constructs
    its own `SQLiteSnapshotStore` here: the only caller is
    `EventStoreSessionRepository`, which already has one open against this
    file (BACKLOG B5 -- a second instance leaks a non-daemon thread nothing
    closes), so this always takes it as given rather than repeating the
    choice of whether to build one.
    """
    return AggregateRepository(
        store,
        Project,
        event_publisher=publisher,
        snapshot_store=snapshot_store,
        snapshot_threshold=SNAPSHOT_THRESHOLD,
        snapshot_mode="background",
    )


def build_ask_conversation_repository(
    store: SQLiteEventStore,
    publisher: InMemoryEventBus | None = None,
) -> AggregateRepository[AskConversation]:
    """Persisted asks, over the same log as everything else.

    Published like its neighbours even though `AskConversation` is in
    `UNROUTED_AGGREGATE_TYPES`: publishing is what `read_since`'s local
    append flag watches, and the scoping decision is made there, once, rather
    than by half-wiring the bus here.

    **No snapshots, unlike `ResearchRun` and `Project`.** A conversation
    appends two events on its first turn and one per turn after, and the
    surface is a person typing -- a stream long enough for the threshold to
    matter is a chat of fifty questions, and the fold over it is a counter and
    two ids. The snapshot store is not even taken as an argument, so nobody
    reads its absence as an oversight. Revisit if `AskConversationState` ever
    grows the turns themselves rather than a count of them.
    """
    return AggregateRepository(store, AskConversation, event_publisher=publisher)


def build_socratic_dialogue_repository(
    store: SQLiteEventStore,
    publisher: InMemoryEventBus | None = None,
) -> AggregateRepository[SocraticDialogue]:
    """Guided dialogues, over the same log as everything else.

    Published like its neighbours even though `SocraticDialogue` is in
    `UNROUTED_AGGREGATE_TYPES`, for `build_ask_conversation_repository`'s
    reason: publishing is what `read_since`'s local append flag watches, and
    the scoping decision is made there rather than by half-wiring the bus here.

    **No snapshots, and this one is closer to the line than the ask's.**
    `SocraticDialogueState.observations` holds the observation texts rather
    than a count, so unlike `AskConversationState` this fold grows with the
    dialogue -- which is precisely the condition
    `build_ask_conversation_repository` names as the trigger to revisit. It is
    still the right call for the first release: a dialogue is a person typing,
    an observation is a sentence, and a stream long enough for the threshold to
    matter is a conversation nobody has had yet. Revisit when a dialogue can
    run unattended, which is the change that would make the length unbounded.
    """
    return AggregateRepository(store, SocraticDialogue, event_publisher=publisher)


def build_research_run_repository(
    store: SQLiteEventStore,
    publisher: InMemoryEventBus | None = None,
    snapshot_store: SQLiteSnapshotStore | None = None,
) -> AggregateRepository[ResearchRun]:
    """Autonomous runs, over the same log as the sessions whose turns they drive.

    Published like everything else, which is what puts a run's rounds on the
    live feed without a second channel: a browser watching a project sees
    `ResearchRoundStarted` arrive the same way it sees a turn's events.

    Snapshots at the usual threshold. A long run appends three events per
    round, so a fold is cheap for a while and not forever, and `ResearchRunState`
    holds counters and ids -- the one unbounded field is `topics_seen`, which
    is bounded in practice by `MAX_OPEN_TOPICS`.
    """
    return AggregateRepository(
        store,
        ResearchRun,
        event_publisher=publisher,
        snapshot_store=snapshot_store,
        snapshot_threshold=SNAPSHOT_THRESHOLD,
        snapshot_mode="background",
    )


def build_topic_repository(
    store: SQLiteEventStore,
    publisher: InMemoryEventBus | None = None,
    snapshot_store: SQLiteSnapshotStore | None = None,
) -> AggregateRepository[Topic]:
    """One topic, over the same log as everything else.

    Unlike `Corpus` and `Project`, a topic does *not* share the project's UUID:
    a project has many topics, so each gets its own id and carries
    `project_id` in its creation event. That is what makes the topic table's
    per-project reads a column lookup rather than a stream-id convention.

    Snapshots are on at the usual threshold, and are affordable for the same
    reason the corpus's are: `TopicState` holds counts, ids and statuses, never
    finding text. A fold that accumulated prose would put the whole research
    history into every snapshot.
    """
    return AggregateRepository(
        store,
        Topic,
        event_publisher=publisher,
        snapshot_store=snapshot_store,
        snapshot_threshold=SNAPSHOT_THRESHOLD,
        snapshot_mode="background",
    )


def build_corpus_repository(
    store: SQLiteEventStore,
    publisher: InMemoryEventBus | None = None,
    snapshot_store: SQLiteSnapshotStore | None = None,
) -> AggregateRepository[Corpus]:
    """A project's corpus, over the same log as its sessions and its project.

    Shares the project's UUID and is kept apart by `aggregate_type`, which the
    repository puts into the `StreamId` for us -- so the corpus of project P
    is addressed by P and nothing has to invent or store a second id.

    Snapshots are on, at the same threshold as everywhere else. That is only
    affordable because `CorpusState` holds no text (see `domain/corpus.py`);
    were the fold to keep the documents, each snapshot would be a copy of the
    whole corpus.
    """
    return AggregateRepository(
        store,
        Corpus,
        event_publisher=publisher,
        snapshot_store=snapshot_store,
        snapshot_threshold=SNAPSHOT_THRESHOLD,
        snapshot_mode="background",
    )


def build_judgements_repository(
    store: SQLiteEventStore,
    publisher: InMemoryEventBus | None = None,
    snapshot_store: SQLiteSnapshotStore | None = None,
) -> AggregateRepository[EntityJudgements]:
    """A project's entity judgements, over the same log as its corpus.

    Shares the project's UUID and is kept apart by `aggregate_type`, exactly as
    the corpus is, so nothing has to invent or store a third id.

    Snapshots are on at the house threshold. Affordable because the state holds
    only human-authored judgements -- a set that grows with decisions a person
    made, not with documents ingested.
    """
    return AggregateRepository(
        store,
        EntityJudgements,
        event_publisher=publisher,
        snapshot_store=snapshot_store,
        snapshot_threshold=SNAPSHOT_THRESHOLD,
        snapshot_mode="background",
    )


def build_learner_progress_repository(
    store: SQLiteEventStore,
    publisher: InMemoryEventBus | None = None,
    snapshot_store: SQLiteSnapshotStore | None = None,
) -> AggregateRepository[LearnerProgress]:
    """One learner's progress, over the same log as the session it belongs to.

    Shares the *session's* UUID, the way a corpus shares its project's, and is
    kept apart by `aggregate_type`. There is no user system (B18), so a session
    is the only identity in this codebase that means "one person working
    through this material" -- see `domain/learner.py` for why that is stated
    rather than assumed, and what has to change when authentication arrives.

    Snapshots are on at the usual threshold, and are affordable for the same
    reason the corpus's are: `LearnerProgressState` holds counts and flags, not
    the text of anything anyone typed.
    """
    return AggregateRepository(
        store,
        LearnerProgress,
        event_publisher=publisher,
        snapshot_store=snapshot_store,
        snapshot_threshold=SNAPSHOT_THRESHOLD,
        snapshot_mode="background",
    )


def build_aggregate_repository(
    store: SQLiteEventStore,
    publisher: InMemoryEventBus | None = None,
    *,
    snapshot_store: SQLiteSnapshotStore,
) -> AggregateRepository[Session]:
    """Sessions, over `store`, snapshotting into `snapshot_store`.

    `snapshot_store` is required rather than defaulted. It used to fall back to
    building its own, which was safe while `SQLiteSnapshotStore` opened a
    connection per operation and owned nothing. Since eventsource 0.12 it holds
    one connection for its lifetime and must be closed -- and a store built
    here is returned to nobody, so nothing can close it. The old B5 note had
    this the other way round: the reason not to build one here was that a
    second instance leaked. The reason now is that *any* instance built here
    leaks, because this function does not hand it back.
    """
    return AggregateRepository(
        store,
        Session,
        # Publishing is a notification, not a delivery mechanism: subscribers
        # are told that something landed and go read the log for themselves.
        # It fires after the append commits, so a signal never runs ahead of
        # the write it is announcing.
        event_publisher=publisher,
        # Opened against the same database file as the event store: the schema
        # that creates the `snapshots` table is applied by the store's
        # connection, so a separate path would leave the table missing.
        snapshot_store=snapshot_store,
        snapshot_threshold=SNAPSHOT_THRESHOLD,
        # A snapshot is an optimisation for a future read, and the turn that
        # triggers it is the one thing in this application a person is actually
        # waiting on. Scheduling it off the save path spends the latency where
        # nobody is watching. `await_pending_snapshots()` is how tests -- and
        # shutdown -- pin the timing back down when they need it.
        snapshot_mode="background",
    )


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

        **`Project` is read for the course page, which had no live path at
        all.** `ProjectStageAdvanced` and `ProjectWorkflowSelected` are appended here and the
        rail is what they moved, so a stage that advanced while a tab was open
        reached the browser through nothing and the page only moved on a
        reload. It is the same shape as `Topic`, the graph and `Corpus` before
        it -- the fourth time -- which is why `FEED_AGGREGATE_TYPES` and
        `UNROUTED_AGGREGATE_TYPES` now exist instead of a literal here.

        One admission covers the whole aggregate rather than `ProjectStageAdvanced`
        alone, and that is deliberate: `ProjectWorkflowSelected` is what turns the
        course page from a 409 into a rail, and the lifecycle events
        (`ProjectSessionJoined`, `ProjectTipAdvanced`, `ProjectDeleted`) move
        the holding-session link and the project list. Filtering to one event
        class would have fixed the reported symptom and left its siblings
        invisible until the next report.

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
