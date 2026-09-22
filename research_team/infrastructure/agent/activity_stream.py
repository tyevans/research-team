"""Activity stream extraction and reporting for turns in flight."""

import logging
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from research_team.infrastructure.agent.messages import to_recorded
from research_team.platform.shared.ports import (
    ActivityDelta,
    ActivityMessage,
    ActivityReporter,
)

logger = logging.getLogger(__name__)

MAIN_AGENT_NODE = "model"
"""The graph node the top-level agent's model call runs under.

Subagents stream on the same channel. Without this discriminator a subagent's
internal reasoning would render as the main agent's answer to the user.
"""

__all__ = [
    "MAIN_AGENT_NODE",
    "_first_arg",
    "_report",
    "describe_activity",
    "to_activity_delta",
    "to_activity_message",
]


def describe_activity(message: BaseMessage) -> str | None:
    """A one-line progress note for a message, or None if it is not worth showing."""
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        return "· " + ", ".join(
            f"{call['name']}({_first_arg(call.get('args', {}))})" for call in tool_calls
        )
    if isinstance(message, ToolMessage):
        first_line = str(message.content).strip().splitlines()
        return f"  ↳ {first_line[0][:70]}" if first_line else None
    return None


def to_activity_message(message: BaseMessage) -> ActivityMessage | None:
    """A whole message as a provisional note, or None if it cannot be keyed.

    Built from `to_recorded` rather than from a second reading of the message,
    so what streams and what is eventually recorded cannot disagree about kind
    or payload -- that divergence is the failure mode this channel most needs
    to avoid.

    A message with no id is dropped rather than given a synthetic one: the id
    is what the browser accumulates deltas against, and a guessed one would
    splice two messages into one bubble.
    """
    message_id = getattr(message, "id", None)
    if not message_id:
        return None
    recorded = to_recorded(message)
    return ActivityMessage(
        message_id=str(message_id),
        kind=recorded.kind,
        payload=recorded.payload,
        is_error=recorded.is_error,
    )


def to_activity_delta(chunk: Any) -> ActivityDelta | None:
    """A prose delta from a `messages`-mode chunk, or None if it is not one.

    Returns None for tool calls, for subagent chunks, and for anything without
    text -- this channel carries only what a person is waiting to read.

    The type test is `AIMessage`, which covers `AIMessageChunk` because it
    subclasses it. Testing for the chunk type alone would report nothing at
    all from a non-streaming model, which delivers one whole message here.
    """
    try:
        message, metadata = chunk
    except (TypeError, ValueError):
        return None
    if metadata.get("langgraph_node") != MAIN_AGENT_NODE:
        return None
    if not isinstance(message, AIMessage):
        return None
    if getattr(message, "tool_calls", None):
        return None
    message_id = getattr(message, "id", None)
    if not message_id:
        return None
    text = message.text if isinstance(getattr(message, "text", None), str) else message.content
    if not isinstance(text, str) or not text:
        return None
    return ActivityDelta(message_id=str(message_id), text=text)


def _report(
    on_activity: ActivityReporter | None, note: ActivityMessage | ActivityDelta
) -> None:
    """Deliver one note to the reporter, never letting it fail the turn.

    A minute of model work is not worth discarding because a browser feed
    raised -- this is a side channel to a human watching, not a dependency
    the turn's outcome should ever hinge on.
    """
    if on_activity is None:
        return
    try:
        on_activity(note)
    except Exception:
        logger.exception("activity reporter raised; continuing the turn")


def _first_arg(args: dict[str, object]) -> str:
    for key in ("file_path", "path", "pattern", "command"):
        if key in args:
            return str(args[key])
    return ""
