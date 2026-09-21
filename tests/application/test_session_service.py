from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from research_team.infrastructure.agent.deep_agent import DeepAgentTurnExecutor
from research_team.platform.shared.ports import TurnAccountingError
from research_team.session.domain import (
    AssistantMessageAdded,
    FileWritten,
    SessionPurpose,
    SessionStarted,
    StartSession,
    TurnCompleted,
    TurnFailed,
    UserMessageSent,
)
from tests.conftest import start_session


@pytest.fixture
async def service(build_service, fake_model):
    return await build_service(model=fake_model)


@pytest.fixture
async def session_id(service):
    """The session under test. The caller owns the cursor now, so tests do too."""
    return await start_session(service)


@pytest.fixture
def explode(monkeypatch):
    """Force the turn executor's single seam to fail mid-turn."""

    def _explode(message: str) -> None:
        async def boom(*args, **kwargs):
            raise RuntimeError(message)

        monkeypatch.setattr(DeepAgentTurnExecutor, "_invoke", boom)

    return _explode


async def test_create_session_starts_a_stream(service, session_id):
    events = await service.history(session_id)
    assert [type(e) for e in events] == [SessionStarted]


async def test_run_turn_records_user_and_assistant(service, session_id):
    outcome = await service.run_turn(session_id, "hello")
    assert outcome.reply == "done"

    types = [type(e) for e in await service.history(session_id)]
    assert types[0] is SessionStarted
    assert UserMessageSent in types
    assert AssistantMessageAdded in types
    assert types[-1] is TurnCompleted


async def test_turn_index_increments(service, session_id):
    await service.run_turn(session_id, "one")
    await service.run_turn(session_id, "two")
    aggregate = await service.load(session_id)
    assert aggregate.state.turn_index == 2


async def test_history_is_ordered_by_version(service, session_id):
    await service.run_turn(session_id, "hello")
    events = await service.history(session_id)
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
    session_id = await start_session(service)
    outcome = await service.run_turn(session_id, "write hello.py")

    assert outcome.reply == "wrote it"
    aggregate = await service.load(session_id)
    assert aggregate.state.files["/hello.py"]["content"] == "print('hi')\n"
    assert FileWritten in [type(e) for e in await service.history(session_id)]


async def test_failed_turn_appends_only_a_marker(service, session_id, explode):
    """The turn stays all-or-nothing; only a TurnFailed marker is recorded."""
    before = [type(e) for e in await service.history(session_id)]

    explode("model exploded")
    with pytest.raises(RuntimeError, match="model exploded"):
        await service.run_turn(session_id, "hello")

    after = [type(e) for e in await service.history(session_id)]
    assert after == [*before, TurnFailed]


async def test_failed_turn_records_the_cause(service, session_id, explode):
    explode("model exploded")
    with pytest.raises(RuntimeError):
        await service.run_turn(session_id, "hello")

    failure = [e for e in await service.history(session_id) if isinstance(e, TurnFailed)][-1]
    assert failure.error_type == "RuntimeError"
    assert "model exploded" in failure.error_message


async def test_failed_turn_does_not_advance_turn_index(service, session_id, explode):
    explode("nope")
    with pytest.raises(RuntimeError):
        await service.run_turn(session_id, "hello")

    aggregate = await service.load(session_id)
    assert aggregate.state.turn_index == 0
    assert aggregate.state.failed_turns == 1


async def test_user_message_from_a_failed_turn_is_not_kept(service, session_id, explode):
    explode("nope")
    with pytest.raises(RuntimeError):
        await service.run_turn(session_id, "this should not persist")

    aggregate = await service.load(session_id)
    assert aggregate.state.messages == []


async def test_fork_creates_independent_stream(service, session_id):
    await service.run_turn(session_id, "hello")
    original_events = await service.history(session_id)

    forked_id = await service.fork(session_id, at=1)
    assert forked_id != session_id
    assert len(await service.history(session_id)) == len(original_events)

    forked = await service.load(forked_id)
    # The copied prefix, plus the SessionForkedFrom marker recording lineage.
    assert forked.version == 2
    assert forked.state.messages == []
    assert forked.state.forked_from == session_id
    assert forked.state.forked_at == 1


async def test_forking_leaves_the_original_intact(service, session_id):
    await service.run_turn(session_id, "hello")

    forked_id = await service.fork(session_id, at=1)

    assert forked_id != session_id
    assert len(await service.history(forked_id)) == 2  # prefix + lineage marker
    original = await service.load(session_id)
    assert original.version > 1, "forking must not destroy the original"


