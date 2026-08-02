"""Domain events for a coding session.

One stream carries both the conversation and the virtual filesystem, so
ordering between "the model said X" and "file Y changed" is total.
"""

from typing import Any

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
    UserMessageSent,
    AssistantMessageAdded,
    ToolResultRecorded,
    TurnCompleted,
    FileWritten,
    FileEdited,
    FileDeleted,
)
