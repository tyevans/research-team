"""Conversion between stored message payloads and langchain messages.

Storage format is whatever `langchain_core.messages.message_to_dict`
produces, so we never define or maintain a message schema of our own.
"""

from typing import TYPE_CHECKING

from eventsource import DomainEvent
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    messages_from_dict,
)

from research_team.events import (
    AssistantMessageAdded,
    ToolResultRecorded,
    UserMessageSent,
)

if TYPE_CHECKING:
    from research_team.session import SessionState

_EVENT_FOR_MESSAGE: tuple[tuple[type[BaseMessage], type[DomainEvent]], ...] = (
    (HumanMessage, UserMessageSent),
    (AIMessage, AssistantMessageAdded),
    (ToolMessage, ToolResultRecorded),
)


def to_langchain(state: "SessionState") -> list[BaseMessage]:
    """Fold stored payloads into the message list the agent consumes."""
    history = messages_from_dict(state.messages)
    if not state.system_prompt:
        return history
    return [SystemMessage(state.system_prompt), *history]


def classify(message: BaseMessage) -> type[DomainEvent]:
    """Return the event class that records this message."""
    for message_type, event_class in _EVENT_FOR_MESSAGE:
        if isinstance(message, message_type):
            return event_class
    raise TypeError(f"cannot record message of type {type(message).__name__}")


def new_messages(sent_count: int, after: list[BaseMessage]) -> list[BaseMessage]:
    """The messages the agent appended beyond the `sent_count` we gave it.

    LangGraph returns the input messages verbatim and in order, then the new
    ones, and the SystemMessage is not among them (deepagents passes the
    system prompt separately). So the suffix is exactly the new work.
    """
    return after[sent_count:]
