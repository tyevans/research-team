"""What can be asked of a session.

Commands are values, not method calls: `decide` matches on the pair
*(command, state)*, so a request has to be something you can hold, pass to a
pure function, and assert about without an aggregate in scope.

They are never stored. A command that `decide` refuses leaves no trace -- the
log records what happened, and a rejected request did not happen. That is the
difference between these and the events in `events.py`, which are frozen facts
about the past and are written down forever.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

MAX_ERROR_MESSAGE = 500
"""How much of a failure's message the log keeps. Enough to recognise it."""


class Command(BaseModel):
    """Base for every session command: frozen, and closed to stray fields.

    Frozen because a command is a request someone made, and rewriting it after
    the fact would make `decide`'s inputs untrustworthy in exactly the way the
    event log refuses to be.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class StartSession(Command):
    system_prompt: str
    model_name: str


class SendUserMessage(Command):
    message: dict[str, Any]


class RecordAssistantMessage(Command):
    message: dict[str, Any]


class RecordToolResult(Command):
    message: dict[str, Any]
    is_error: bool = False


class CompleteTurn(Command):
    pass


class FailTurn(Command):
    """A turn was attempted and did not complete.

    Carries plain values rather than the exception itself, so `decide` stays a
    function over data. `from_error` is where an exception becomes those
    values -- the truncation and the cancelled/failed distinction live there,
    at the edge, rather than inside the rule.
    """

    error_type: str
    error_message: str
    cancelled: bool = False

    @classmethod
    def from_error(cls, error: BaseException, *, cancelled: bool = False) -> "FailTurn":
        """Describe an exception as a command.

        Whether an attempt counts as cancelled is the caller's judgement --
        what counts depends on how the turn was being run, which is not
        something the session knows.
        """
        return cls(
            error_type="Cancelled" if cancelled else type(error).__name__,
            error_message=str(error)[:MAX_ERROR_MESSAGE] or "cancelled",
            cancelled=cancelled,
        )


class CompactConversation(Command):
    """Replace older messages, for the model's benefit, with a summary."""

    summary: str
    through_index: int
    strategy: str
    tokens_before: int = 0
    tokens_after: int = 0


class RecordForkSource(Command):
    source_session_id: UUID
    at_event: int


class WriteFile(Command):
    path: str
    file_data: dict[str, Any]


class EditFile(Command):
    path: str
    file_data: dict[str, Any]
    old_string: str
    new_string: str
    replace_all: bool = False


class DeleteFile(Command):
    path: str


class RecordToolDecision(Command):
    """A tool call was allowed, refused, or amended, and by whom."""

    tool_name: str
    args: dict[str, Any]
    decision: str
    decided_by: str
    edited_args: dict[str, Any] | None = None


class ChangeAutonomy(Command):
    """A tool's autonomy level changed mid-session."""

    tool_name: str
    level: str


SessionCommand = (
    StartSession
    | SendUserMessage
    | RecordAssistantMessage
    | RecordToolResult
    | CompleteTurn
    | FailTurn
    | CompactConversation
    | RecordForkSource
    | WriteFile
    | EditFile
    | DeleteFile
    | RecordToolDecision
    | ChangeAutonomy
)
"""Every request a session accepts.

The union is the written-down surface: one place that says what a session can
be asked, which `decide` is expected to answer for in full. Nothing checks
that statically today -- this project runs ruff, not a type checker -- so the
guarantee at runtime is `decide`'s closing `raise`, which turns a command
nobody handled into a rejection rather than a silent no-op. Adding a type
checker later would move that from runtime to build time without changing
anything here.
"""
