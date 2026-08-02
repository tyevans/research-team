"""The application layer: use cases, read models, and the ports they need.

Depends on the domain and on its own port declarations -- never on a concrete
store, model provider, or user interface.
"""

from research_team.application.ports import (
    ActivityReporter,
    RecordedMessage,
    SessionRepository,
    TurnAccountingError,
    TurnExecutor,
    TurnResult,
)
from research_team.application.session_service import (
    DEFAULT_SYSTEM_PROMPT,
    SessionService,
    create_session,
)
from research_team.application.summaries import SessionSummary, summarize_sessions

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "ActivityReporter",
    "RecordedMessage",
    "SessionRepository",
    "SessionService",
    "SessionSummary",
    "TurnAccountingError",
    "TurnExecutor",
    "TurnResult",
    "create_session",
    "summarize_sessions",
]
