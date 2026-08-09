from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage, ToolMessage, message_to_dict

from research_team.application.ports import ActivityDelta, ActivityMessage
from research_team.domain import FileEdited, FileWritten, SessionStarted, TurnCompleted
from research_team.interfaces.cli import repl
from research_team.interfaces.cli.formatters import (
    format_activity,
    format_diff,
    format_file_history,
    format_files,
    format_log,
)
from tests.conftest import start_session


@pytest.fixture
async def current(build_service, fake_model):
    """A REPL pointed at a fresh session -- the terminal owns the cursor."""
    return await repl.Repl.start(await build_service(model=fake_model))


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


async def test_quit_returns_none(current):
    assert await repl.handle_command(current, "/quit") is None


async def test_help_lists_commands(current):
    output = await repl.handle_command(current, "/help")
    for command in ("/log", "/files", "/cat", "/history", "/rewind", "/fork", "/state"):
        assert command in output


async def test_unknown_command_is_reported(current):
    output = await repl.handle_command(current, "/bogus")
    assert "unknown command" in output.lower()


async def test_cat_requires_argument(current):
    output = await repl.handle_command(current, "/cat")
    assert "usage" in output.lower()


async def test_cat_missing_file(current):
    output = await repl.handle_command(current, "/cat /nope.py")
    assert "not found" in output.lower()


async def test_rewind_requires_integer(current):
    output = await repl.handle_command(current, "/rewind abc")
    assert "usage" in output.lower()


async def test_rewind_out_of_range_is_reported(current):
    output = await repl.handle_command(current, "/rewind 99")
    assert "cannot" in output.lower() or "range" in output.lower()


async def test_state_reports_session_facts(current):
    output = await repl.handle_command(current, "/state")
    assert str(current.session_id) in output
    assert "events" in output.lower()


async def test_plain_input_runs_a_turn(current):
    output = await repl.handle_command(current, "hello there")
    assert output.startswith("done")


async def test_a_turn_reports_the_events_it_wrote(current):
    """So `/log` is navigable afterwards without counting backwards."""
    output = await repl.handle_command(current, "hello there")
    assert "[turn 1 · events #2-4]" in output


# ---- sessions, diff, and live activity ----


async def test_sessions_lists_and_marks_the_current_one(current):
    output = await repl.handle_command(current, "/sessions")
    assert str(current.session_id)[:8] in output
    assert output.lstrip().startswith("*") or "*" in output.splitlines()[0]


async def test_resume_by_list_position(current):
    original = current.session_id
    current.session_id = await start_session(current.service)
    assert current.session_id != original

    # Newest first, so the original is position 2.
    output = await repl.handle_command(current, "/resume 2")
    assert current.session_id == original
    assert "resumed" in output


async def test_resume_by_id_prefix(current):
    original = current.session_id
    current.session_id = await start_session(current.service)

    await repl.handle_command(current, f"/resume {str(original)[:8]}")
    assert current.session_id == original


async def test_resume_rejects_unknown_id(current):
    output = await repl.handle_command(current, "/resume zzzzzzzz")
    assert "no session matching" in output


async def test_resume_rejects_out_of_range_position(current):
    output = await repl.handle_command(current, "/resume 99")
    assert "no session 99" in output


async def test_resume_requires_argument(current):
    assert "usage" in (await repl.handle_command(current, "/resume")).lower()


async def test_new_starts_a_fresh_session(current):
    original = current.session_id
    output = await repl.handle_command(current, "/new")
    assert current.session_id != original
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


async def test_diff_requires_argument(current):
    assert "usage" in (await repl.handle_command(current, "/diff")).lower()


def test_format_log_includes_timestamps():
    events = [TurnCompleted(turn_index=1, aggregate_id=uuid4(), aggregate_version=1)]
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
    current = await repl.Repl.start(await build_service(model=fake_model))

    seen: list[str] = []

    def collect_formatted(note):
        formatted = repl.format_activity(note)
        if formatted is not None:
            seen.append(formatted)

    await repl.handle_command(current, "write a.py", on_activity=collect_formatted)

    assert any("write_file" in note for note in seen)
    assert any("/a.py" in note for note in seen)


