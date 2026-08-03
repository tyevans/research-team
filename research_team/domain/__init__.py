"""The domain layer: events, the aggregate, and the state they fold into.

Depends on nothing but the event-sourcing primitives and pydantic. No
langchain, no deepagents, no SQLite, no environment. Everything above may
import from here; nothing here imports from above.
"""

from research_team.domain.events import (
    SESSION_EVENTS,
    AssistantMessageAdded,
    ConversationCompacted,
    FileDeleted,
    FileEdited,
    FileWritten,
    SessionForkedFrom,
    SessionStarted,
    ToolResultRecorded,
    TurnCompleted,
    TurnFailed,
    UserMessageSent,
)
from research_team.domain.session import CodingSession, SessionState

__all__ = [
    "SESSION_EVENTS",
    "AssistantMessageAdded",
    "CodingSession",
    "ConversationCompacted",
    "FileDeleted",
    "FileEdited",
    "FileWritten",
    "SessionForkedFrom",
    "SessionStarted",
    "SessionState",
    "ToolResultRecorded",
    "TurnCompleted",
    "TurnFailed",
    "UserMessageSent",
]
