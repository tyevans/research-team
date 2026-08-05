"""The in-flight buffer that lets a browser join a turn late."""

from uuid import uuid4

import pytest

from research_team.application.ports import ActivityDelta, ActivityMessage
from research_team.interfaces.web.activity import ACTIVITY, TurnActivity


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


async def test_stop_listening_ends_delivery(session_id):
    activity = TurnActivity()
    activity.begin(session_id)
    queue = activity.listen()
    activity.stop_listening(queue)
    activity.reporter(session_id)(
        ActivityMessage(message_id="a1", kind="assistant", payload={})
    )
    assert queue.empty()
