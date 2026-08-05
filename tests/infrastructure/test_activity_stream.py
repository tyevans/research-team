"""What the executor reports while a turn is in flight."""

from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage

from research_team.application.ports import ActivityDelta, ActivityMessage
from research_team.domain import StartSession
from research_team.infrastructure.agent.deep_agent import (
    DeepAgentTurnExecutor,
    to_activity_message,
)


class ToolAwareFakeChatModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any) -> "ToolAwareFakeChatModel":
        return self


def test_assistant_message_becomes_an_activity_message():
    note = to_activity_message(AIMessage(content="hello", id="a1"))
    assert isinstance(note, ActivityMessage)
    assert note.message_id == "a1"
    assert note.kind == "assistant"
    assert note.is_error is False


def test_tool_message_becomes_a_tool_activity_message():
    note = to_activity_message(
        ToolMessage(content="result text", tool_call_id="c1", id="t1")
    )
    assert isinstance(note, ActivityMessage)
    assert note.message_id == "t1"
    assert note.kind == "tool"


def test_a_message_without_an_id_is_not_reported():
    """Guessing an id would splice two messages together in the accumulator."""
    assert to_activity_message(AIMessage(content="hello", id=None)) is None


async def test_running_a_turn_reports_whole_messages(aggregates, session_id):
    session = aggregates.create_new(session_id)
    session.execute(StartSession(system_prompt="be brief", model_name="fake"))
    model = ToolAwareFakeChatModel(
        responses=[AIMessage(content="the reply", id="a1")]
    )
    executor = DeepAgentTurnExecutor(model)

    seen: list = []
    await executor.execute(
        session,
        messages=[executor.encode_user_message("hi")],
        system_prompt="be brief",
        on_activity=seen.append,
    )

    messages = [n for n in seen if isinstance(n, ActivityMessage)]
    assert any(n.kind == "assistant" for n in messages)
    assert all(isinstance(n, (ActivityMessage, ActivityDelta)) for n in seen)
    assert not any(isinstance(n, str) for n in seen)