async def test_fork_with_retargeted_purpose_closes_b101(service):
    """B101: Forking a research round or workflow session can retarget purpose to CHAT."""
    # Create a session with RESEARCH_ROUND purpose
    source_id = uuid4()
    session = service._repository.create(source_id)
    session.execute(
        StartSession(
            session_id=source_id,
            system_prompt="workflow prompt",
            model_name="fake",
            project_id=uuid4(),
            purpose=SessionPurpose.RESEARCH_ROUND,
        )
    )
    await service._repository.save(session)
    await service.run_turn(source_id, "round task")

    # Fork with purpose retargeted to CHAT
    forked_id = await service.fork(source_id, at=1, purpose=SessionPurpose.CHAT)
    forked = await service.load(forked_id)

    assert forked.state.purpose is SessionPurpose.CHAT
    original = await service.load(source_id)
    assert original.state.purpose is SessionPurpose.RESEARCH_ROUND

    forked_events = await service.history(forked_id)
    fork_marker = forked_events[-1]
    assert fork_marker.purpose is SessionPurpose.CHAT


async def test_session_stats_queries(service, session_id):
    stats = await service.session_stats(session_id)
    assert stats.session_id == session_id
    assert stats.turn_index == 0
    assert stats.total_messages == 0
    assert stats.file_count == 0

    await service.write_file(session_id, "/hello.txt", "content")
    await service.run_turn(session_id, "say hello")

    stats_after = await service.session_stats(session_id)
    assert stats_after.turn_index == 1
    assert stats_after.total_messages > 0
    assert stats_after.file_count == 1
    assert "/hello.txt" in stats_after.file_paths


async def test_find_messages_filtering(service, session_id):
    await service.run_turn(session_id, "find me special keyword")

    # Filter by role
    human_msgs = await service.find_messages(session_id, role="human")
    assert len(human_msgs) == 1
    assert "special keyword" in str(human_msgs[0]["data"]["content"])

    # Filter by query
    found = await service.find_messages(session_id, query="keyword")
    assert len(found) == 1

    not_found = await service.find_messages(session_id, query="nonexistent_xyz")
    assert len(not_found) == 0

    # Limit
    all_msgs = await service.find_messages(session_id, limit=1)
    assert len(all_msgs) == 1


async def test_diff_session_files(service, session_id):
    other_id = await start_session(service)
    await service.write_file(session_id, "/common.txt", "line1\nline2\n")
    await service.write_file(session_id, "/only_s1.txt", "s1 only")

    await service.write_file(other_id, "/common.txt", "line1\nline2 modified\nline3\n")
    await service.write_file(other_id, "/only_s2.txt", "s2 only")

    diff = await service.diff_session_files(session_id, other_id)
    assert diff["added"] == ["/only_s2.txt"]
    assert diff["removed"] == ["/only_s1.txt"]
    assert "/common.txt" in diff["modified"]
    assert diff["modified"]["/common.txt"]["added_lines"] >= 1


async def test_turn_records_each_message_exactly_once(service, session_id):
    """Regression: a SystemMessage in the sent list shifted turn accounting,
    causing the user's own message to be re-recorded as an assistant message."""
    await service.run_turn(session_id, "hello")

    types = [type(e) for e in await service.history(session_id)]
    assert types == [
        SessionStarted,
        UserMessageSent,
        AssistantMessageAdded,
        TurnCompleted,
    ]


