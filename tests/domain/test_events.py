from uuid import uuid4

import pytest
from pydantic import ValidationError

from research_team.domain.events import (
    SESSION_EVENTS,
    AssistantMessageAdded,
    SessionForkedFrom,
    TurnFailed,
    FileDeleted,
    FileEdited,
    FileWritten,
    SessionStarted,
    ToolResultRecorded,
    TurnCompleted,
    UserMessageSent,
)
from eventsource.domain.event_registry import get_event_class


def test_all_events_exported():
    assert set(SESSION_EVENTS) == {
        SessionStarted, UserMessageSent, AssistantMessageAdded,
        ToolResultRecorded, TurnCompleted, TurnFailed, SessionForkedFrom,
        FileWritten, FileEdited, FileDeleted,
    }


@pytest.mark.parametrize("event_class", list(SESSION_EVENTS))
def test_event_is_registered_under_its_name(event_class):
    assert get_event_class(event_class.__name__) is event_class


@pytest.mark.parametrize("event_class", list(SESSION_EVENTS))
def test_aggregate_type_is_coding_session(event_class):
    assert event_class.model_fields["aggregate_type"].default == "CodingSession"


def test_events_are_frozen():
    event = TurnCompleted(aggregate_id=uuid4(), turn_index=1)
    with pytest.raises(ValidationError):
        event.turn_index = 2


def test_events_forbid_extra_fields():
    with pytest.raises(ValidationError):
        TurnCompleted(aggregate_id=uuid4(), turn_index=1, bogus="nope")


def test_file_written_round_trips():
    file_data = {"content": "print(1)\n", "encoding": "utf-8"}
    event = FileWritten(aggregate_id=uuid4(), path="/a.py", file_data=file_data)
    restored = FileWritten.model_validate_json(event.model_dump_json())
    assert restored.path == "/a.py"
    assert restored.file_data == file_data


def test_file_edited_carries_intent_and_result():
    event = FileEdited(
        aggregate_id=uuid4(),
        path="/a.py",
        file_data={"content": "print(2)\n"},
        old_string="1",
        new_string="2",
        replace_all=False,
    )
    assert (event.old_string, event.new_string, event.replace_all) == ("1", "2", False)
    assert event.file_data["content"] == "print(2)\n"


def test_tool_result_defaults_to_success():
    assert ToolResultRecorded(aggregate_id=uuid4(), message={"type": "tool"}).is_error is False
