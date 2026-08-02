from uuid import uuid4

import pytest

from research_team import repl
from research_team import runtime as rt
from research_team.events import FileEdited, FileWritten, SessionStarted, TurnCompleted


@pytest.fixture
async def runtime(fake_model):
    return await rt.build_runtime(model=fake_model)


def test_format_log_numbers_events():
    events = [
        SessionStarted(
            aggregate_id=uuid4(), system_prompt="s", model_name="m", aggregate_version=1
        ),
        TurnCompleted(aggregate_id=uuid4(), turn_index=1, aggregate_version=2),
    ]
    output = repl.format_log(events, limit=10)
    assert "#1" in output and "SessionStarted" in output
    assert "#2" in output and "TurnCompleted" in output


def test_format_log_respects_limit():
    events = [
        TurnCompleted(aggregate_id=uuid4(), turn_index=i, aggregate_version=i)
        for i in range(1, 6)
    ]
    output = repl.format_log(events, limit=2)
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
    output = repl.format_files(events, {"/a.py": {"content": "y\n"}})
    assert "/a.py" in output
    assert "2" in output


def test_format_files_when_empty():
    assert "no files" in repl.format_files([], {}).lower()


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
    output = repl.format_file_history(events, "/a.py")
    assert "FileWritten" in output and "FileEdited" in output
    assert "/b.py" not in output


def test_format_file_history_unknown_path():
    assert "no history" in repl.format_file_history([], "/nope.py").lower()


async def test_quit_returns_none(runtime):
    assert await repl.handle_command(runtime, "/quit") is None


async def test_help_lists_commands(runtime):
    output = await repl.handle_command(runtime, "/help")
    for command in ("/log", "/files", "/cat", "/history", "/rewind", "/fork", "/state"):
        assert command in output


async def test_unknown_command_is_reported(runtime):
    output = await repl.handle_command(runtime, "/bogus")
    assert "unknown command" in output.lower()


async def test_cat_requires_argument(runtime):
    output = await repl.handle_command(runtime, "/cat")
    assert "usage" in output.lower()


async def test_cat_missing_file(runtime):
    output = await repl.handle_command(runtime, "/cat /nope.py")
    assert "not found" in output.lower()


async def test_rewind_requires_integer(runtime):
    output = await repl.handle_command(runtime, "/rewind abc")
    assert "usage" in output.lower()


async def test_rewind_out_of_range_is_reported(runtime):
    output = await repl.handle_command(runtime, "/rewind 99")
    assert "cannot" in output.lower() or "range" in output.lower()


async def test_state_reports_session_facts(runtime):
    output = await repl.handle_command(runtime, "/state")
    assert str(runtime.session_id) in output
    assert "events" in output.lower()


async def test_plain_input_runs_a_turn(runtime):
    output = await repl.handle_command(runtime, "hello there")
    assert output == "done"
