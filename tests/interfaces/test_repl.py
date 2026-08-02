from uuid import uuid4

import pytest

from langchain_core.messages import AIMessage

from research_team.domain import FileEdited, FileWritten, SessionStarted, TurnCompleted
from research_team.interfaces.cli import repl
from research_team.interfaces.cli.formatters import (
    format_diff,
    format_file_history,
    format_files,
    format_log,
)


@pytest.fixture
async def service(build_service, fake_model):
    return await build_service(model=fake_model)


def test_format_log_numbers_events():
    events = [
        SessionStarted(
            aggregate_id=uuid4(), system_prompt="s", model_name="m", aggregate_version=1
        ),
        TurnCompleted(aggregate_id=uuid4(), turn_index=1, aggregate_version=2),
    ]
    output = format_log(events, limit=10)
    assert "#1" in output and "SessionStarted" in output
    assert "#2" in output and "TurnCompleted" in output


def test_format_log_respects_limit():
    events = [
        TurnCompleted(aggregate_id=uuid4(), turn_index=i, aggregate_version=i)
        for i in range(1, 6)
    ]
    output = format_log(events, limit=2)
    assert output.count("\n") == 1
    assert "#5" in output and "#1" not in output


def test_format_files_reports_revision_count():
    events = [
        FileWritten(
            aggregate_id=uuid4(),
            path="/a.py",
            file_data={"content": "x\n"},
            aggregate_version=1,
        ),
        FileEdited(
            aggregate_id=uuid4(),
            path="/a.py",
            file_data={"content": "y\n"},
            old_string="x",
            new_string="y",
            replace_all=False,
            aggregate_version=2,
        ),
    ]
    output = format_files(events, {"/a.py": {"content": "y\n"}})
    assert "/a.py" in output
    assert "2" in output


def test_format_files_when_empty():
    assert "no files" in format_files([], {}).lower()


def test_format_file_history_lists_touching_events():
    events = [
        FileWritten(
            aggregate_id=uuid4(),
            path="/a.py",
            file_data={"content": "x\n"},
            aggregate_version=1,
        ),
        FileWritten(
            aggregate_id=uuid4(),
            path="/b.py",
            file_data={"content": "z\n"},
            aggregate_version=2,
        ),
        FileEdited(
            aggregate_id=uuid4(),
            path="/a.py",
            file_data={"content": "y\n"},
            old_string="x",
            new_string="y",
            replace_all=False,
            aggregate_version=3,
        ),
    ]
    output = format_file_history(events, "/a.py")
    assert "FileWritten" in output and "FileEdited" in output
    assert "/b.py" not in output


def test_format_file_history_unknown_path():
    assert "no history" in format_file_history([], "/nope.py").lower()


async def test_quit_returns_none(service):
    assert await repl.handle_command(service, "/quit") is None


async def test_help_lists_commands(service):
    output = await repl.handle_command(service, "/help")
    for command in ("/log", "/files", "/cat", "/history", "/rewind", "/fork", "/state"):
        assert command in output


async def test_unknown_command_is_reported(service):
    output = await repl.handle_command(service, "/bogus")
    assert "unknown command" in output.lower()


async def test_cat_requires_argument(service):
    output = await repl.handle_command(service, "/cat")
    assert "usage" in output.lower()


async def test_cat_missing_file(service):
    output = await repl.handle_command(service, "/cat /nope.py")
    assert "not found" in output.lower()


async def test_rewind_requires_integer(service):
    output = await repl.handle_command(service, "/rewind abc")
    assert "usage" in output.lower()


async def test_rewind_out_of_range_is_reported(service):
    output = await repl.handle_command(service, "/rewind 99")
    assert "cannot" in output.lower() or "range" in output.lower()


async def test_state_reports_session_facts(service):
    output = await repl.handle_command(service, "/state")
    assert str(service.session_id) in output
    assert "events" in output.lower()


async def test_plain_input_runs_a_turn(service):
    output = await repl.handle_command(service, "hello there")
    assert output == "done"


# ---- sessions, diff, and live activity ----


async def test_sessions_lists_and_marks_the_current_one(service):
    output = await repl.handle_command(service, "/sessions")
    assert str(service.session_id)[:8] in output
    assert output.lstrip().startswith("*") or "*" in output.splitlines()[0]


async def test_resume_by_list_position(service):
    original = service.session_id
    await service.start_session()
    assert service.session_id != original

    # Newest first, so the original is position 2.
    output = await repl.handle_command(service, "/resume 2")
    assert service.session_id == original
    assert "resumed" in output


async def test_resume_by_id_prefix(service):
    original = service.session_id
    await service.start_session()

    await repl.handle_command(service, f"/resume {str(original)[:8]}")
    assert service.session_id == original


async def test_resume_rejects_unknown_id(service):
    output = await repl.handle_command(service, "/resume zzzzzzzz")
    assert "no session matching" in output


async def test_resume_rejects_out_of_range_position(service):
    output = await repl.handle_command(service, "/resume 99")
    assert "no session 99" in output


async def test_resume_requires_argument(service):
    assert "usage" in (await repl.handle_command(service, "/resume")).lower()


async def test_new_starts_a_fresh_session(service):
    original = service.session_id
    output = await repl.handle_command(service, "/new")
    assert service.session_id != original
    assert "started" in output


def test_format_diff_shows_old_and_new():
    events = [
        FileEdited(
            path="/a.py",
            file_data={"content": "y\n"},
            old_string="x",
            new_string="y",
            replace_all=False,
            aggregate_id=uuid4(),
            aggregate_version=1,
        )
    ]
    output = format_diff(events, "/a.py")
    assert "- x" in output
    assert "+ y" in output


def test_format_diff_marks_replace_all():
    events = [
        FileEdited(
            path="/a.py",
            file_data={"content": "y\n"},
            old_string="x",
            new_string="y",
            replace_all=True,
            aggregate_id=uuid4(),
            aggregate_version=1,
        )
    ]
    assert "all occurrences" in format_diff(events, "/a.py")


def test_format_diff_when_never_edited():
    assert "no recorded edits" in format_diff([], "/a.py")


async def test_diff_requires_argument(service):
    assert "usage" in (await repl.handle_command(service, "/diff")).lower()


def test_format_log_includes_timestamps():
    events = [
        TurnCompleted(turn_index=1, aggregate_id=uuid4(), aggregate_version=1)
    ]
    output = format_log(events, limit=10)
    assert f"{events[0].occurred_at:%H:%M:%S}" in output


async def test_turn_reports_tool_activity(build_service, fake_model):
    fake_model.responses = [
        AIMessage(
            content="",
            id="a1",
            tool_calls=[
                {
                    "name": "write_file",
                    "args": {"file_path": "/a.py", "content": "x\n"},
                    "id": "t1",
                }
            ],
        ),
        AIMessage(content="wrote it", id="a2"),
    ]
    service = await build_service(model=fake_model)

    seen: list[str] = []
    await repl.handle_command(service, "write a.py", on_activity=seen.append)

    assert any("write_file" in note for note in seen)
    assert any("/a.py" in note for note in seen)


async def test_no_activity_reported_for_a_plain_reply(build_service, fake_model):
    service = await build_service(model=fake_model)
    seen: list[str] = []
    await repl.handle_command(service, "hello", on_activity=seen.append)
    assert seen == []
