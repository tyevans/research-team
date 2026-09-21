"""Turn executor wiring for application composition.

Extracts the DeepAgentTurnExecutor construction, including granted tools,
automatic corpus keeping, turn middleware, dynamic subagents, and per-project
model overrides out of composition.py.
"""

import logging
from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from research_team.infrastructure.agent import DeepAgentTurnExecutor, build_model
from research_team.infrastructure.agent.component_feedback import ComponentFeedback
from research_team.infrastructure.agent.fetch import build_fetch_tool
from research_team.infrastructure.agent.recall import PageMemo, Recall
from research_team.infrastructure.agent.research_budget import ResearchBudget
from research_team.infrastructure.agent.search import SearchAttempts
from research_team.infrastructure.agent.search_middleware import SearchAttemptsMiddleware
from research_team.infrastructure.persistence import CorpusRunner
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.knowledge.application import (
    KnowledgeError,
    SourceRef,
    source_id_for_url,
)
from research_team.platform.shared.blobs import BlobStorePort
from research_team.platform.shared.ports import ApprovalPort
from research_team.session.application.autonomy import AutonomyPolicy
from research_team.session.domain import Session, SessionPurpose
from research_team.settings.application.effective import EffectiveSettings
from research_team.tenancy.application.grants import GrantRegistry
from research_team.wiring.helpers import _subagents_for

logger = logging.getLogger(__name__)


def build_turn_executor(
    *,
    resolved_model: BaseChatModel,
    injected_model: BaseChatModel | None,
    subagents: Sequence[dict],
    tools: Sequence[BaseTool],
    policy: AutonomyPolicy,
    approvals: ApprovalPort | None,
    grants: GrantRegistry,
    corpus: CorpusRunner,
    blob_store: BlobStorePort,
    recall: Recall,
    pages: PageMemo,
    search_attempts: SearchAttempts | None,
    authoring_rounds: int,
    effective_settings: EffectiveSettings,
    get_attachment: Callable[[], Any],
    build_fetch: Callable[..., BaseTool] = build_fetch_tool,
) -> DeepAgentTurnExecutor:
    """Wire DeepAgentTurnExecutor with dynamic per-turn providers."""

    def _keeper(project_id: UUID):
        """Save a fetched page to project_id's corpus, without extracting it."""

        async def keep(url: str) -> str | None:
            retained = pages.get(url)
            attachment = get_attachment() if get_attachment is not None else None
            knowledge = attachment.current if attachment is not None else None
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
                logger.warning(
                    "could not keep %s for project %s", url, project_id, exc_info=True
                )
                return None
            return source_id

        return keep

    async def granted_tools(session: Session) -> tuple[BaseTool, ...]:
        grant = grants.get(session.aggregate_id)
        if grant is None:
            return ()
        project_id = session.state.project_id
        return (
            build_fetch(
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

    async def turn_tools(session: Session) -> tuple[BaseTool, ...]:
        return await granted_tools(session)

    async def turn_middleware(session: Session) -> tuple[AgentMiddleware, ...]:
        return (
            ComponentFeedback(
                read=lambda path: session.state.files.get(path, {}).get("content")
            ),
            *(
                (SearchAttemptsMiddleware(search_attempts),)
                if search_attempts is not None
                else ()
            ),
            *(
                (ResearchBudget(rounds=authoring_rounds),)
                if session.state.purpose is SessionPurpose.COURSE_AUTHORING
                and authoring_rounds > 0
                else ()
            ),
        )

    async def turn_subagents(session: Session) -> Sequence[dict]:
        return _subagents_for(session, subagents)

    async def turn_model(session: Session) -> BaseChatModel | None:
        if injected_model is not None:
            return None
        project_id = session.state.project_id
        if project_id is None:
            return None
        return build_model(await effective_settings.research(project_id))

    return DeepAgentTurnExecutor(
        resolved_model,
        subagents=subagents,
        tools=tools,
        policy=policy,
        approvals=approvals,
        middleware_provider=turn_middleware,
        tools_provider=turn_tools,
        subagents_provider=turn_subagents,
        model_provider=turn_model,
        grants=grants,
    )
