"""Content extraction, corpus editing, media perception, and acquisition wiring."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

import httpx
from eventsource import EventPublisher
from eventsource.adapters.sqlite import SQLiteEventStore, SQLiteSnapshotStore
from eventsource.application.aggregates.repository import AggregateRepository
from langchain_core.tools import BaseTool

from research_team.infrastructure import config
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from research_team.infrastructure.persistence import build_corpus_repository
from research_team.infrastructure.persistence.read_models import MediaProposalRunner
from research_team.knowledge.application import ExtractionNote, KnowledgePort
from research_team.platform.shared.blobs import BlobStorePort
from research_team.research.application.corpus_editing import CorpusEditor
from research_team.research.application.corpus_read import CorpusReadPort
from research_team.research.application.document_extraction import DocumentExtractor
from research_team.research.application.media_acquisition import (
    MediaAcceptReconciler,
    MediaAcceptWorker,
)
from research_team.research.application.perception import MediaPerceiver, PerceptionPort
from research_team.research.domain.corpus import Corpus
from research_team.research.domain.media_proposals import MediaProposals
from research_team.session.application.workers import ExtractionChannel


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


__all__ = [
    "ContentPipeline",
    "MediaAcquisitionWiring",
    "build_content_pipeline",
    "build_corpus_editor",
    "build_document_extractor",
    "build_media_acquisition",
    "build_media_perceiver",
]
