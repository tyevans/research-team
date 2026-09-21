"""Service construction builders for the composition root.

Extracts AskService, SocraticDialogueService, DocumentExtractor,
CorpusEditor, and MediaPerceiver construction out of _build_application.
"""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from eventsource import EventPublisher
from eventsource.adapters.sqlite import SQLiteEventStore, SQLiteSnapshotStore
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.observability import Tracer
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from research_team.application import (
    AutonomyPolicy,
    DispatchesInFlight,
    ExtractionChannel,
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
from research_team.application.ask import AskExecutor, AskService, ConversationRegistry
from research_team.application.autonomy import FETCH_TOOL
from research_team.application.blobs import BlobStorePort
from research_team.application.context import ContextStrategy
from research_team.application.corpus_editing import CorpusEditor
from research_team.application.corpus_read import CorpusReadPort
from research_team.application.course_authoring import CourseAuthor
from research_team.application.document_extraction import DocumentExtractor
from research_team.application.grants import GrantRegistry
from research_team.application.knowledge import ExtractionNote, KnowledgePort
from research_team.application.knowledge_attachment import KnowledgeAttachment
from research_team.application.media_acquisition import (
    MediaAcceptReconciler,
    MediaAcceptWorker,
)
from research_team.application.perception import MediaPerceiver, PerceptionPort
from research_team.application.ports import TurnExecutor
from research_team.application.socratic import (
    DialogueReadModel,
    DialogueRegistry,
    SocraticDialogueService,
    SocraticExecutor,
)
from research_team.application.topic_dispatch import TopicDispatcher
from research_team.application.topic_read import TopicReadPort
from research_team.application.topic_seeding import TopicSeeder
from research_team.application.topics import TOPICS_PROMPT
from research_team.domain.ask_conversation import AskConversation
from research_team.domain.corpus import Corpus
from research_team.domain.learner import LearnerProgress
from research_team.domain.media_proposals import MediaProposals
from research_team.domain.research_run import Budget, ResearchRun
from research_team.domain.socratic_dialogue import SocraticDialogue
from research_team.domain.topic import Topic
from research_team.infrastructure import config
from research_team.infrastructure.agent.ask_agent import DeepAgentAskExecutor
from research_team.infrastructure.agent.corpus_tools import CORPUS_PROMPT
from research_team.infrastructure.agent.fetch import FETCH_CORPUS_PROMPT
from research_team.infrastructure.agent.knowledge_tools import KNOWLEDGE_PROMPT
from research_team.infrastructure.agent.socratic_agent import DeepAgentSocraticExecutor
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from research_team.infrastructure.persistence import (
    EventStoreSessionRepository,
    SessionSummaryRunner,
    TopicRunner,
    build_ask_conversation_repository,
    build_corpus_repository,
    build_learner_progress_repository,
)
from research_team.infrastructure.persistence.event_store import (
    build_socratic_dialogue_repository,
)
from research_team.infrastructure.persistence.read_models import (
    MediaProposalRunner,
)

__all__ = [
    "ContentPipeline",
    "MediaAcquisitionWiring",
    "SessionWiring",
    "SupervisorWiring",
    "build_ask_service",
    "build_content_pipeline",
    "build_corpus_editor",
    "build_document_extractor",
    "build_media_acquisition",
    "build_media_perceiver",
    "build_session_service",
    "build_socratic_service",
    "build_supervisor_roster",
]


def build_ask_service(
    *,
    model: BaseChatModel,
    open_graph: Callable[[UUID], Awaitable[tuple[RedstringKnowledge, tuple[BaseTool, ...]]]],
    project_files: Callable[..., Any],
    store: SQLiteEventStore,
    publisher: EventPublisher | None = None,
    now: Callable[[], float] = time.monotonic,
    executor: AskExecutor | None = None,
    conversations: ConversationRegistry | None = None,
    transcripts: AggregateRepository[AskConversation] | None = None,
) -> AskService:
    """Construct the ask conversation service and its executor.

    Built here because `open_graph` is a closure over this build's stores:
    the ask agent takes the project tools that closure assembles and keeps
    the readers, so it cannot be constructed anywhere a caller could reach.
    `time.monotonic` rather than wall-clock for both clocks, because the only
    questions asked of them are durations -- how long a conversation has been
    idle -- and a clock that can step backwards would evict a chat somebody
    is in the middle of.
    """
    resolved_executor = (
        executor
        if executor is not None
        else DeepAgentAskExecutor(
            model=model,
            open_graph=open_graph,
            project_files=project_files,
        )
    )
    resolved_conversations = (
        conversations if conversations is not None else ConversationRegistry(now=now)
    )
    resolved_transcripts = (
        transcripts
        if transcripts is not None
        else build_ask_conversation_repository(store, publisher)
    )
    return AskService(
        executor=resolved_executor,
        conversations=resolved_conversations,
        now=now,
        transcripts=resolved_transcripts,
    )


def build_socratic_service(
    *,
    model: BaseChatModel,
    open_graph: Callable[[UUID], Awaitable[tuple[RedstringKnowledge, tuple[BaseTool, ...]]]],
    project_files: Callable[..., Any],
    dialogues: DialogueReadModel,
    store: SQLiteEventStore,
    publisher: EventPublisher | None = None,
    snapshot_store: SQLiteSnapshotStore | None = None,
    now: Callable[[], float] = time.monotonic,
    clock: Callable[[], datetime] | None = None,
    executor: SocraticExecutor | None = None,
    dialogue_registry: DialogueRegistry | None = None,
    transcripts: AggregateRepository[SocraticDialogue] | None = None,
    progress: AggregateRepository[LearnerProgress] | None = None,
) -> SocraticDialogueService:
    """Construct the Socratic dialogue service and its executor.

    Built here for `ask_service`'s reason: the executor takes the project
    tools `open_graph` assembles and keeps the readers, so it cannot be
    constructed anywhere a caller could reach.

    A second executor beside the ask's, differently prompted over identical
    plumbing.

    `read_model=dialogues` is the whole of resumption's wiring, and it is one
    keyword. A build that passed something else here -- or nothing -- would
    compose, serve, and start every resumed dialogue over.
    """
    resolved_executor = (
        executor
        if executor is not None
        else DeepAgentSocraticExecutor(
            model=model,
            open_graph=open_graph,
            project_files=project_files,
        )
    )
    resolved_registry = (
        dialogue_registry if dialogue_registry is not None else DialogueRegistry(now=now)
    )
    resolved_clock = clock if clock is not None else (lambda: datetime.now(UTC))
    resolved_transcripts = (
        transcripts
        if transcripts is not None
        else build_socratic_dialogue_repository(store, publisher)
    )
    resolved_progress = (
        progress
        if progress is not None
        else build_learner_progress_repository(store, publisher, snapshot_store=snapshot_store)
    )
    return SocraticDialogueService(
        executor=resolved_executor,
        dialogues=resolved_registry,
        read_model=dialogues,
        now=now,
        transcripts=resolved_transcripts,
        clock=resolved_clock,
        progress=resolved_progress,
    )


def build_document_extractor(
    *,
    open_knowledge: Callable[[UUID], Awaitable[KnowledgePort]],
    corpus_readers: Callable[[UUID], CorpusReadPort],
    reporters: Callable[[UUID], Callable[[ExtractionNote], None]] | None = None,
) -> DocumentExtractor:
    """Construct the document extraction service."""
    return DocumentExtractor(
        open_knowledge=open_knowledge,
        corpus_readers=corpus_readers,
        reporters=reporters,
    )


def build_corpus_editor(
    *,
    open_knowledge: Callable[[UUID], Awaitable[KnowledgePort]],
    corpus_readers: Callable[[UUID], CorpusReadPort],
    corpus_repository: AggregateRepository[Corpus],
    blob_store: BlobStorePort,
) -> CorpusEditor:
    """Construct the corpus editing service."""
    return CorpusEditor(
        open_knowledge=open_knowledge,
        readers=corpus_readers,
        corpus=corpus_repository,
        blobs=blob_store,
    )


def build_media_perceiver(
    *,
    perception: PerceptionPort,
    corpus_readers: Callable[[UUID], CorpusReadPort],
    corpus_repository: AggregateRepository[Corpus],
    max_chars: Callable[[], int] | None = None,
) -> MediaPerceiver:
    """Construct the media perception service."""
    resolved_max_chars = max_chars if max_chars is not None else config.perception_max_chars
    return MediaPerceiver(
        port=perception,
        corpus_readers=corpus_readers,
        corpus=corpus_repository,
        max_chars=resolved_max_chars,
    )


@dataclass(frozen=True)
class ContentPipeline:
    """The bundle of content extraction, editing, and perception services."""

    document_extractor: DocumentExtractor
    editor: CorpusEditor
    media_perceiver: MediaPerceiver
    corpus_repository: AggregateRepository[Corpus]


def build_content_pipeline(
    *,
    open_graph: (
        Callable[[UUID], Awaitable[tuple[RedstringKnowledge, tuple[BaseTool, ...]]]] | None
    ) = None,
    open_knowledge: Callable[[UUID], Awaitable[KnowledgePort]] | None = None,
    corpus_readers: Callable[[UUID], CorpusReadPort],
    store: SQLiteEventStore,
    publisher: EventPublisher | None = None,
    snapshot_store: SQLiteSnapshotStore | None = None,
    blob_store: BlobStorePort,
    perception: PerceptionPort,
    perception_max_chars: Callable[[], int] | None = None,
    extractions: ExtractionChannel | None = None,
    reporters: Callable[[UUID], Callable[[ExtractionNote], None]] | None = None,
    corpus_repository: AggregateRepository[Corpus] | None = None,
) -> ContentPipeline:
    """Construct document extractor, corpus editor, and media perceiver.

    `open_graph` returns the knowledge port *and* the project's tools; only
    the port is wanted here. Discarding the tools costs building them -- four
    tool sets constructed and dropped per extraction -- which is a handful of
    dataclasses against a call that is about to spend minutes of model time.
    """
    if open_knowledge is None:
        if open_graph is None:
            raise ValueError("Either open_graph or open_knowledge must be provided")

        async def _open_knowledge(target_project_id: UUID) -> RedstringKnowledge:
            knowledge, _tools = await open_graph(target_project_id)
            return knowledge

        resolved_open_knowledge: Callable[[UUID], Awaitable[KnowledgePort]] = _open_knowledge
    else:
        resolved_open_knowledge = open_knowledge

    resolved_reporters = (
        reporters
        if reporters is not None
        else (extractions.reporter if extractions is not None else None)
    )

    resolved_corpus_repo = (
        corpus_repository
        if corpus_repository is not None
        else build_corpus_repository(
            store,
            publisher,
            snapshot_store=snapshot_store,
        )
    )

    document_extractor = build_document_extractor(
        open_knowledge=resolved_open_knowledge,
        corpus_readers=corpus_readers,
        reporters=resolved_reporters,
    )
    editor = build_corpus_editor(
        open_knowledge=resolved_open_knowledge,
        corpus_readers=corpus_readers,
        corpus_repository=resolved_corpus_repo,
        blob_store=blob_store,
    )
    media_perceiver = build_media_perceiver(
        perception=perception,
        corpus_readers=corpus_readers,
        corpus_repository=resolved_corpus_repo,
        max_chars=perception_max_chars,
    )

    return ContentPipeline(
        document_extractor=document_extractor,
        editor=editor,
        media_perceiver=media_perceiver,
        corpus_repository=resolved_corpus_repo,
    )


@dataclass(frozen=True)
class SessionWiring:
    """Session service and turn supervisor."""

    service: SessionService
    turns: TurnSupervisor


def build_session_service(
    *,
    repository: EventStoreSessionRepository,
    executor: TurnExecutor,
    summaries: SessionSummaryRunner,
    system_prompt: str,
    prompt_suffix: str = "",
    context: ContextStrategy | None = None,
    tracer: Tracer | None = None,
    attachment: KnowledgeAttachment,
    graphs: ProjectGraphs | None = None,
    activity: TurnActivityBuffer | None = None,
    progress: AggregateRepository[LearnerProgress] | None = None,
) -> SessionWiring:
    """Construct SessionService and TurnSupervisor with full tool prompt support."""
    resolved_progress = (
        progress
        if progress is not None
        else build_learner_progress_repository(
            repository.store,
            repository.publisher,
            snapshot_store=repository.snapshot_store,
        )
    )
    service = SessionService(
        repository,
        executor,
        summaries,
        repository.projects,
        default_system_prompt=system_prompt + prompt_suffix,
        context=context,
        tracer=tracer,
        knowledge_prompt=(
            KNOWLEDGE_PROMPT + CORPUS_PROMPT + FETCH_CORPUS_PROMPT + TOPICS_PROMPT
        ),
        attachment=attachment,
        progress=resolved_progress,
        graphs=graphs,
    )
    turns = TurnSupervisor(service, activity=activity)
    return SessionWiring(service=service, turns=turns)


@dataclass(frozen=True)
class MediaAcquisitionWiring:
    """Worker, reconciler, and HTTP client for media acquisition."""

    worker: MediaAcceptWorker
    reconciler: MediaAcceptReconciler
    client: httpx.AsyncClient


def build_media_acquisition(
    *,
    media_proposals: MediaProposalRunner,
    media_proposal_repository: AggregateRepository[MediaProposals],
    editor: CorpusEditor,
    media_perceiver: MediaPerceiver,
    media_http_client: httpx.AsyncClient | None = None,
) -> MediaAcquisitionWiring:
    """Construct media download worker, accept reconciler, and HTTP client."""
    client = (
        media_http_client
        if media_http_client is not None
        else httpx.AsyncClient(timeout=httpx.Timeout(30.0))
    )
    worker = MediaAcceptWorker(
        reads=media_proposals,
        proposals=media_proposal_repository,
        editor=editor,
        perceiver=media_perceiver,
        client=client,
    )
    reconciler = MediaAcceptReconciler(
        reads=media_proposals,
        worker=worker,
    )
    return MediaAcquisitionWiring(worker=worker, reconciler=reconciler, client=client)


@dataclass(frozen=True)
class SupervisorWiring:
    """Supervisors, dispatchers, and worker roster for autonomous execution."""

    research: ResearchSupervisor
    topic_seeder: TopicSeeder
    course_author: CourseAuthor
    dispatcher: TopicDispatcher
    workers: WorkerRoster


def build_supervisor_roster(
    *,
    service: SessionService,
    turns: TurnSupervisor,
    runs: AggregateRepository[ResearchRun],
    topics: TopicRunner,
    topic_repository: AggregateRepository[Topic],
    topic_reader: Callable[[UUID], TopicReadPort],
    policy: AutonomyPolicy,
    grants: GrantRegistry,
    summaries: SessionSummaryRunner,
    extractions: ExtractionChannel | None = None,
    dispatches: DispatchesInFlight | None = None,
    worker_roster_cls: type[WorkerRoster] | Callable[..., WorkerRoster] = WorkerRoster,
) -> SupervisorWiring:
    """Construct autonomous run driver, supervisors, dispatchers, and worker roster."""

    async def start_run(
        run_id: UUID,
        run_project_id: UUID,
        session_id: UUID,
        budget: Budget | None,
        fetch_hosts: list[str],
        fetch_budget: int,
        cancelled,
    ):
        """One autonomous run: a driver, bound to one session's turns."""
        return await ResearchRunDriver(
            runs,
            topic_repository,
            topics.queue,
            run_round=TopicRoundRunner(
                topic_repository,
                lambda prompt: turns.run(session_id, prompt),
            ),
            settle=topics.caught_up,
            grants=grants,
        ).run(
            run_project_id,
            session_id,
            budget=budget,
            fetch_hosts=fetch_hosts,
            fetch_budget=fetch_budget,
            run_id=run_id,
            cancelled=cancelled,
            autonomy_snapshot=policy.levels(),
            read_only=policy.level_for(FETCH_TOOL) != "auto",
        )

    research_supervisor = ResearchSupervisor(start_run, runs)
    topic_seeder = TopicSeeder(service, turns)
    course_author = CourseAuthor(service, turns)
    dispatcher = TopicDispatcher(service, turns, topic_reader)
    worker_roster = worker_roster_cls(
        service,
        turns=turns,
        runs=research_supervisor,
        extractions=extractions,
        dispatches=dispatches,
        summaries=SummaryProjects(summaries),
    )
    return SupervisorWiring(
        research=research_supervisor,
        topic_seeder=topic_seeder,
        course_author=course_author,
        dispatcher=dispatcher,
        workers=worker_roster,
    )
