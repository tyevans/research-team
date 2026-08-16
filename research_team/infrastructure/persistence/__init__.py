"""Storage adapters. The only layer that knows the log lives in SQLite."""

from research_team.infrastructure.persistence.event_store import (
    SNAPSHOT_THRESHOLD,
    EventStoreSessionRepository,
    build_aggregate_repository,
    build_corpus_repository,
    build_judgements_repository,
    build_learner_progress_repository,
    build_project_repository,
    build_research_run_repository,
    build_topic_repository,
)
from research_team.infrastructure.persistence.read_models import (
    CorpusDocumentRow,
    CorpusMediaRow,
    CorpusProjection,
    CorpusRunner,
    CorpusStore,
    SessionSummaryProjection,
    SessionSummaryRow,
    SessionSummaryRunner,
    SessionSummaryStore,
)
from research_team.infrastructure.persistence.topics import (
    TopicProjection,
    TopicQueue,
    TopicRow,
    TopicRunner,
    TopicStore,
)

__all__ = [
    "SNAPSHOT_THRESHOLD",
    "CorpusDocumentRow",
    "CorpusMediaRow",
    "CorpusProjection",
    "CorpusRunner",
    "CorpusStore",
    "EventStoreSessionRepository",
    "SessionSummaryProjection",
    "SessionSummaryRow",
    "SessionSummaryRunner",
    "SessionSummaryStore",
    "TopicProjection",
    "TopicQueue",
    "TopicRow",
    "TopicRunner",
    "TopicStore",
    "build_aggregate_repository",
    "build_corpus_repository",
    "build_judgements_repository",
    "build_learner_progress_repository",
    "build_project_repository",
    "build_research_run_repository",
    "build_topic_repository",
]
