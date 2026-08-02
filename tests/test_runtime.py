import pytest
from langchain_core.messages import AIMessage

from research_team import runtime as rt
from research_team.events import (
    AssistantMessageAdded,
    TurnFailed,
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


async def test_failed_turn_appends_only_a_marker(runtime, monkeypatch):
    """The turn stays all-or-nothing; only a TurnFailed marker is recorded."""
    before = [type(e) for e in await rt.history(runtime)]

    async def boom(*args, **kwargs):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(rt, "_invoke_agent", boom)
    with pytest.raises(RuntimeError, match="model exploded"):
        await rt.run_turn(runtime, "hello")

    after = [type(e) for e in await rt.history(runtime)]
    assert after == [*before, TurnFailed]


async def test_failed_turn_records_the_cause(runtime, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(rt, "_invoke_agent", boom)
    with pytest.raises(RuntimeError):
        await rt.run_turn(runtime, "hello")

    failure = [e for e in await rt.history(runtime) if isinstance(e, TurnFailed)][-1]
    assert failure.error_type == "RuntimeError"
    assert "model exploded" in failure.error_message


async def test_failed_turn_does_not_advance_turn_index(runtime, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("nope")

    monkeypatch.setattr(rt, "_invoke_agent", boom)
    with pytest.raises(RuntimeError):
        await rt.run_turn(runtime, "hello")

    aggregate = await runtime.repo.load(runtime.session_id)
    assert aggregate.state.turn_index == 0
    assert aggregate.state.failed_turns == 1


async def test_user_message_from_a_failed_turn_is_not_kept(runtime, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("nope")

    monkeypatch.setattr(rt, "_invoke_agent", boom)
    with pytest.raises(RuntimeError):
        await rt.run_turn(runtime, "this should not persist")

    aggregate = await runtime.repo.load(runtime.session_id)
    assert aggregate.state.messages == []


async def test_fork_creates_independent_stream(runtime):
    await rt.run_turn(runtime, "hello")
    original_events = await rt.history(runtime)

    forked_id = await rt.fork(runtime, at=1)
    forked = await runtime.repo.load(forked_id)

    assert forked_id != runtime.session_id
    # The copied prefix, plus the SessionForkedFrom marker recording lineage.
    assert forked.version == 2
    assert forked.state.messages == []
    assert forked.state.forked_from == runtime.session_id
    assert forked.state.forked_at == 1
    assert len(await rt.history(runtime)) == len(original_events)


async def test_rewind_repoints_session(runtime):
    await rt.run_turn(runtime, "hello")
    original_id = runtime.session_id

    await rt.rewind(runtime, at=1)

    assert runtime.session_id != original_id
    assert len(await rt.history(runtime)) == 2  # prefix + lineage marker
    original = await runtime.repo.load(original_id)
    assert original.version > 1, "rewind must not destroy the original stream"


async def test_snapshot_threshold_is_configured(runtime):
    assert runtime.repo.snapshot_threshold == 50
    assert runtime.repo.has_snapshot_support


async def test_turn_records_each_message_exactly_once(runtime):
    """Regression: a SystemMessage in the sent list shifted turn accounting,
    causing the user's own message to be re-recorded as an assistant message."""
    await rt.run_turn(runtime, "hello")

    types = [type(e) for e in await rt.history(runtime)]
    assert types == [
        SessionStarted,
        UserMessageSent,
        AssistantMessageAdded,
        TurnCompleted,
    ]


async def test_user_text_is_never_recorded_as_assistant(runtime):
    await rt.run_turn(runtime, "a very distinctive user utterance")

    assistant_texts = [
        e.message.get("data", {}).get("content")
        for e in await rt.history(runtime)
        if isinstance(e, AssistantMessageAdded)
    ]
    assert "a very distinctive user utterance" not in assistant_texts


async def test_second_turn_does_not_replay_earlier_messages(fake_model):
    # Distinct ids per turn: LangGraph's message reducer dedupes by id, so a
    # fake that replays one id would silently append nothing on turn two.
    fake_model.responses = [
        AIMessage(content="first reply", id="a1"),
        AIMessage(content="second reply", id="a2"),
    ]
    runtime = await rt.build_runtime(model=fake_model)

    await rt.run_turn(runtime, "first")
    after_first = len(await rt.history(runtime))
    await rt.run_turn(runtime, "second")

    # Exactly UserMessageSent + AssistantMessageAdded + TurnCompleted again.
    assert len(await rt.history(runtime)) == after_first + 3
