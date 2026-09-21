"""The wired application: use cases, plus a live view of the same log."""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from uuid import UUID

import httpx
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.application.aggregates.repository import AggregateRepository
from langchain_core.tools import BaseTool

from research_team.curriculum.application.course_authoring import CourseAuthor
from research_team.curriculum.application.course_catalog import CatalogService
from research_team.curriculum.application.course_realization import CourseService
from research_team.curriculum.domain.authoring_run import CourseAuthoringRun
from research_team.curriculum.domain.course import Course
from research_team.dialogue.application.ask import AskService
from research_team.dialogue.application.socratic import SocraticDialogueService
from research_team.infrastructure import config
from research_team.infrastructure.identity import EventStoreUserRecorder
from research_team.infrastructure.interaction.recorder import EventStoreInteractionRecorder
from research_team.infrastructure.knowledge.blurb_writer import ModelBlurbWriter
from research_team.infrastructure.knowledge.catalog_recorder import (
    EventStoreCatalogFeatureRecorder,
)
from research_team.infrastructure.knowledge.library_art import LibraryArtProvider
from research_team.infrastructure.knowledge.outline_writer import ModelOutlineWriter
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from research_team.infrastructure.knowledge.svg_artist import ModelSvgArtist
from research_team.infrastructure.persistence import (
    CorpusRunner,
    SessionSummaryRunner,
    TopicRunner,
)
from research_team.infrastructure.persistence.interaction_log import InteractionLogRunner
from research_team.infrastructure.persistence.read_models import (
    AskConversationRunner,
    AuthoringRunRunner,
    CatalogFeatureStore,
    CourseStore,
    EntityDefinitionRunner,
    MediaProposalRunner,
    OntologyRunner,
    SocraticDialogueRunner,
)
from research_team.infrastructure.persistence.tenants import TenantRunner
from research_team.infrastructure.persistence.users import UserRunner
from research_team.interfaces.web.art_sweep import ArtReroll, ArtSweep
from research_team.interfaces.web.blurb_sweep import BlurbSweep
from research_team.interfaces.web.settings import SettingsDeps
from research_team.knowledge.application.entity_definitions import DefinitionService
from research_team.knowledge.application.ontology_discovery import OntologyDiscoveryService
from research_team.knowledge.application.project_graphs import ProjectGraphs
from research_team.platform.shared.blobs import BlobStorePort
from research_team.platform.shared.live_feed import LiveFeed
from research_team.research.application.corpus_editing import CorpusEditor
from research_team.research.application.document_extraction import DocumentExtractor
from research_team.research.application.media_acquisition import (
    MediaAcceptReconciler,
    MediaAcceptWorker,
)
from research_team.research.application.media_curation import (
    MediaCurationTextPort,
    MediaSearchPort,
)
from research_team.research.application.perception import MediaPerceiver, PerceptionPort
from research_team.research.application.research_supervisor import ResearchSupervisor
from research_team.research.application.topic_dispatch import TopicDispatcher
from research_team.research.application.topic_read import TopicReadPort
from research_team.research.application.topic_seeding import TopicSeeder
from research_team.research.domain.media_proposals import MediaProposals
from research_team.research.domain.topic import Topic
from research_team.session.application.autonomy import AutonomyPolicy
from research_team.session.application.session_service import SessionService
from research_team.session.application.turn_supervisor import TurnSupervisor
from research_team.session.application.workers import WorkerRoster
from research_team.tenancy.application.authorization import Authorizer
from research_team.tenancy.application.grants import GrantRegistry
from research_team.wiring.lifecycle import _close_every_step
from research_team.wiring.resources import (
    _LazyArtStore,
    _LazyBlurbCache,
    _LazyCandidateArtStore,
    _LazyOutlineCache,
    _LazyProjectSummaries,
)
from research_team.wiring.runners import (
    _CatalogFeatureRunner,
    _CourseRunner,
)

logger = logging.getLogger(__name__)

__all__ = ["Application"]


