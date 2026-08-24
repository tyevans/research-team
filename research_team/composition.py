"""The composition root: the one place that picks concrete adapters.

Every other module receives what it needs. This module is where SQLite,
deepagents, and the environment are chosen and wired to the ports -- so
swapping any of them is an edit here and nowhere else.
"""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

# Imported for its side effect as much as its names: redstring registers its
# event types at import time, and the session store may hold them -- the
# `Document` and `Consolidation` streams live in the same SQLite file as
# sessions. A read that meets a `DocumentExtracted` without this import raises
# `EventTypeNotFoundError`, including on the "no project at all" path, where
# nothing else would have pulled redstring in.
import httpx
import redstring.events  # noqa: F401
from eventsource import (
    InMemoryEventBus,
    SQLCheckpointRepository,
    SQLDLQRepository,
    create_async_engine,
)
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.application.subscriptions import SubscriptionConfig, SubscriptionManager
from eventsource.observability import Tracer
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from redstring import SlidingWindowChunker
from redstring.llm.adapters.langchain import LangChainLlmProvider

from research_team.application import (
    DEFAULT_SYSTEM_PROMPT,
    ApprovalPort,
    AutonomyPolicy,
    ContextStrategy,
    DispatchesInFlight,
    ElideToolResults,
    ExtractionChannel,
    FullHistory,
    KnowledgeAttachment,
    LiveFeed,
    ProjectGraphs,
    ResearchRunDriver,
    ResearchSupervisor,
    SessionService,
    SummaryProjects,
    TopicRoundRunner,
    TurnActivityBuffer,
    TurnSupervisor,
    WorkerRoster,
)
from research_team.application.artifacts import stage_artifact_instructions
from research_team.application.ask import AskService, ConversationRegistry
from research_team.application.autonomy import ADVANCE_STAGE_TOOL, FETCH_TOOL
from research_team.application.blobs import BlobStorePort
from research_team.application.check_telemetry_read import CheckTelemetryReadPort
from research_team.application.components import component_guidance
from research_team.application.corpus_editing import CorpusEditor
from research_team.application.course_authoring import CourseAuthor
from research_team.application.course_catalog import (
    CachedBlurb,
    CachedOutline,
    CatalogService,
)
from research_team.application.course_realization import CourseService, RealizedCourse
from research_team.application.document_extraction import DocumentExtractor
from research_team.application.entity_definitions import DefinitionService
from research_team.application.grants import GrantRegistry
from research_team.application.knowledge import KnowledgeError, SourceRef, source_id_for_url
from research_team.application.media_acquisition import (
    MediaAcceptReconciler,
    MediaAcceptWorker,
)
from research_team.application.media_curation import MediaCurationTextPort, MediaSearchPort
from research_team.application.ontology_discovery import OntologyDiscoveryService
from research_team.application.perception import MediaPerceiver, PerceptionPort
from research_team.application.ports import GateReview
from research_team.application.prompts import (
    DEFAULT_PROMPT_ROOT,
    DirectoryPromptLibrary,
    prompting_for,
)
from research_team.application.session_service import NO_SEARCH_CLAUSE
from research_team.application.socratic import DialogueRegistry, SocraticDialogueService
from research_team.application.stage_exit import (
    findings_path,
    gate_context,
    refusal,
    render_review,
    review_stage,
)
from research_team.application.stage_runner import StageRunner
from research_team.application.topic_dispatch import TopicDispatcher
from research_team.application.topic_read import TopicReadPort
from research_team.application.topic_seeding import TopicSeeder
from research_team.application.topics import TOPICS_PROMPT
from research_team.domain import ProjectState, Session, SessionPurpose, current_stage_of
from research_team.domain.commands import RecordStageReview, WriteFile
from research_team.domain.course import Course
from research_team.domain.course_authoring_run import CourseAuthoringRun
from research_team.domain.media_proposals import MediaProposals
from research_team.domain.research_run import Budget
from research_team.domain.topic import Topic
from research_team.domain.workflow import Preset
from research_team.infrastructure import config
from research_team.infrastructure.agent import (
    DeepAgentTurnExecutor,
    build_embedding_provider,
    build_extraction_model,
    build_model,
)
from research_team.infrastructure.agent.ask_agent import DeepAgentAskExecutor
from research_team.infrastructure.agent.compaction import SummarizingStrategy
from research_team.infrastructure.agent.component_feedback import ComponentFeedback
from research_team.infrastructure.agent.corpus_tools import (
    CORPUS_PROMPT,
    build_corpus_tools,
)
from research_team.infrastructure.agent.definition_model import ChatModelDefinitionText
from research_team.infrastructure.agent.delegation import (
    DEFAULT_SUBAGENTS,
    DELEGATION_PROMPT,
)
from research_team.infrastructure.agent.fetch import (
    FETCH_CORPUS_PROMPT,
    FETCH_PROMPT,
    build_fetch_tool,
)
from research_team.infrastructure.agent.fetch_media import build_fetch_media_tool
from research_team.infrastructure.agent.knowledge_tools import (
    KNOWLEDGE_PROMPT,
    build_knowledge_tools,
)
from research_team.infrastructure.agent.media_curation_adapter import build_curation_ports
from research_team.infrastructure.agent.ontology_model import ChatModelOntologyText
from research_team.infrastructure.agent.recall import PageMemo, Recall
from research_team.infrastructure.agent.search import (
    SEARCH_PROMPT,
    SearchAttempts,
    build_search_tool,
)
from research_team.infrastructure.agent.search_middleware import SearchAttemptsMiddleware
from research_team.infrastructure.agent.socratic_agent import DeepAgentSocraticExecutor
from research_team.infrastructure.agent.source_mount import mounted_sources
from research_team.infrastructure.agent.stage_middleware import (
    StageMiddleware,
    managed_tools_for,
)
from research_team.infrastructure.agent.topic_tools import (
    RepositoryTopics,
    build_topic_tools,
)
from research_team.infrastructure.agent.workflow_tools import (
    WORKFLOW_PROMPT,
    EndTurnOnStageAdvance,
    build_workflow_tools,
)
from research_team.infrastructure.interaction.recorder import EventStoreInteractionRecorder
from research_team.infrastructure.knowledge.blurb_writer import ModelBlurbWriter
from research_team.infrastructure.knowledge.catalog_recorder import (
    EventStoreCatalogFeatureRecorder,
)
from research_team.infrastructure.knowledge.co_mentions import CoMentionIndex
from research_team.infrastructure.knowledge.entity_cards import index_cards
from research_team.infrastructure.knowledge.entity_embeddings import (
    refresh_project_embeddings,
)
from research_team.infrastructure.knowledge.graph_reader import ProjectGraphReader
from research_team.infrastructure.knowledge.library_art import LibraryArtProvider
from research_team.infrastructure.knowledge.markdown_table_chunker import MarkdownTableChunker
from research_team.infrastructure.knowledge.ontology_recorder import EventStoreOntologyRecorder
from research_team.infrastructure.knowledge.outline_writer import ModelOutlineWriter
from research_team.infrastructure.knowledge.rebuild import rebuild_graph
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from research_team.infrastructure.knowledge.seeded_art import SeededArtProvider
from research_team.infrastructure.knowledge.stores import (
    build_card_vector_store,
    build_chunk_store,
    build_graph_store,
    build_vector_store,
)
from research_team.infrastructure.knowledge.svg_artist import ModelSvgArtist
from research_team.infrastructure.knowledge.type_plurality_grouper import TypePluralityGrouper
from research_team.infrastructure.knowledge.usage_reader import UsageReader
from research_team.infrastructure.perception.readeverything_adapter import (
    build_perception_adapter,
)
from research_team.infrastructure.persistence import (
    CorpusRunner,
    EventStoreSessionRepository,
    SessionSummaryRunner,
    TopicRunner,
    build_ask_conversation_repository,
    build_corpus_repository,
    build_judgements_repository,
    build_learner_progress_repository,
    build_research_run_repository,
    build_topic_repository,
)
from research_team.infrastructure.persistence.blob_store import FilesystemBlobStore
from research_team.infrastructure.persistence.check_telemetry import CheckTelemetryRunner
from research_team.infrastructure.persistence.check_telemetry_reader import (
    ProjectCheckTelemetryReader,
)
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.infrastructure.persistence.definition_cache import ProjectDefinitionCache
from research_team.infrastructure.persistence.event_store import (
    build_course_authoring_run_repository,
    build_course_repository,
    build_socratic_dialogue_repository,
)
from research_team.infrastructure.persistence.interaction_log import InteractionLogRunner
from research_team.infrastructure.persistence.project_workflow import ProjectWorkflow
from research_team.infrastructure.persistence.read_models import (
    ArtRow,
    ArtStore,
    AskConversationRunner,
    AuthoringRunRunner,
    CandidateArtRow,
    CandidateArtStore,
    CatalogFeatureProjection,
    CatalogFeatureStore,
    CourseBlurbStore,
    CourseOutlineStore,
    CourseProjection,
    CourseRow,
    CourseStore,
    EntityDefinitionRunner,
    MediaProposalRunner,
    OntologyRunner,
    SocraticDialogueRunner,
)
from research_team.infrastructure.persistence.topic_reader import ProjectTopicReader
from research_team.infrastructure.telemetry import build_tracer
from research_team.interfaces.web.art_sweep import ArtSweep
from research_team.interfaces.web.blurb_sweep import BlurbSweep
from research_team.workflows import PRESETS

logger = logging.getLogger(__name__)

WORKFLOW_DRIVEN = frozenset({SessionPurpose.CHAT, SessionPurpose.WORKFLOW_STAGE})
"""The purposes a workflow attaches to.

An allowlist rather than a denylist of the unattended kinds, so a purpose
added later gets no workflow until somebody says it should. The failure
directions are not symmetric: a new unattended kind that wrongly *keeps* the
workflow is the bug this whole change removes and is invisible -- nothing
raises, the stage prompt simply argues with the round prompt and the model
picks one. A new kind that wrongly *loses* it is a missing stage prompt, which
whoever added the kind sees on the first turn.
"""


