"""Tests for LearnerProgressService and cross-BC progress isolation."""

from typing import Any
from uuid import uuid4

import pytest
from eventsource import OptimisticLockError

from research_team.curriculum.application.learner_progress import (
    LearnerProgressService,
    learner_initial_state,
)
from research_team.curriculum.domain.learner import LearnerProgress


class InMemoryProgressAggregate:
    def __init__(self, progress_id):
        self.aggregate_id = progress_id
        self._aggregate = LearnerProgress(progress_id)

    @property
    def state(self):
        return self._aggregate.state

    def execute(self, command):
        self._aggregate.execute(command)


class InMemoryProgressRepository:
    def __init__(self):
        self._store: dict[Any, InMemoryProgressAggregate] = {}
        self.save_count = 0
        self.fail_once_with: Exception | None = None

    async def load_or_create(self, progress_id):
        if progress_id not in self._store:
            self._store[progress_id] = InMemoryProgressAggregate(progress_id)
        return self._store[progress_id]

    async def save(self, aggregate):
        self.save_count += 1
        if self.fail_once_with is not None:
            err = self.fail_once_with
            self.fail_once_with = None
            raise err
        self._store[aggregate.aggregate_id] = aggregate


@pytest.mark.asyncio
async def test_learner_progress_service_without_repository():
    service = LearnerProgressService(repository=None)
    assert service.repository is None

    progress_id = uuid4()
    state = await service.get_progress(progress_id)
    assert state == learner_initial_state()
    assert state.status == "new"

    attempt_state = await service.record_attempt(
        progress_id,
        path="/lesson-1.md",
        component_id="q1",
        component_type="mcq",
        digest="sha256-abc",
        correct=True,
        score=1.0,
    )
    assert attempt_state == learner_initial_state()

    checklist_state = await service.record_checklist(
        progress_id,
        path="/lesson-1.md",
        component_id="c1",
        checked=[0, 1],
    )
    assert checklist_state == learner_initial_state()


@pytest.mark.asyncio
async def test_learner_progress_service_records_attempts_and_checklists():
    repo = InMemoryProgressRepository()
    service = LearnerProgressService(repository=repo)
    assert service.repository is repo

    progress_id = uuid4()

    # Initial state is clean
    initial = await service.get_progress(progress_id)
    assert initial.status == "new"
    assert len(initial.items) == 0

    # Record first attempt (correct)
    state1 = await service.record_attempt(
        progress_id,
        path="/lesson-1.md",
        component_id="q1",
        component_type="mcq",
        digest="digest-1",
        response={"choice": 2},
        correct=True,
        score=1.0,
    )
    assert state1.status == "created"
    item1 = state1.item("/lesson-1.md", "q1")
    assert item1 is not None
    assert item1.correct is True
    assert item1.attempts == 1

    # Record checklist state
    state2 = await service.record_checklist(
        progress_id,
        path="/lesson-1.md",
        component_id="checklist-1",
        checked=[0, 2],
    )
    chk = state2.item("/lesson-1.md", "checklist-1")
    assert chk is not None
    assert chk.checked == [0, 2]

    # Verify get_progress returns current state
    current = await service.get_progress(progress_id)
    assert current == state2
    assert repo.save_count == 2


@pytest.mark.asyncio
async def test_learner_progress_service_retries_on_optimistic_lock():
    repo = InMemoryProgressRepository()
    service = LearnerProgressService(repository=repo)
    progress_id = uuid4()

    # Pre-seed failure on first save attempt
    repo.fail_once_with = OptimisticLockError("concurrent modification", 1, 2)

    state = await service.record_attempt(
        progress_id,
        path="/lesson-2.md",
        component_id="q2",
        component_type="input",
        digest="digest-2",
        correct=True,
        score=1.0,
    )
    item2 = state.item("/lesson-2.md", "q2")
    assert item2 is not None
    assert item2.correct is True
    # Saved twice due to retry
    assert repo.save_count == 2
