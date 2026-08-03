"""Domain events for a coding session.

One stream carries both the conversation and the virtual filesystem, so
ordering between "the model said X" and "file Y changed" is total.
"""

from typing import Any
from uuid import UUID

from eventsource import DomainEvent, register_event


@register_event
class SessionStarted(DomainEvent):
    """Creation event. Must be the first event on the stream."""

    aggregate_type: str = "CodingSession"
    system_prompt: str
    model_name: str


@register_event
class UserMessageSent(DomainEvent):
    aggregate_type: str = "CodingSession"
    message: dict[str, Any]


@register_event
class AssistantMessageAdded(DomainEvent):
    aggregate_type: str = "CodingSession"
    message: dict[str, Any]


@register_event
class ToolResultRecorded(DomainEvent):
    aggregate_type: str = "CodingSession"
    message: dict[str, Any]
    is_error: bool = False


@register_event
class TurnCompleted(DomainEvent):
    aggregate_type: str = "CodingSession"
    turn_index: int


@register_event
class TurnFailed(DomainEvent):
    """A turn was attempted and did not complete.

    Appended on its own, after the failed turn's events have been discarded --
    so the log gains the attempt without gaining a half-applied turn. The
    turn_index is the one that was being attempted, and is not advanced.

    `cancelled` separates "someone stopped this" from "this broke". Both leave
    the same hole in the log, but they are different facts about what happened,
    and an audit trail that cannot tell them apart is a worse audit trail.
    Defaults to False, so events written before the distinction existed read
    as ordinary failures -- which is what they were.
    """

    aggregate_type: str = "CodingSession"
    turn_index: int
    error_type: str
    error_message: str
    cancelled: bool = False


@register_event
class ConversationCompacted(DomainEvent):
    """Older messages were replaced, for the model's benefit, by a summary.

    The messages themselves are not removed -- nothing is ever removed. This
    records a decision about what the *model* is shown from here on, so the
    fold can apply it while the log still holds every original message. Replay
    stays exact, and folding to a point before this event shows the
    conversation as it was.

    `through_index` is the 1-based index, within the session's message list, of
    the last message the summary stands in for.
    """

    aggregate_type: str = "CodingSession"
    summary: str
    through_index: int
    strategy: str
    """Which strategy produced this, so a log reader knows what made the call."""


@register_event
class SessionForkedFrom(DomainEvent):
    """Records that this stream was branched off another one.

    Emitted after the copied prefix rather than before it: `SessionStarted` is
    the creation event and must come first, and its reducer replaces state
    wholesale, so lineage recorded ahead of it would be overwritten.
    """

    aggregate_type: str = "CodingSession"
    source_session_id: UUID
    at_event: int


@register_event
class FileWritten(DomainEvent):
    aggregate_type: str = "CodingSession"
    path: str
    file_data: dict[str, Any]


@register_event
class FileEdited(DomainEvent):
    """Carries both the resulting file_data and the edit intent.

    file_data keeps the fold O(1); old_string/new_string keep the audit
    trail meaningful.
    """

    aggregate_type: str = "CodingSession"
    path: str
    file_data: dict[str, Any]
    old_string: str
    new_string: str
    replace_all: bool = False


@register_event
class FileDeleted(DomainEvent):
    aggregate_type: str = "CodingSession"
    path: str


SESSION_EVENTS: tuple[type[DomainEvent], ...] = (
    SessionStarted,
    ConversationCompacted,
    UserMessageSent,
    AssistantMessageAdded,
    ToolResultRecorded,
    TurnCompleted,
    TurnFailed,
    SessionForkedFrom,
    FileWritten,
    FileEdited,
    FileDeleted,
)
