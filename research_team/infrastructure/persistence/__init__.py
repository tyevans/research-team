"""Storage adapters. The only layer that knows the log lives in SQLite."""

from research_team.infrastructure.persistence.event_store import (
    SNAPSHOT_THRESHOLD,
    EventStoreSessionRepository,
    build_aggregate_repository,
)

__all__ = [
    "SNAPSHOT_THRESHOLD",
    "EventStoreSessionRepository",
    "build_aggregate_repository",
]
