"""The web view models, as pure functions over domain objects."""

from datetime import UTC, datetime
from uuid import uuid4

from research_team.domain import (
    AssistantMessageAdded,
    FileDeleted,
    FileEdited,
    FileWritten,
    SessionForkedFrom,
    SessionStarted,
    ToolResultRecorded,
    TurnCompleted,
    TurnFailed,
    UserMessageSent,
)
from research_team.interfaces.web.presenters import (
    event_row,
    event_rows,
    event_summary,
    file_history,
    message_view,
)

AGGREGATE = uuid4()


def make(event_class, **fields):
    return event_class(
        aggregate_id=AGGREGATE,
        aggregate_version=1,
        occurred_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
        **fields,
    )


def text_message(kind: str, content: str) -> dict:
    return {"type": kind, "data": {"content": content}}


# ---------------- summaries ----------------


def test_a_started_session_is_summarised_by_its_model():
    event = make(SessionStarted, system_prompt="p", model_name="qwen3.6-27b")
    assert event_summary(event) == "qwen3.6-27b"


def test_a_written_file_is_summarised_by_its_path():
    event = make(FileWritten, path="/a.py", file_data={"content": "x"})
    assert event_summary(event) == "/a.py"


def test_an_edited_file_summary_carries_the_intent_not_just_the_path():
    """The log records why the file changed; a timeline row should show it."""
    event = make(
        FileEdited,
        path="/a.py",
        file_data={"content": "new"},
        old_string="print(i)",
        new_string="print(i * 2)",
        replace_all=False,
    )
    summary = event_summary(event)
    assert summary.startswith("/a.py")
    assert "print(i)" in summary
    assert "print(i * 2)" in summary


def test_an_edit_summary_stays_short_enough_for_one_row():
    event = make(
        FileEdited,
        path="/a.py",
        file_data={"content": "x"},
        old_string="a" * 200,
        new_string="b" * 200,
        replace_all=False,
    )
    assert len(event_summary(event)) < 100


def test_a_deleted_file_is_summarised_by_its_path():
    assert event_summary(make(FileDeleted, path="/gone.py")) == "/gone.py"


def test_a_failed_turn_reports_the_error():
    event = make(
        TurnFailed,
        turn_index=2,
        error_type="RuntimeError",
        error_message="model exploded",
    )
    summary = event_summary(event)
    assert "RuntimeError" in summary
    assert "model exploded" in summary


def test_a_completed_turn_reports_its_number():
    assert event_summary(make(TurnCompleted, turn_index=3)) == "turn 3"


def test_a_fork_reports_where_it_came_from():
    source = uuid4()
    event = make(SessionForkedFrom, source_session_id=source, at_event=7)
    summary = event_summary(event)
    assert str(source)[:8] in summary
    assert "7" in summary


def test_a_message_is_summarised_by_its_text():
    event = make(UserMessageSent, message=text_message("human", "hello   there\n"))
    assert event_summary(event) == "hello there"


def test_a_tool_calling_message_is_summarised_by_the_calls():
    event = make(
        AssistantMessageAdded,
        message={
            "type": "ai",
            "data": {
                "content": "",
                "tool_calls": [{"name": "write_file"}, {"name": "edit_file"}],
            },
        },
    )
    assert event_summary(event) == "→ write_file, edit_file"


# ---------------- rows ----------------


def test_rows_are_numbered_from_one():
    events = [
        make(SessionStarted, system_prompt="p", model_name="m"),
        make(UserMessageSent, message=text_message("human", "hi")),
    ]
    assert [row["index"] for row in event_rows(events)] == [1, 2]


def test_a_row_exposes_the_path_for_file_events():
    row = event_row(4, make(FileWritten, path="/a.py", file_data={"content": "x"}))
    assert row["path"] == "/a.py"
    assert row["type"] == "FileWritten"
    assert row["occurred_at"].startswith("2026-08-02T12:00")


def test_a_row_flags_an_errored_tool_result():
    event = make(
        ToolResultRecorded,
        message={"type": "tool", "data": {"content": "boom"}},
        is_error=True,
    )
    assert event_row(1, event)["is_error"] is True


# ---------------- messages ----------------


def test_message_roles_are_translated_for_the_browser():
    assert message_view(text_message("human", "x"))["role"] == "user"
    assert message_view(text_message("ai", "x"))["role"] == "assistant"
    assert message_view(text_message("tool", "x"))["role"] == "tool"


def test_a_message_view_carries_its_tool_calls():
    view = message_view(
        {
            "type": "ai",
            "data": {
                "content": "",
                "tool_calls": [{"name": "write_file", "args": {"file_path": "/a.py"}}],
            },
        }
    )
    assert view["tool_calls"] == [
        {"name": "write_file", "args": {"file_path": "/a.py"}}
    ]


def test_an_errored_tool_message_is_marked():
    view = message_view({"type": "tool", "data": {"content": "boom", "status": "error"}})
    assert view["is_error"] is True


# ---------------- file history ----------------


def test_file_history_only_covers_the_asked_for_path():
    events = [
        make(FileWritten, path="/a.py", file_data={"content": "a"}),
        make(FileWritten, path="/b.py", file_data={"content": "b"}),
    ]
    rows = file_history(events, "/a.py")
    assert [row["index"] for row in rows] == [1]
    assert rows[0]["content"] == "a"


def test_file_history_exposes_the_edit_strings_for_diffing():
    events = [
        make(FileWritten, path="/a.py", file_data={"content": "old"}),
        make(
            FileEdited,
            path="/a.py",
            file_data={"content": "new"},
            old_string="old",
            new_string="new",
            replace_all=True,
        ),
    ]
    rows = file_history(events, "/a.py")
    assert rows[0]["old_string"] is None
    assert rows[1]["old_string"] == "old"
    assert rows[1]["new_string"] == "new"
    assert rows[1]["replace_all"] is True


def test_file_history_of_an_untouched_path_is_empty():
    assert file_history([], "/nothing.py") == []
