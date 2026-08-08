"""The application layer: use cases, read models, and the ports they need.

Depends on the domain and on its own port declarations -- never on a concrete
store, model provider, or user interface.
"""

from research_team.application.auto_research import (
    AutoResearchDriver,
    RoundOutcome,
    RunReport,
)
from research_team.application.auto_round import (
    ROUND_INSTRUCTIONS,
    TopicRoundRunner,
    round_prompt,
)
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
    ExtractionNote,
    ExtractionReporter,
    ExtractionStage,
    IngestReport,
    KnowledgeError,
    KnowledgePort,
    Match,
    MergeRecord,
    SourceRef,
)
from research_team.application.knowledge_attachment import (
    CloseGraph,
    KnowledgeAttachment,
    OpenGraph,
    TurnExecutorTools,
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
from research_team.application.research_supervisor import (
    ActiveRun,
    ResearchSupervisor,
    RunAlreadyActive,
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
from research_team.application.workers import (
    ExtractionChannel,
    ExtractionsInFlight,
    ExtractionSnapshot,
    Roster,
    Worker,
    WorkerRoster,
)

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "GATED_TOOLS",
    "GRAPH_SEARCH_TOOL",
    "REMEMBER_TOOL",
    "ROUND_INSTRUCTIONS",
    "SEARCH_TOOL",
    "UNMERGE_TOOL",
    "ActiveRun",
    "ActivityReporter",
    "ApprovalDecision",
    "ApprovalPort",
    "ApprovalRequest",
    "AutoResearchDriver",
    "AutonomyPolicy",
    "Cancellation",
    "CloseGraph",
    "Compaction",
    "ContextStrategy",
    "ElideToolResults",
    "EventFeed",
    "ExtractionChannel",
    "ExtractionNote",
    "ExtractionReporter",
    "ExtractionSnapshot",
    "ExtractionStage",
    "ExtractionsInFlight",
    "FeedEntry",
    "ForkNode",
    "FullHistory",
    "IngestReport",
    "KnowledgeAttachment",
    "KnowledgeError",
    "KnowledgePort",
    "Level",
    "LiveFeed",
    "Match",
    "MergeRecord",
    "OpenGraph",
    "PreparedContext",
    "RecordedMessage",
    "ResearchSupervisor",
    "Roster",
    "RoundOutcome",
    "RunAlreadyActive",
    "RunReport",
    "RunningTurn",
    "SessionRepository",
    "SessionService",
    "SessionSummaries",
    "SessionSummary",
    "SourceRef",
    "SummaryHealth",
    "TopicRoundRunner",
    "TurnAccountingError",
    "TurnAlreadyRunning",
    "TurnCancelled",
    "TurnExecutor",
    "TurnExecutorTools",
    "TurnOutcome",
    "TurnResult",
    "TurnSupervisor",
    "Worker",
    "WorkerRoster",
    "build_fork_tree",
    "round_prompt",
    "summarize_sessions",
]
