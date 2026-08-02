import pytest
from langchain_core.messages import AIMessage

from research_team import runtime as rt
from research_team.events import (
    AssistantMessageAdded,
    FileWritten,
    SessionStarted,
    TurnCompleted,
    UserMessageSent,
)


@pytest.fixture
async def runtime(fake_model):
    return await rt.build_runtime(model=fake_model)


async def test_build_runtime_starts_session(runtime):
    events = await rt.history(runtime)
    assert [type(e) for e in events] == [SessionStarted]


async def test_run_turn_records_user_and_assistant(runtime):
    reply = await rt.run_turn(runtime, "hello")
    assert reply == "done"

    types = [type(e) for e in await rt.history(runtime)]
    assert types[0] is SessionStarted
    assert UserMessageSent in types
    assert AssistantMessageAdded in types
    assert types[-1] is TurnCompleted


async def test_turn_index_increments(runtime):
    await rt.run_turn(runtime, "one")
    await rt.run_turn(runtime, "two")
    aggregate = await runtime.repo.load(runtime.session_id)
    assert aggregate.state.turn_index == 2


async def test_history_is_ordered_by_version(runtime):
    await rt.run_turn(runtime, "hello")
    events = await rt.history(runtime)
    versions = [e.aggregate_version for e in events]
    assert versions == sorted(versions)


async def test_tool_call_writes_file_and_records_events(fake_model):
    fake_model.responses = [
        AIMessage(
            content="",
            id="a1",
            tool_calls=[
                {
                    "name": "write_file",
                    "args": {"file_path": "/hello.py", "content": "print('hi')\n"},
                    "id": "t1",
                }
            ],
        ),
        AIMessage(content="wrote it", id="a2"),
    ]
    runtime = await rt.build_runtime(model=fake_model)
    reply = await rt.run_turn(runtime, "write hello.py")

    assert reply == "wrote it"
    aggregate = await runtime.repo.load(runtime.session_id)
    assert aggregate.state.files["/hello.py"]["content"] == "print('hi')\n"
    assert FileWritten in [type(e) for e in await rt.history(runtime)]


async def test_failed_turn_appends_nothing(runtime, monkeypatch):
    before = len(await rt.history(runtime))

    async def boom(*args, **kwargs):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(rt, "_invoke_agent", boom)
    with pytest.raises(RuntimeError):
        await rt.run_turn(runtime, "hello")

    assert len(await rt.history(runtime)) == before


async def test_fork_creates_independent_stream(runtime):
    await rt.run_turn(runtime, "hello")
    original_events = await rt.history(runtime)

    forked_id = await rt.fork(runtime, at=1)
    forked = await runtime.repo.load(forked_id)

    assert forked_id != runtime.session_id
    assert forked.version == 1
    assert forked.state.messages == []
    assert len(await rt.history(runtime)) == len(original_events)


async def test_rewind_repoints_session(runtime):
    await rt.run_turn(runtime, "hello")
    original_id = runtime.session_id

    await rt.rewind(runtime, at=1)

    assert runtime.session_id != original_id
    assert len(await rt.history(runtime)) == 1
    original = await runtime.repo.load(original_id)
    assert original.version > 1, "rewind must not destroy the original stream"


async def test_snapshot_threshold_is_configured(runtime):
    assert runtime.repo.snapshot_threshold == 50
    assert runtime.repo.has_snapshot_support
