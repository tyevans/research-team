from uuid import uuid4

import pytest
from eventsource.adapters.memory import InMemoryEventStore
from eventsource.adapters.memory.snapshots import InMemorySnapshotStore
from eventsource.application.aggregates.repository import AggregateRepository

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
