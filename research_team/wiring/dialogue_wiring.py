"""Dialogue service construction builders for Ask and Socratic flows."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from eventsource import EventPublisher
from eventsource.adapters.sqlite import SQLiteEventStore, SQLiteSnapshotStore
from eventsource.application.aggregates.repository import AggregateRepository
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from research_team.curriculum.domain.learner import LearnerProgress
from research_team.dialogue.application.ask import (
    AskExecutor,
    AskService,
    ConversationRegistry,
)
from research_team.dialogue.application.socratic import (
    DialogueReadModel,
    DialogueRegistry,
    SocraticDialogueService,
    SocraticExecutor,
)
from research_team.dialogue.domain.ask import AskConversation
from research_team.dialogue.domain.socratic import SocraticDialogue
from research_team.infrastructure.agent.ask_agent import DeepAgentAskExecutor
from research_team.infrastructure.agent.socratic_agent import DeepAgentSocraticExecutor
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from research_team.infrastructure.persistence import (
    build_ask_conversation_repository,
    build_learner_progress_repository,
)
from research_team.infrastructure.persistence.event_store import (
    build_socratic_dialogue_repository,
)


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


__all__ = [
    "build_ask_service",
    "build_socratic_service",
]
