"""Learner progress application service.

Encapsulates aggregate repository persistence, optimistic concurrency
retries, and fallback to initial empty state when no repository is wired.
"""

from typing import Any, Protocol
from uuid import UUID

from eventsource.application.aggregates.repository import AggregateRepository

from research_team.curriculum.domain.learner import (
    LearnerProgress,
    LearnerProgressState,
    RecordAttempt,
    RecordChecklistState,
)
from research_team.curriculum.domain.learner import (
    initial_state as learner_initial_state,
)
from research_team.platform.shared.retry import with_retry

__all__ = [
    "LearnerProgressPort",
    "LearnerProgressService",
    "LearnerProgressState",
    "learner_initial_state",
]


class LearnerProgressPort(Protocol):
    """Abstract port for reading and recording learner progress."""

    async def get_progress(self, progress_id: UUID) -> LearnerProgressState: ...

    async def record_attempt(
        self,
        progress_id: UUID,
        *,
        path: str,
        component_id: str,
        component_type: str,
        digest: str,
        response: Any = None,
        correct: bool = False,
        score: float = 0.0,
        at: int | None = None,
    ) -> LearnerProgressState: ...

    async def record_checklist(
        self,
        progress_id: UUID,
        *,
        path: str,
        component_id: str,
        checked: list[int],
    ) -> LearnerProgressState: ...


class LearnerProgressService:
    """Application service for reading and updating learner progress records.

    Manages repository interactions, optimistic concurrency retries, and default
    initial state when no progress aggregate repository is configured.
    """

    def __init__(
        self,
        repository: AggregateRepository[LearnerProgress] | None = None,
    ) -> None:
        self._repository = repository

    @property
    def repository(self) -> AggregateRepository[LearnerProgress] | None:
        """The underlying aggregate repository, if wired."""
        return self._repository

    async def get_progress(self, progress_id: UUID) -> LearnerProgressState:
        """What a learner has done with components under this progress id.

        Returns an empty initial state if progress tracking is disabled or if
        no answers have been recorded yet.
        """
        if self._repository is None:
            return learner_initial_state()
        aggregate = await self._repository.load_or_create(progress_id)
        return aggregate.state

    async def record_attempt(
        self,
        progress_id: UUID,
        *,
        path: str,
        component_id: str,
        component_type: str,
        digest: str,
        response: Any = None,
        correct: bool = False,
        score: float = 0.0,
        at: int | None = None,
    ) -> LearnerProgressState:
        """Record an attempt on a component with retry on concurrency conflicts."""
        if self._repository is None:
            return learner_initial_state()

        async def record() -> LearnerProgressState:
            aggregate = await self._repository.load_or_create(progress_id)
            aggregate.execute(
                RecordAttempt(
                    progress_id=progress_id,
                    path=path,
                    component_id=component_id,
                    component_type=component_type,
                    digest=digest,
                    response=response,
                    correct=correct,
                    score=score,
                    at=at,
                )
            )
            await self._repository.save(aggregate)
            return aggregate.state

        return await with_retry(record, what=f"recording an attempt at {component_id!r}")

    async def record_checklist(
        self,
        progress_id: UUID,
        *,
        path: str,
        component_id: str,
        checked: list[int],
    ) -> LearnerProgressState:
        """Remember which items on a checklist are checked with concurrency retries."""
        if self._repository is None:
            return learner_initial_state()

        async def record() -> LearnerProgressState:
            aggregate = await self._repository.load_or_create(progress_id)
            aggregate.execute(
                RecordChecklistState(
                    progress_id=progress_id,
                    path=path,
                    component_id=component_id,
                    checked=checked,
                )
            )
            await self._repository.save(aggregate)
            return aggregate.state

        return await with_retry(record, what=f"recording checklist {component_id!r}")
