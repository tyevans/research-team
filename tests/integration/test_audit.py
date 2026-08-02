"""The log must record what actually happened -- including failures and lineage."""

import pytest
from langchain_core.messages import AIMessage

from research_team.domain import SessionForkedFrom, ToolResultRecorded, TurnFailed
from research_team.infrastructure.agent.deep_agent import DeepAgentTurnExecutor
from research_team.interfaces.cli import repl
from research_team.interfaces.cli.formatters import format_log


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


async def test_failed_tool_call_is_flagged(build_service, failing_edit_model):
    service = await build_service(model=failing_edit_model)
    await service.run_turn("edit a file that does not exist")

    results = [
        e for e in await service.history() if isinstance(e, ToolResultRecorded)
    ]
    assert results, "no tool result recorded"
    assert results[-1].is_error is True
    assert "not found" in results[-1].message["data"]["content"]


async def test_successful_tool_call_is_not_flagged(build_service, fake_model):
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
    service = await build_service(model=fake_model)
    await service.run_turn("write it")

    results = [
        e for e in await service.history() if isinstance(e, ToolResultRecorded)
    ]
    assert results and all(r.is_error is False for r in results)


async def test_errored_tool_result_is_marked_in_the_log(
    build_service, failing_edit_model
):
    service = await build_service(model=failing_edit_model)
    await service.run_turn("edit a file that does not exist")
    assert "!" in format_log(await service.history(), limit=50)


async def test_fork_records_its_source(build_service, repository, db_path, fake_model):
    service = await build_service(model=fake_model, db_path=db_path)
    await service.run_turn("hello")
    source = service.session_id

    forked_id = await service.fork(at=2)
    forked = await repository.load(forked_id)

    assert forked.state.forked_from == source
    assert forked.state.forked_at == 2


async def test_fork_lineage_is_an_event_on_the_stream(build_service, fake_model):
    service = await build_service(model=fake_model)
    await service.run_turn("hello")
    await service.switch_to_fork(at=2)

    events = await service.history()
    assert isinstance(events[-1], SessionForkedFrom)
    assert events[-1].at_event == 2


async def test_lineage_survives_a_cold_refold(build_service, fake_model, db_path):
    service = await build_service(model=fake_model, db_path=db_path)
    await service.run_turn("hello")
    source = service.session_id
    forked_id = await service.fork(at=2)
    await service.close()

    reopened = await build_service(
        model=fake_model, db_path=db_path, session_id=forked_id
    )
    assert (await reopened.load()).state.forked_from == source


async def test_unforked_session_has_no_lineage(build_service, fake_model):
    service = await build_service(model=fake_model)
    aggregate = await service.load()
    assert aggregate.state.forked_from is None


async def test_sessions_view_shows_lineage_and_failures(
    build_service, fake_model, monkeypatch
):
    service = await build_service(model=fake_model)
    await service.run_turn("hello")
    source = service.session_id
    await service.switch_to_fork(at=2)

    async def boom(*args, **kwargs):
        raise RuntimeError("nope")

    monkeypatch.setattr(DeepAgentTurnExecutor, "_invoke", boom)
    with pytest.raises(RuntimeError):
        await service.run_turn("will fail")
    monkeypatch.undo()

    output = await repl.handle_command(service, "/sessions")
    assert str(source)[:8] in output
    assert "failed" in output


async def test_state_reports_lineage(build_service, fake_model):
    service = await build_service(model=fake_model)
    await service.run_turn("hello")
    await service.switch_to_fork(at=2)

    output = await repl.handle_command(service, "/state")
    assert "forked" in output


async def test_turn_failed_appears_in_the_log(service_with_failure):
    events = await service_with_failure.history()
    assert isinstance(events[-1], TurnFailed)
    assert "RuntimeError" in format_log(events, limit=10)


@pytest.fixture
async def service_with_failure(build_service, fake_model, monkeypatch):
    service = await build_service(model=fake_model)

    async def boom(*args, **kwargs):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(DeepAgentTurnExecutor, "_invoke", boom)
    with pytest.raises(RuntimeError):
        await service.run_turn("hello")
    monkeypatch.undo()
    return service
