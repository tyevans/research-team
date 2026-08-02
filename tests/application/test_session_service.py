import pytest
from langchain_core.messages import AIMessage, HumanMessage

from research_team.application import TurnAccountingError
from research_team.domain import (
    AssistantMessageAdded,
    FileWritten,
    SessionStarted,
    TurnCompleted,
    TurnFailed,
    UserMessageSent,
)
from research_team.infrastructure.agent.deep_agent import DeepAgentTurnExecutor


@pytest.fixture
async def service(build_service, fake_model):
    return await build_service(model=fake_model)


@pytest.fixture
def explode(monkeypatch):
    """Force the turn executor's single seam to fail mid-turn."""

    def _explode(message: str) -> None:
        async def boom(*args, **kwargs):
            raise RuntimeError(message)

        monkeypatch.setattr(DeepAgentTurnExecutor, "_invoke", boom)

    return _explode


async def test_build_service_starts_session(service):
    events = await service.history()
    assert [type(e) for e in events] == [SessionStarted]


async def test_run_turn_records_user_and_assistant(service):
    reply = await service.run_turn("hello")
    assert reply == "done"

    types = [type(e) for e in await service.history()]
    assert types[0] is SessionStarted
    assert UserMessageSent in types
    assert AssistantMessageAdded in types
    assert types[-1] is TurnCompleted


async def test_turn_index_increments(service):
    await service.run_turn("one")
    await service.run_turn("two")
    aggregate = await service.load()
    assert aggregate.state.turn_index == 2


async def test_history_is_ordered_by_version(service):
    await service.run_turn("hello")
    events = await service.history()
    versions = [e.aggregate_version for e in events]
    assert versions == sorted(versions)


async def test_tool_call_writes_file_and_records_events(build_service, fake_model):
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
    service = await build_service(model=fake_model)
    reply = await service.run_turn("write hello.py")

    assert reply == "wrote it"
    aggregate = await service.load()
    assert aggregate.state.files["/hello.py"]["content"] == "print('hi')\n"
    assert FileWritten in [type(e) for e in await service.history()]


async def test_failed_turn_appends_only_a_marker(service, explode):
    """The turn stays all-or-nothing; only a TurnFailed marker is recorded."""
    before = [type(e) for e in await service.history()]

    explode("model exploded")
    with pytest.raises(RuntimeError, match="model exploded"):
        await service.run_turn("hello")

    after = [type(e) for e in await service.history()]
    assert after == [*before, TurnFailed]


async def test_failed_turn_records_the_cause(service, explode):
    explode("model exploded")
    with pytest.raises(RuntimeError):
        await service.run_turn("hello")

    failure = [e for e in await service.history() if isinstance(e, TurnFailed)][-1]
    assert failure.error_type == "RuntimeError"
    assert "model exploded" in failure.error_message


async def test_failed_turn_does_not_advance_turn_index(service, explode):
    explode("nope")
    with pytest.raises(RuntimeError):
        await service.run_turn("hello")

    aggregate = await service.load()
    assert aggregate.state.turn_index == 0
    assert aggregate.state.failed_turns == 1


async def test_user_message_from_a_failed_turn_is_not_kept(service, explode):
    explode("nope")
    with pytest.raises(RuntimeError):
        await service.run_turn("this should not persist")

    aggregate = await service.load()
    assert aggregate.state.messages == []


async def test_fork_creates_independent_stream(service):
    await service.run_turn("hello")
    original_id = service.session_id
    original_events = await service.history()

    forked_id = await service.fork(at=1)
    assert forked_id != original_id
    assert len(await service.history()) == len(original_events)

    forked = await service.resume(forked_id)
    # The copied prefix, plus the SessionForkedFrom marker recording lineage.
    assert forked.version == 2
    assert forked.state.messages == []
    assert forked.state.forked_from == original_id
    assert forked.state.forked_at == 1


async def test_switch_to_fork_repoints_session(service):
    await service.run_turn("hello")
    original_id = service.session_id

    await service.switch_to_fork(at=1)

    assert service.session_id != original_id
    assert len(await service.history()) == 2  # prefix + lineage marker
    original = await service.resume(original_id)
    assert original.version > 1, "switching to a fork must not destroy the original"


async def test_turn_records_each_message_exactly_once(service):
    """Regression: a SystemMessage in the sent list shifted turn accounting,
    causing the user's own message to be re-recorded as an assistant message."""
    await service.run_turn("hello")

    types = [type(e) for e in await service.history()]
    assert types == [
        SessionStarted,
        UserMessageSent,
        AssistantMessageAdded,
        TurnCompleted,
    ]


async def test_user_text_is_never_recorded_as_assistant(service):
    await service.run_turn("a very distinctive user utterance")

    assistant_texts = [
        e.message.get("data", {}).get("content")
        for e in await service.history()
        if isinstance(e, AssistantMessageAdded)
    ]
    assert "a very distinctive user utterance" not in assistant_texts


async def test_second_turn_does_not_replay_earlier_messages(build_service, fake_model):
    # Distinct ids per turn: LangGraph's message reducer dedupes by id, so a
    # fake that replays one id would silently append nothing on turn two.
    fake_model.responses = [
        AIMessage(content="first reply", id="a1"),
        AIMessage(content="second reply", id="a2"),
    ]
    service = await build_service(model=fake_model)

    await service.run_turn("first")
    after_first = len(await service.history())
    await service.run_turn("second")

    # Exactly UserMessageSent + AssistantMessageAdded + TurnCompleted again.
    assert len(await service.history()) == after_first + 3


async def test_accounting_drift_leaves_the_log_completely_untouched(
    service, monkeypatch
):
    """A TurnAccountingError must not even record a TurnFailed marker.

    An ordinary failure is a fact about the world and earns a marker. Drift in
    our own accounting of what the agent added means we cannot describe the
    turn truthfully at all, so the append-only log gains nothing.
    """
    before = [type(e) for e in await service.history()]

    async def returns_a_human_message(self, session, messages, system_prompt, on_activity):
        return [*messages, HumanMessage("the agent should never emit this", id="x1")]

    monkeypatch.setattr(DeepAgentTurnExecutor, "_invoke", returns_a_human_message)

    with pytest.raises(TurnAccountingError, match="turn accounting is wrong"):
        await service.run_turn("hello")

    assert [type(e) for e in await service.history()] == before
    assert TurnFailed not in [type(e) for e in await service.history()]