class _CatalogFeatureRunner:
    """Keeps `catalog_features` following the log, over the application's own
    event store and publisher rather than a second one -- catalog events
    (`CourseFeatured`/`CourseUnfeatured`) sit on their own aggregate type and
    stream, so this only ever needs to agree with `catalog_recorder`'s
    writes over the same file, matching `CatalogFeatureProjection`'s own
    reasoning.

    Mirrors `OntologyRunner` in shape, but is not one: `Application` exposes
    `catalog_features` as the `CatalogFeatureStore` itself, not a runner
    wrapping it, per the contract Task 9's reviewer wrote down -- so this
    class lives here instead, private, and `catalog_features` below is a
    property reading through its `features` attribute. `Application` is
    `frozen=True` (see `_initial_project_id`'s docstring), so `start()`
    cannot rebind a field to the store once it is open; a property reading
    through a mutable holder is what the rest of this class already does for
    exactly that reason.
    """

    def __init__(self, store: SQLiteEventStore, bus: InMemoryEventBus, db_path: str) -> None:
        self._store = store
        self._bus = bus
        self._db_path = db_path
        self.features: CatalogFeatureStore | None = None
        self._manager: SubscriptionManager | None = None
        self._subscription = None

    async def start(self) -> None:
        if self._manager is not None:
            return
        await self._store.current_position()
        engine = create_async_engine(f"sqlite+aiosqlite:///{self._db_path}")
        checkpoints = SQLCheckpointRepository(engine)
        dlq = SQLDLQRepository(engine)
        self.features = await CatalogFeatureStore.open(self._db_path)
        projection = CatalogFeatureProjection(self.features, checkpoints, dlq)
        self._manager = SubscriptionManager(self._store, self._bus, checkpoints, dlq_repo=dlq)
        self._subscription = await self._manager.subscribe(
            projection, SubscriptionConfig(start_from="checkpoint")
        )
        results = await self._manager.start()
        failures = {name: err for name, err in results.items() if err is not None}
        if failures:
            raise RuntimeError(f"the catalog feature projection failed to start: {failures}")

    async def caught_up(self, timeout: float = 10.0) -> None:
        """A test affordance, matching `definitions_caught_up` and the rest:
        waits until the projection has replayed everything appended so far,
        rather than everything that will ever be appended."""
        if self._manager is None:
            return
        target = await self._store.current_position()
        if target is None:
            return
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if self._subscription.last_processed_position is not None and (
                self._subscription.last_processed_position >= target
            ):
                return
            await asyncio.sleep(0.01)
        raise TimeoutError("the catalog feature projection did not catch up in time")

    async def stop(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
        if self.features is not None:
            await self.features.close()


class _CourseRunner:
    """Keeps `courses` following the log, mirroring `_CatalogFeatureRunner`
    exactly and for the same reason: `CourseStore.open` needs a running event
    loop, so it opens in `start()`, and `Application` is `frozen=True`
    (see `_initial_project_id`'s docstring), so `courses` below has to read
    through this runner's mutable `courses` attribute rather than being a
    field `start()` could rebind once the store is open.

    Over the application's own event store and publisher, not a second one --
    `CourseRealized`/`CourseAbandoned` sit on `Course`'s own aggregate type
    and stream, so this only ever needs to agree with `course_repository`'s
    writes over the same file.
    """

    def __init__(self, store: SQLiteEventStore, bus: InMemoryEventBus, db_path: str) -> None:
        self._store = store
        self._bus = bus
        self._db_path = db_path
        self.courses: CourseStore | None = None
        self._manager: SubscriptionManager | None = None
        self._subscription = None

    async def start(self) -> None:
        if self._manager is not None:
            return
        await self._store.current_position()
        engine = create_async_engine(f"sqlite+aiosqlite:///{self._db_path}")
        checkpoints = SQLCheckpointRepository(engine)
        dlq = SQLDLQRepository(engine)
        self.courses = await CourseStore.open(self._db_path)
        projection = CourseProjection(self.courses, checkpoints, dlq)
        self._manager = SubscriptionManager(self._store, self._bus, checkpoints, dlq_repo=dlq)
        self._subscription = await self._manager.subscribe(
            projection, SubscriptionConfig(start_from="checkpoint")
        )
        results = await self._manager.start()
        failures = {name: err for name, err in results.items() if err is not None}
        if failures:
            raise RuntimeError(f"the course projection failed to start: {failures}")

    async def caught_up(self, timeout: float = 10.0) -> None:
        """A test affordance, matching `_CatalogFeatureRunner.caught_up`:
        waits until the projection has replayed everything appended so far,
        rather than everything that will ever be appended."""
        if self._manager is None:
            return
        target = await self._store.current_position()
        if target is None:
            return
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if self._subscription.last_processed_position is not None and (
                self._subscription.last_processed_position >= target
            ):
                return
            await asyncio.sleep(0.01)
        raise TimeoutError("the course projection did not catch up in time")

    async def stop(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
        if self.courses is not None:
            await self.courses.close()


class _LazyBlurbCache:
    """`BlurbCachePort` over `CourseBlurbStore`, opened on first use.

    `CatalogService` is built inside `build_application`, before any event
    loop is running -- `start()`'s own docstring says why nothing here can
    open an aiosqlite connection until then. Unlike `catalog_features`, which
    is read through a property because `catalog` itself (not this cache) is
    what a route holds a reference to, this port is handed directly to
    `CatalogService` at construction, so it has to defer the open internally
    rather than being swapped in later. Guarded by a lock so two concurrent
    card renders do not each open their own connection to the same file.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._store: CourseBlurbStore | None = None
        self._lock = asyncio.Lock()

    async def _opened(self) -> CourseBlurbStore:
        if self._store is None:
            async with self._lock:
                if self._store is None:
                    self._store = await CourseBlurbStore.open(self._db_path)
        return self._store

    async def get(self, project_id: UUID, slug: str) -> CachedBlurb | None:
        store = await self._opened()
        row = await store.get(project_id, slug)
        if row is None:
            return None
        return CachedBlurb(
            text=row.text,
            title=row.title,
            membership_hash=row.membership_hash,
            model=row.model,
            generated_at=datetime.fromisoformat(row.generated_at),
        )

    async def all_for_project(self, project_id: UUID) -> dict[str, CachedBlurb]:
        store = await self._opened()
        rows = await store.all_for_project(project_id)
        return {
            slug: CachedBlurb(
                text=row.text,
                title=row.title,
                membership_hash=row.membership_hash,
                model=row.model,
                generated_at=datetime.fromisoformat(row.generated_at),
            )
            for slug, row in rows.items()
        }

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
        store = await self._opened()
        await store.put(project_id, slug, title, text, membership_hash, model, generated_at)

    async def close(self) -> None:
        if self._store is not None:
            await self._store.close()


class _LazyArtStore:
    """`ArtStore`, opened on first use -- `_LazyBlurbCache`'s exact shape and
    reason, but exposing the store's own methods directly rather than a
    narrower port. Nothing in this increment builds an `ArtGeneratorPort`
    adapter yet (that is a sibling task's job), so there is no port to defer
    behind; this exists solely so `create_app`'s `art_store` parameter has
    something to serve `/api/art/{art_id}.svg` from without opening a
    connection before uvicorn's event loop exists -- see `_LazyBlurbCache`'s
    docstring for why that ordering matters.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._store: ArtStore | None = None
        self._lock = asyncio.Lock()

    async def _opened(self) -> ArtStore:
        if self._store is None:
            async with self._lock:
                if self._store is None:
                    self._store = await ArtStore.open(self._db_path)
        return self._store

    async def get(self, art_id: UUID) -> ArtRow | None:
        store = await self._opened()
        return await store.get(art_id)

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
        store = await self._opened()
        await store.put(art_id, svg, description, tags, palette, created_at, source, uses)

    async def all(self) -> list[ArtRow]:
        store = await self._opened()
        return await store.all()

    async def increment_uses(self, art_id: UUID) -> None:
        store = await self._opened()
        await store.increment_uses(art_id)

    async def close(self) -> None:
        if self._store is not None:
            await self._store.close()


class _LazyCandidateArtStore:
    """`CandidateArtStore`, opened on first use -- `_LazyArtStore`'s exact
    shape and reason. A second small wrapper rather than one class managing
    both tables: `ArtStore` and `CandidateArtStore` are two different
    connections to two different tables in `read_models.py` already, and
    `_LazyOutlineCache`'s own docstring gives the precedent for keeping a
    lazy wrapper one store to one class."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._store: CandidateArtStore | None = None
        self._lock = asyncio.Lock()

    async def _opened(self) -> CandidateArtStore:
        if self._store is None:
            async with self._lock:
                if self._store is None:
                    self._store = await CandidateArtStore.open(self._db_path)
        return self._store

    async def get(self, project_id: UUID, slug: str) -> CandidateArtRow | None:
        store = await self._opened()
        return await store.get(project_id, slug)

    async def put(self, project_id: UUID, slug: str, art_id: UUID) -> None:
        store = await self._opened()
        await store.put(project_id, slug, art_id)

    async def close(self) -> None:
        if self._store is not None:
            await self._store.close()


class _LazyOutlineCache:
    """`OutlineCachePort` over `CourseOutlineStore`, opened on first use.

    `_LazyBlurbCache`'s shape exactly, and for the same reason: `CourseService`
    is built inside `build_application`, before any event loop is running, so
    the port handed to it at construction has to defer opening its own
    connection rather than being swapped in once one exists. A separate class
    rather than a generic wrapper over both stores -- the two stores' `get`/
    `put` return different row shapes (`CourseOutlineRow.sections` is a list of
    dicts; `CachedOutline.sections` is a tuple of pairs), so the translation is
    the whole body of each method and sharing it would buy nothing.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._store: CourseOutlineStore | None = None
        self._lock = asyncio.Lock()

    async def _opened(self) -> CourseOutlineStore:
        if self._store is None:
            async with self._lock:
                if self._store is None:
                    self._store = await CourseOutlineStore.open(self._db_path)
        return self._store

    async def get(self, project_id: UUID, slug: str) -> CachedOutline | None:
        store = await self._opened()
        row = await store.get(project_id, slug)
        if row is None:
            return None
        return CachedOutline(
            promise=row.promise,
            sections=tuple((s["heading"], s["summary"]) for s in row.sections),
            membership_hash=row.membership_hash,
            model=row.model,
            generated_at=datetime.fromisoformat(row.generated_at),
        )

    async def put(
        self,
        project_id: UUID,
        slug: str,
        promise: str,
        sections: tuple[tuple[str, str], ...],
        membership_hash: str,
        model: str,
        generated_at: datetime,
    ) -> None:
        store = await self._opened()
        await store.put(
            project_id,
            slug,
            promise,
            [{"heading": heading, "summary": summary} for heading, summary in sections],
            membership_hash,
            model,
            generated_at,
        )

    async def close(self) -> None:
        if self._store is not None:
            await self._store.close()


class _RealizedCourses:
    """`RealizedCoursePort` joining `_CourseRunner`'s store with
    `AuthoringRunRunner.authored_session_for` -- the join `RealizedCoursePort`'s
    own docstring assigns to the adapter, not the port.

    Reads through `_CourseRunner` lazily, the same way `CatalogService`'s
    routes read through `catalog_features`: `CourseService` (this adapter's
    only caller) is built before `start()` has opened `courses`, so a request
    reaching this adapter before startup finishes raises rather than silently
    answering "nothing realized" -- the distinction `_started()` on
    `AuthoringRunRunner` already draws for the same reason.
    """

    def __init__(self, course_runner: _CourseRunner, authoring: AuthoringRunRunner) -> None:
        self._course_runner = course_runner
        self._authoring = authoring

    def _store(self) -> CourseStore:
        store = self._course_runner.courses
        if store is None:
            raise RuntimeError("the course projection has not been started")
        return store

    async def for_project(self, project_id: UUID) -> Sequence[RealizedCourse]:
        rows = await self._store().for_project(project_id)
        return tuple([await self._joined(project_id, row) for row in rows])

    async def get(self, project_id: UUID, slug: str) -> RealizedCourse | None:
        row = await self._store().get(project_id, slug)
        if row is None or row.abandoned:
            # `CourseStore.get` answers regardless of `abandoned` -- see its
            # own docstring -- but `RealizedCoursePort`'s contract
            # (`course_realization.py`) is that every implementation returns
            # only non-abandoned rows, so that filter belongs here.
            return None
        return await self._joined(project_id, row)

    async def _joined(self, project_id: UUID, row: CourseRow) -> RealizedCourse:
        authored_session_id = await self._authoring.authored_session_for(project_id, row.slug)
        return RealizedCourse(
            slug=row.slug,
            title=row.title,
            member_entity_ids=tuple(row.member_entity_ids),
            membership_hash=row.membership_hash,
            realized_at=row.realized_at,
            authored_session_id=authored_session_id,
        )


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

    topics: TopicRunner
    """Keeps the topic tables following the log. Idle until `start()`.

    A field for the same reason `corpus` is one: the queue is read by the
    agent through the tools attached with a project, and by anything driving an
    autonomous run, which shares nothing else with a session."""

    check_telemetry: CheckTelemetryRunner
    """Keeps `check_outcomes` following the log. Idle until `start()`.

    A field for the reason `corpus` is one, with the emphasis reversed: nothing
    *reads* this on the hot path -- `/checks` is a maintainer's occasional
    question -- but everything writes to it, on every gate, and a projection
    that is constructed and never started records nothing while looking wired.
    Exposing it here is what makes `rebuild()` and `failures()` reachable when
    the numbers turn out to disagree with the log."""

    definitions: EntityDefinitionRunner
    """Keeps cached entity definitions marked stale. Idle until `start()`.

    A field for `check_telemetry`'s reason and one more: it is not only a
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

    A field for `check_telemetry`'s reason -- a projection nobody would
    otherwise start -- and because `rebuild()` has to be reachable when the
    tables disagree with the log. Unlike `definitions`, nothing reads *through*
    this runner to write: the discovery service appends to the event store and
    the projection does the writing, so this is the read side only."""

    ontology_discoverers: Callable[[UUID], OntologyDiscoveryService]
    """One project's `OntologyDiscoveryService`, built fresh per call.

    A factory for `topic_readers`' reason: the project is bound at construction,
    so no caller can run a pass against a project it was not handed. Synchronous
    and never `None`, unlike `definition_readers` -- see `ontology_discoverer`
    in `build_application` for why nothing it needs can be absent."""

    media_proposals: MediaProposalRunner
    """Keeps the proposal tables following the log. Idle until `start()`.

    A field for `check_telemetry`'s reason -- a projection nobody would
    otherwise start, and `rebuild()`/`failures()` have to be reachable when
    the tables disagree with the log. Like `ontology`, nothing reads *through*
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

    check_telemetry_readers: Callable[[UUID], CheckTelemetryReadPort]
    """One project's `CheckTelemetryReadPort`, built fresh per call.

    A factory for `topic_readers`' reason: the project is bound at construction
    so no caller can read another project's measurements, and the CLI has no
    business knowing a reader is a runner plus a project id."""

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

    stage_runner: StageRunner
    """Drives a project's stages, asking at every boundary it reaches.

    A field and not a route, deliberately. `workflow-engine.md` §5 and
    `stage-boundaries.md` open question 1 both say the same thing: the runner
    should be built *after* a human has prompted a preset through by hand,
    because the thing that would falsify its design is a prompt, and no preset
    resolves end to end yet. Exposing it here makes it usable and testable
    without committing a front end to a button that would spend a budget on
    stages whose prompts do not exist. `TopicDispatcher` was reachable the
    same way before `/dispatch` existed.

    Built from the same `service`, `turns`, `approvals` and `policy` the rest
    of this module holds -- the policy especially, for the reason stated where
    it is constructed."""

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

    A field for `check_telemetry`'s reason -- a projection nobody would
    otherwise start -- and, like `ontology`, read-only: `ask` above appends to
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
        """A test affordance, matching `definitions_caught_up` and the rest:
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
        await self.check_telemetry.start()
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
        await self.interaction_log.start()
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

    async def check_telemetry_caught_up(self) -> None:
        """Wait until `check_outcomes` has seen every session event appended.

        A test affordance more than a production one, unlike its three
        neighbours: nothing in a run reads these numbers back, so nothing races
        the projection. It exists because a test that drives a gate and then
        asks `/checks` what happened would otherwise be asserting against
        whatever the projection had got to.
        """
        await self.check_telemetry.caught_up()

    async def interaction_log_caught_up(self) -> None:
        """Wait until `interaction_events` has seen every appended event.

        For tests. Nothing in production waits on this -- the browser is not
        told when its batch landed, and could not use the answer.
        """
        await self.interaction_log.caught_up()

    async def definitions_caught_up(self) -> None:
        """Wait until the definition cache has seen every event appended.

        A test affordance, like `check_telemetry_caught_up` and unlike the
        other two: nothing on the read path waits for staleness to land. The
        cost of not waiting in production is one extra read of text that was
        about to be marked stale, which is the same text the reader would
        have seen a moment earlier anyway.
        """
        await self.definitions.caught_up()
        await self.ontology.caught_up()

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
        await self.research.stop_all()
        await self.turns.cancel_all()
        await self.summaries.stop()
        await self.corpus.stop()
        await self.topics.stop()
        await self.check_telemetry.stop()
        await self.definitions.stop()
        await self.ontology.stop()
        await self._catalog_runner.stop()
        await self._course_runner.stop()
        await self._blurb_cache.close()
        await self._outline_cache.close()
        await self.art_store.close()
        await self._candidate_art_store.close()
        await self.media_proposals.stop()
        await self.asks.stop()
        await self.authoring.stop()
        await self.dialogues.stop()
        await self.interaction_log.stop()
        await self._interaction_store.close()
        await self.service.close()
        # Unconditional, whether this client was built here or handed in by a
        # test: whoever built it, `Application` owns it for its lifetime, and
        # an unclosed `httpx.AsyncClient` leaks its connection pool.
        await self._media_http_client.aclose()
        await self.detach_project()
        # Every project this instance ever opened a graph for, not just the
        # one that happened to be attached -- `detach_project` above only
        # releases that one, and a read route can have opened others through
        # `graphs` directly without ever attaching them.
        await self.graphs.close_all()


def _context_parts(
    mode: str, model: BaseChatModel, system_prompt: str
) -> tuple[ContextStrategy, tuple[dict, ...], str]:
    """Turn a mode name into a strategy, subagents, and a prompt suffix.

    The three modes treat the same problem differently: `elide` shortens what
    is replayed, `compact` replaces it with a summary, and `delegate` keeps it
    from accumulating by sending work to a fresh context. Only this function
    knows the mapping; everything else takes what it is given.
    """
    if mode == "elide":
        return (
            ElideToolResults(
                keep_results=config.context_keep_results(),
                clear_over_chars=config.context_clear_over_chars(),
            ),
            (),
            "",
        )
    if mode == "compact":
        return (
            SummarizingStrategy(
                model,
                trigger_tokens=config.context_trigger_tokens(),
                keep_messages=config.context_keep_messages(),
            ),
            (),
            "",
        )
    if mode == "delegate":
        # Delegation does not transform the history -- there is simply less of
        # it, because the expensive work happened somewhere else.
        return FullHistory(), DEFAULT_SUBAGENTS, DELEGATION_PROMPT
    return FullHistory(), (), ""


def _extraction_model(injected: BaseChatModel | None) -> BaseChatModel:
    """The chat model knowledge extraction runs on, given what the caller passed.

    An injected model is handed back untouched. `build_application(model=...)`
    is how tests supply fakes, and a fake is not a `ChatOpenAI` -- it has no
    `extra_body` to set, and rebuilding one here would quietly point extraction
    at a real endpoint the test never asked for. Wrapping the injected model in
    a copy carrying `extra_body` would be no better: nothing guarantees the
    fake can be copied, and a caller who injects a model has said which model
    they want used.

    A model this project built for itself is a `ChatOpenAI` against
    `config.base_url()`, so extraction gets its own with thinking turned off --
    see `build_extraction_model`. The agent's model is deliberately left
    alone; only extraction is measured to be better off not reasoning.
    """
    return injected if injected is not None else build_extraction_model()


def build_application(
    *,
    model: BaseChatModel | None = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    db_path: str | None = None,
    context_mode: str | None = None,
    tracer: Tracer | None = None,
    approvals: ApprovalPort | None = None,
    extractions: ExtractionChannel | None = None,
    dispatches: DispatchesInFlight | None = None,
    policy: AutonomyPolicy | None = None,
    project_id: UUID | None = None,
    grants: GrantRegistry | None = None,
    activity: TurnActivityBuffer | None = None,
    perception: PerceptionPort | None = None,
    media_http_client: httpx.AsyncClient | None = None,
    interaction_db_path: str | None = None,
) -> Application:
    """Wire everything over one event store.

    Creates no session: which session a caller is working on is the caller's
    business, and one application serves as many of them as ask.

    The repository backs both ports -- it is one connection to one log, read
    two ways -- so the service and the feed are always looking at the same
    events, with no chance of a live view lagging a different database.

    `grants` accepts an existing `GrantRegistry` for the same reason
    `approvals` does: `web.py` builds a `WebApprovals(grants=...)` *before*
    calling this function, and the two must share one registry or the gate
    and the tool would disagree about the same call -- the silent-failure
    mode this feature is most exposed to. `None` builds a fresh one, which is
    correct for the REPL (no `WebApprovals` to share with) and for every test
    that does not care.

    `activity` is the buffer every turn's provisional content flows through,
    and it arrives here for the same reason `approvals` does: `web.py` builds
    one `TurnActivity` and both halves of the channel must be that instance.
    The supervisor writes into it; the catch-up route reads out of it. `None`
    is the REPL's case and most tests' -- turns then run unbuffered, which is
    what happened on every path but the web one before this was wired.

    `perception` accepts an existing `PerceptionPort` for the same reason
    `approvals` does, and for one reason unique to this port: `build_perception_
    adapter()` builds a `ReadEverythingPerception`, whose *construction* touches
    no network -- capabilities are declared from configuration, not probed --
    but whose first `perceive()` does. `None` is correct for the REPL and for
    every test that does not perceive anything; a test that does must inject a
    fake here, exactly as the no-network guard tests in this module do, or it
    reaches whatever `AGENT_VISION_MODEL`/`AGENT_TRANSCRIBER_URL` happen to be
    set to in the environment the suite runs in.

    `media_http_client` accepts an existing `httpx.AsyncClient` for
    `MediaAcceptWorker`'s downloads, for the same reason `perception` does: a
    test hands in one built over `httpx.MockTransport`
    (`tests/application/test_media_acquisition.py`'s own `_client` helper) so
    accepting a proposal never reaches the network. `None` builds a real
    client, owned by this `Application` and closed in `close()`.
    """
    resolved_path = db_path if db_path is not None else config.default_db_path()
    resolved_interaction_path = (
        interaction_db_path
        if interaction_db_path is not None
        else config.interaction_db_path()
    )
    resolved_model = model if model is not None else build_model()
    # Extraction runs on its own model, not the agent's: it is the one job
    # here that is measurably better off not reasoning first.
    extraction_model = _extraction_model(model)
    mode = context_mode if context_mode is not None else config.context_mode()
    strategy, subagents, prompt_suffix = _context_parts(mode, resolved_model, system_prompt)
    resolved_policy = policy if policy is not None else AutonomyPolicy()
    resolved_grants = grants if grants is not None else GrantRegistry()
    # Synchronous, deliberately -- see `build_perception_adapter`'s own
    # docstring for why `build_application` is not `async def` for this one
    # port. Resolved here, beside the other three optional-port defaults,
    # rather than beside `document_extractor` below, so every override this
    # function accepts is decided in one place.
    resolved_perception = perception if perception is not None else build_perception_adapter()

    # Loaded once here, and allowed to raise: a prompt file that will not parse
    # is a broken installation, and the useful moment to learn that is startup,
    # exactly as `problems()` validates presets at import rather than at
    # selection. What does *not* raise is a ref with no file at all -- that is
    # the common case today (32 of 38) and `prompting_for` degrades it per
    # stage. The two are different facts: one says the library is wrong, the
    # other says the library is incomplete, and only the first is a reason to
    # refuse to start.
    prompt_library = DirectoryPromptLibrary.load(DEFAULT_PROMPT_ROOT)

    # Opened before the tools below so the knowledge adapter can share this
    # connection's event store and snapshot store rather than opening its own
    # (BACKLOG B5: a second `SQLiteSnapshotStore` leaks a non-daemon thread).
    repository = EventStoreSessionRepository.open(resolved_path)

    # Two tools leave the process, and they are withheld differently because
    # there are two different things to withhold them with.
    #
    # `fetch` is registered unconditionally: there is no instance to leave
    # unconfigured, and a research agent that can see five snippets and never
    # read a page is not much of one. Its floor of `ask` is the switch instead
    # -- present and discoverable, but it cannot reach anything until a person
    # says so once. See `TOOL_FLOORS`.
    #
    # `web_search` keeps its configuration switch: an instance is a real thing
    # someone has to stand up, and "unset means absent" is a stronger promise
    # than any gate, so there is no reason to trade it for one.
    # One memo for both network tools and for every session this application
    # serves. Process-wide rather than per-session because `build_fetch_tool`
    # is called once here -- and correct at that scope for the same reason it
    # is safe: it holds only responses from public URLs, which are the same
    # bytes whoever asked. Nothing project-scoped may ever go in it.
    recall = Recall()
    # One store, shared by both `fetch` builds exactly as `recall` is: it holds
    # only bytes from public URLs, which are the same whoever asked. Nothing
    # project-scoped may ever go in it.
    pages = PageMemo()
    tools: tuple[BaseTool, ...] = (build_fetch_tool(recall=recall, pages=pages),)
    prompt_suffix += FETCH_PROMPT

    # `None` when unconfigured, same as the tool itself -- `turn_middleware`
    # below only installs `SearchAttemptsMiddleware` when this is not `None`,
    # so a build with no SearXNG instance carries no middleware that resets a
    # counter for a tool it never registered.
    search_attempts: SearchAttempts | None = None
    searxng = config.searxng_url()
    if searxng is not None:
        # One instance, handed to both the tool and the middleware below --
        # not two `SearchAttempts()` calls. Two instances would mean the
        # middleware resets a counter the tool never reads and the tool's own
        # counter never resets, so an empty streak would silently outlive the
        # turn that produced it and eventually wedge `web_search` for good.
        search_attempts = SearchAttempts()
        tools += (
            build_search_tool(
                searxng,
                limit=config.searxng_results(),
                recall=recall,
                attempts=search_attempts,
            ),
        )
        prompt_suffix += SEARCH_PROMPT
    else:
        prompt_suffix += NO_SEARCH_CLAUSE

    # `None`/`None` when `searxng` is, matching `search_attempts` above: the
    # curation chain's search port needs the same instance the agent's own
    # `web_search` tool does, and a build with neither configured has nothing
    # for `MediaCurationService` to search with either. The text port is
    # gated the same way rather than built unconditionally, so the pair
    # answers `create_app`'s 503 check together instead of one half being
    # present for a service the other half can never actually run.
    media_curation_text: MediaCurationTextPort | None = None
    media_curation_search: MediaSearchPort | None = None
    if searxng is not None:
        # `extraction_model` -- the house pattern `ChatModelOntologyText` and
        # `ChatModelDefinitionText` also follow: one already-built model
        # instance, reused rather than constructing a second connection to
        # the same provider. `model_name=config.curation_model()`, not
        # `config.model_name()`, is the other half: `curation_model()` is a
        # documented, tested user-facing knob (`AGENT_CURATION_MODEL`, see
        # `docs/configuration.md`) that was never called anywhere, so setting
        # it changed no behaviour. The name threaded through here is only
        # ever used for `LangChainLlmProvider`'s tracing/logging label (see
        # `ChatModelOntologyText` for the same split) -- it does not select a
        # different model instance, since `extraction_model` is one shared
        # client regardless -- but a label that never reflected the
        # documented override was the bug, not the split itself.
        media_curation_text, media_curation_search = build_curation_ports(
            extraction_model,
            model_name=config.curation_model(),
            searxng_url=searxng,
            limit=config.searxng_results(),
        )

    if project_id is not None:
        # A `project_id=` at build time scopes the whole application to that
        # project, not just sessions started through `start_in_project` --
        # `create_session` on an application built this way still gets the
        # knowledge tools (the `_initial_project_id` path, attached at
        # `start()`), so its default prompt has to describe them too, the
        # same way `start_in_project`'s per-session prompt does. Otherwise a
        # session it creates has `remember` on the executor and no idea the
        # tool exists.
        prompt_suffix += KNOWLEDGE_PROMPT + CORPUS_PROMPT + FETCH_CORPUS_PROMPT + TOPICS_PROMPT

    resolved_tracer = tracer if tracer is not None else build_tracer()
    # Built here rather than beside `summaries` below because `open_graph`
    # closes over it: the corpus tools are attached with a project, and the
    # thing they read has to exist by the time that callable is defined.
    corpus = CorpusRunner(
        repository.store, resolved_path, repository.publisher, resolved_tracer
    )
    # The one `FilesystemBlobStore` this process builds. Every
    # `ProjectCorpusReader` below is handed this exact instance rather than
    # building its own -- two instances would each hold their own root, and a
    # test that repointed one would silently leave the other pointed at the
    # real `~/.research-team/blobs`, which is a bug that only shows up as a
    # test writing to a developer's home directory.
    blob_store = FilesystemBlobStore(config.blob_root())
    # Same reasoning as `corpus`: `open_graph` closes over it, so the thing the
    # topic tools read has to exist by the time that callable is defined.
    topics = TopicRunner(
        repository.store, resolved_path, repository.publisher, resolved_tracer
    )
    # Unlike its two neighbours nothing closes over this one -- no tool reads
    # check telemetry -- but it is built here anyway so that all four
    # projections over this store are constructed in one place and started by
    # one line in `start()`. A projection wired somewhere else is a projection
    # somebody forgets to start.
    check_telemetry = CheckTelemetryRunner(
        repository.store, resolved_path, repository.publisher, resolved_tracer
    )
    # The fifth projection over this store, built beside the other four for
    # the reason stated above them. It matters more here than for its
    # neighbours: this runner is *both* the thing that marks a definition
    # stale and the thing the read route caches through (see
    # `definition_reader` below), so a second instance would give the route
    # its own connection and its own view of `stale` -- the cache would then
    # go on serving text the invalidator had already marked untrustworthy,
    # which is precisely the state `stale` exists to make impossible.
    definition_invalidation = EntityDefinitionRunner(
        repository.store, resolved_path, repository.publisher, resolved_tracer
    )
    # The sixth, and unlike its neighbour above it is *only* a projection: the
    # discovery service writes through the event store, not through this
    # runner, so the read route and the projection share a connection here for
    # the ordinary reason rather than to keep a cache honest.
    ontology = OntologyRunner(
        repository.store, resolved_path, repository.publisher, resolved_tracer
    )
    # The seventh, built here for the reason stated above `check_telemetry`:
    # "all [N] projections over this store are constructed in one place and
    # started by one line in `start()`. A projection wired somewhere else is a
    # projection somebody forgets to start." Measured directly on this one --
    # `EntityDefinitionRunner`'s absence once shipped a fully green suite
    # behind an empty read model, and `tests/integration/
    # test_media_proposals_reach_the_read_model.py` exists to catch the same
    # failure here.
    media_proposals = MediaProposalRunner(
        repository.store, resolved_path, repository.publisher, resolved_tracer
    )
    # The eighth, built here with the other seven for the same reason, and it
    # is the one with the worst failure mode if it is not: an ask appends
    # whether or not anything is following, so a build missing this line
    # answers 200 with an empty history for every conversation anyone ever
    # had, and nothing anywhere raises.
    asks = AskConversationRunner(
        repository.store, resolved_path, repository.publisher, resolved_tracer
    )
    # The ninth, built here with the other eight and for the same reason, with
    # a worse failure mode than any of them: a dialogue appends whether or not
    # anything is following, so a build missing this line answers 200 with an
    # empty history for every dialogue anyone ever held -- AND makes every
    # resumed dialogue start over with a blank goal while telling the reader it
    # continued. `test_a_dialogue_survives_a_restart.py` is what fails.
    dialogues = SocraticDialogueRunner(
        repository.store, resolved_path, repository.publisher, resolved_tracer
    )
    # The tenth, built here with the other nine and for the same reason, with
    # the same failure mode as the ask's and a longer-lived consequence: an
    # authoring run appends whether or not anything is following, so a build
    # missing this line loses the area-to-session mapping for every course
    # anyone ever wrote -- permanently, because the files stay on the log with
    # nothing saying which session holds which area.
    # `tests/integration/test_an_authoring_run_survives_a_restart.py` is what
    # fails.
    authoring = AuthoringRunRunner(
        repository.store, resolved_path, repository.publisher, resolved_tracer
    )

    # A second store, and its own bus. Not a second projection over the
    # sessions store: `eventsource` derives a store id from the database
    # string and every position carries it, so nothing can order a position
    # from one against the other -- which is the boundary this feature wants
    # rather than an obstacle to it.
    #
    # Its own `InMemoryEventBus` for the same reason. Handing this runner the
    # sessions bus would give its subscription wake-ups about a log it is not
    # reading, and that fails as silence.
    interaction_store = SQLiteEventStore(resolved_interaction_path)
    interaction_bus = InMemoryEventBus()
    interaction_log = InteractionLogRunner(
        interaction_store,
        resolved_interaction_path,
        interaction_bus,
        resolved_tracer,
    )
    interaction_recorder = EventStoreInteractionRecorder(interaction_store, interaction_bus)

    async def running_workflow(
        session: Session,
    ) -> tuple[UUID, ProjectState, Preset] | None:
        """The workflow this session's run is under, or None if there is none.

        None is the answer for a session outside a project and for a project
        that never selected a workflow -- which is every project written before
        workflows existed. Those runs get exactly the agent they got before:
        no gate tool, no middleware, nothing to reason about.

        Folded off the `Project` aggregate on every turn rather than held
        anywhere, for the reason `_resolved_middleware` sets out at length: the
        checkpointer is per-turn, so the event log is the only place where
        "where does this run stand" survives, and it is deliberately the only
        place. A replay per turn is the price of not having two answers.

        Shared by the two callers below so they cannot disagree. A turn where
        the gate tool is bound but the stage filter is absent, or the reverse,
        would be a run gated by half a workflow -- and the failure would look
        like a model behaving oddly rather than like a wiring fault.
        """
        if session.state.purpose not in WORKFLOW_DRIVEN:
            # An autonomous round, a seeding turn or a dispatch turn. Three
            # things follow from returning None here, and the third is the one
            # nobody reported: no `advance_stage` (floored at `ask`, so an
            # unattended call is an approval nobody answers), no stage prompt
            # arguing with the round's own instructions, and no stage tool
            # denylist -- which on any stage declaring no `tools` of its own
            # was withdrawing `list_sources`, `read_source` and `graph_search`
            # from a round whose entire job is reading the corpus.
            return None
        project_id = session.state.project_id
        if project_id is None:
            return None
        state = (await repository.projects.load(project_id)).state
        if state.preset_id is None:
            return None
        preset = PRESETS.get(state.preset_id)
        if preset is None:
            # A preset that was shipped when the run started and has since been
            # renamed or withdrawn. Gating on a preset we do not have would
            # mean inventing one; running ungated is at least the behaviour the
            # project had before it chose, and it is visible in the log.
            logger.warning(
                "project %s runs unknown workflow %s; no stage gate applied",
                project_id,
                state.preset_id,
            )
            return None
        if state.preset_version != preset.version:
            # Gated by what is installed, not by what was selected. Editing a
            # preset is expected -- they are content -- and refusing to run
            # would strand every project mid-flight on an edit. The event log
            # keeps `preset_version`, so a later reader can still tell which
            # revision each stage was actually decided under.
            logger.info(
                "project %s selected %s v%s; running under installed v%s",
                project_id,
                preset.id,
                state.preset_version,
                preset.version,
            )
        return project_id, state, preset

    async def workflow_tools(session: Session) -> tuple[BaseTool, ...]:
        """`advance_stage`, for a run that has a workflow to advance through.

        Registered per turn rather than with the project's other tools, which
        is the awkward-looking half of this and the load-bearing half. A
        workflow is selected by `POST /api/projects/{id}/workflow`: it appends
        an event and returns, with no attachment to hang a tool registration
        off. Bound at attach time instead, the gate would be missing for the
        whole of the session that chose the workflow -- which is every session,
        the first time.

        Bound to one project through `ProjectWorkflow`, so the tool cannot be
        pointed at another run. The preset comes from the same fold the stage
        filter uses, so the stage the model is held to and the stage list the
        tool advances along are always the same list.
        """
        running = await running_workflow(session)
        if running is None:
            return ()
        project_id, _, preset = running
        return build_workflow_tools(
            ProjectWorkflow(repository.projects, project_id), preset=preset
        )

    async def granted_tools(session: Session) -> tuple[BaseTool, ...]:
        """A grant-bound `fetch`, for a session `resolved_grants` holds one for.

        Resolved per turn, from the one `GrantRegistry` this build shares
        with the approval gate (`interrupt_config`, below) and the driver
        that registers a run's grant when it starts (`start_run`) -- three
        consumers of one instance, which is the whole of what keeps the gate
        and this tool from disagreeing about the same call. Two registries
        would let a run's grant exist for the gate and not for the tool, or
        the reverse, and every unit test would still pass; see
        `application/grants.py` and the note beside `resolved_grants` above.

        `None` from `resolved_grants.get` means this session is not a
        registered run's session at all -- a person's own turn, or a run
        that has already stopped -- and the answer is nothing, leaving
        `fetch` (or, once a project is attached, `project_fetch`) exactly as
        it was. Shadowing here with an ungranted, grant-bound tool would turn
        off redirect-following and add a spend check to a session that was
        never a party to any of this.

        A *registered* session with an empty grant still gets one: an empty
        `FetchGrant` covers no host, so nothing new becomes reachable, but
        the tool built here also disables redirect-following for every call
        it makes (`fetch.py`'s `grant is not None` branch) -- a property an
        unattended run should have whether or not a person actually granted
        it hosts, not only once they do.

        Built with this project's corpus reader, mirroring `project_fetch`
        below -- otherwise a covered fetch under a grant would stop finding
        pages this project already has, for the whole time a grant is
        attached, which is a regression `_compose`'s shadowing would otherwise
        hide until someone noticed stale corpus reads.

        **The reader and the keeper follow the *project*, not the workflow.**
        This used to take the project id out of `running_workflow`'s first
        tuple slot, which reads as harmless and is not: it silently made both
        of them conditional on the project having selected a preset, so a run
        on a preset-less project already fetched with no corpus and saved
        nothing. Giving a round no workflow turned that latent bug into a live
        one on *every* round. `turn_sources` keys off `session.state.
        project_id` for the same reason and states it; this now matches.
        """
        grant = resolved_grants.get(session.aggregate_id)
        if grant is None:
            return ()
        project_id = session.state.project_id
        return (
            build_fetch_tool(
                recall=recall,
                corpus=(
                    ProjectCorpusReader(corpus, project_id, blob_store)
                    if project_id is not None
                    else None
                ),
                pages=pages,
                grant=grant,
                keep=_keeper(project_id) if project_id is not None else None,
            ),
        )

    def _keeper(project_id: UUID):
        """Save a fetched page to `project_id`'s corpus, without extracting it.

        Built here and nowhere else, which is what makes automatic saving a
        property of the *unattended run* rather than of fetching. This closure
        is only reached past `granted_tools`' `grant is None` check, and a
        registered grant is already this codebase's definition of a session
        nobody is watching (`GrantRegistry.is_unattended`). A person's own
        fetches keep the existing arrangement, where saving is a judgement the
        model makes with `remember_page` and `KNOWLEDGE_PROMPT` tells it not to
        save everything it happened to look at. Nobody is there to make that
        judgement in a run, and a page not saved before the round ends is gone.

        **`store_source`, not `ingest`.** An ingest is store-extract-
        consolidate and runs for minutes; calling it here would put that
        inside every `fetch`, and multiply extraction load by every page read
        rather than every page kept. The text is what cannot be recovered
        later -- the graph can always be built from it, by a `remember_page`
        on a page that proves to matter or by `/rebuild` -- so this saves the
        irrecoverable half at seconds rather than minutes and leaves the rest
        to a decision made with more information than "the page loaded".

        **The `source_id` is derived from the url, not the url.** This used to
        read "the url is the `source_id`", on the reasoning that the url is
        already what the page is and a prettier id would invent identity. The
        argument is sound and the consequence was not: a url contains `/`,
        `{source_id}` is one path segment, and uvicorn decodes the path before
        Starlette routes it -- so every per-source route 404'd for every page
        this closure ever kept. See `source_id_for_url` for the measurement.

        The cost of deriving it is that the model no longer knows the id from
        having typed the url, and `link_source` does not check that the id it
        is given exists -- so a model citing the url would write a dangling
        link, silently. `keep` returns the id for that reason and `fetch` puts
        it in the citation block; that return value is not decoration, it is
        what keeps the cite-immediately property the old id had for free.

        A later `remember_page` stores a second record of the same bytes, which
        `_store_document` allows deliberately -- worth knowing, since here it is
        one URI under two ids rather than the two-URIs case that rule was
        written for. `remember_page` now derives its id the same way, so the
        two ids agree and the second record is the same document rather than a
        differently-named one.
        """

        async def keep(url: str) -> str | None:
            retained = pages.get(url)
            # The attachment is process-wide and last-join-wins (see the web
            # layer's join), so `current` may belong to a project that is not
            # this run's. Without the guard a run's pages would land in
            # whichever project joined most recently -- silently, and visible
            # only as documents in the wrong corpus.
            knowledge = attachment.current
            if retained is None or knowledge is None:
                return None
            if attachment.attached_project_id != project_id:
                return None
            source_id = source_id_for_url(url)
            try:
                await knowledge.store_source(
                    SourceRef(
                        source_id=source_id,
                        text=retained.text,
                        uri=retained.uri,
                        title=retained.title,
                        published_at=retained.published_at,
                        fetched_at=retained.fetched_at,
                    )
                )
            except KnowledgeError:
                # Logged, not raised, and not reported to the model either.
                # The read succeeded and is about to be shown; a failed corpus
                # copy is worth less than the read, and a note about it in the
                # tool result would spend the model's attention on something it
                # did not ask for and cannot fix.
                logger.warning(
                    "could not keep %s for project %s", url, project_id, exc_info=True
                )
                # None on failure, so `fetch` cites nothing rather than an id
                # the corpus does not hold. The alternative -- returning the id
                # regardless -- would hand the model a citation that resolves to
                # a document the store just refused, which is the dangling link
                # this return value exists to prevent.
                return None
            return source_id

        return keep

    async def turn_tools(session: Session) -> tuple[BaseTool, ...]:
        """Everything this turn adds on top of the registered set.

        `granted_tools` last, so a grant-bound `fetch` shadows whatever
        `workflow_tools` returned too, per `_compose`'s by-name rule --
        though today the two never collide (`advance_stage` vs. `fetch`),
        naming an explicit order here is cheaper than trusting that stays
        true.
        """
        return (*await workflow_tools(session), *await granted_tools(session))

    async def turn_middleware(session: Session) -> tuple[AgentMiddleware, ...]:
        """This turn's middleware: component feedback always, the stage gate if any.

        `ComponentFeedback` is unconditional because a component can appear in
        any markdown file the agent writes, workflow or no workflow, and a
        session driving no preset is exactly where nobody is watching the
        transcript closely enough to notice a malformed widget.

        `managed_tools_for` takes the union across *every* stage rather than
        the current stage's list, because the middleware is a denylist: the
        executor registers all of them once at agent creation -- `factory.py`
        rejects a tool that was not -- and the gate withdraws what this stage
        does not claim. Narrowing this to one stage would leave the next
        stage's tools permanently visible.

        `advance_stage` is subtracted from that union, which is the deliberate
        answer to "should the gate tool be available in every stage". It should.
        A stage is a gate because leaving it *requires a human*, not because
        the model cannot ask -- `TOOL_FLOORS` floors this tool at `ask`, so
        every crossing is an interrupt somebody has to answer, in every stage,
        including the ones whose preset declares no `gate` of its own. Hiding
        it per stage would buy nothing (the human is already in the way) and
        cost the run its only way forward: a stage that claims a tool list, as
        `hybrid.step1.framing` does, would be enterable and not leavable.

        Subtracted here rather than in `StageMiddleware` because the middleware
        takes `managed_tools` as an argument precisely so this decision belongs
        to the caller -- the mechanism is "hide what the stage does not claim",
        and which tools are exempt from that is policy. Doing it here also
        means the exemption survives a preset that names `advance_stage` in
        some stage's `tools`, which would otherwise pull it into the managed
        set and hide it from every stage that did not.

        The instructions open with the stage's *methodology* -- the text its
        `prompt_ref` names, or a notice saying that ref has no file -- and the
        rest is mechanical. The artifact block says which files it owes, at
        which paths, with which frontmatter, derived from the stage's own
        declared outputs so a preset edit cannot leave the prompt describing
        files nothing looks for. `WORKFLOW_PROMPT` joins it because a bound
        tool nobody explained is a tool the model calls at the wrong moment:
        it says the gate asks a human, and that advancing is for when this
        stage's outputs exist, not for when the model has run out to say.

        Resolved per turn rather than once at build, for the same reason the
        middleware itself is: the executor outlives the stage. It also means a
        prompt edited mid-run lands on the next turn, which is the behaviour
        `DirectoryPromptLibrary` is explicitly built for -- the run in front of
        you is how you find out a prompt is wrong.
        """
        # Reads off the aggregate the tool just wrote through, so an `edit_file`
        # is validated against the document it produced rather than the
        # replacement it was given.
        base: tuple[AgentMiddleware, ...] = (
            ComponentFeedback(
                read=lambda path: session.state.files.get(path, {}).get("content")
            ),
            # In `base` rather than beside `StageMiddleware` below, because
            # `advance_stage` is bound whenever a workflow is running -- which
            # includes the arm where the stage is not one the preset defines
            # and no stage gate is applied at all. It is inert without a result
            # carrying `STAGE_ADVANCED`, so a session with no workflow pays a
            # scan of the trailing tool messages and nothing else.
            EndTurnOnStageAdvance(),
            # Only when `search_attempts` is not `None` -- the same switch
            # that decided whether `web_search` was registered at all.
            # Installing this unconditionally would reset a counter that
            # exists in every build, including ones with no search tool to
            # bound, which is harmless today but asserts a dependency this
            # build does not have.
            *(
                (SearchAttemptsMiddleware(search_attempts),)
                if search_attempts is not None
                else ()
            ),
        )

        running = await running_workflow(session)
        if running is None:
            return base
        project_id, state, preset = running
        stage = current_stage_of(state, preset)
        if stage is None:
            logger.warning(
                "project %s is at stage %s, which %s does not define; no stage gate applied",
                project_id,
                state.current_stage,
                preset.id,
            )
            return base
        prompting = prompting_for(stage, prompt_library)
        if prompting.missing is not None:
            # Warned every turn rather than once at build, because which stage
            # is current is a per-turn fact and a build-time survey would name
            # refs for stages this run may never reach. Noisy on a long
            # `hybrid.default` run, and that is the intended weight: twenty
            # unprompted stages should read as twenty problems.
            logger.warning(
                "project %s stage %s has no prompt for %s; running with the "
                "unprompted-stage notice instead of its methodology",
                project_id,
                stage.id,
                prompting.missing,
            )
        return (
            *base,
            StageMiddleware(
                stage,
                managed_tools=managed_tools_for(preset.stages) - {ADVANCE_STAGE_TOOL},
                instructions=(
                    # First, and the ordering is the argument the prompt
                    # contract rests on: a prompt must not name its paths, its
                    # frontmatter, the gate or its tools, because the three
                    # terms below already do. Placed after them it would read as
                    # a correction to the mechanics; placed before, the mechanics
                    # read as the means to what it asked for. `prompting_for`
                    # carries `role_line` with it, which is where `role`,
                    # `taxonomy_binding` and `over_generate_factor` are finally
                    # read after being declared and never consulted.
                    #
                    # Conditional on the text rather than unconditional, so a
                    # `FieldStage` -- no generator, no critic, nothing an agent
                    # executes -- does not open its instructions with a blank
                    # line where a methodology would be.
                    (f"{prompting.text}\n\n" if prompting.text else "")
                    + stage_artifact_instructions(preset, stage)
                    + WORKFLOW_PROMPT
                    # Derived from this stage's declared outputs, so a stage
                    # writing source claims is told nothing about widgets and a
                    # stage writing assessment items is told which ones an
                    # assessment is made of. Empty for most stages, by design.
                    + component_guidance(stage.outputs)
                ),
            ),
        )

    async def gate_review(session: Session, tool_name: str, args: dict) -> GateReview | None:
        """Run the stage's checks before anyone is asked to let it go.

        Only for `advance_stage`. Every other gated tool is gated because it
        costs money or leaves the process, and there is nothing about a web
        search for a human to have found out beforehand; running a course
        review for one would be work nobody reads.

        The findings artifact is written straight onto the aggregate rather
        than through the agent's filesystem, because the agent is suspended
        inside an interrupt at this point and has no turn in which to write
        anything.

        **It is not visible to the reviewer while they decide, and neither are
        the artifacts they are deciding about.** `session.execute` appends to
        `uncommitted_events`; the only thing that writes to the store is
        `_save_turn`, at the *end* of the turn, and `DeepAgentTurnExecutor`
        holds no repository with which to do otherwise. `GET
        /api/sessions/{id}/files` loads the aggregate from the store, so
        everything this turn has written -- the stage's outputs and this report
        -- is invisible to that route until the turn finishes. This paragraph
        replaces a claim that the file was "in the log and in the viewer
        immediately", which was never true.

        What the reviewer actually gets at the interrupt is `gate_context`,
        carried inline on the `ApprovalRequest` and delivered over SSE: the
        findings, the counts, the checks that could not run. That is real
        evidence and it is why the gate is not blind. What it is missing is the
        artifacts themselves. Closing that gap is a visibility change (put the
        stage's files in the context) rather than a durability one, and it is
        deliberately not made here -- see the PR that added
        `EndTurnOnStageAdvance`, which records why committing mid-turn was
        rejected.

        The *model* does not see the report until its next turn rebuilds state
        from the aggregate. That is the right way round -- the report is for
        the reviewer, and a model that could read its own report mid-decision
        would be tempted to argue with it.

        A run whose project has no workflow, or whose stage the preset does
        not define, gets `None`: there is no stage to check, and inventing one
        to have something to report would be the gate making things up.
        """
        if tool_name != ADVANCE_STAGE_TOOL:
            return None
        running = await running_workflow(session)
        if running is None:
            return None
        project_id, state, preset = running
        stage = current_stage_of(state, preset)
        if stage is None:
            return None
        review = review_stage(preset, stage, session.state.files)
        path = findings_path(preset, stage)
        session.execute(
            WriteFile(path=path, file_data={"content": render_review(review, preset)})
        )
        # Recorded here rather than in `review_stage`, for the reason
        # `_gate_and_advance` states: `course_progress` reviews a stage on
        # every course view, and counting those would make a fire rate a
        # measure of how often somebody opened a page.
        #
        # Both this and the `RecordToolDecision` that answers it land at
        # `_save_turn` on this path, milliseconds apart, which is why the event
        # carries `posed_by="tool"`: a consumer must report no duration rather
        # than an instant one. See BACKLOG.md B36.
        review_id = uuid4()
        session.execute(
            RecordStageReview(
                review_id=review_id,
                project_id=project_id,
                stage=stage.id,
                preset=preset.id,
                preset_version=str(preset.version),
                evaluated=[
                    {
                        "check": entry.check,
                        "severity": entry.severity,
                        "findings": entry.findings,
                    }
                    for entry in review.evaluated
                ],
                unimplemented=[
                    {"check": entry.check, "severity": entry.severity}
                    for entry in review.unimplemented_bindings
                ],
                posed_by="tool",
            )
        )
        return GateReview(
            context=gate_context(review, path),
            refusal=refusal(review),
            review_id=review_id,
        )

    # Shared by the turn executor, the ask executor, `document_extractor`,
    # `editor` and `perceiver`: all of them read one project's corpus the same
    # way, and separate lambdas would be separate places a future change to how
    # a reader is built could drift. Defined here rather than beside its first
    # user below because the executors above it need it too.
    corpus_readers = lambda target_project_id: ProjectCorpusReader(  # noqa: E731
        corpus, target_project_id, blob_store
    )

    async def turn_sources(session: Session) -> dict[str, Any]:
        """This turn's corpus mount, or nothing for a session outside a project.

        Keyed off `project_id` alone, not off `running_workflow`: a session's
        sources are searchable whether or not it ever selected a workflow, and
        hanging the mount off the workflow fold would have made `grep` answer
        differently for two projects holding the same documents.
        """
        project_id = session.state.project_id
        if project_id is None:
            return {}
        return await mounted_sources(corpus_readers(project_id))

    executor = DeepAgentTurnExecutor(
        resolved_model,
        subagents=subagents,
        tools=tools,
        policy=resolved_policy,
        approvals=approvals,
        middleware_provider=turn_middleware,
        tools_provider=turn_tools,
        sources_provider=turn_sources,
        gate_reviewer=gate_review,
        # The same registry `turn_tools` (via `granted_tools`) and `start_run`
        # (below) consult -- see `resolved_grants`'s own note for why there
        # is exactly one instance and what two would cost.
        grants=resolved_grants,
    )

    # The single owner of an open graph store per project: `open_graph` below
    # borrows from it rather than building its own, which is what lets a read
    # route see the same store extraction just wrote to instead of
    # a second one rebuilt independently and stale from the moment it exists.
    # One provider and one store for the process, not one per project.
    # `OpenAIEmbeddings` holds a connection pool and the vectors are tenant-
    # scoped inside the store, so a second set per project would buy isolation
    # that redstring already provides and pay for it in sockets. Built eagerly
    # rather than per `open_graph` so a misconfigured *name* -- the one failure
    # that does not need the network to detect -- surfaces at startup; the
    # endpoint itself is probed on first ingest, in the adapter.
    #
    # `None` everywhere when `AGENT_VECTOR_STORE=none`, which is the whole of
    # switching the feature off: nothing is constructed and nothing is probed.
    #
    # The *store* is no longer built here, and that is not a tidy-up.
    # `PgVectorStore.connect` is a coroutine which awaits `asyncpg.create_pool`
    # -- unlike `Neo4jGraphStore.connect`, which is an ordinary method building
    # a lazy driver -- and this function is synchronous, so building it here
    # produced an un-awaited coroutine that was passed onwards as if it were a
    # store. `ProjectGraphs` owns the open instead, because `open` is the first
    # `await` on the path to the store being used; the config is still *read*
    # here, so `AGENT_VECTOR_STORE=chroma` is still refused at startup rather
    # than at the first project open.
    vector_kind = config.vector_store()
    embedding_dimension = config.embedding_dimension()

    async def open_vector_store():
        return await build_vector_store(vector_kind, dimension=embedding_dimension)

    # The provider stays eager: it needs no network to build, and a
    # misconfigured model *name* is the one embedding failure that can be
    # caught at startup. The endpoint itself is probed on first ingest, in the
    # adapter.
    embedding_provider = build_embedding_provider() if vector_kind != "none" else None

    graphs = ProjectGraphs(
        build_store=lambda: build_graph_store(config.graph_store()),
        rebuild=lambda store, target_project_id, **rebuild_kwargs: rebuild_graph(
            store, feed=repository.store, project_id=target_project_id, **rebuild_kwargs
        ),
        open_vector_store=open_vector_store,
        # Taken from the provider rather than from `config.embedding_model()`,
        # so the name the fold filters on is the name the writer stamps on the
        # event. Two reads of the same setting is how those come to disagree,
        # and a fold filtering on a name nothing writes is a vector store that
        # silently stays empty.
        embedding_model=embedding_provider.model if embedding_provider is not None else None,
        # In-memory unconditionally, even where the consolidation store is
        # pgvector. Card embeddings are folded from `EntitiesEmbedded` at open
        # exactly as chunks are folded from `DocumentChunked`, so the store is
        # derived and losing it costs a replay rather than data -- which is the
        # argument `build_chunk_store` already makes for the corpus. A second
        # pgvector table would buy durability the log already provides and cost
        # a schema, a DSN and a width to keep in step.
        build_card_vectors=(
            (lambda: build_card_vector_store(dimension=embedding_dimension))
            if embedding_provider is not None
            else None
        ),
        # Same `embedding_dimension` read above for the vector store, not a
        # second `config.embedding_dimension()` call: a corpus and the vector
        # store built from two separate reads could disagree if the env
        # changed between them, and `build_chunk_store`'s docstring is
        # explicit that a corpus built under one width can't accept vectors
        # of another without a rebuild.
        build_chunk_store=lambda: build_chunk_store(
            config.chunk_store(), dimension=embedding_dimension
        ),
        # No config switch and no `kind`: the co-mention index is three fields
        # per passage with no backend to choose, folded from the same
        # `DocumentChunked` events the corpus is. Unconditional for the reason
        # `build_card_vector_store` is in-memory unconditionally -- it is
        # derived, so having it costs a fold and not a decision. Unlike the
        # corpus it does **not** honour `AGENT_CHUNK_STORE=none`: that setting
        # turns off holding passage *text*, which this does not hold.
        build_co_mentions=CoMentionIndex,
        # Cards are chunked with the same settings as the quotable corpus, and
        # for a different reason than symmetry: a card is short, so the window
        # almost never fires, and matching the corpus keeps one number to
        # reason about instead of two that happen to agree.
        index_cards=lambda *, graph, cards, tenant_id: index_cards(
            graph=graph,
            cards=cards,
            tenant_id=tenant_id,
            chunker=SlidingWindowChunker(default_chunk_size=1000, default_overlap=500),
        ),
    )

    async def reembed_project(target_project_id: UUID) -> int:
        """Re-embed every entity in one project, from the graph as it stands.

        The repair route's engine. Assembles a card per canonical entity,
        embeds them, appends one `EntitiesEmbedded` and folds it straight into
        the project's card vector store -- so the effect is visible on the next
        projection rather than only after the next restart.

        Returns 0 rather than raising when embeddings are off, when the project
        has no entities, or when the provider declines: the route reports the
        number, and a build with `AGENT_VECTOR_STORE=none` should answer "0
        embedded" rather than an error every caller has to special-case.

        The event is appended *before* the store is written. Both orders leave
        a window, and this is the one whose failure is recoverable: an append
        that lands with no upsert is corrected by the next project open, while
        an upsert that lands with no append is a store holding vectors the log
        cannot reproduce -- which is the exact state this whole change exists
        to end.
        """
        if embedding_provider is None:
            return 0
        store = await graphs.open(target_project_id)
        card_vectors = graphs.card_vectors(target_project_id)
        if card_vectors is None:
            return 0
        return await refresh_project_embeddings(
            graph=store,
            provider=embedding_provider,
            event_store=repository.store,
            vectors=card_vectors,
            tenant_id=target_project_id,
        )

    async def open_graph(
        target_project_id: UUID,
    ) -> tuple[RedstringKnowledge, tuple[BaseTool, ...]]:
        """Build one project's `RedstringKnowledge` over its shared graph store.

        The store itself comes from `graphs`, which owns it for as long as
        the project stays open -- not just for the duration of this
        attachment. Raises before anything is returned if `graphs.open`
        fails -- an unreachable Neo4j or a replay `KnowledgeError` -- which is
        what lets `KnowledgeAttachment.attach` stay atomic: nothing here is
        handed back for it to wire in until the store has actually opened.
        Unlike the store this used to build for itself, a store that fails to
        open here is *not* closed on the way out: `graphs` is what decided to
        build it, and only `graphs` gets to decide it is done with it --
        closing a cache's handle out from under it on a failure it did not
        cause would leave the cache holding a closed store the next `open`
        would hand straight back out.
        """
        store = await graphs.open(target_project_id)
        knowledge = RedstringKnowledge(
            target_project_id,
            store=store,
            event_store=repository.store,
            snapshot_store=repository.snapshot_store,
            provider=LangChainLlmProvider(extraction_model, model=config.model_name()),
            # `repository.publisher`, like every other repository built here,
            # and it was the one that did not have it. The corpus read model
            # follows the log through this bus, so without it a `remember`
            # appended `CorpusDocumentStored` and woke nothing: the event was
            # in the log, `topic_corpus_facts` had it (that repository
            # publishes), and `corpus_documents` stayed empty for the life of
            # the process -- which is "Documents" listing nothing while
            # research is visibly fetching pages. Not caught by a signature:
            # `event_publisher` is optional and defaults to None, so the wrong
            # wiring is the quiet one. See
            # `tests/integration/test_corpus_publishing.py`.
            corpus=build_corpus_repository(
                repository.store,
                repository.publisher,
                snapshot_store=repository.snapshot_store,
            ),
            # Same three arguments as the corpus, including the publisher, for
            # the reason the comment above gives: `event_publisher` is optional
            # and defaults to None, so the wrong wiring is the silent one.
            judgements=build_judgements_repository(
                repository.store,
                repository.publisher,
                snapshot_store=repository.snapshot_store,
            ),
            domain=config.knowledge_domain(),
            embeddings=embedding_provider,
            # `graphs.vectors()` rather than a captured store: `graphs.open`
            # above has already opened it, so this is a cached attribute read,
            # and routing both through the same owner is what keeps "the store
            # whose schema was ensured" and "the store this adapter writes to"
            # the same object.
            vector_store=await graphs.vectors(),
            # Per project, unlike the one above, and folded from the log at
            # the `graphs.open` two lines up -- so this is the store that
            # already holds every card embedding this project has recorded,
            # not a fresh one this ingest would start filling from empty.
            card_vector_store=graphs.card_vectors(target_project_id),
            concurrency=config.extraction_concurrency(),
            consolidation_batch=config.consolidation_batch_size(),
            # One chunker per project adapter rather than one for the process.
            # `SlidingWindowChunker` holds only its three numbers -- no buffer,
            # no state carried between `chunk` calls -- so sharing one would
            # save an object and buy nothing, while making the size look like
            # a process-wide fact when it is a per-adapter argument.
            #
            # Overlap and the boundary flags are left at redstring's defaults:
            # only the size is ours to choose, and passing the others would
            # freeze values we have no reason to hold against upstream's.
            # Wrapped so a chunk of table rows reaches the model with the
            # header naming its columns; without it, every chunk after the
            # first of a long table is rows whose cells mean nothing. This
            # does not change the chunk size -- `MarkdownTableChunker` makes
            # no boundary decisions, it only prepends a header the delegate's
            # cut left behind -- but a header-carrying chunk does exceed
            # `extraction_chunk_size` by the header's length. See that
            # module's docstring for why that was preferred to shrinking the
            # budget, and for the measurement.
            chunker=MarkdownTableChunker(
                SlidingWindowChunker(default_chunk_size=config.extraction_chunk_size())
            ),
            # `graphs.chunks(...)`, not a second `build_chunk_store()` call:
            # `graphs.open` above already built this project's chunk store and
            # folded it in the same replay pass as the graph (see
            # `ProjectGraphs.open`), and a second store built here would be
            # empty. Indexing would write into it, replay would keep filling
            # the *other* one, and every read downstream would silently see
            # an empty corpus -- the exact failure this call is here to rule
            # out rather than the one it happens to avoid. `None` when
            # `AGENT_CHUNK_STORE=none`, matching `ProjectGraphs.chunks`'s own
            # None-when-off return.
            chunks=graphs.chunks(target_project_id),
            # `graphs.cards(...)`, for `chunks`' reason: `graphs.open` above
            # already built and filled this project's card store, and a second
            # one built here would be empty -- every ingest would re-card into
            # a store nothing reads while the store the reader holds stayed at
            # whatever `open` left. `None` when cards are off.
            cards=graphs.cards(target_project_id),
            # Where this ingest's entity links land live. They reach the log
            # either way -- `build_graph` records the chunking whenever it has
            # an event store -- so this is about the *current* session seeing
            # its own passages rather than about durability.
            # `graphs.co_mentions(...)` for `chunks`' reason: `open` already
            # folded this one, and a second built here would be written to by
            # ingest while every reader held the other.
            co_mentions=graphs.co_mentions(target_project_id),
        )
        # Both tool sets travel back through the one channel `KnowledgeAttachment`
        # already has. A second callable for the corpus would need its own copy of
        # the atomicity guarantee -- a failed attach leaves the executor's tools
        # untouched -- and two half-attached states are exactly what that
        # guarantee exists to rule out. The corpus reader needs nothing closed,
        # so `close_graph` stays about the graph.
        reader = ProjectCorpusReader(corpus, target_project_id, blob_store)
        # The topic tools ride the same channel, for the reason the corpus
        # tools do: `KnowledgeAttachment` already carries the atomicity
        # guarantee that a failed attach leaves the executor's tools untouched,
        # and a second callable would need its own copy of it.
        topic_port = RepositoryTopics(
            build_topic_repository(
                repository.store,
                repository.publisher,
                snapshot_store=repository.snapshot_store,
            ),
            topics,
            target_project_id,
        )
        # Shadows the base `fetch` for as long as this project is attached --
        # see `_compose` in `knowledge_attachment.py`. It is the same tool
        # with one more place to look: this project's own sources, which is
        # the only lookup that can return something citable.
        project_fetch = build_fetch_tool(recall=recall, corpus=reader, pages=pages)
        # Unlike `project_fetch` above, `fetch_media` has no ungranted,
        # project-less form to shadow: `fetch` can run and simply not save
        # (`_keeper` below is the thing that decides that), but a
        # `fetch_media` that cannot store what it downloads is the exact
        # defect this tool was built to fix -- see `build_fetch_media_tool`'s
        # own refusal. So it exists only from here, once a project is
        # attached, rather than being registered unconditionally alongside
        # the base `fetch` in `tools` above and reaching for a project it
        # might not have.
        #
        # `editor` and `resolved_media_http_client` are both closed over from
        # the outer `build_application` scope, defined further down in this
        # function (`editor` beside `document_extractor`,
        # `resolved_media_http_client` beside `media_accept_worker`) --
        # ordinary in a nested `async def`, since Python resolves a closure's
        # free variables at call time, and `open_graph` is never called until
        # `build_application` has finished assembling both. Reusing the
        # worker's own client rather than building a second one is what
        # keeps "the connection pool a model's direct fetch uses" and "the
        # one an accepted proposal's download uses" the same pool, not two
        # that happen to agree on configuration today.
        fetch_media = build_fetch_media_tool(
            client=resolved_media_http_client,
            editor=editor,
            project_id=target_project_id,
        )
        return knowledge, (
            project_fetch,
            fetch_media,
            # The reporter is per-project and so is this closure, which is why
            # it is made here rather than passed in already bound. None when
            # nothing is listening: a build with no web layer has nobody to
            # tell, and `remember` is unchanged by its absence.
            *build_knowledge_tools(
                knowledge,
                report=extractions.reporter(target_project_id)
                if extractions is not None
                else None,
                pages=pages,
            ),
            *build_corpus_tools(reader),
            *build_topic_tools(topic_port, target_project_id),
        )

    async def close_graph(knowledge: RedstringKnowledge) -> None:
        """A no-op: detaching a project from one session no longer closes its store.

        Before `graphs` existed, this was the only thing that closed a graph
        store, so it closed the one `knowledge` held. Now the store outlives
        any single attachment -- `graphs` is what opened it and `graphs` is
        what gets to close it, on project delete or process shutdown. Closing
        it here too would pull it out from under the cache: `graphs` would
        still list the project as open, and the next `open` would hand back a
        store that no longer accepts calls instead of rebuilding a working one.
        """

    attachment = KnowledgeAttachment(
        executor,
        tools,
        open_graph=open_graph,
        close_graph=close_graph,
    )

    summaries = SessionSummaryRunner(
        repository.store, resolved_path, repository.publisher, resolved_tracer
    )
    service = SessionService(
        repository,
        executor,
        summaries,
        repository.projects,
        default_system_prompt=system_prompt + prompt_suffix,
        context=strategy,
        # Resolved once and shared: whether this process exports traces is a
        # deployment decision, and the composition root is where deployment
        # decisions live. The projection gets the same instance, so a turn and
        # the read-model work it causes are read off one trace rather than two.
        tracer=resolved_tracer,
        # A session started in a project gets this appended to its prompt;
        # one started plainly does not, so it never hears
        # about tools it was not given.
        # `TOPICS_PROMPT` belongs here for the same reason the other three do,
        # and its absence was a plain oversight: `open_graph` attaches
        # `build_topic_tools` alongside the knowledge and corpus tools, so a
        # joined session has always *had* `open_topic` -- and was never told.
        # The comment beside the build-time suffix above already names this
        # exact failure ("no idea the tool exists") while claiming parity with
        # this line, which is what made the gap invisible.
        #
        # Visible from the outside as an autonomous run that stops on its first
        # round with `queue_empty` forever: the only thing that can put a topic
        # on the queue is the agent calling `open_topic`, the driver never opens
        # one itself, and nothing had told the agent the tool was there.
        knowledge_prompt=(
            KNOWLEDGE_PROMPT + CORPUS_PROMPT + FETCH_CORPUS_PROMPT + TOPICS_PROMPT
        ),
        # The service owns the attachment: `/project use` calls
        # `service.attach_project` directly, so it lives where the REPL
        # already reaches rather than behind a second accessor on `Application`.
        attachment=attachment,
        # Learner progress rides the same log and the same snapshot table as
        # everything else, keyed by the session it belongs to. Wired here
        # rather than defaulted inside the service, because which store an
        # aggregate lands in is exactly the decision this root exists to make.
        progress=build_learner_progress_repository(
            repository.store, repository.publisher, snapshot_store=repository.snapshot_store
        ),
        # So `delete_project` can evict the deleted project's cached store --
        # the same `graphs` `open_graph` above borrows from, not a second
        # instance that would cache independently of the one attachment uses.
        graphs=graphs,
    )
    turns = TurnSupervisor(service, activity=activity)
    # Built here because `open_graph` is a closure over this build's stores:
    # the ask agent takes the project tools that closure assembles and keeps
    # the readers, so it cannot be constructed anywhere a caller could reach.
    # `time.monotonic` rather than wall-clock for both clocks, because the only
    # questions asked of them are durations -- how long a conversation has been
    # idle -- and a clock that can step backwards would evict a chat somebody
    # is in the middle of.
    ask_service = AskService(
        executor=DeepAgentAskExecutor(
            model=resolved_model,
            open_graph=open_graph,
            project_files=service.project_files,
            project_sources=lambda target_project_id: mounted_sources(
                corpus_readers(target_project_id)
            ),
        ),
        conversations=ConversationRegistry(now=time.monotonic),
        now=time.monotonic,
        # The durable half of the same record. Wired here rather than
        # defaulted inside the service for `progress`'s reason above: which
        # store an aggregate lands in is the decision this root exists to
        # make. No snapshot store -- see the builder's docstring.
        transcripts=build_ask_conversation_repository(repository.store, repository.publisher),
    )

    # Built here for `ask_service`'s reason: the executor takes the project
    # tools `open_graph` assembles and keeps the readers, so it cannot be
    # constructed anywhere a caller could reach.
    #
    # A second executor beside the ask's, differently prompted over identical
    # plumbing -- which is the whole of what the design's §4 said this would
    # cost, and it is these four lines.
    #
    # `read_model=dialogues` is the whole of resumption's wiring, and it is one
    # keyword. A build that passed something else here -- or nothing -- would
    # compose, serve, and start every resumed dialogue over.
    socratic_service = SocraticDialogueService(
        executor=DeepAgentSocraticExecutor(
            model=resolved_model,
            open_graph=open_graph,
            project_files=service.project_files,
            project_sources=lambda target_project_id: mounted_sources(
                corpus_readers(target_project_id)
            ),
        ),
        dialogues=DialogueRegistry(now=time.monotonic),
        read_model=dialogues,
        now=time.monotonic,
        transcripts=build_socratic_dialogue_repository(repository.store, repository.publisher),
        clock=lambda: datetime.now(UTC),
        # The same builder `SessionService` uses, over the same log. Keyed on
        # the dialogue id here rather than a session id -- see
        # `SocraticDialogueService.progress_for` and the design's §3 for why
        # this surface can answer the identity question the ask path skipped.
        # The two share a log and are kept apart by aggregate id, which is what
        # `LearnerProgress` already does between sessions.
        progress=build_learner_progress_repository(
            repository.store, repository.publisher, snapshot_store=repository.snapshot_store
        ),
    )

    # Built here for `ask_service`'s reason, and it is the same reason: this
    # needs the `open_graph` closure above, which is assembled from this
    # build's stores and cannot be reached from anywhere a caller could stand.
    #
    # `open_graph` returns the knowledge port *and* the project's tools; only
    # the port is wanted here. Discarding the tools costs building them -- four
    # tool sets constructed and dropped per extraction -- which is a handful of
    # dataclasses against a call that is about to spend minutes of model time.
    # The alternative is a second closure that opens a store and builds a
    # `RedstringKnowledge` without them, and a second place that decides how an
    # adapter is configured is exactly how the concurrency and chunker settings
    # would come to differ between the agent's `remember` and this button.
    async def open_knowledge(target_project_id: UUID) -> RedstringKnowledge:
        knowledge, _tools = await open_graph(target_project_id)
        return knowledge

    document_extractor = DocumentExtractor(
        open_knowledge=open_knowledge,
        corpus_readers=corpus_readers,
        # The same channel `remember` reports through, so a queued extraction
        # and an agent's own land in one pane rather than two accounts of the
        # same graph being written. None when nothing is listening, matching
        # how `open_graph` binds the reporter for the knowledge tools.
        reporters=extractions.reporter if extractions is not None else None,
    )
    # Built from the same `open_knowledge` closure and corpus reader factory
    # `document_extractor` uses, plus an `AggregateRepository[Corpus]` of its
    # own -- `corpus` in this scope is the `CorpusRunner` read model
    # `ProjectCorpusReader` wraps, not the aggregate repository `drop` and
    # `restore` need to execute `DropSourceDocument`/`StoreSourceDocument`
    # against. Built the same three-argument way `open_graph` builds one for
    # `RedstringKnowledge`, including the publisher: leaving it out is the
    # silent-wiring failure that comment already explains, and a `drop` or
    # `restore` that missed it would corrupt the corpus row and wake nothing.
    #
    # Held in a variable and handed to `perceiver` below too, rather than
    # built a second time: `StoreDerivedText` and `DropSourceDocument` both
    # execute against this same aggregate stream, and a second repository
    # built the same three-argument way would still be one connection to one
    # log -- but two objects that only happen to agree, where composition
    # should have made them the same object outright.
    corpus_repository = build_corpus_repository(
        repository.store,
        repository.publisher,
        snapshot_store=repository.snapshot_store,
    )
    editor = CorpusEditor(
        open_knowledge=open_knowledge,
        readers=corpus_readers,
        corpus=corpus_repository,
        blobs=blob_store,
    )
    # Constructed beside `document_extractor`, sharing its `corpus_readers`
    # closure and the corpus repository `editor` holds -- see both comments
    # above. `resolved_perception` is this build's port: a real
    # `ReadEverythingPerception` unless a test injected a fake through
    # `build_application(perception=...)`.
    media_perceiver = MediaPerceiver(
        port=resolved_perception,
        corpus_readers=corpus_readers,
        corpus=corpus_repository,
        max_chars=config.perception_max_chars,
    )
    runs = build_research_run_repository(
        repository.store, repository.publisher, snapshot_store=repository.snapshot_store
    )
    topic_repository = build_topic_repository(
        repository.store, repository.publisher, snapshot_store=repository.snapshot_store
    )
    # Unsnapshotted, unlike `topic_repository` above -- `MediaProposals` has no
    # `build_media_proposal_repository` helper yet because nothing needing a
    # snapshot policy has been written against it, mirroring the bare
    # `AggregateRepository` construction `tests/application/
    # test_media_curation.py` already uses over `harness.event_store`. Built
    # over `repository.store`/`.publisher` so `MediaCurationService`'s writes
    # and `media_proposals`'s subscription above read and write the same log.
    media_proposal_repository = AggregateRepository(
        repository.store, MediaProposals, event_publisher=repository.publisher
    )
    # Task 11b: the accept route (below, in `create_app`) only appends
    # `MediaProposalAccepted` and answers 202 -- nothing downstream of it
    # calls `MediaAcceptWorker` unless this build hands it one. Built here,
    # after `media_proposal_repository`, `editor` and `media_perceiver` all
    # exist, rather than beside the other projections above: those three are
    # exactly the collaborators the worker needs, and `media_proposals` (the
    # runner just above) already satisfies `MediaProposalReadPort` on its own
    # -- see `MediaProposalRunner.get` -- so no separate read adapter is
    # built either. The same "construct once, in one place" reasoning that
    # motivates gathering the projections applies here too: a worker built
    # somewhere else, or not at all, is a worker nobody notices is missing
    # until an accepted proposal never turns into a source.

    def topic_reader(target_project_id: UUID) -> TopicReadPort:
        """This project's `TopicReadPort`, over the one repository above.

        Built per call rather than held, mirroring `ProjectCorpusReader`
        above: the project is bound at construction so no caller can pass a
        different one, and a call is cheap enough (three attribute reads and
        an object) that there is no reason to cache it.
        """
        return ProjectTopicReader(
            topics, topic_repository, topics.corpus_facts, target_project_id
        )

    async def definition_reader(target_project_id: UUID) -> DefinitionService | None:
        """This project's `DefinitionService`, or `None` if it cannot be built.

        Async and per-call, unlike `topic_reader` above, because two of the
        three collaborators come from `graphs.open` -- which may open a store
        and replay into it -- and none of them can be bound before a project
        id exists. `ProjectGraphs` caches the stores, so the cost of building
        one of these per request is the three adapter objects, not the opens.

        **Two lifetimes meet here and they are deliberately different.** The
        graph and chunk stores are per-project and owned by `graphs`. The
        definition cache is one SQLite table for the whole process, keyed by
        `(project_id, entity_id)`, owned by `definition_invalidation`; what is
        per-project about it is only the id `ProjectDefinitionCache` binds, so
        that no caller can reach another project's rows. Building a cache per
        project would give each one its own connection to the same table --
        the drift described where the runner is constructed.

        `None` rather than a raise when there is no chunk store
        (`AGENT_CHUNK_STORE=none`), matching what the usages route does with
        the same absence: the caller renders it as 503 "not configured",
        which is the truth. It costs nothing in definitions: with no chunk
        store there are no passages, and `DefinitionService._generate`
        refuses a passage-less entity before the model call, because a
        definition assembled from edges alone cites nothing `_verified`
        could check. A null usage reader here would buy the same `None`
        one HTTP round trip later.
        """
        # `open` before `chunks`, and the order is the whole of a bug this
        # had: `ProjectGraphs.chunks` answers `None` for a project whose
        # store has not been opened yet -- it is built during `open`, in the
        # same replay pass as the graph -- so asking first made the *first*
        # request for any project 503 with "no chunk store is configured",
        # and only that one. A reviewer's probe caught it; `_usage_reader` in
        # `app.py` had the order right and this did not.
        store = await graphs.open(target_project_id)
        chunk_store = graphs.chunks(target_project_id)
        if chunk_store is None:
            return None
        return DefinitionService(
            graph=ProjectGraphReader(
                project_id=target_project_id, store=store, ontology=ontology
            ),
            usages=UsageReader(store, chunk_store, target_project_id),
            cache=ProjectDefinitionCache(definition_invalidation, target_project_id),
            # The extraction model, not a second client -- see
            # `ChatModelDefinitionText` for why, and for what that costs.
            model=ChatModelDefinitionText(extraction_model, model_name=config.model_name()),
        )

    def ontology_discoverer(target_project_id: UUID) -> OntologyDiscoveryService:
        """This project's `OntologyDiscoveryService`.

        Synchronous and never `None`, unlike `definition_reader` above, and the
        difference is what each one needs. A definition needs the graph and the
        chunk store, so it has to await `graphs.open` and can fail when
        chunking is off. Discovery needs the document text and a model: the
        corpus reader is constructed from a runner that is already open, and
        the recorder writes to the event store directly. Nothing here can be
        absent, so there is no `None` for a route to render as 503.

        That also means the `open`-before-`chunks` ordering bug documented on
        `definition_reader` cannot occur here -- this factory does not touch
        `graphs` at all. Checked rather than assumed.
        """
        return OntologyDiscoveryService(
            corpus=ProjectCorpusReader(corpus, target_project_id, blob_store),
            # The extraction model, not a second client -- see
            # `ChatModelOntologyText` for why, and for what that costs.
            model=ChatModelOntologyText(extraction_model, model_name=config.model_name()),
            recorder=EventStoreOntologyRecorder(
                repository.store, repository.publisher, target_project_id
            ),
        )

    def catalog_recorder(target_project_id: UUID) -> EventStoreCatalogFeatureRecorder:
        """This project's write side for course featuring, over this
        instance's own event store and publisher -- built the same way
        `ontology_discoverer` builds its recorder, for the same reason:
        catalog events have no aggregate to consult, so the factory closes
        over the store directly rather than going through
        `AggregateRepository`."""
        return EventStoreCatalogFeatureRecorder(
            repository.store, repository.publisher, target_project_id
        )

    # `_catalog_runner` follows the log over `repository.store`/`.publisher`
    # -- the application's own store, not a second one -- which is the piece
    # `tests/interfaces/test_catalog_routes.py`'s module docstring names as
    # what Task 10 was left to thread through: that module builds a
    # standalone `SQLiteEventStore`/`InMemoryEventBus` pair over the same
    # file only because this wiring did not exist yet. Registered with
    # `start()`/`close()` below beside every other projection, per
    # `EntityDefinitionRunner`'s comment on why one built and never started
    # is a projection nobody starts.
    catalog_runner = _CatalogFeatureRunner(
        repository.store, repository.publisher, resolved_path
    )
    # `TypePluralityGrouper` is the one production adapter `CategoryGrouper`
    # has today -- see its own docstring for why. `ArtPort` now has two:
    # `LibraryArtProvider` below is what `catalog_service` is built with,
    # falling back to `SeededArtProvider` -- see `test_catalog_wiring.py` for
    # the both-ends-over-real-data test CLAUDE.md's co-mention section
    # demands of exactly this shape.
    blurb_cache = _LazyBlurbCache(resolved_path)
    # The art library's storage half. Opened lazily for `blurb_cache`'s
    # exact reason -- no event loop yet -- and over the same `resolved_path`
    # every other cache in this function reads, so a piece of art assigned
    # by one request is visible to the very next one.
    art_store = _LazyArtStore(resolved_path)
    candidate_art_store = _LazyCandidateArtStore(resolved_path)
    art_matcher = LibraryArtProvider(
        art_store=art_store,
        candidate_art_store=candidate_art_store,
        fallback=SeededArtProvider(),
    )
    catalog_service = CatalogService(
        grouper=TypePluralityGrouper(),
        art=art_matcher,
        blurbs=blurb_cache,
    )
    # R5: constructed even though nothing calls `.write()` yet this
    # increment -- see `Application.blurbs`'s own docstring for the reasoning
    # (a caller-less port is the exact shape CLAUDE.md's co-mention section
    # warns about, and building the object graph now turns the later
    # increment into adding one call rather than a whole graph).
    blurb_writer = ModelBlurbWriter(extraction_model)
    # `outline_cache` is built here, ahead of `blurb_sweep` below, rather than
    # down beside `course_service` where it used to live -- the sweep now
    # writes outlines as well as copy (see `blurb_sweep.py`'s module
    # docstring) and needs the same cache `course_service` reads.
    outline_cache = _LazyOutlineCache(resolved_path)
    outline_writer = ModelOutlineWriter(extraction_model)
    # The same `extraction_model` `blurb_writer` above takes -- the brief's
    # own instruction, and `ModelOutlineWriter`'s docstring gives the reason:
    # a second model configuration would be a second thing to keep in sync
    # with `config.model_name()` for no benefit, since both jobs want the
    # same "reason less, answer in a fixed shape" trade-off extraction
    # already makes.
    # The sweep nothing called yet in increment 1 -- see `Application
    # .blurb_sweep`'s docstring. Built over the same `blurb_cache` and
    # `outline_cache` every other reader of either uses, so a sweep and an
    # on-demand `catalog`/course-detail read of the same slug see one cache
    # each, not two.
    blurb_sweep = BlurbSweep(blurb_cache, outline_cache)
    # Same `extraction_model` `blurb_writer` above takes -- no second model
    # configuration, matching `outline_writer`'s own comment above on why.
    art_generator = ModelSvgArtist(extraction_model)
    art_sweep = ArtSweep(art_store, candidate_art_store)

    # `_course_runner` follows the log the same way `catalog_runner` does,
    # over this application's own store and bus -- see its own docstring for
    # why it is a runner (mutable `courses` attribute) rather than a plain
    # field, and `CourseProjection`'s registration below is what
    # `test-8-brief.md`'s failing test guards: an event no projection handles
    # counts as applied, so an omitted registration would answer every
    # request 200 with an empty table rather than raising anything.
    course_runner = _CourseRunner(repository.store, repository.publisher, resolved_path)
    # Unsnapshotted, over this application's own store and publisher, mirroring
    # `media_proposal_repository` -- see `build_course_repository`'s own
    # docstring for why no snapshot policy is warranted here.
    course_repository = build_course_repository(repository.store, repository.publisher)
    # `outline_writer` is not passed here: `CourseService` no longer calls a
    # model at all -- see `course_realization.py`'s module docstring. It
    # stays a local above only because `blurb_sweep` needs it.
    course_service = CourseService(
        realized=_RealizedCourses(course_runner, authoring),
        outline_cache=outline_cache,
    )

    def check_telemetry_reader(target_project_id: UUID) -> CheckTelemetryReadPort:
        """This project's `CheckTelemetryReadPort`, over the one runner above.

        Built per call rather than held, mirroring `topic_reader`: two
        attribute reads and an object, and the project bound at construction is
        the point of having it at all.
        """
        return ProjectCheckTelemetryReader(check_telemetry, target_project_id)

    async def start_run(
        run_id: UUID,
        run_project_id: UUID,
        session_id: UUID,
        budget: Budget | None,
        fetch_hosts: list[str],
        fetch_budget: int,
        cancelled,
    ):
        """One autonomous run: a driver, bound to one session's turns.

        Built per run rather than once, because `run_round` closes over the
        session the rounds are turns on. The driver itself holds no state, so
        there is nothing to share by keeping one around.

        Rounds go through `turns` rather than straight to the service, which
        is what makes "one turn at a time per session" cover an autonomous run
        as well as a person typing: a `/turns` POST arriving mid-run is refused
        with the 409 it would get from any other second turn, rather than
        interleaving with a round.

        `read_only` is read from the policy rather than asserted. The default
        is a read-only run because `fetch` floors at `ask` and an unattended
        approval deadlocks -- but someone who has set `fetch` to `auto` has a
        run that can leave the process, and recording `read_only=True` over
        that would put a false claim in the audit trail of the one kind of run
        that most needs a true one. The policy is read here and never written,
        which is what keeps `TOOL_FLOORS` a floor rather than a suggestion.

        `fetch_hosts`/`fetch_budget` travel from the HTTP request all the way
        here (`app.py`'s `NewRun` -> `ResearchSupervisor.start` -> this
        `StartRun` callable) and go straight to the driver, which is the one
        thing that turns them into a `FetchGrant` and registers it --
        `resolved_grants` is threaded to the driver below for exactly that.
        """
        return await ResearchRunDriver(
            runs,
            topic_repository,
            topics.queue,
            run_round=TopicRoundRunner(
                topic_repository,
                lambda prompt: turns.run(session_id, prompt),
            ),
            # The queue is a projection, so the look a round just recorded is
            # not in the table the next round reads until it catches up.
            # Without this the run is handed back the topic it has just
            # finished, which looks exactly like a loop that cannot learn.
            settle=topics.caught_up,
            # The same registry `turn_tools` and the gate consult -- see
            # `resolved_grants`'s own note.
            grants=resolved_grants,
        ).run(
            run_project_id,
            session_id,
            budget=budget,
            fetch_hosts=fetch_hosts,
            fetch_budget=fetch_budget,
            run_id=run_id,
            cancelled=cancelled,
            autonomy_snapshot=resolved_policy.levels(),
            read_only=resolved_policy.level_for(FETCH_TOOL) != "auto",
        )

    research_supervisor = ResearchSupervisor(start_run, runs)
    # Built over the same `service` and `turns` a person's own turns run
    # through -- a seeding turn is a turn like any other, and `TopicSeeder`
    # joins and releases the project the same way `start_research_run` does.
    topic_seeder = TopicSeeder(service, turns)
    # Same `service` and `turns` a third time. An authoring run is three turns
    # rather than one, but they are ordinary turns against a joined project --
    # which is the point: a lesson can quote the corpus because the agent
    # writing it has the same tools every other turn has.
    course_author = CourseAuthor(service, turns)
    # Same `service` and `turns` again: a dispatch turn is a turn like any
    # other. `topic_reader` is the same factory the read routes close over, so
    # the number in `/topics/<nn>-<slug>/` and the order the topic list renders
    # in cannot come from two different reads.
    dispatcher = TopicDispatcher(service, turns, topic_reader)
    # The same `service`, `turns` and `resolved_policy` again. The policy in
    # particular must be *this* instance's and not a copy: it is what decides
    # whether the runner asks at a boundary, and a second policy object would
    # let a run cross gates the operator had not relaxed -- which is the one
    # property `stage-boundaries.md` §4.4 insists no second mechanism may
    # decide. `approvals` is the same port the tool gate poses through, so a
    # reviewer sees one kind of request whichever route proposed the advance.
    stage_runner = StageRunner(
        service,
        turns,
        lambda target: ProjectWorkflow(repository.projects, target),
        approvals,
        resolved_policy,
    )
    # The same object the tools report through, not a second one: the roster's
    # "an extraction is running" and the pane's frames are two reads of one
    # buffer, and two instances would let them disagree.
    worker_roster = WorkerRoster(
        service,
        turns=turns,
        runs=research_supervisor,
        extractions=extractions,
        # Passed in rather than built here for `extractions`' reason: the
        # queue the routes enqueue into and the one the roster reads must be
        # the same object, and only the process that owns both can say so.
        dispatches=dispatches,
        # The same runner the `stage_runner` field exposes. A second instance
        # would hold its own in-flight dict and the dock would show nothing
        # while a stage was being driven -- the exact failure #79 fixed for
        # extractions by insisting on one buffer.
        stages=stage_runner,
        # The projection, not the service: `everywhere` needs session -> project
        # for the turns it finds, and asking the service would fold a session
        # per running turn to learn something a read-model column already says.
        summaries=SummaryProjects(summaries),
    )

    # Built last, deliberately: this used to be built ~250 lines earlier,
    # immediately after `media_perceiver`, where nothing built from
    # `resolved_media_http_client`/`media_accept_worker` was used before the
    # `Application(...)` call at the end of this function -- both names are
    # only read from inside closures (`open_graph`'s `fetch_media` below,
    # and `Application`'s own field) that Python resolves at call time, not
    # at definition time. Anything raising between the old site and
    # `Application(...)` left the client constructed with no owner to close
    # it, since `Application.close()` is unconditional but only exists once
    # an `Application` does. Moved here, directly preceding
    # `Application(...)`, instead of wrapped in `try/finally`: the window
    # closes by construction rather than by a handler that would itself
    # need testing (see `fece941`'s commit message for the full reasoning).
    #
    # `media_http_client` is a parameter, mirroring `perception` elsewhere in
    # this function, so a test can inject an `httpx.MockTransport` and never
    # reach the network --
    # exactly how `tests/application/test_media_acquisition.py`'s own fakes
    # work, and the no-network guarantee `build_application`'s docstring
    # already promises for `perception`.
    #
    # A bare `httpx.AsyncClient()` carries httpx's 5-second default read
    # timeout, which made `fetch_media.TIMEOUT = httpx.Timeout(30.0)` inert
    # for every caller through this composition site -- that constant only
    # applies on the branch where a caller builds its own client, and nothing
    # here ever did. Downloading a multi-megabyte video under a 5s ceiling is
    # how "stuck accepted forever" (see `MediaAcceptWorker.run`'s widened
    # exception handling) got hit routinely rather than rarely: a slow but
    # otherwise healthy host would trip `httpx.HTTPError` on ordinary size,
    # not just on an actually-broken one. 30s matches `fetch_media.TIMEOUT`
    # so the two paths that share `download_media` also share the ceiling
    # they run it under.
    resolved_media_http_client = (
        media_http_client
        if media_http_client is not None
        else httpx.AsyncClient(timeout=httpx.Timeout(30.0))
    )
    media_accept_worker = MediaAcceptWorker(
        reads=media_proposals,
        proposals=media_proposal_repository,
        editor=editor,
        perceiver=media_perceiver,
        client=resolved_media_http_client,
    )
    # Built here rather than at the projections above, because it needs the
    # worker, which needs everything the comment above `media_accept_worker`
    # explains. `reads` is `media_proposals` again -- the same runner the
    # worker resolves one proposal through, now also asked for the whole
    # accepted set.
    media_accept_reconciler = MediaAcceptReconciler(
        reads=media_proposals,
        worker=media_accept_worker,
    )

    return Application(
        service=service,
        feed=LiveFeed(repository),
        turns=turns,
        context_mode=mode,
        summaries=summaries,
        corpus=corpus,
        blob_store=blob_store,
        topics=topics,
        check_telemetry=check_telemetry,
        check_telemetry_readers=check_telemetry_reader,
        definitions=definition_invalidation,
        definition_readers=definition_reader,
        ontology=ontology,
        ontology_discoverers=ontology_discoverer,
        media_proposals=media_proposals,
        media_proposal_repository=media_proposal_repository,
        media_curation_text=media_curation_text,
        media_curation_search=media_curation_search,
        graphs=graphs,
        topic_readers=topic_reader,
        topic_repository=topic_repository,
        research=research_supervisor,
        topic_seeder=topic_seeder,
        course_author=course_author,
        reembed=reembed_project,
        dispatcher=dispatcher,
        stage_runner=stage_runner,
        workers=worker_roster,
        policy=resolved_policy,
        grants=resolved_grants,
        ask=ask_service,
        asks=asks,
        authoring_runs=build_course_authoring_run_repository(
            repository.store, repository.publisher
        ),
        authoring=authoring,
        socratic=socratic_service,
        dialogues=dialogues,
        interaction_log=interaction_log,
        interaction_recorder=interaction_recorder,
        _interaction_store=interaction_store,
        catalog=catalog_service,
        _catalog_runner=catalog_runner,
        catalog_recorder=catalog_recorder,
        blurbs=blurb_writer,
        _blurb_cache=blurb_cache,
        course_service=course_service,
        _course_runner=course_runner,
        course_repository=course_repository,
        outlines=outline_writer,
        _outline_cache=outline_cache,
        blurb_sweep=blurb_sweep,
        art_store=art_store,
        art_generator=art_generator,
        art_matcher=art_matcher,
        _candidate_art_store=candidate_art_store,
        art_sweep=art_sweep,
        document_extractor=document_extractor,
        editor=editor,
        perception=resolved_perception,
        perceiver=media_perceiver,
        media_accept_worker=media_accept_worker,
        media_accept_reconciler=media_accept_reconciler,
        media_reconcile_interval=config.media_reconcile_interval_seconds(),
        _media_http_client=resolved_media_http_client,
        _initial_project_id=project_id,
    )


def build_service(
    *,
    model: BaseChatModel | None = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    db_path: str | None = None,
    context_mode: str | None = None,
    tracer: Tracer | None = None,
) -> SessionService:
    """Just the use cases, for callers with no use for a live feed."""
    return build_application(
        model=model,
        system_prompt=system_prompt,
        db_path=db_path,
        context_mode=context_mode,
        tracer=tracer,
    ).service
