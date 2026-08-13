"""The in-flight buffer that lets a browser join a turn late."""

from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from research_team.application.ports import (
    ActivityDelta,
    ActivityMessage,
    ActivityRemark,
)
from research_team.interfaces.web.activity import (
    ACTIVITY,
    REMARK,
    REMARK_ID_PREFIX,
    TurnActivity,
)
from tests.conftest import start_session


@pytest.fixture
def session_id():
    return uuid4()


def test_a_whole_message_lands_in_the_buffer(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    activity.reporter(session_id)(
        ActivityMessage(message_id="a1", kind="assistant", payload={"content": "hi"})
    )
    assert [e["message_id"] for e in activity.current(session_id)] == ["a1"]


def test_deltas_accumulate_onto_one_entry(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    report = activity.reporter(session_id)
    report(ActivityDelta(message_id="a1", text="hel"))
    report(ActivityDelta(message_id="a1", text="lo"))
    entries = activity.current(session_id)
    assert len(entries) == 1
    assert entries[0]["text"] == "hello"


def test_a_whole_message_supersedes_its_deltas(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    report = activity.reporter(session_id)
    report(ActivityDelta(message_id="a1", text="par"))
    report(ActivityMessage(message_id="a1", kind="assistant", payload={"content": "partial"}))
    entries = activity.current(session_id)
    assert len(entries) == 1
    assert entries[0]["payload"] == {"content": "partial"}
    # The other half of "replace, don't merge": the browser's renderProvisional
    # prefers entry.text and only falls back to payload when text is empty, so
    # a whole message must also reset the accumulated delta text -- otherwise
    # the superseded "par" would keep winning over the real payload.
    assert entries[0]["text"] == ""


def test_entries_keep_arrival_order(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    report = activity.reporter(session_id)
    report(ActivityMessage(message_id="a1", kind="assistant", payload={}))
    report(ActivityMessage(message_id="t1", kind="tool", payload={}))
    report(ActivityDelta(message_id="a1", text="more"))
    assert [e["message_id"] for e in activity.current(session_id)] == ["a1", "t1"]


def test_beginning_a_turn_clears_both_slots(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    activity.reporter(session_id)(
        ActivityMessage(message_id="a1", kind="assistant", payload={})
    )
    activity.settle(session_id, committed=False)
    activity.begin(session_id)
    assert activity.current(session_id) == []
    assert activity.discarded(session_id) == []


def test_committing_drops_the_buffer(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    activity.reporter(session_id)(
        ActivityMessage(message_id="a1", kind="assistant", payload={})
    )
    activity.settle(session_id, committed=True)
    assert activity.current(session_id) == []
    assert activity.discarded(session_id) == []


def test_failing_moves_the_buffer_to_discarded(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    activity.reporter(session_id)(
        ActivityMessage(message_id="a1", kind="assistant", payload={})
    )
    activity.settle(session_id, committed=False)
    assert activity.current(session_id) == []
    assert [e["message_id"] for e in activity.discarded(session_id)] == ["a1"]


def test_sessions_do_not_share_a_buffer():
    activity = TurnActivity()
    one, two = uuid4(), uuid4()
    activity.begin(one)
    activity.begin(two)
    activity.reporter(one)(ActivityMessage(message_id="a1", kind="assistant", payload={}))
    assert activity.current(two) == []


async def test_listeners_receive_frames(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    queue = activity.listen()
    activity.reporter(session_id)(
        ActivityMessage(message_id="a1", kind="assistant", payload={"content": "hi"})
    )
    frame = queue.get_nowait()
    assert frame["type"] == ACTIVITY
    assert frame["session_id"] == str(session_id)
    assert frame["message_id"] == "a1"


def test_a_remark_is_buffered_under_an_id_of_the_buffers_own_making(session_id):
    """The note has no message to belong to, so the buffer names it.

    Synthesised here rather than in the application layer on purpose: the id is
    the browser's accumulation key, and only the layer that owns every other
    key in this buffer can promise a new one collides with none of them.
    """
    activity = TurnActivity()
    activity.begin(session_id)
    activity.reporter(session_id)(ActivityRemark(text="cleared 4 older tool result(s)"))

    entries = activity.current(session_id)
    assert [e["kind"] for e in entries] == [REMARK]
    assert entries[0]["text"] == "cleared 4 older tool result(s)"
    assert entries[0]["message_id"], "a frame without one is dropped by the browser"


def test_two_remarks_do_not_land_on_one_entry(session_id):
    """The failure this guards: one id for both, and the second overwrites."""
    activity = TurnActivity()
    activity.begin(session_id)
    report = activity.reporter(session_id)
    report(ActivityRemark(text="first"))
    report(ActivityRemark(text="second"))
    assert [e["text"] for e in activity.current(session_id)] == ["first", "second"]


def test_a_remarks_id_is_namespaced_away_from_model_ids(session_id):
    """What keeps a remark and a real message out of one bubble.

    The buffer keys on `message_id` and the browser accumulates on it, so an id
    a model could also produce would splice the two together. The prefix is the
    whole of the defence, which is why it is asserted rather than assumed.
    """
    activity = TurnActivity()
    activity.begin(session_id)
    activity.reporter(session_id)(ActivityRemark(text="ours"))
    assert activity.current(session_id)[0]["message_id"].startswith(REMARK_ID_PREFIX)


async def test_a_remark_reaches_the_feed(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    queue = activity.listen()
    activity.reporter(session_id)(ActivityRemark(text="cleared 4"))
    frame = queue.get_nowait()
    assert frame["type"] == ACTIVITY
    assert frame["kind"] == REMARK
    assert frame["text"] == "cleared 4"


async def test_a_turn_that_elides_reports_it_without_crashing(
    monkeypatch, build_service, fake_model
):
    """The 500 this all came from: a `str` where an `ActivityNote` belonged.

    Wired with the real reporter, not a spy that appends to a list -- a spy
    accepts a string happily, which is exactly why every existing test passed
    while the browser got an AttributeError. It needs an eliding strategy and a
    history worth eliding, which is why it took a long session to show up.

    Reverting the fix restores the AttributeError here, before any assertion.
    """
    monkeypatch.setenv("AGENT_CONTEXT_KEEP_RESULTS", "0")
    monkeypatch.setenv("AGENT_CONTEXT_CLEAR_OVER", "1")
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
        AIMessage(content="and again", id="a3"),
    ]
    service = await build_service(model=fake_model, context_mode="elide")
    started = await start_session(service)
    await service.run_turn(started, "write hello.py")

    activity = TurnActivity()
    activity.begin(started)
    outcome = await service.run_turn(started, "again", activity.reporter(started))

    assert outcome.reply == "and again"
    remarks = [e for e in activity.current(started) if e["kind"] == REMARK]
    assert remarks and "cleared" in remarks[0]["text"]


async def test_stop_listening_ends_delivery(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    queue = activity.listen()
    activity.stop_listening(queue)
    activity.reporter(session_id)(
        ActivityMessage(message_id="a1", kind="assistant", payload={})
    )
    assert queue.empty()