async def test_user_text_is_never_recorded_as_assistant(service, session_id):
    await service.run_turn(session_id, "a very distinctive user utterance")

    assistant_texts = [
        e.message.get("data", {}).get("content")
        for e in await service.history(session_id)
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
    session_id = await start_session(service)

    await service.run_turn(session_id, "first")
    after_first = len(await service.history(session_id))
    await service.run_turn(session_id, "second")

    # Exactly UserMessageSent + AssistantMessageAdded + TurnCompleted again.
    assert len(await service.history(session_id)) == after_first + 3


async def test_accounting_drift_leaves_the_log_completely_untouched(
    service, session_id, monkeypatch
):
    """A TurnAccountingError must not even record a TurnFailed marker.

    An ordinary failure is a fact about the world and earns a marker. Drift in
    our own accounting of what the agent added means we cannot describe the
    turn truthfully at all, so the append-only log gains nothing.
    """
    before = [type(e) for e in await service.history(session_id)]

    async def returns_a_human_message(self, session, messages, system_prompt, on_activity):
        return [*messages, HumanMessage("the agent should never emit this", id="x1")]

    monkeypatch.setattr(DeepAgentTurnExecutor, "_invoke", returns_a_human_message)

    with pytest.raises(TurnAccountingError, match="turn accounting is wrong"):
        await service.run_turn(session_id, "hello")

    assert [type(e) for e in await service.history(session_id)] == before
    assert TurnFailed not in [type(e) for e in await service.history(session_id)]


# ---- folding a prefix ----


@pytest.fixture
def editing_model(fake_model):
    """Writes /a.py, then edits it -- two distinct states to travel between."""
    fake_model.responses = [
        AIMessage(
            content="",
            id="a1",
            tool_calls=[
                {
                    "name": "write_file",
                    "args": {"file_path": "/a.py", "content": "original\n"},
                    "id": "t1",
                }
            ],
        ),
        AIMessage(content="wrote it", id="a2"),
        AIMessage(
            content="",
            id="a3",
            tool_calls=[
                {
                    "name": "edit_file",
                    "args": {
                        "file_path": "/a.py",
                        "old_string": "original",
                        "new_string": "revised",
                    },
                    "id": "t2",
                }
            ],
        ),
        AIMessage(content="edited it", id="a4"),
    ]
    return fake_model


async def test_state_at_reproduces_the_earlier_workspace(build_service, editing_model):
    service = await build_service(model=editing_model)
    session_id = await start_session(service)
    await service.run_turn(session_id, "write a.py")
    await service.run_turn(session_id, "revise it")

    events = await service.history(session_id)
    after_write = next(i for i, e in enumerate(events, start=1) if isinstance(e, FileWritten))

    earlier = await service.state_at(session_id, after_write)
    assert earlier.state.files["/a.py"]["content"] == "original\n"
    assert (await service.load(session_id)).state.files["/a.py"]["content"] == "revised\n"


async def test_state_at_writes_nothing_to_the_log(build_service, editing_model):
    service = await build_service(model=editing_model)
    session_id = await start_session(service)
    await service.run_turn(session_id, "write a.py")
    before = await service.history(session_id)

    await service.state_at(session_id, 1)

    assert len(await service.history(session_id)) == len(before)


async def test_state_at_creates_no_session(build_service, editing_model):
    service = await build_service(model=editing_model)
    session_id = await start_session(service)
    await service.run_turn(session_id, "write a.py")
    before = len(await service.list_sessions())

    await service.state_at(session_id, 1)

    assert len(await service.list_sessions()) == before


@pytest.mark.parametrize("at", [0, 99])
async def test_state_at_rejects_an_out_of_range_point(service, session_id, at):
    with pytest.raises(ValueError, match="cannot fold at"):
        await service.state_at(session_id, at)


# ---- whose prompt runs the turn ----


async def test_turn_runs_under_the_sessions_own_prompt(build_service, fake_model, monkeypatch):
    """A session keeps the prompt it was started with, whatever the service default."""
    seen: list[str] = []

    async def capture(self, session, messages, system_prompt, on_activity):
        seen.append(system_prompt)
        return [*messages, AIMessage("ok", id="z1")]

    monkeypatch.setattr(DeepAgentTurnExecutor, "_invoke", capture)

    service = await build_service(model=fake_model, system_prompt="the service default")

    # Started through the repository rather than through the service, because
    # no service method takes a prompt any more: `start_in_project` composes
    # the default with the knowledge prompt, so a session made that way would
    # carry a prompt derived from the default and there would be nothing to
    # tell "the session's own" apart from "the service's". The claim under
    # test is about what `run_turn` reads, and `StartSession` is where a
    # session's prompt is set either way.
    session_id = uuid4()
    session = service._repository.create(session_id)
    session.execute(
        StartSession(
            session_id=session_id,
            system_prompt="a distinctive prompt",
            model_name=fake_model.__class__.__name__,
            project_id=uuid4(),
            purpose=SessionPurpose.CHAT,
        )
    )
    await service._repository.save(session)

    await service.run_turn(session_id, "hello")

    assert seen == ["a distinctive prompt"]


async def test_state_at_leaves_the_folded_aggregate_with_nothing_to_commit(
    build_service, editing_model
):
    """A fold is a read. If it left uncommitted events, a later save would
    silently append a duplicate of the past to the log."""
    service = await build_service(model=editing_model)
    session_id = await start_session(service)
    await service.run_turn(session_id, "write a.py")

    folded = await service.state_at(session_id, 2)

    assert folded.uncommitted_events == []
    assert not folded.has_uncommitted_events


async def test_state_at_does_not_disturb_the_live_aggregate(build_service, editing_model):
    service = await build_service(model=editing_model)
    session_id = await start_session(service)
    await service.run_turn(session_id, "write a.py")
    await service.run_turn(session_id, "revise it")
    live_before = await service.load(session_id)

    await service.state_at(session_id, 2)

    live_after = await service.load(session_id)
    assert live_after.version == live_before.version
    assert live_after.state.turn_index == live_before.state.turn_index
    assert live_after.state.files == live_before.state.files
