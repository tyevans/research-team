from typing import Any
from uuid import uuid4

import pytest
from eventsource.adapters.memory import InMemoryEventStore
from eventsource.adapters.memory.snapshots import InMemorySnapshotStore
from eventsource.application.aggregates.repository import AggregateRepository
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from research_team.session import CodingSession

SYSTEM_PROMPT = "You are a coding agent."
MODEL_NAME = "test-model"


@pytest.fixture
def store() -> InMemoryEventStore:
    return InMemoryEventStore()


@pytest.fixture
def snapshots() -> InMemorySnapshotStore:
    return InMemorySnapshotStore()


@pytest.fixture
def repo(store, snapshots) -> AggregateRepository[CodingSession]:
    return AggregateRepository(
        store,
        CodingSession,
        snapshot_store=snapshots,
        snapshot_threshold=50,
        snapshot_mode="sync",
    )


@pytest.fixture
def session_id():
    return uuid4()


@pytest.fixture
def session(repo, session_id) -> CodingSession:
    aggregate = repo.create_new(session_id)
    aggregate.start(SYSTEM_PROMPT, MODEL_NAME)
    return aggregate


class ToolAwareFakeChatModel(FakeMessagesListChatModel):
    """langchain's fake, plus the bind_tools deepagents requires.

    Replays `responses` one per invocation. Do not hand-roll a BaseChatModel
    subclass -- this is the library's fake with a single method added.
    """

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ToolAwareFakeChatModel":
        return self


@pytest.fixture
def fake_model() -> ToolAwareFakeChatModel:
    return ToolAwareFakeChatModel(responses=[AIMessage(content="done", id="a1")])
