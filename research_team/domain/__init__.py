"""The domain layer: commands, events, and the decider that relates them.

Depends on nothing but the event-sourcing primitives and pydantic. No
langchain, no deepagents, no SQLite, no environment. Everything above may
import from here; nothing here imports from above.
"""

from research_team.domain.commands import (
    ChangeAutonomy,
    CompactConversation,
    CompleteTurn,
    DeleteFile,
    EditFile,
    FailTurn,
    RecordAssistantMessage,
    RecordForkSource,
    RecordToolDecision,
    RecordToolResult,
    SendUserMessage,
    SessionCommand,
    StartSession,
    WriteFile,
)
from research_team.domain.events import (
    SESSION_EVENTS,
    AssistantMessageAdded,
    AutonomyChanged,
    ConversationCompacted,
    FileDeleted,
    FileEdited,
    FileWritten,
    SessionForkedFrom,
    SessionStarted,
    ToolCallDecided,
    ToolResultRecorded,
    TurnCompleted,
    TurnFailed,
    UserMessageSent,
)
from research_team.domain.session import (
    CodingSession,
    SessionState,
    decide,
    evolve,
    initial_state,
)

__all__ = [
    "SESSION_EVENTS",
    "AssistantMessageAdded",
    "AutonomyChanged",
    "ChangeAutonomy",
    "CodingSession",
    "CompactConversation",
    "CompleteTurn",
    "ConversationCompacted",
    "DeleteFile",
    "EditFile",
    "FailTurn",
    "FileDeleted",
    "FileEdited",
    "FileWritten",
    "RecordAssistantMessage",
    "RecordForkSource",
    "RecordToolDecision",
    "RecordToolResult",
    "SendUserMessage",
    "SessionCommand",
    "SessionForkedFrom",
    "SessionStarted",
    "SessionState",
    "StartSession",
    "ToolCallDecided",
    "ToolResultRecorded",
    "TurnCompleted",
    "TurnFailed",
    "UserMessageSent",
    "WriteFile",
    "decide",
    "evolve",
    "initial_state",
]
