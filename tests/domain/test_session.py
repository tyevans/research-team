import pytest
from conftest import MODEL_NAME, SYSTEM_PROMPT
from eventsource.testing.assertions import EventAssertions

from research_team.domain import CodingSession
from research_team.domain.events import (
    AssistantMessageAdded,
    FileDeleted,
    FileEdited,
    FileWritten,
    SessionStarted,
    ToolResultRecorded,
    TurnCompleted,
    UserMessageSent,
)

FILE_DATA = {"content": "print(1)\n", "encoding": "utf-8"}
EDITED = {"content": "print(2)\n", "encoding": "utf-8"}


def types_of(aggregate: CodingSession) -> list[type]:
    return [type(e) for e in aggregate.uncommitted_events]


def emitted(aggregate: CodingSession) -> EventAssertions:
    """The library's assertions over what this aggregate has emitted.

    Worth reaching for wherever the whole sequence is the claim -- it reports
    what it actually saw when the sequence is wrong, where a bare list
    comparison just prints two lists and leaves you to diff them. The
    positional `types_of(...)[-1]` checks below stay as they are: what they
    assert is *where* an event landed, which these helpers do not express.
    """
    return EventAssertions(list(aggregate.uncommitted_events))


def tool_result(call_id: str, content: str = "ok") -> dict:
    return {"type": "tool", "data": {"tool_call_id": call_id, "content": content}}


def calling(*call_ids: str) -> dict:
    """An assistant message that asked for the given tool calls."""
    return {
        "type": "ai",
        "data": {
            "content": "",
            "tool_calls": [
                {"id": call_id, "name": "write_file", "args": {}} for call_id in call_ids
            ],
        },
    }


def test_start_emits_session_started(session):
    emitted(session).assert_event_sequence([SessionStarted])
    assert session.state.system_prompt == SYSTEM_PROMPT
    assert session.state.model_name == MODEL_NAME


def test_start_twice_is_rejected(session):
    with pytest.raises(ValueError, match="already started"):
        session.start(SYSTEM_PROMPT, MODEL_NAME)


def test_commands_require_started_session(aggregates, session_id):
    fresh = aggregates.create_new(session_id)
    with pytest.raises(ValueError, match="not started"):
        fresh.write_file("/a.py", FILE_DATA)


def test_user_message_appended(session):
    session.send_user_message({"type": "human", "data": {"content": "hi"}})
    assert types_of(session)[-1] is UserMessageSent
    assert session.state.messages[-1]["data"]["content"] == "hi"


def test_assistant_message_appended(session):
    session.record_assistant_message(
        {"type": "ai", "data": {"content": "yo", "tool_calls": []}}
    )
    assert types_of(session)[-1] is AssistantMessageAdded
    assert session.state.messages[-1]["type"] == "ai"


def test_write_file_creates_entry(session):
    session.write_file("/a.py", FILE_DATA)
    assert types_of(session)[-1] is FileWritten
    assert session.state.files["/a.py"] == FILE_DATA


def test_edit_file_replaces_entry(session):
    session.write_file("/a.py", FILE_DATA)
    session.edit_file("/a.py", EDITED, "1", "2", False)
    assert types_of(session)[-1] is FileEdited
    assert session.state.files["/a.py"] == EDITED


def test_edit_missing_file_is_rejected(session):
    with pytest.raises(ValueError, match="does not exist"):
        session.edit_file("/nope.py", EDITED, "1", "2", False)


def test_delete_file_removes_entry(session):
    session.write_file("/a.py", FILE_DATA)
    session.delete_file("/a.py")
    assert types_of(session)[-1] is FileDeleted
    assert "/a.py" not in session.state.files


def test_delete_missing_file_is_rejected(session):
    with pytest.raises(ValueError, match="does not exist"):
        session.delete_file("/nope.py")


def test_tool_result_requires_outstanding_call(session):
    with pytest.raises(ValueError, match="no outstanding tool call"):
        session.record_tool_result(tool_result("t1", "ok"))


def test_tool_result_accepted_when_call_outstanding(session):
    session.record_assistant_message(calling("t1"))
    session.record_tool_result(tool_result("t1", "ok"))
    assert types_of(session)[-1] is ToolResultRecorded


def test_tool_results_may_resolve_out_of_order(session):
    session.record_assistant_message(calling("t1", "t2"))
    session.record_tool_result(tool_result("t2", "b"))
    session.record_tool_result(tool_result("t1", "a"))
    assert types_of(session)[-2:] == [ToolResultRecorded, ToolResultRecorded]


def test_complete_turn_increments_index(session):
    session.complete_turn()
    session.complete_turn()
    assert types_of(session)[-1] is TurnCompleted
    assert session.state.turn_index == 2


async def test_state_survives_save_and_reload(aggregates, session, session_id):
    session.write_file("/a.py", FILE_DATA)
    session.send_user_message({"type": "human", "data": {"content": "hi"}})
    await aggregates.save(session)

    reloaded = await aggregates.load(session_id)
    assert reloaded.state.files == {"/a.py": FILE_DATA}
    assert reloaded.state.messages[-1]["data"]["content"] == "hi"
    assert reloaded.version == 3


# ---- conversation compaction ----


def test_compaction_records_what_the_model_will_see(session):
    for i in range(4):
        session.send_user_message({"type": "human", "data": {"content": f"m{i}"}})

    session.compact_conversation("a summary", through_index=3, strategy="compact")

    assert session.state.compacted_through == 3
    assert session.state.compaction_summary == "a summary"


def test_compaction_keeps_every_message(session):
    """The summary is a view. Nothing leaves the log, ever."""
    for i in range(4):
        session.send_user_message({"type": "human", "data": {"content": f"m{i}"}})

    session.compact_conversation("a summary", through_index=3, strategy="compact")

    assert len(session.state.messages) == 4
    assert session.state.messages[0]["data"]["content"] == "m0"


def test_compaction_cannot_go_backwards(session):
    """Uncovering messages an earlier summary covered would show both."""
    for i in range(6):
        session.send_user_message({"type": "human", "data": {"content": f"m{i}"}})
    session.compact_conversation("first", through_index=4, strategy="compact")

    with pytest.raises(ValueError, match="cannot compact through"):
        session.compact_conversation("second", through_index=2, strategy="compact")


def test_compaction_cannot_cover_messages_that_do_not_exist(session):
    session.send_user_message({"type": "human", "data": {"content": "only one"}})

    with pytest.raises(ValueError, match="cannot compact through"):
        session.compact_conversation("premature", through_index=5, strategy="compact")


def test_compaction_needs_a_started_session(aggregates, session_id):
    fresh = aggregates.create_new(session_id)

    with pytest.raises(ValueError, match="not started"):
        fresh.compact_conversation("s", through_index=1, strategy="compact")


def test_compaction_always_covers_a_prefix(session):
    """The summary stands in for the *first* N messages, never a middle window.

    Anything reading `compacted_through` -- the web console slices the
    conversation on it -- is entitled to assume that, so the aggregate has to
    guarantee it rather than leave it to whichever strategy is installed.
    """
    for i in range(6):
        session.send_user_message({"type": "human", "data": {"content": f"m{i}"}})

    session.compact_conversation("first", through_index=2, strategy="compact")
    session.compact_conversation("second", through_index=5, strategy="compact")

    # Each compaction extends the covered prefix; none can carve out a window.
    assert session.state.compacted_through == 5
    with pytest.raises(ValueError, match="cannot compact through"):
        session.compact_conversation("backwards", through_index=3, strategy="compact")
