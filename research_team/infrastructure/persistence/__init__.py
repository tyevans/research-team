"""Storage adapters. The only layer that knows the log lives in SQLite."""

from research_team.infrastructure.persistence.event_store import (
    SNAPSHOT_THRESHOLD,
    EventStoreSessionRepository,
    build_aggregate_repository,
    build_project_repository,
)
from research_team.infrastructure.persistence.read_models import (
    SessionSummaryProjection,
    SessionSummaryRow,
    SessionSummaryRunner,
    SessionSummaryStore,
)

__all__ = [
    "SNAPSHOT_THRESHOLD",
    "EventStoreSessionRepository",
    "SessionSummaryProjection",
    "SessionSummaryRow",
    "SessionSummaryRunner",
    "SessionSummaryStore",
    "build_aggregate_repository",
    "build_project_repository",
]
