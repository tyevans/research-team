"""Translation between stored message payloads and langchain messages.

Storage format is whatever `langchain_core.messages.message_to_dict`
produces, so we never define or maintain a message schema of our own. That
choice is exactly why this module is infrastructure: the payloads in the log
have langchain's shape, and this is the only place that knows it.
"""

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
    message_to_dict,
    messages_from_dict,
)

from research_team.application import RecordedMessage, TurnAccountingError


def to_payload_messages(payloads: list[dict]) -> list[BaseMessage]:
    """Turn stored payloads into the message list the agent consumes.

    Takes the payloads rather than the session, because which of them to send
    is decided a layer up -- a context strategy may have shortened or replaced
    some of them before they get here.

    The system prompt is deliberately NOT prepended. `create_deep_agent` takes
    `system_prompt` as its own parameter and owns it; putting a SystemMessage
    in this list as well would give the prompt two owners and show it to the
    model twice. It would also break turn accounting: LangGraph echoes back
    every message it is given, so an extra leading message shifts the "what did
    the agent add" suffix by one and the user's own message gets recorded a
    second time as an assistant message.
    """
    return messages_from_dict(payloads)


def encode_user_message(text: str) -> dict:
    """The stored payload for a user's turn."""
    return message_to_dict(HumanMessage(text))


def to_recorded(message: BaseMessage) -> RecordedMessage:
    """Convert an agent-produced message into something the log can hold."""
    if isinstance(message, ToolMessage):
        return RecordedMessage(
            kind="tool",
            payload=message_to_dict(message),
            # deepagents marks failed tool calls itself; trust its signal
            # rather than sniffing the message text for "Error:".
            is_error=getattr(message, "status", None) == "error",
        )
    if isinstance(message, AIMessage):
        return RecordedMessage(kind="assistant", payload=message_to_dict(message))
    # A HumanMessage here means turn accounting has drifted: the user's message
    # would be recorded twice. Fail loudly rather than quietly writing a corrupt
    # event to an append-only log -- `TurnAccountingError` is the signal that
    # this turn must leave no trace at all, not even a failure marker.
    raise TurnAccountingError(
        f"cannot record message of type {type(message).__name__} in agent output "
        "suffix; turn accounting is wrong"
    )


def new_messages(sent_count: int, after: list[BaseMessage]) -> list[BaseMessage]:
    """The messages the agent appended beyond the `sent_count` we gave it.

    LangGraph echoes the input messages back verbatim and in order, then
    appends the new ones, so the suffix is exactly the new work. `sent_count`
    must be the length of the list actually handed to the agent -- not the
    stored message count -- or the accounting silently shifts.
    """
    return after[sent_count:]


def last_text(messages: list[BaseMessage]) -> str:
    """The agent's final prose reply, if it made one."""
    for message in reversed(messages):
        if (
            isinstance(message, AIMessage)
            and isinstance(message.content, str)
            and message.content
        ):
            return message.content
    return ""
