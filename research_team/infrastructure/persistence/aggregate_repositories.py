"""Aggregate repository factories over `eventsource`'s SQLite store.

Extracted from `event_store.py`: each function configures an `AggregateRepository`
with its snapshot store, threshold, event publisher, and background snapshotting
mode.
"""

from eventsource import InMemoryEventBus
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.snapshots import SQLiteSnapshotStore
from eventsource.application.aggregates.repository import AggregateRepository

from research_team.curriculum.domain.authoring_run import CourseAuthoringRun
from research_team.curriculum.domain.course import Course
from research_team.curriculum.domain.learner import LearnerProgress
from research_team.dialogue.domain.ask import AskConversation
from research_team.dialogue.domain.socratic import SocraticDialogue
from research_team.knowledge.domain import EntityJudgements
from research_team.research.domain import Corpus
from research_team.research.domain.run import ResearchRun
from research_team.research.domain.topic import Topic
from research_team.session.domain import Session
from research_team.tenancy.domain import Project

SNAPSHOT_THRESHOLD = 50


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


def build_course_authoring_run_repository(
    store: SQLiteEventStore,
    publisher: InMemoryEventBus | None = None,
) -> AggregateRepository[CourseAuthoringRun]:
    """Authoring runs, over the same log as the sessions their turns write into.

    Published like its neighbours even though `CourseAuthoringRun` is in
    `UNROUTED_AGGREGATE_TYPES`, for `build_ask_conversation_repository`'s
    reason: publishing is what `read_since`'s local append flag watches, and
    the scoping decision is made there rather than by half-wiring the bus here.

    **No snapshots**, and this one is not close to the line. A run appends one
    event to start, one per target, and one to settle -- a path over eight
    areas is ten events and then the stream is closed forever, because a
    settled run refuses every further command. There is no way for one of these
    to grow long enough for a threshold to matter.
    """
    return AggregateRepository(store, CourseAuthoringRun, event_publisher=publisher)


def build_course_repository(
    store: SQLiteEventStore,
    publisher: InMemoryEventBus | None = None,
) -> AggregateRepository[Course]:
    """Realized courses, over the same log as everything else.

    Published unlike `build_course_authoring_run_repository`'s neighbours are
    *not* unlike it -- `Course` is on `FEED_AGGREGATE_TYPES` (see the
    docstring there), so publishing here is what makes a `CourseRealized` or
    `CourseAbandoned` reach `read_since`'s local append flag at all, not only
    what other repositories do out of habit.

    **No snapshots**, for `build_course_authoring_run_repository`'s reason.
    `decide` refuses two consecutive `RealizeCourse`s or two consecutive
    `AbandonCourse`s on the same stream -- realize/abandon can alternate
    indefinitely, but each alternation is one person's one decision, and a
    slug realized and abandoned often enough to make the fold worth
    memoizing is not a case this feature was built for.
    """
    return AggregateRepository(store, Course, event_publisher=publisher)


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


__all__ = [
    "SNAPSHOT_THRESHOLD",
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
