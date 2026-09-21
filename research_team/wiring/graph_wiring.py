"""Graph and knowledge store wiring for application composition.

Extracts ProjectGraphs, vector store opening, re-embedding, and
knowledge attachment construction out of composition.py.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from eventsource.adapters.sqlite import SQLiteEventStore
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from redstring import SlidingWindowChunker
from redstring.llm.adapters.langchain import LangChainLlmProvider

from research_team.infrastructure import config
from research_team.infrastructure.agent import (
    DeepAgentTurnExecutor,
    build_embedding_provider,
    build_extraction_model,
)
from research_team.infrastructure.agent.corpus_tools import build_corpus_tools
from research_team.infrastructure.agent.fetch import build_fetch_tool
from research_team.infrastructure.agent.fetch_media import build_fetch_media_tool
from research_team.infrastructure.agent.knowledge_tools import build_knowledge_tools
from research_team.infrastructure.agent.recall import PageMemo, Recall
from research_team.infrastructure.agent.topic_tools import (
    RepositoryTopics,
    build_topic_tools,
)
from research_team.infrastructure.knowledge.co_mentions import CoMentionIndex
from research_team.infrastructure.knowledge.entity_cards import index_cards
from research_team.infrastructure.knowledge.entity_embeddings import (
    refresh_project_embeddings,
)
from research_team.infrastructure.knowledge.markdown_table_chunker import (
    MarkdownTableChunker,
)
from research_team.infrastructure.knowledge.rebuild import rebuild_graph
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from research_team.infrastructure.knowledge.stores import (
    build_card_vector_store,
    build_chunk_store,
    build_graph_store,
    build_vector_store,
)
from research_team.infrastructure.persistence import (
    CorpusRunner,
    EventStoreSessionRepository,
    TopicRunner,
    build_corpus_repository,
    build_judgements_repository,
    build_topic_repository,
)
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.knowledge.application.knowledge_attachment import KnowledgeAttachment
from research_team.knowledge.application.project_graphs import ProjectGraphs
from research_team.platform.shared.blobs import BlobStorePort
from research_team.research.application.corpus_editing import CorpusEditor
from research_team.session.application.workers import ExtractionChannel
from research_team.settings.application.effective import EffectiveSettings


@dataclass(frozen=True)
class WiredGraphs:
    """Project graphs, embedding provider, and re-embedding routine."""

    graphs: ProjectGraphs
    embedding_provider: Any | None
    reembed_project: Callable[[UUID], Awaitable[int]]


def _index_cards_wrapper(*, graph: Any, cards: Any, tenant_id: UUID) -> Any:
    """Index cards with SlidingWindowChunker, preserving seam hygiene.

    The parameter is redstring's `tenant_id` (a project ID), forwarded as
    `tenant_id=project_id` to comply with test_tenant_naming_seam.py.
    """
    project_id = tenant_id
    return index_cards(
        graph=graph,
        cards=cards,
        tenant_id=project_id,
        chunker=SlidingWindowChunker(default_chunk_size=1000, default_overlap=500),
    )


def build_project_graphs(
    event_store: SQLiteEventStore,
    *,
    vector_kind: str | None = None,
    embedding_dimension: int | None = None,
    graph_store_kind: str | None = None,
    chunk_store_kind: str | None = None,
) -> WiredGraphs:
    """Wire ProjectGraphs and its lazy vector/chunk/card stores.

    PgVectorStore.connect is an async coroutine which awaits asyncpg.create_pool,
    while Neo4jGraphStore.connect is a synchronous lazy driver constructor.
    ProjectGraphs owns the open because `open` is the first `await` on the path.
    """
    resolved_vector_kind = vector_kind if vector_kind is not None else config.vector_store()
    resolved_embedding_dim = (
        embedding_dimension
        if embedding_dimension is not None
        else config.embedding_dimension()
    )
    resolved_graph_kind = (
        graph_store_kind if graph_store_kind is not None else config.graph_store()
    )
    resolved_chunk_kind = (
        chunk_store_kind if chunk_store_kind is not None else config.chunk_store()
    )

    async def open_vector_store():
        return await build_vector_store(resolved_vector_kind, dimension=resolved_embedding_dim)

    embedding_provider = (
        build_embedding_provider() if resolved_vector_kind != config.NO_VECTOR_STORE else None
    )

    graphs = ProjectGraphs(
        build_store=lambda: build_graph_store(resolved_graph_kind),
        rebuild=lambda store, target_project_id, **rebuild_kwargs: rebuild_graph(
            store, feed=event_store, project_id=target_project_id, **rebuild_kwargs
        ),
        open_vector_store=open_vector_store,
        embedding_model=embedding_provider.model if embedding_provider is not None else None,
        build_card_vectors=(
            (lambda: build_card_vector_store(dimension=resolved_embedding_dim))
            if embedding_provider is not None
            else None
        ),
        build_chunk_store=lambda: build_chunk_store(
            resolved_chunk_kind, dimension=resolved_embedding_dim
        ),
        build_co_mentions=CoMentionIndex,
        index_cards=_index_cards_wrapper,
    )

    async def reembed_project(target_project_id: UUID) -> int:
        """Re-embed every entity in one project, from the graph as it stands."""
        if embedding_provider is None:
            return 0
        store = await graphs.open(target_project_id)
        card_vectors = graphs.card_vectors(target_project_id)
        if card_vectors is None:
            return 0
        return await refresh_project_embeddings(
            graph=store,
            provider=embedding_provider,
            event_store=event_store,
            vectors=card_vectors,
            tenant_id=target_project_id,
        )

    return WiredGraphs(
        graphs=graphs,
        embedding_provider=embedding_provider,
        reembed_project=reembed_project,
    )


def build_graph_opener(
    *,
    graphs: ProjectGraphs,
    effective_settings: EffectiveSettings,
    model: BaseChatModel | None,
    extraction_model: BaseChatModel,
    repository: EventStoreSessionRepository,
    corpus: CorpusRunner,
    topics: TopicRunner,
    blob_store: BlobStorePort,
    recall: Recall,
    pages: PageMemo,
    extractions: ExtractionChannel | None,
    get_media_http_client: Callable[[], httpx.AsyncClient],
    get_editor: Callable[[], CorpusEditor],
    embedding_provider: Any | None,
    build_fetch: Callable[..., BaseTool] = build_fetch_tool,
) -> Callable[[UUID], Awaitable[tuple[RedstringKnowledge, tuple[BaseTool, ...]]]]:
    """Construct the `open_graph` closure for a project attachment."""

    async def open_graph(
        target_project_id: UUID,
    ) -> tuple[RedstringKnowledge, tuple[BaseTool, ...]]:
        store = await graphs.open(target_project_id)
        settings = await effective_settings.extraction(target_project_id)
        project_extraction_model = (
            extraction_model if model is not None else build_extraction_model(settings)
        )
        knowledge = RedstringKnowledge(
            target_project_id,
            store=store,
            event_store=repository.store,
            snapshot_store=repository.snapshot_store,
            provider=LangChainLlmProvider(project_extraction_model, model=settings.model),
            corpus=build_corpus_repository(
                repository.store,
                repository.publisher,
                snapshot_store=repository.snapshot_store,
            ),
            judgements=build_judgements_repository(
                repository.store,
                repository.publisher,
                snapshot_store=repository.snapshot_store,
            ),
            domain=settings.knowledge_domain,
            embeddings=embedding_provider,
            vector_store=await graphs.vectors(),
            card_vector_store=graphs.card_vectors(target_project_id),
            concurrency=settings.concurrency,
            consolidation_batch=settings.consolidation_batch,
            chunker=MarkdownTableChunker(
                SlidingWindowChunker(default_chunk_size=settings.chunk_size)
            ),
            chunks=graphs.chunks(target_project_id),
            cards=graphs.cards(target_project_id),
            co_mentions=graphs.co_mentions(target_project_id),
        )

        reader = ProjectCorpusReader(corpus, target_project_id, blob_store)
        topic_port = RepositoryTopics(
            build_topic_repository(
                repository.store,
                repository.publisher,
                snapshot_store=repository.snapshot_store,
            ),
            topics,
            target_project_id,
        )
        project_fetch = build_fetch(recall=recall, corpus=reader, pages=pages)
        fetch_media = build_fetch_media_tool(
            client=get_media_http_client(),
            editor=get_editor(),
            project_id=target_project_id,
        )
        return knowledge, (
            project_fetch,
            fetch_media,
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

    return open_graph


def build_knowledge_attachment(
    executor: DeepAgentTurnExecutor,
    tools: Sequence[BaseTool],
    open_graph: Callable[[UUID], Awaitable[tuple[RedstringKnowledge, tuple[BaseTool, ...]]]],
) -> KnowledgeAttachment:
    """Build KnowledgeAttachment over executor, base tools, and open_graph."""

    async def close_graph(knowledge: RedstringKnowledge) -> None:
        """A no-op: detaching a project from one session no longer closes its store."""

    return KnowledgeAttachment(
        executor,
        tools,
        open_graph=open_graph,
        close_graph=close_graph,
    )
