"""The application layer: use cases, read models, and the ports they need.

Depends on the domain and on its own port declarations -- never on a concrete
store, model provider, or user interface.
"""

from research_team.application.live_feed import LiveFeed
from research_team.application.ports import (
    ActivityReporter,
    EventFeed,
    FeedEntry,
    RecordedMessage,
    SessionRepository,
    TurnAccountingError,
    TurnExecutor,
    TurnResult,
)
from research_team.application.session_service import (
    DEFAULT_SYSTEM_PROMPT,
    SessionService,
    TurnOutcome,
)
from research_team.application.turn_supervisor import (
    Cancellation,
    RunningTurn,
    TurnAlreadyRunning,
    TurnCancelled,
    TurnSupervisor,
)
from research_team.application.summaries import (
    ForkNode,
    SessionSummary,
    build_fork_tree,
    summarize_sessions,
)

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "ActivityReporter",
    "Cancellation",
    "RunningTurn",
    "EventFeed",
    "FeedEntry",
    "ForkNode",
    "LiveFeed",
    "build_fork_tree",
    "RecordedMessage",
    "SessionRepository",
    "SessionService",
    "SessionSummary",
    "TurnAccountingError",
    "TurnAlreadyRunning",
    "TurnCancelled",
    "TurnExecutor",
    "TurnOutcome",
    "TurnSupervisor",
    "TurnResult",
    "summarize_sessions",
]
