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
    """Fold stored payloads into the message list the agent consumes.

    The system prompt is deliberately NOT prepended. `create_deep_agent`
    takes `system_prompt` as its own parameter and owns it; putting a
    SystemMessage in this list as well would give the prompt two owners and
    show it to the model twice. It would also break turn accounting:
    LangGraph echoes back every message it is given, so an extra leading
    message shifts the "what did the agent add" suffix by one and the user's
    own message gets recorded a second time as an assistant message.
    """
    return messages_from_dict(state.messages)


def classify(message: BaseMessage) -> type[DomainEvent]:
    """Return the event class that records this message."""
    for message_type, event_class in _EVENT_FOR_MESSAGE:
        if isinstance(message, message_type):
            return event_class
    raise TypeError(f"cannot record message of type {type(message).__name__}")


def new_messages(sent_count: int, after: list[BaseMessage]) -> list[BaseMessage]:
    """The messages the agent appended beyond the `sent_count` we gave it.

    LangGraph echoes the input messages back verbatim and in order, then
    appends the new ones, so the suffix is exactly the new work. `sent_count`
    must be the length of the list actually handed to the agent -- not the
    stored message count -- or the accounting silently shifts.
    """
    return after[sent_count:]
