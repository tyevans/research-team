"""The application layer: use cases, read models, and the ports they need.

Depends on the domain and on its own port declarations -- never on a concrete
store, model provider, or user interface.
"""

from research_team.application.autonomy import (
    GATED_TOOLS,
    SEARCH_TOOL,
    AutonomyPolicy,
    Level,
)
from research_team.application.context import (
    Compaction,
    ContextStrategy,
    ElideToolResults,
    FullHistory,
    PreparedContext,
)
from research_team.application.knowledge import (
    GRAPH_SEARCH_TOOL,
    REMEMBER_TOOL,
    UNMERGE_TOOL,
    IngestReport,
    KnowledgeError,
    KnowledgePort,
    Match,
    MergeRecord,
    SourceRef,
)
from research_team.application.live_feed import LiveFeed
from research_team.application.ports import (
    ActivityReporter,
    ApprovalDecision,
    ApprovalPort,
    ApprovalRequest,
    EventFeed,
    FeedEntry,
    RecordedMessage,
    SessionRepository,
    SessionSummaries,
    SummaryHealth,
    TurnAccountingError,
    TurnExecutor,
    TurnResult,
)
from research_team.application.session_service import (
    DEFAULT_SYSTEM_PROMPT,
    SessionService,
    TurnOutcome,
)
from research_team.application.summaries import (
    ForkNode,
    SessionSummary,
    build_fork_tree,
    summarize_sessions,
)
from research_team.application.turn_supervisor import (
    Cancellation,
    RunningTurn,
    TurnAlreadyRunning,
    TurnCancelled,
    TurnSupervisor,
)

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "GATED_TOOLS",
    "GRAPH_SEARCH_TOOL",
    "REMEMBER_TOOL",
    "SEARCH_TOOL",
    "UNMERGE_TOOL",
    "ActivityReporter",
    "ApprovalDecision",
    "ApprovalPort",
    "ApprovalRequest",
    "AutonomyPolicy",
    "Cancellation",
    "Compaction",
    "ContextStrategy",
    "ElideToolResults",
    "EventFeed",
    "FeedEntry",
    "ForkNode",
    "FullHistory",
    "IngestReport",
    "KnowledgeError",
    "KnowledgePort",
    "Level",
    "LiveFeed",
    "Match",
    "MergeRecord",
    "PreparedContext",
    "RecordedMessage",
    "RunningTurn",
    "SessionRepository",
    "SessionService",
    "SessionSummaries",
    "SessionSummary",
    "SourceRef",
    "SummaryHealth",
    "TurnAccountingError",
    "TurnAlreadyRunning",
    "TurnCancelled",
    "TurnExecutor",
    "TurnOutcome",
    "TurnResult",
    "TurnSupervisor",
    "build_fork_tree",
    "summarize_sessions",
]
