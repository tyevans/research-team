from typing import Any
from uuid import uuid4

import pytest
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.snapshots import SQLiteSnapshotStore
from eventsource.application.aggregates.repository import AggregateRepository
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from research_team import runtime as rt
from research_team.session import CodingSession

SYSTEM_PROMPT = "You are a coding agent."
MODEL_NAME = "test-model"


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "test.db")


@pytest.fixture(autouse=True)
async def isolate_database(tmp_path, monkeypatch):
    """Keep tests off the real database, and close what they open.

    Every test gets its own file, so `AGENT_DB` is pointed at it -- otherwise
    a bare `build_runtime()` in a test body would append to the developer's
    own `~/.research-team/sessions.db`. Runtimes built during the test are
    tracked and closed here, since SQLite connections are not garbage.
    """
    monkeypatch.setenv("AGENT_DB", str(tmp_path / "auto.db"))

    opened: list[rt.AgentRuntime] = []
    real_build = rt.build_runtime

    async def tracking_build(**kwargs):
        runtime = await real_build(**kwargs)
        opened.append(runtime)
        return runtime

    monkeypatch.setattr(rt, "build_runtime", tracking_build)
    yield
    for runtime in opened:
        await runtime.close()


@pytest.fixture
async def store(db_path) -> SQLiteEventStore:
    opened = SQLiteEventStore(db_path)
    yield opened
    await opened.close()


@pytest.fixture
def repo(store, db_path) -> AggregateRepository[CodingSession]:
    return AggregateRepository(
        store,
        CodingSession,
        # Same file as the event store: the store's connection is what applies
        # the schema that creates the `snapshots` table.
        snapshot_store=SQLiteSnapshotStore(db_path),
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
