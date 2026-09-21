"""The application layer: use cases, read models, and the ports they need.

Depends on the domain and on its own port declarations -- never on a concrete
store, model provider, or user interface.
"""

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
from research_team.application.knowledge.knowledge_attachment import (
    CloseGraph,
    KnowledgeAttachment,
    OpenGraph,
    TurnExecutorTools,
)
from research_team.application.knowledge.project_graphs import ProjectGraphs
from research_team.application.research.research_round import (
    ROUND_INSTRUCTIONS,
    TopicRoundRunner,
    round_prompt,
)
from research_team.application.research.research_run import (
    ResearchRunDriver,
    RoundOutcome,
    RunReport,
)
from research_team.application.research.research_supervisor import (
    ActiveRun,
    ResearchSupervisor,
    RunAlreadyActive,
)
from research_team.application.session.autonomy import (
    GATED_TOOLS,
    SEARCH_TOOL,
    AutonomyPolicy,
    Level,
)
from research_team.application.session.session_service import (
    DEFAULT_SYSTEM_PROMPT,
    SessionService,
    TurnOutcome,
)
from research_team.application.session.summaries import (
    ForkNode,
    SessionSummary,
    build_fork_tree,
    summarize_sessions,
)
from research_team.application.session.turn_supervisor import (
    Cancellation,
    RunningTurn,
    TurnAlreadyRunning,
    TurnCancelled,
    TurnSupervisor,
)
from research_team.application.session.workers import (
    DispatchesInFlight,
    DispatchSnapshot,
    ExtractionChannel,
    ExtractionsInFlight,
    ExtractionSnapshot,
    Roster,
    SummaryProjects,
    Worker,
    WorkerRoster,
)
from research_team.application.shared.context import (
    Compaction,
    ContextStrategy,
    ElideToolResults,
    FullHistory,
    PreparedContext,
)
from research_team.application.shared.live_feed import LiveFeed
from research_team.application.shared.ports import (
    ActivityReporter,
    ApprovalDecision,
    ApprovalPort,
    ApprovalRefused,
    ApprovalRequest,
    EventFeed,
    FeedEntry,
    RecordedMessage,
    SessionRepository,
    SessionSummaries,
    SummaryHealth,
    TurnAccountingError,
    TurnActivityBuffer,
    TurnExecutor,
    TurnResult,
)
from research_team.application.tenancy.project_sessions import ProjectSessions

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
    "ApprovalRefused",
    "ApprovalRequest",
    "AutonomyPolicy",
    "Cancellation",
    "CloseGraph",
    "Compaction",
    "ContextStrategy",
    "DispatchSnapshot",
    "DispatchesInFlight",
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
    "ProjectGraphs",
    "ProjectSessions",
    "RecordedMessage",
    "ResearchRunDriver",
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
    "SummaryProjects",
    "TopicRoundRunner",
    "TurnAccountingError",
    "TurnActivityBuffer",
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
