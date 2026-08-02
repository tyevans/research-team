"""The log must record what actually happened -- including failures and lineage."""

import pytest
from langchain_core.messages import AIMessage

from research_team import repl
from research_team import runtime as rt
from research_team.events import SessionForkedFrom, ToolResultRecorded, TurnFailed


@pytest.fixture
def failing_edit_model(fake_model):
    fake_model.responses = [
        AIMessage(
            content="",
            id="a1",
            tool_calls=[
                {
                    "name": "edit_file",
                    "args": {
                        "file_path": "/missing.py",
                        "old_string": "a",
                        "new_string": "b",
                    },
                    "id": "t1",
                }
            ],
        ),
        AIMessage(content="that failed", id="a2"),
    ]
    return fake_model


async def test_failed_tool_call_is_flagged(failing_edit_model):
    runtime = await rt.build_runtime(model=failing_edit_model)
    await rt.run_turn(runtime, "edit a file that does not exist")

    results = [e for e in await rt.history(runtime) if isinstance(e, ToolResultRecorded)]
    assert results, "no tool result recorded"
    assert results[-1].is_error is True
    assert "not found" in results[-1].message["data"]["content"]


async def test_successful_tool_call_is_not_flagged(fake_model):
    fake_model.responses = [
        AIMessage(
            content="",
            id="a1",
            tool_calls=[
                {
                    "name": "write_file",
                    "args": {"file_path": "/ok.py", "content": "x\n"},
                    "id": "t1",
                }
            ],
        ),
        AIMessage(content="wrote", id="a2"),
    ]
    runtime = await rt.build_runtime(model=fake_model)
    await rt.run_turn(runtime, "write it")

    results = [e for e in await rt.history(runtime) if isinstance(e, ToolResultRecorded)]
    assert results and all(r.is_error is False for r in results)


async def test_errored_tool_result_is_marked_in_the_log(failing_edit_model):
    runtime = await rt.build_runtime(model=failing_edit_model)
    await rt.run_turn(runtime, "edit a file that does not exist")
    assert "!" in repl.format_log(await rt.history(runtime), limit=50)


async def test_fork_records_its_source(fake_model):
    runtime = await rt.build_runtime(model=fake_model)
    await rt.run_turn(runtime, "hello")
    source = runtime.session_id

    forked_id = await rt.fork(runtime, at=2)
    forked = await runtime.repo.load(forked_id)

    assert forked.state.forked_from == source
    assert forked.state.forked_at == 2


async def test_fork_lineage_is_an_event_on_the_stream(fake_model):
    runtime = await rt.build_runtime(model=fake_model)
    await rt.run_turn(runtime, "hello")
    forked_id = await rt.fork(runtime, at=2)

    runtime.session_id = forked_id
    events = await rt.history(runtime)
    assert isinstance(events[-1], SessionForkedFrom)
    assert events[-1].at_event == 2


async def test_lineage_survives_a_cold_refold(fake_model, db_path):
    runtime = await rt.build_runtime(model=fake_model, db_path=db_path)
    await rt.run_turn(runtime, "hello")
    source = runtime.session_id
    forked_id = await rt.fork(runtime, at=2)
    await runtime.close()

    reopened = await rt.build_runtime(
        model=fake_model, db_path=db_path, session_id=forked_id
    )
    assert (await reopened.repo.load(forked_id)).state.forked_from == source


async def test_unforked_session_has_no_lineage(fake_model):
    runtime = await rt.build_runtime(model=fake_model)
    aggregate = await runtime.repo.load(runtime.session_id)
    assert aggregate.state.forked_from is None


async def test_sessions_view_shows_lineage_and_failures(fake_model, monkeypatch):
    runtime = await rt.build_runtime(model=fake_model)
    await rt.run_turn(runtime, "hello")
    source = runtime.session_id
    forked_id = await rt.fork(runtime, at=2)
    runtime.session_id = forked_id

    async def boom(*args, **kwargs):
        raise RuntimeError("nope")

    monkeypatch.setattr(rt, "_invoke_agent", boom)
    with pytest.raises(RuntimeError):
        await rt.run_turn(runtime, "will fail")
    monkeypatch.undo()

    output = await repl.handle_command(runtime, "/sessions")
    assert str(source)[:8] in output
    assert "failed" in output


async def test_state_reports_lineage(fake_model):
    runtime = await rt.build_runtime(model=fake_model)
    await rt.run_turn(runtime, "hello")
    forked_id = await rt.fork(runtime, at=2)
    runtime.session_id = forked_id

    output = await repl.handle_command(runtime, "/state")
    assert "forked" in output


async def test_turn_failed_appears_in_the_log(runtime_with_failure):
    events = await rt.history(runtime_with_failure)
    assert isinstance(events[-1], TurnFailed)
    assert "RuntimeError" in repl.format_log(events, limit=10)


@pytest.fixture
async def runtime_with_failure(fake_model, monkeypatch):
    runtime = await rt.build_runtime(model=fake_model)

    async def boom(*args, **kwargs):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(rt, "_invoke_agent", boom)
    with pytest.raises(RuntimeError):
        await rt.run_turn(runtime, "hello")
    monkeypatch.undo()
    return runtime
