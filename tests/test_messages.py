# tests/test_messages.py
import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    message_to_dict,
)

from research_team.events import (
    AssistantMessageAdded,
    ToolResultRecorded,
    UserMessageSent,
)
from research_team.messages import classify, new_messages, to_langchain
from research_team.session import SessionState

from uuid import uuid4


def make_state(**kwargs) -> SessionState:
    return SessionState(session_id=uuid4(), system_prompt="SYS", **kwargs)


def test_system_prompt_is_prepended():
    messages = to_langchain(make_state())
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == "SYS"


def test_round_trip_preserves_human_message():
    state = make_state(messages=[message_to_dict(HumanMessage("hello", id="h1"))])
    restored = to_langchain(state)[1]
    assert isinstance(restored, HumanMessage)
    assert restored.content == "hello"


def test_round_trip_preserves_tool_calls():
    original = AIMessage(
        content="",
        id="a1",
        tool_calls=[{"name": "write_file", "args": {"path": "/a.py"}, "id": "t1"}],
    )
    state = make_state(messages=[message_to_dict(original)])
    restored = to_langchain(state)[1]
    assert isinstance(restored, AIMessage)
    assert restored.tool_calls[0]["id"] == "t1"
    assert restored.tool_calls[0]["args"] == {"path": "/a.py"}


def test_round_trip_preserves_tool_message():
    state = make_state(
        messages=[message_to_dict(ToolMessage(content="done", tool_call_id="t1", id="m1"))]
    )
    restored = to_langchain(state)[1]
    assert isinstance(restored, ToolMessage)
    assert restored.tool_call_id == "t1"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (HumanMessage("x"), UserMessageSent),
        (AIMessage("x"), AssistantMessageAdded),
        (ToolMessage(content="x", tool_call_id="t1"), ToolResultRecorded),
    ],
)
def test_classify(message, expected):
    assert classify(message) is expected


def test_classify_rejects_unknown_type():
    with pytest.raises(TypeError, match="cannot record"):
        classify(SystemMessage("x"))


def test_new_messages_returns_suffix():
    after = [HumanMessage("a", id="1"), AIMessage("b", id="2")]
    assert [m.id for m in new_messages(1, after)] == ["2"]


def test_new_messages_empty_when_nothing_appended():
    after = [HumanMessage("a", id="1")]
    assert new_messages(1, after) == []


def test_new_messages_returns_all_when_count_zero():
    after = [HumanMessage("a", id="1"), AIMessage("b", id="2")]
    assert len(new_messages(0, after)) == 2
