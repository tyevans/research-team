from typing import Any
from uuid import uuid4

import pytest
from eventsource.adapters.sqlite import SQLiteEventStore
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from research_team import composition
from research_team.application import SessionService
from research_team.domain import CodingSession
from research_team.infrastructure.persistence import (
    EventStoreSessionRepository,
    build_aggregate_repository,
)

SYSTEM_PROMPT = "You are a coding agent."
MODEL_NAME = "test-model"


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "test.db")


@pytest.fixture(autouse=True)
def isolate_database(tmp_path, monkeypatch):
    """Keep tests off the real database.

    Every test gets its own file, so `AGENT_DB` is pointed at it -- otherwise a
    bare `build_service()` in a test body would append to the developer's own
    `~/.research-team/sessions.db`.
    """
    monkeypatch.setenv("AGENT_DB", str(tmp_path / "auto.db"))


@pytest.fixture
async def build_service():
    """Build services and close them afterwards.

    SQLite connections are not garbage, so anything opened during a test is
    tracked here and closed when it ends. Building is synchronous -- a service
    creates no session, so there is nothing to await.
    """
    opened: list[SessionService] = []

    def build(**kwargs) -> SessionService:
        service = composition.build_service(**kwargs)
        opened.append(service)
        return service

    yield build
    for service in opened:
        await service.close()


@pytest.fixture
async def store(db_path) -> SQLiteEventStore:
    opened = SQLiteEventStore(db_path)
    yield opened
    await opened.close()


@pytest.fixture
def aggregates(store, db_path):
    """The raw `eventsource` aggregate repository, for tests that need it."""
    return build_aggregate_repository(store, db_path)


@pytest.fixture
def repository(store, aggregates) -> EventStoreSessionRepository:
    return EventStoreSessionRepository(store, aggregates)


@pytest.fixture
def session_id():
    return uuid4()


@pytest.fixture
def session(aggregates, session_id) -> CodingSession:
    aggregate = aggregates.create_new(session_id)
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
