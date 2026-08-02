# tests/test_messages.py
import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    message_to_dict,
)

from research_team.application import TurnAccountingError
from research_team.infrastructure.agent.messages import (
    new_messages,
    to_langchain,
    to_recorded,
)
from research_team.domain import SessionState

from uuid import uuid4


def make_state(**kwargs) -> SessionState:
    return SessionState(session_id=uuid4(), system_prompt="SYS", **kwargs)


def test_system_prompt_is_not_prepended():
    """create_deep_agent owns the system prompt; two owners breaks turn accounting."""
    state = make_state(messages=[message_to_dict(HumanMessage("hello", id="h1"))])
    messages = to_langchain(state)
    assert not any(isinstance(m, SystemMessage) for m in messages)
    assert len(messages) == len(state.messages)


def test_empty_history_folds_to_empty_list():
    assert to_langchain(make_state()) == []


def test_round_trip_preserves_human_message():
    state = make_state(messages=[message_to_dict(HumanMessage("hello", id="h1"))])
    restored = to_langchain(state)[0]
    assert isinstance(restored, HumanMessage)
    assert restored.content == "hello"


def test_round_trip_preserves_tool_calls():
    original = AIMessage(
        content="",
        id="a1",
        tool_calls=[{"name": "write_file", "args": {"path": "/a.py"}, "id": "t1"}],
    )
    state = make_state(messages=[message_to_dict(original)])
    restored = to_langchain(state)[0]
    assert isinstance(restored, AIMessage)
    assert restored.tool_calls[0]["id"] == "t1"
    assert restored.tool_calls[0]["args"] == {"path": "/a.py"}


def test_round_trip_preserves_tool_message():
    state = make_state(
        messages=[message_to_dict(ToolMessage(content="done", tool_call_id="t1", id="m1"))]
    )
    restored = to_langchain(state)[0]
    assert isinstance(restored, ToolMessage)
    assert restored.tool_call_id == "t1"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (AIMessage("x"), "assistant"),
        (ToolMessage(content="x", tool_call_id="t1"), "tool"),
    ],
)
def test_to_recorded_kind(message, expected):
    assert to_recorded(message).kind == expected


def test_to_recorded_tool_success_is_not_an_error():
    recorded = to_recorded(ToolMessage(content="ok", tool_call_id="t1"))
    assert recorded.kind == "tool"
    assert recorded.is_error is False


def test_to_recorded_marks_failed_tool_results():
    recorded = to_recorded(
        ToolMessage(content="boom", tool_call_id="t1", status="error")
    )
    assert recorded.kind == "tool"
    assert recorded.is_error is True


def test_to_recorded_rejects_human_message():
    with pytest.raises(TurnAccountingError, match="cannot record"):
        to_recorded(HumanMessage("x"))


def test_to_recorded_rejects_unknown_type():
    with pytest.raises(TurnAccountingError, match="cannot record"):
        to_recorded(SystemMessage("x"))


def test_new_messages_returns_suffix():
    after = [HumanMessage("a", id="1"), AIMessage("b", id="2")]
    assert [m.id for m in new_messages(1, after)] == ["2"]


def test_new_messages_empty_when_nothing_appended():
    after = [HumanMessage("a", id="1")]
    assert new_messages(1, after) == []


def test_new_messages_returns_all_when_count_zero():
    after = [HumanMessage("a", id="1"), AIMessage("b", id="2")]
    assert len(new_messages(0, after)) == 2