async def test_no_activity_reported_for_a_plain_reply(build_service, fake_model):
    current = await repl.Repl.start(await build_service(model=fake_model))
    seen: list[str] = []

    def collect_formatted(note):
        formatted = repl.format_activity(note)
        if formatted is not None:
            seen.append(formatted)

    await repl.handle_command(current, "hello", on_activity=collect_formatted)
    assert seen == []


# ---- resolving a session by number or prefix ----


async def test_resume_by_a_prefix_that_is_all_digits(current, monkeypatch):
    """Regression: about one session id in forty starts with eight digits.

    Those were unresolvable by prefix, because a digit string was always read
    as a list position -- and a position that large is always out of range.
    """
    from research_team.application import session_service

    digity = UUID("12345678-0000-4000-8000-00000000abcd")
    monkeypatch.setattr(session_service, "uuid4", lambda: digity)
    await start_session(current.service)
    monkeypatch.undo()

    output = await repl.handle_command(current, "/resume 12345678")

    assert current.session_id == digity
    assert "resumed" in output


async def test_a_small_number_is_still_a_list_position(current):
    original = current.session_id
    current.session_id = await start_session(current.service)

    await repl.handle_command(current, "/resume 2")

    summaries = await current.service.list_sessions()
    assert current.session_id == summaries[1].session_id
    assert current.session_id == original


async def test_a_number_that_is_neither_reports_the_position_error(current):
    output = await repl.handle_command(current, "/resume 97")
    assert "no session 97" in output
    assert "stored" in output


async def test_a_short_number_is_never_read_as_an_id_prefix(current, monkeypatch):
    """Otherwise the command's behaviour depends on the random ids in the
    database: `/resume 97` would usually report a bad position, and about one
    run in a hundred would resume a session that happened to start with "97"."""
    from research_team.application import session_service

    monkeypatch.setattr(
        session_service, "uuid4", lambda: UUID("97000000-0000-4000-8000-00000000dddd")
    )
    await start_session(current.service)
    monkeypatch.undo()
    before = current.session_id

    output = await repl.handle_command(current, "/resume 97")

    assert "no session 97" in output
    assert current.session_id == before, "a position error must not switch sessions"


async def test_a_long_enough_prefix_is_still_a_prefix(current, monkeypatch):
    """The rule must not undo the fix it sits next to."""
    from research_team.application import session_service

    target = UUID("97001234-0000-4000-8000-00000000eeee")
    monkeypatch.setattr(session_service, "uuid4", lambda: target)
    await start_session(current.service)
    monkeypatch.undo()

    await repl.handle_command(current, "/resume 9700")

    assert current.session_id == target


async def test_health_command_reports_the_session_list_is_trustworthy(current):
    output = await repl.handle_command(current, "/health")
    assert "ok" in output.lower()


async def test_rebuild_command_rederives_the_session_list(current):
    """The operator's repair, reachable without a database client."""
    output = await repl.handle_command(current, "/rebuild")
    assert "rebuilt" in output.lower()
    # And the list still answers afterwards.
    assert await repl.handle_command(current, "/sessions")


# ---- activity formatting ----


def test_tool_calls_format_as_a_bullet_line():
    msg = AIMessage(
        content="",
        id="a1",
        tool_calls=[
            {
                "name": "read_file",
                "args": {"file_path": "a.py"},
                "id": "c1",
                "type": "tool_call",
            }
        ],
    )
    note = ActivityMessage(
        message_id="a1",
        kind="assistant",
        payload=message_to_dict(msg),
    )
    assert format_activity(note) == "· read_file(a.py)"


def test_tool_results_format_as_an_indented_first_line():
    msg = ToolMessage(content="found 3 matches\nline two", tool_call_id="c1", id="t1")
    note = ActivityMessage(
        message_id="t1",
        kind="tool",
        payload=message_to_dict(msg),
    )
    assert format_activity(note) == "  ↳ found 3 matches"


def test_plain_prose_prints_nothing():
    msg = AIMessage(content="hello", id="a1")
    note = ActivityMessage(message_id="a1", kind="assistant", payload=message_to_dict(msg))
    assert format_activity(note) is None


def test_deltas_print_nothing():
    """The terminal shows the reply when the turn completes, not token by token."""
    assert format_activity(ActivityDelta(message_id="a1", text="hel")) is None