@dataclass(frozen=True)
class Application:
    """The wired application: use cases, plus a live view of the same log."""

    service: SessionService
    feed: LiveFeed
    turns: TurnSupervisor
    context_mode: str
    """How this instance manages context. Not the same as the strategy name:
    `delegate` sends the full history and simply has less of it."""

    summaries: SessionSummaryRunner
    """Keeps `/sessions` following the log. Idle until `start()`."""

    corpus: CorpusRunner
    """Keeps the corpus table following the log. Idle until `start()`.

    A field rather than something reached through the service, because the
    corpus is read by two callers that share nothing else: the agent, through
    the tools attached with a project, and the web layer, which lists and
    reads any project's sources without attaching anything."""

    blob_store: BlobStorePort
    """Where media bytes live. A field for `corpus`'s reason and one more:
    this is the single instance every `ProjectCorpusReader` in this build is
    handed -- see the comment beside its construction in `build_application`
    -- so `web.py` has to be able to reach it too, to hand the same instance
    to `create_app`."""

    tenants: TenantRunner
    """Keeps the four tenancy tables following the log. Idle until `start()`.

    A field rather than a local for `topics`'s reason, sharpened: `authorizer`
    below reads through it, and a second instance would give the checker its own
    connection and its own view of who is a member -- which is a permission
    answer that disagrees with the one `/api/tenants/{id}/members` renders."""

    authorizer: Authorizer
    """Which adapter answers "may this principal do this". Chosen once, here.

    `PermissiveAuthorizer` unless `AGENT_AUTH` is on, and **not** an absent
    dependency: see the class docstring for why off has to be a real authorizer.
    Nothing calls this yet -- slice B3 puts the `Requires` marker on the routes
    -- so at the time of writing this is wired and unread, which is stated
    plainly because a wired-and-unread port is the shape CLAUDE.md's
    "one adapter, no test between them" entry is about. The test that answers it
    is `tests/integration/test_authorization_over_real_grants.py`, which drives
    the real writer and the real checker over one database."""

    topics: TopicRunner
    """Keeps the topic tables following the log. Idle until `start()`.

    A field for the same reason `corpus` is one: the queue is read by the
    agent through the tools attached with a project, and by anything driving an
    autonomous run, which shares nothing else with a session."""

    settings: SettingsDeps
    """What the settings and provider routes need: the override table, the
    secret box, and the provider probe.

    A field rather than something `web.py` builds, for the reason every other
    collaborator here is one: a dependency assembled at the call site is one
    the tests never see assembled, and `test_web_entrypoint.py` exists because
    that gap has shipped three times. The store inside it opens on first use
    rather than in `start()` -- see `SettingsStore` for why that is about the
    event loop and not about laziness."""

    definitions: EntityDefinitionRunner
    """Keeps cached entity definitions marked stale. Idle until `start()`.

    A field for the reason `topics` is one and one more: it is not only a
    projection nobody would otherwise start, it is also the owner of the
    table `definition_readers` reads and writes through, so `rebuild()` and
    `failures()` have to be reachable when a definition disagrees with the
    graph beside it."""

    definition_readers: Callable[[UUID], Awaitable[DefinitionService | None]]
    """One project's `DefinitionService`, built fresh per call, or `None` when
    this build has no chunk store.

    A factory for `topic_readers`' reason -- the project is bound at
    construction so no caller can read or overwrite another project's cached
    definitions -- and awaitable because building one opens that project's
    graph store. See `definition_reader` in `build_application` for why the
    cache inside it is process-wide while the graph beside it is not."""

    ontology: OntologyRunner
    """Keeps the discovered-class tables following the log. Idle until `start()`.

    A field because a projection that is constructed and never started
    records nothing while looking wired, and because `rebuild()` has to be
    reachable when the tables disagree with the log. Unlike `definitions`,
    nothing reads *through* this runner to write: the discovery service appends
    to the event store and the projection does the writing, so this is the read
    side only."""

    ontology_discoverers: Callable[[UUID], OntologyDiscoveryService]
    """One project's `OntologyDiscoveryService`, built fresh per call.

    A factory for `topic_readers`' reason: the project is bound at construction,
    so no caller can run a pass against a project it was not handed. Synchronous
    and never `None`, unlike `definition_readers` -- see `ontology_discoverer`
    in `build_application` for why nothing it needs can be absent."""

    media_proposals: MediaProposalRunner
    """Keeps the proposal tables following the log. Idle until `start()`.

    A field for `ontology`'s reason -- a projection nobody would otherwise
    start, and `rebuild()`/`failures()` have to be reachable when the tables
    disagree with the log. Like `ontology`, nothing reads *through*
    this runner to write: `MediaCurationService` appends to the event store
    via `media_proposal_repository` below and the projection does the writing."""

    media_proposal_repository: AggregateRepository[MediaProposals]
    """The `MediaProposals` aggregate repository, for `MediaCurationService`.

    Exposed directly rather than behind a factory, mirroring `topic_repository`:
    a `MediaProposals` aggregate is keyed on `project_id` alone, so there is no
    per-project object to assemble and nothing a factory would buy here. Built
    over this instance's own event store (`repository.store`/`.publisher`), the
    same one `media_proposals` above subscribes to -- a repository built over a
    different store would let a curation and the projection reading it disagree
    about what was ever appended."""

    media_curation_text: MediaCurationTextPort | None
    """The chain's text port, or `None` when this install has no model to
    curate with. Paired with `media_curation_search` below rather than
    exposed only as a bundle, mirroring `corpus`/`blob_store`: `create_app`
    takes each optional dependency on its own name, and a route checks each
    the way `_reader` checks `corpus` and `blob_store` together."""

    media_curation_search: MediaSearchPort | None
    """The chain's search port, `None` exactly when `searxng` above is --
    `build_curation_ports` needs a SearXNG instance the same way
    `build_search_tool` does, and a build with no instance configured has
    nothing for either to search."""

    graphs: ProjectGraphs
    """The single owner of every project's open graph store in this instance.

    A field rather than something reached only through `open_graph`'s
    closure, because a graph-browsing read route needs to `open` the same
    store the attached agent writes to, and a delete route needs to `close` it --
    neither is reachable through the executor or the service, so this is
    where both go looking."""

    topic_readers: Callable[[UUID], TopicReadPort]
    """One project's `TopicReadPort`, built fresh per call.

    A factory rather than a bare repository, for the reason `_reader` in
    `app.py` is a function and not a field: the web layer has no business
    knowing that a topic reader is assembled from a queue projection, an
    aggregate repository and a corpus-facts callable -- that is composition
    knowledge, and handing it out piecemeal would make every future change to
    how a reader is built a change to the web layer too. This closes over the
    one `AggregateRepository[Topic]` also used by `start_run` below, so
    there is exactly one such object, not a second built to avoid depending
    on this field."""

    topic_repository: AggregateRepository[Topic]
    """The `Topic` aggregate repository, for routes that change a topic's state.

    Exposed directly rather than behind a factory, unlike `topic_readers`:
    an `AggregateRepository[Topic]` needs no project bound at construction --
    `load` takes the topic id and the aggregate carries its own `project_id`
    -- so there is no per-project object to assemble and nothing a factory
    would buy here. The same object `topic_readers` and `start_run` already
    close over, not a second one, for the reason given above. Mirrors
    `SessionService.projects`, which exposes the `Project` repository the
    same way for the same reason: a write that is not a session use case has
    nowhere else to reach for the aggregate it needs."""

    research: ResearchSupervisor
    """Autonomous runs over this instance's topic queues.

    A field rather than something built where it is used, because a run needs
    four things that only this module holds together -- the run repository, the
    topic repository, the queue projection and the turn supervisor -- and both
    front ends want the same one. Two supervisors over one database would each
    believe they held the only run on a project."""

    reembed: "Callable[[UUID], Awaitable[int]]"
    """Re-embed one project's entities from its current graph; returns how many.

    A field rather than something the web layer builds, because it reaches
    across four things composition owns and nothing else does: the graph store,
    the embedding provider, the event log and the per-project card vector
    store. See `create_app`'s `ReembedProject`.
    """

    course_author: CourseAuthor
    """Writes one learning area's unit and lessons, by Understanding by Design.

    A field for `topic_seeder`'s reason: built from the same `service` and
    `turns` this module already holds, and wanted by whichever front end is
    running. The projection it authors *from* is not a field -- see
    `CurriculumService`, which is a cache in front of a pure function and has
    no dependencies to compose.
    """

    topic_seeder: TopicSeeder
    """Names a project's first topics in one turn, given a subject.

    A field for the same reason `research` is one: both front ends want the
    same object, and it is built from the same `service` and `turns` this
    module already holds -- nothing a factory would buy over exposing the
    one instance directly, the way `topic_repository` is exposed rather than
    rebuilt per call."""

    dispatcher: TopicDispatcher
    """Writes down what this project understands about one topic, in one turn.

    A field for the same reason `topic_seeder` is one, and built from the same
    three things this module already holds -- `service`, `turns` and
    `topic_readers`. The reader in particular must be *this* instance's: the
    dispatcher numbers a topic's directory by its position in the project's
    topic list, and a second reader over the same database would answer the
    same question, which is exactly why building one here rather than
    threading it through would look harmless and be a second source of a fact
    the front end also reads."""

    workers: WorkerRoster
    """Everything in flight on a project, for a front end that wants to show it.

    A field for the same reason `research` is one: it needs three things only
    this module holds together -- the session service, the turn supervisor and
    the research supervisor -- and both front ends want the same answer from
    the same three."""

    policy: AutonomyPolicy
    """Per-tool autonomy levels for this instance, mutable after construction.

    Exposed here rather than buried in the executor because a front end that
    lets someone change autonomy mid-session needs a handle to mutate -- this
    is that handle, whichever adapter (CLI, web) drives it."""

    grants: GrantRegistry
    """This instance's fetch pre-authorizations, keyed by session.

    Exposed for the same reason `policy` is: `web.py` builds its own
    `WebApprovals` around one and has to hand this build the *same* one
    (`build_application(grants=...)`), and a test that wants to see what a
    run registered -- or that a stopped run's entry is gone -- needs the
    identical registry the executor's gate and the grant-bound `fetch` tool
    consult, not a second one that would just happen to agree by accident."""

    ask: AskService
    """Questions about a project, answered without touching the project's log.

    A field beside `service` rather than something reached through it, because
    it is deliberately not a session use case: it starts nothing and joins
    nothing, and routing it through `SessionService` would put a conversational
    path behind the one object whose whole job is durability. It does append,
    since `docs/superpowers/specs/2026-08-16-ask-persistence-design.md` -- to
    an `AskConversation` stream of its own, which is off the project's stream
    and off its feed.
    It shares this instance's `open_graph` closure, so an ask reads the same
    open graph store the attached agent writes to rather than a second one
    rebuilt for the question -- which is also why it is constructed inside
    `build_application` and cannot be assembled by a caller."""

    asks: AskConversationRunner
    """The read side of persisted asks: history for a project, one
    conversation with its turns. Idle until `start()`.

    A field for `ontology`'s reason -- a projection nobody would otherwise
    start -- and, like it, read-only: `ask` above appends to
    the log and this follows it. The two must never be collapsed into one
    object; a service that both answered questions and owned the table would
    make "the answer was given" and "the answer was recorded" the same
    assertion, and they are exactly the pair this feature needs kept apart."""

    socratic: SocraticDialogueService
    """Guided dialogues: framing a topic, and answering a reply with a question.

    A field beside `ask` and for its reason -- it is composed from this build's
    stores and no caller could assemble it. Its executor closes over the same
    `open_graph` the ask's does, so like `ask` it cannot be constructed anywhere
    a caller could stand."""

    dialogues: SocraticDialogueRunner
    """The read side of dialogues: a project's dialogues, one dialogue with its
    turns. Idle until `start()`.

    A field for `asks`'s reason, and it carries one more job than `asks` does:
    `socratic` above reads *through* this when the live registry has dropped a
    dialogue, so this is not only the history surface but the whole of
    resumption. The two must never be collapsed into one object."""
    users: UserRunner
    """Keeps the `users` mirror following the log. Idle until `start()`.

    A field for `asks`'s reason and one more: `user_recorder` below reads
    *through* this to decide whether the IdP's claims have changed since the
    last sign-in, so the read side and the write side are two halves of one
    channel and must be the same object. Two instances would each open their
    own connection, and the recorder would compare fresh claims against a view
    of the table nothing was updating -- appending a `UserProfileChanged` on
    every sign-in, forever, and never noticing."""
    user_recorder: EventStoreUserRecorder
    """Appends `UserSignedIn`/`UserProfileChanged` when a sign-in completes.

    A field rather than something the web layer builds, because it needs the
    application's own event store and publisher; a recorder built at the call
    site would append to one store while `users` above followed another, which
    is the failure `catalog_features` and `topic_repository` both shipped."""
    authoring_runs: AggregateRepository[CourseAuthoringRun]
    """The write side of course-authoring runs: what a run wrote, and where.

    A field beside `course_author` rather than something reached through it,
    because it is not the authoring *work* -- it is the record that the work
    happened, appended by the web layer's `AuthoringActivity` around calls into
    `course_author`. Collapsing the two would make "the course was written" and
    "which session holds it" one assertion, and the second is the one that used
    to be lost on every restart."""

    authoring: AuthoringRunRunner
    """The read side of the same feature: this project's last run, its targets,
    and one session id per authored area. Idle until `start()`.

    A field for `asks`'s reason -- a projection nobody would otherwise start --
    and read-only. Its failure mode when unwired is the worst of the ten:
    authoring appends whether or not anything follows, so a build missing it
    answers "no run has ever happened" for every project while the courses sit
    on the log unfindable, which is the original bug restored by omission."""

    interaction_log: InteractionLogRunner
    """Keeps `interaction_events` following the interaction log. Idle until
    `start()`. Its own store, so nothing here can be ordered against the
    domain log."""

    interaction_recorder: EventStoreInteractionRecorder
    """Where the ingest route writes. Appends and publishes; see its module
    docstring for why the publish is not optional."""

    _interaction_store: SQLiteEventStore
    """The store `interaction_log` and `interaction_recorder` share. Held only
    so `close()` can close it -- mirrors `_media_http_client` above: neither
    `InteractionLogRunner.stop()` nor `EventStoreInteractionRecorder` owns the
    connection, since composition is what opened it."""

    catalog: CatalogService
    """Turns a curriculum into ranked, categorised course cards for one
    project. Takes an already-built `Curriculum` per call, not a `project_id`
    at construction -- one instance serves every project, matching
    `curriculum`'s own statelessness in `web.py`."""

    _catalog_runner: _CatalogFeatureRunner
    """Owns `catalog_features` and the projection that keeps it level with
    the log. Private for `_reconciliation`'s reason -- `Application` is
    frozen, so `catalog_features` below reads through this runner's own
    mutable `features` attribute rather than being a field `start()` could
    rebind once the store is open."""

    catalog_recorder: Callable[[UUID], EventStoreCatalogFeatureRecorder]
    """One project's write side for featuring, built fresh per call --
    mirrors `ontology_discoverers`: the project is bound at construction, so
    no caller can append a `CourseFeatured`/`CourseUnfeatured` to a project it
    was not handed."""

    blurbs: ModelBlurbWriter
    """Writes catalog copy for a cluster, given its title and anchors.

    Constructed here even though nothing calls it yet -- on-demand blurb
    generation is a later increment's job, and its caller is what is deferred,
    not the object graph underneath it. CLAUDE.md's own account of the
    co-mention channel is why: a port built with no production caller shipped
    once already, unnoticed for a whole release because every piece of it
    was individually tested. Building the writer now means that increment
    adds one call, not a constructor, an adapter and a wiring decision all at
    once -- and a mistake in *this* wiring fails loudly at start-up rather
    than silently the first time a reader asks for a blurb."""

    _blurb_cache: _LazyBlurbCache
    """The `BlurbCachePort` handed to `catalog` at construction. Private
    for `_catalog_runner`'s reason turned around: this one is not read
    through a property because `catalog` itself is the field a route holds,
    not this cache -- it is kept here solely so `close()` can close the
    connection it lazily opens."""

    course_service: CourseService
    """Assembles one course detail page: a candidate, its outline, its
    membership and -- if realized -- its drift. Takes an already-built
    `Curriculum` and `Catalog` per call, mirroring `catalog`'s own
    statelessness, for the same reason: one instance serves every project."""

    _outline_cache: _LazyOutlineCache
    """The `OutlineCachePort` handed to `course_service` at construction.
    Private for `_blurb_cache`'s exact reason: kept here solely so `close()`
    can close the connection it lazily opens, not because any route reads
    through it -- `course_service` is the field a route holds."""

    _course_runner: _CourseRunner
    """Owns `courses` and the projection that keeps it level with the log.
    Private for `_catalog_runner`'s exact reason -- `Application` is frozen,
    so `courses` below reads through this runner's own mutable `courses`
    attribute rather than being a field `start()` could rebind once the store
    is open."""

    course_repository: AggregateRepository[Course]
    """The `Course` aggregate repository, for whatever route executes
    `RealizeCourse`/`AbandonCourse` -- not built yet; Task 9's job. Exposed
    directly rather than behind a factory, mirroring `topic_repository`: a
    `Course` stream is keyed by `(project_id, slug)` through `course_stream_id`,
    which needs no project bound at construction, so there is no per-project
    object to assemble."""

    outlines: ModelOutlineWriter
    """Writes a course outline for a cluster, given its title and anchors.

    Called from exactly one place: `blurb_sweep`'s background sweep, which is
    handed this field per call to `.start()` (see `web.py`'s
    `outline_writer=application.outlines`). `CourseService` no longer holds
    a reference to this writer at all -- `_outline_for` is cache-read-only,
    per `course_realization.py`'s module docstring -- so `_LazyOutlineCache`
    above (handed to both `course_service` and `blurb_sweep`) is the one
    place an outline is read *and* the one place it is written."""

    blurb_sweep: BlurbSweep
    """One copy-and-outline sweep per project, over `_blurb_cache` and
    `_outline_cache`.

    Built here rather than left for whichever route starts a sweep, matching
    `blurbs`' reasoning turned into an object rather than a bare port. Writes
    outlines as well as copy -- folded in rather than built as a second sweep
    beside it, since course-detail outline generation moved out of the
    request path entirely; see `blurb_sweep.py`'s module docstring."""

    art_store: _LazyArtStore
    """The art library's storage half. Handed to `create_app`'s `art_store`
    parameter directly, so `/api/art/{art_id}.svg` can serve what
    `art_generator`/`art_sweep` below write to it."""

    art_generator: ModelSvgArtist
    """Generates one piece of art from a candidate's title and anchors, or
    refuses -- see `ArtGeneratorPort`'s docstring. Built over the same
    `extraction_model` `blurbs`/`outlines` use; no second model
    configuration, matching `outline_writer`'s own comment on why."""

    project_summaries: _LazyProjectSummaries
    """Every project's pipeline position, in one read for the whole listing.

    Public rather than private, unlike the three lazy wrappers above it:
    those exist so `close()` can reach a connection some *other* field opened
    lazily, where this one is itself what `create_app` is handed
    (`project_summaries=application.project_summaries` in `web.py`). It is the
    field a route reads through."""

    _candidate_art_store: _LazyCandidateArtStore
    """The candidate-to-art assignment table `art_matcher`/`art_sweep` read
    and write through `LibraryArtProvider`. Private for `_blurb_cache`'s
    reason turned around -- kept here solely so `close()` can close the
    connection it lazily opens."""

    art_matcher: LibraryArtProvider
    """The same `LibraryArtProvider` `catalog_service` was built with,
    exposed separately so `art_sweep` can call `.match()` to check "does the
    library already cover this candidate" without generating for it -- see
    `art_sweep.py`'s module docstring for why the sweep and the on-demand
    path share exactly one search implementation rather than each carrying
    their own."""

    art_sweep: ArtSweep
    """One art-generation sweep per project, over `art_store`/
    `_candidate_art_store` -- `blurb_sweep`'s reasoning turned to art: built
    here so a route only has to add one call to `.start()`."""

    art_reroll: ArtReroll
    """Single-candidate reroll, over the same `art_store`/
    `_candidate_art_store` pair as `art_sweep` -- see `ArtReroll`'s docstring
    for why it is a separate tracker rather than `art_sweep` handed a
    one-candidate list."""

    document_extractor: DocumentExtractor
    """Extracts a stored document into its project's graph, without re-fetching.

    A field beside `ask` and for the same reason: it closes over `open_graph`,
    which is assembled inside `build_application` from this build's stores, so
    no caller could construct it. The web layer needs it because "extract this
    document" is a button on the Documents page, and nothing else on the way
    from that button to `KnowledgePort.ingest` knows how to build a port."""

    editor: CorpusEditor
    """Upload, revise, drop and restore one project's documents, over HTTP.

    A field beside `document_extractor` and for the same reason: it closes
    over `open_knowledge` and the corpus repository, both assembled inside
    `build_application` from this build's stores, so no caller could
    construct it. The web layer needs it because "add a document", "edit a
    document" and "drop/restore a document" are all buttons on the Documents
    page with no other way to reach `Corpus`."""

    perception: PerceptionPort
    """What this instance can read a medium with.

    Exposed as a field, matching `approvals`/`extractions`/`grants`/`activity`
    above: `build_application(perception=...)` is how a test hands this build
    a fake, so a suite that perceives media never reaches a network or a
    vision endpoint. `None` at that parameter calls `build_perception_adapter()`,
    which is synchronous -- see its module docstring for why `build_application`
    does not become `async def` for this one port."""

    _media_http_client: httpx.AsyncClient
    """The client `media_accept_worker` downloads through. Held here only so
    `close()` can `aclose()` it -- not a field a route or a test should read;
    see `media_accept_worker` for the collaborator callers actually want."""

    media_accept_worker: MediaAcceptWorker
    """Downloads, stores and perceives an accepted media proposal.

    A field for `create_app` to hand to the accept route, mirroring `editor`
    and `perceiver` above: it closes over collaborators assembled inside
    `build_application`, so no route could construct one itself. See the
    long comment where this is built, beside `media_proposal_repository`, for
    why it lives there and not among the projections above it."""

    media_accept_reconciler: MediaAcceptReconciler
    """Re-runs `media_accept_worker` over every proposal a crash left
    `accepted`, once, from `start()`.

    A field rather than a local built inside `start()` because `start()` is
    handed no collaborators -- and a field with no route reading it, unlike
    `media_accept_worker` above: nothing outside `start()` calls this, and the
    spec (`docs/superpowers/specs/2026-08-16-accept-reconciliation-design.md`)
    rules out an operator surface that would give it a second caller."""

    perceiver: MediaPerceiver
    """Reads a stored medium into a derived text source, over this instance's
    `perception` and corpus repository.

    A field beside `document_extractor` and for the same reason: it shares
    that use case's `corpus_readers` closure and the corpus repository
    `editor` also holds, both assembled inside `build_application` from this
    build's stores, so no caller could construct it. The web layer needs it
    because "perceive this medium" is a button on the Documents page with no
    other way to reach `PerceptionPort`."""

    media_reconcile_interval: float = config.DEFAULT_MEDIA_RECONCILE_INTERVAL_SECONDS
    """Seconds between periodic reconciliation sweeps -- the upper bound of the
    sweep loop's jittered sleep, not a fixed period. See
    `_sweep_reconciliation` for the jitter and `config.
    media_reconcile_interval_seconds` for why five minutes.

    A field with a default rather than a required constructor argument, so the
    dozens of tests that build an `Application` directly are untouched;
    `build_application` overrides it from the environment. A test that needs
    the sweep to fire wants a fraction of a second here, and setting a field is
    cheaper than monkeypatching a module-level read."""

    _initial_project_id: UUID | None = None
    """`project_id`, if `build_application` was given one. Attached in
    `start()` rather than at construction, because attaching talks to a
    store and building is deliberately synchronous."""

    _reconciliation: list[asyncio.Task[None]] = field(default_factory=list, repr=False)
    """The reconciliation task `start()` scheduled, if it has been called.

    A one-element list rather than a plain `asyncio.Task | None` field:
    `Application` is `frozen=True`, so `start()` cannot rebind an attribute.
    `Grant._remaining` in `application/grants.py` uses the same shape for the
    same reason.

    Held at all because `asyncio.create_task` only weakly references its task
    -- the note `app.py` already carries above `create_app`'s body -- so a
    reconciliation nothing kept a reference to could be collected mid-download."""

    _sweep: list[asyncio.Task[None]] = field(default_factory=list, repr=False)
    """The periodic sweep task `start()` scheduled, if it has been called.

    A *separate* list from `_reconciliation` above rather than another entry in
    it, and the separation is load-bearing: `reconciled()` awaits everything in
    `_reconciliation`, and the sweep never finishes, so a sweep task in that
    list would hang every test that calls `reconciled()` -- and every one of
    them would hang for the full test timeout rather than fail with anything
    naming the cause. Same one-element-list shape and the same reason
    (`frozen=True`, and `create_task` holds only a weak reference)."""

    @property
    def knowledge(self) -> RedstringKnowledge | None:
        """This instance's currently attached knowledge graph, or None.

        Not a fixed field: which project is attached can change after
        construction, now that a REPL can `/project use` into one. Reads
        through the service, which is what actually owns the attachment --
        so this and `service.current_knowledge` can never disagree.
        """
        return self.service.current_knowledge

    @property
    def catalog_features(self) -> CatalogFeatureStore | None:
        """The read side of course featuring, or `None` until `start()` has
        opened it. `CatalogFeatureStore.open` needs a running event loop --
        the same reason every other projection's store here is opened in
        `start()`, not at construction -- so this reads through
        `_catalog_runner`'s mutable `features` attribute rather than being a
        field of its own; see `_catalog_runner`'s docstring."""
        return self._catalog_runner.features

    async def catalog_caught_up(self) -> None:
        """A test affordance, matching `interaction_log_caught_up` and the rest:
        waits until `catalog_features` has replayed every `CourseFeatured`/
        `CourseUnfeatured` appended so far."""
        await self._catalog_runner.caught_up()

    @property
    def courses(self) -> CourseStore | None:
        """The read side of realized courses, or `None` until `start()` has
        opened it. Mirrors `catalog_features` exactly, and for the same
        reason: `CourseStore.open` needs a running event loop, so this reads
        through `_course_runner`'s mutable `courses` attribute rather than
        being a field of its own; see `_course_runner`'s docstring."""
        return self._course_runner.courses

    async def courses_caught_up(self) -> None:
        """A test affordance, matching `catalog_caught_up`: waits until
        `courses` has replayed every `CourseRealized`/`CourseAbandoned`
        appended so far."""
        await self._course_runner.caught_up()

    async def attach_project(self, project_id: UUID) -> None:
        """Open `project_id`'s graph and give the executor its tools.

        Thin delegation: the service owns the attachment and its atomicity
        guarantee (a failure here must leave `knowledge` at None and the
        executor's tools unchanged), because the REPL calls the same method
        on the service directly -- this exists so the build-time
        `project_id=` path below has one path to go through as well, not two.
        """
        await self.service.attach_project(project_id)

    async def detach_project(self) -> None:
        """Close whatever graph is attached and restore the tools without it."""
        await self.service.detach_project()

    async def start(self) -> None:
        """Open what needs a running event loop to open.

        Building an application is deliberately synchronous -- it picks
        adapters and wires them, nothing more -- because the web entrypoint
        constructs it before uvicorn has a loop, and an aiosqlite connection
        made on one loop cannot be used from another. Anything that has to be
        opened *inside* the loop that will use it is opened here, including
        attaching `_initial_project_id`, if `build_application` was given one
        -- so an unreachable Neo4j fails here, at start, rather than mid-turn.
        """
        await self.summaries.start()
        await self.corpus.start()
        await self.topics.start()
        await self.definitions.start()
        await self.ontology.start()
        await self._catalog_runner.start()
        await self._course_runner.start()
        await self.media_proposals.start()
        # Reconcile proposals a crash left `accepted` -- designed in
        # `docs/superpowers/specs/2026-08-16-accept-reconciliation-design.md`.
        # Here rather than in `web.py`'s lifespan, which is the spec's central
        # ruling: `web.py` carries three "was missing -- these routes have been
        # 503ing in this entrypoint while the test fixture wired one and
        # passed" comments, and a reconciliation that never ran looks exactly
        # like one that found nothing to do, so it must not depend on a call
        # site anyone can forget.
        #
        # After `caught_up()`, not merely `start()`: a projection mid-replay
        # under-reports the accepted set and there is no second pass. The cost
        # is that startup waits for a catch-up it would need before serving
        # anything about proposals anyway.
        #
        # Scheduled, not awaited: an abandoned download is a download, and
        # re-fetching an hour of video must not hold the port closed.
        await self.media_proposals.caught_up()
        self._reconciliation.append(asyncio.create_task(self.media_accept_reconciler.run()))
        # And again, on a timer, for the case the startup pass cannot reach:
        # `BACKLOG.md` B99, now closed -- the design is in the spec named
        # above, under "What this does not do". The pass above fixes a
        # process that died and came back; it does nothing for a process
        # that never dies, where an
        # accept's `asyncio.create_task` raised, hung, or was dropped and the
        # proposal stays `accepted` for as long as the process stays up.
        #
        # Created after `caught_up()` for the same reason the pass above is,
        # and `tests/integration/test_accept_reconciliation.py::
        # test_the_reconciler_reads_only_after_caught_up_returns` is what
        # fails if either line moves above it: the sweep's first read must not
        # land on a projection still mid-replay either.
        self._sweep.append(asyncio.create_task(self._sweep_reconciliation()))
        await self.asks.start()
        await self.authoring.start()
        await self.dialogues.start()
        # Started with the rest rather than lazily on first sign-in: a
        # projection that only starts when somebody logs in is a projection
        # whose absence is invisible on every instance where nobody has yet.
        # It is also the quietest of these to have missing -- the callback
        # still appends, still sets a cookie, and still signs the person in;
        # only `/api/me` comes back describing a stranger. Started
        # unconditionally even with `AGENT_AUTH=off`, so that turning the flag
        # on does not need a restart to have a read model behind it, and so
        # that the two states of the flag differ in one place only.
        await self.users.start()
        await self.interaction_log.start()
        await self.tenants.start()
        if not config.authorization_enabled():
            # `LOCAL_TENANT` is a real tenant with a real row, not a special
            # case in the checker -- see `seed_local_tenant`. Only with auth
            # off: with it on, a `"local"` tenant nobody created would be a
            # tenant nobody can see the membership of.
            await self.tenants.seed_local_tenant()
        if self._initial_project_id is not None:
            await self.attach_project(self._initial_project_id)

    async def _sweep_reconciliation(self) -> None:
        """Re-run reconciliation forever, on a jittered timer.

        `BACKLOG.md` B99, closed by this; the three questions it deferred on
        are answered here and in the spec `start()` names.

        **Full jitter: the sleep is a uniform draw from `[0, interval]`, not
        the interval itself.** That is the standard answer to the failure it
        prevents -- every process in a multi-instance deployment sweeping in
        lockstep, which turns a cheap periodic read into a synchronised burst
        against one database, and keeps them synchronised because they all
        wake, work, and sleep the same amount. The cost is that an individual
        sweep's spacing is unpredictable and averages half the interval, so
        the configured number is an upper bound on the gap rather than the gap.
        Sleeping *before* the first sweep is deliberate: `start()` has just run
        one, and a sweep immediately after it would be pure waste.

        **Two processes sweeping the same proposal at once needs no locking,
        and that is a claim about `StoreMediaProposal` rather than about
        timing.** It *refuses* an already-stored proposal instead of being
        idempotent, and `MediaAcceptWorker` reads that refusal back as its own
        success signal -- so the loser of a race records nothing and reports
        success. The cost of not locking is a duplicated download, bounded by
        the number of processes; the blob store is content-addressed, so the
        bytes land on the same blob and nothing downstream can tell.

        Survives a sweep raising, because the timer is worth more than any one
        sweep: a projection that is briefly unreadable would otherwise kill
        reconciliation for the life of the process, silently, which is the
        exact defect B99 is about. `asyncio.CancelledError` is a
        `BaseException` and so is *not* caught here -- deliberately, and the
        reason for `except Exception` rather than a bare `except`: a sweep
        that swallowed cancellation would outlive `close()`.
        """
        while True:
            await asyncio.sleep(random.uniform(0, self.media_reconcile_interval))
            try:
                await self.media_accept_reconciler.run()
            except Exception:
                logger.exception("periodic media reconciliation sweep failed")

    def turns_tools(self) -> tuple[BaseTool, ...]:
        """The tools available to this instance's agent, for tests that assert on them.

        Reaches into the executor's public `tools` property rather than a
        parallel copy: the executor's tuple is the one actually bound to the
        model, so this is what a test needs to check against."""
        return self.service._executor.tools

    async def summaries_caught_up(self) -> None:
        """Wait until the `/sessions` projection has seen everything appended.

        The read model is eventually consistent by construction -- a turn
        commits to the log and the projection follows -- which is invisible to
        a person clicking around and maddening to a test. This is the seam that
        makes the lag addressable rather than something to sleep through.
        """
        await self.summaries.caught_up()

    async def topics_caught_up(self) -> None:
        """Block until the topic tables have seen everything appended so far.

        Load-bearing rather than a test affordance, for the reason the corpus
        equivalent is: an autonomous round records a look and then asks for the
        next topic, and the gap between the append and the row is exactly where
        it would be handed back the topic it just finished.
        """
        await self.topics.caught_up()

    async def corpus_caught_up(self) -> None:
        """Wait until the corpus projection has seen everything appended.

        The same seam `summaries_caught_up` provides, for the same reason: a
        `remember` commits to the log and the table follows, so a caller that
        stores a document and immediately lists it would otherwise be racing
        the projection.
        """
        await self.corpus.caught_up()

    async def interaction_log_caught_up(self) -> None:
        """Wait until `interaction_events` has seen every appended event.

        For tests. Nothing in production waits on this -- the browser is not
        told when its batch landed, and could not use the answer.
        """
        await self.interaction_log.caught_up()

    async def reconciled(self) -> None:
        """Wait until startup reconciliation has finished, if it was scheduled.

        The same seam `summaries_caught_up` is, and for the same reason: the
        work is deliberately off the startup path, which is invisible to a
        person and untestable without this -- and a reconciliation observable
        only by sleeping is one that would rot.

        Returns immediately if `start()` has not run. Never raises what the
        reconciliation hit: `MediaAcceptReconciler.run` is total by
        construction (its docstring says why), so there is nothing here to
        re-raise.
        """
        for task in self._reconciliation:
            await task

    async def close(self) -> None:
        """Stop anything still running, then let go of the store.

        Cancelling first means an in-flight turn unwinds into a recorded
        failure rather than being abandoned mid-write. The projection stops
        before the store it reads through does, for the same reason.
        `detach_project` is safe to call whether or not anything is attached.

        Runs stop before turns do, and that order is the point: a run asked to
        stop finishes the round it is in, and a turn cancelled underneath it
        would make that round a recorded failure rather than the last one. The
        wait is bounded by whatever the in-flight turn takes.
        """
        # Reconciliation is cancelled rather than awaited, and it goes first
        # because it reads through the projections and the store stopped
        # below. Cancelling loses nothing: the proposal it was working on
        # stays `accepted`, which is precisely the state the next `start()`
        # reconciles -- whereas awaiting would hold shutdown for as long as
        # the download it is in the middle of.
        for task in self._reconciliation:
            task.cancel()
        self._reconciliation.clear()
        # The periodic sweep goes with it, and for a stronger reason: it never
        # finishes on its own, so anything short of cancelling it here leaves a
        # task reading through a stopped projection and a closed store for the
        # life of the event loop. Cancelled rather than awaited for the same
        # reason as above -- mid-download it would hold shutdown, and the
        # proposal it abandons stays `accepted`, which the next sweep or the
        # next `start()` reconciles.
        for task in self._sweep:
            task.cancel()
        self._sweep.clear()
        # Every step runs, whatever the ones before it did (B10). The list was
        # a straight run of `await`s, so the first raise skipped everything
        # under it -- and the two things furthest down are the ones that leak
        # hardest: `detach_project` releases a Neo4j driver, and `close_all`
        # releases every graph store this instance ever opened. A shutdown
        # path that stops at the first problem is a shutdown path that leaks
        # most when something has already gone wrong, which is exactly when
        # nobody is reading the traceback.
        #
        # Order is unchanged and still load-bearing: stops before cancels
        # (see above), projections before the store they read through, and the
        # two graph releases last. Failures are collected rather than dropped
        # and re-raised together at the end, so `close()` still fails loudly --
        # swallowing them would turn one leak into a silent one.
        await _close_every_step(
            ("research", self.research.stop_all),
            ("turns", self.turns.cancel_all),
            ("summaries", self.summaries.stop),
            ("corpus", self.corpus.stop),
            ("topics", self.topics.stop),
            ("definitions", self.definitions.stop),
            ("ontology", self.ontology.stop),
            # Grouped with the projections above rather than beside the
            # interaction log, which it superficially resembles: those two
            # follow *different* stores, and this one follows the sessions
            # store like its four neighbours here. It has to stop before
            # `service` closes that store underneath it.
            ("tenants", self.tenants.stop),
            ("catalog", self._catalog_runner.stop),
            ("course", self._course_runner.stop),
            ("blurb cache", self._blurb_cache.close),
            ("outline cache", self._outline_cache.close),
            ("art store", self.art_store.close),
            ("candidate art store", self._candidate_art_store.close),
            ("project summaries", self.project_summaries.close),
            ("media proposals", self.media_proposals.stop),
            ("asks", self.asks.stop),
            ("authoring", self.authoring.stop),
            ("dialogues", self.dialogues.stop),
            ("users", self.users.stop),
            ("interaction log", self.interaction_log.stop),
            ("interaction store", self._interaction_store.close),
            # Both settings stores, as one step -- see `SettingsDeps.close`.
            # New here as of W-C2 and not optional: until this branch the
            # override table was opened only by a settings *route*, so almost
            # no test ever opened it and the omission cost nothing. Resolution
            # now happens at `open_graph`, which every attach reaches, so the
            # connection is opened in nearly every test -- and `aiosqlite`'s
            # worker thread is non-daemon, so leaking one per test is a
            # process that runs the suite and then never exits.
            ("settings", self.settings.close),
            ("service", self.service.close),
            # Unconditional, whether this client was built here or handed in
            # by a test: whoever built it, `Application` owns it for its
            # lifetime, and an unclosed `httpx.AsyncClient` leaks its
            # connection pool.
            ("media http client", self._media_http_client.aclose),
            ("attached project", self.detach_project),
            # Every project this instance ever opened a graph for, not just
            # the one that happened to be attached -- `detach_project` above
            # only releases that one, and a read route can have opened others
            # through `graphs` directly without ever attaching them.
            ("graphs", self.graphs.close_all),
        )
