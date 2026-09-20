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

from eventsource import EventPublisher
from eventsource.adapters.sqlite import SQLiteEventStore, SQLiteSnapshotStore
from eventsource.application.aggregates.repository import AggregateRepository
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from research_team.application import ExtractionChannel
from research_team.application.ask import AskExecutor, AskService, ConversationRegistry
from research_team.application.blobs import BlobStorePort
from research_team.application.corpus_editing import CorpusEditor
from research_team.application.corpus_read import CorpusReadPort
from research_team.application.document_extraction import DocumentExtractor
from research_team.application.knowledge import ExtractionNote, KnowledgePort
from research_team.application.perception import MediaPerceiver, PerceptionPort
from research_team.application.socratic import (
    DialogueReadModel,
    DialogueRegistry,
    SocraticDialogueService,
    SocraticExecutor,
)
from research_team.domain.ask_conversation import AskConversation
from research_team.domain.corpus import Corpus
from research_team.domain.learner import LearnerProgress
from research_team.domain.socratic_dialogue import SocraticDialogue
from research_team.infrastructure import config
from research_team.infrastructure.agent.ask_agent import DeepAgentAskExecutor
from research_team.infrastructure.agent.socratic_agent import DeepAgentSocraticExecutor
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from research_team.infrastructure.persistence import (
    build_ask_conversation_repository,
    build_corpus_repository,
    build_learner_progress_repository,
)
from research_team.infrastructure.persistence.event_store import (
    build_socratic_dialogue_repository,
)

__all__ = [
    "ContentPipeline",
    "build_ask_service",
    "build_content_pipeline",
    "build_corpus_editor",
    "build_document_extractor",
    "build_media_perceiver",
    "build_socratic_service",
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
