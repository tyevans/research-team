"""Session application ports and contracts.

Ports and protocol interfaces for the Session bounded context, defining how
the use cases orchestrate session lifecycles, turns, approvals, and projections.
"""

from research_team.platform.shared.ports import (
    ActivityDelta,
    ActivityMessage,
    ActivityNote,
    ActivityRemark,
    ActivityReporter,
    ApprovalDecision,
    ApprovalPort,
    ApprovalRefused,
    ApprovalRequest,
    MessageKind,
    RecordedMessage,
    SessionRepository,
    SessionSummaries,
    SummaryHealth,
    TurnAccountingError,
    TurnActivityBuffer,
    TurnExecutor,
    TurnResult,
)

__all__ = [
    "ActivityDelta",
    "ActivityMessage",
    "ActivityNote",
    "ActivityRemark",
    "ActivityReporter",
    "ApprovalDecision",
    "ApprovalPort",
    "ApprovalRefused",
    "ApprovalRequest",
    "MessageKind",
    "RecordedMessage",
    "SessionRepository",
    "SessionSummaries",
    "SummaryHealth",
    "TurnAccountingError",
    "TurnActivityBuffer",
    "TurnExecutor",
    "TurnResult",
]
