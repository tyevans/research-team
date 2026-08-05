from typing import Any
from uuid import uuid4

import pytest
from eventsource import InMemoryEventBus
from eventsource.adapters.sqlite import SQLiteEventStore
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from redstring import FakeLlmProvider

#: A canned extraction result: two people and the relationship between them.
#: Shared by every test that needs `build_graph` to produce *something*
#: recognisable without caring what text it was fed -- `fake_provider()`
#: below answers with this regardless of input.
TWO_PEOPLE = {
    "entities": [
        {"name": "Ada Lovelace", "entity_type": "Person"},
        {"name": "Charles Babbage", "entity_type": "Person"},
    ],
    "relationships": [
        {
            "source_name": "Ada Lovelace",
            "target_name": "Charles Babbage",
            "relationship_type": "WORKED_WITH",
        }
    ],
}


def fake_provider(answer: dict = TWO_PEOPLE) -> FakeLlmProvider:
    """A `FakeLlmProvider` that answers the same regardless of input text.

    `FakeLlmProvider()` with no arguments raises -- it requires exactly one
    of `script=` or `by_substring=`, deliberately, because a fake with no
    canned answers cannot answer anything. An empty `by_substring` mapping
    never matches any text, so every call falls through to `default`, which
    is redstring's own idiom for "same answer no matter what".
    """
    return FakeLlmProvider(by_substring={}, default=answer)


from research_team import composition
from research_team.application import SessionService
from research_team.domain import (
    CodingSession,
    StartSession,
)
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
async def build_applications():
    """Build whole applications, started, and close them afterwards.

    Building is synchronous and starting is not, because the `/sessions`
    projection opens a connection that belongs to whichever loop opened it.
    The fixture does both, so a test never sees an application that is wired
    but not yet following the log.

    SQLite connections are not garbage, so anything opened during a test is
    tracked here and closed when it ends -- including any in-flight turn,
    which is cancelled rather than stranded past the end of the loop.
    """
    opened = []

    async def build(**kwargs):
        application = composition.build_application(**kwargs)
        opened.append(application)
        await application.start()
        return application

    yield build
    for application in opened:
        await application.close()


@pytest.fixture
def build_application(build_applications):
    return build_applications


@pytest.fixture
def build_service(build_applications):
    """Just the use cases, for tests with no use for a live feed."""

    async def build(**kwargs) -> SessionService:
        return (await build_applications(**kwargs)).service

    return build


@pytest.fixture
async def store(db_path) -> SQLiteEventStore:
    opened = SQLiteEventStore(db_path)
    yield opened
    await opened.close()


@pytest.fixture
def publisher() -> InMemoryEventBus:
    """The bus a save announces itself on, so a waiting reader wakes."""
    return InMemoryEventBus()


@pytest.fixture
def aggregates(store, db_path, publisher):
    """The raw `eventsource` aggregate repository, for tests that need it."""
    return build_aggregate_repository(store, db_path, publisher)


@pytest.fixture
def repository(store, aggregates, publisher) -> EventStoreSessionRepository:
    return EventStoreSessionRepository(store, aggregates, publisher)


@pytest.fixture
def session_id():
    return uuid4()


@pytest.fixture
def session(aggregates, session_id) -> CodingSession:
    aggregate = aggregates.create_new(session_id)
    aggregate.execute(StartSession(system_prompt=SYSTEM_PROMPT, model_name=MODEL_NAME))
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
