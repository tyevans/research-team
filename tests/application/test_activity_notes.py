"""The activity note types the executor reports and the web layer buffers."""

from research_team.application.ports import (
    ActivityDelta,
    ActivityMessage,
    ActivityReporter,
)


def test_activity_message_carries_an_opaque_payload():
    note = ActivityMessage(
        message_id="a1",
        kind="assistant",
        payload={"content": "hello", "id": "a1"},
        is_error=False,
    )
    assert note.message_id == "a1"
    assert note.kind == "assistant"
    assert note.payload["content"] == "hello"
    assert note.is_error is False


def test_activity_message_defaults_to_not_an_error():
    note = ActivityMessage(message_id="t1", kind="tool", payload={})
    assert note.is_error is False


def test_activity_delta_carries_text_for_one_message():
    note = ActivityDelta(message_id="a1", text="hel")
    assert note.message_id == "a1"
    assert note.text == "hel"


def test_notes_are_frozen():
    import dataclasses
    import pytest

    note = ActivityDelta(message_id="a1", text="hel")
    with pytest.raises(dataclasses.FrozenInstanceError):
        note.text = "changed"


def test_reporter_accepts_either_note():
    seen: list = []
    reporter: ActivityReporter = seen.append
    reporter(ActivityMessage(message_id="a1", kind="assistant", payload={}))
    reporter(ActivityDelta(message_id="a1", text="x"))
    assert len(seen) == 2
