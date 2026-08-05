"""The pure context strategies, as functions over a session's state."""

from uuid import uuid4

import pytest

from research_team.application import ElideToolResults, FullHistory
from research_team.domain import SessionState


def message(kind: str, content: str, **data) -> dict:
    return {"type": kind, "data": {"content": content, **data}}


def state(*messages: dict, **overrides) -> SessionState:
    return SessionState(session_id=uuid4(), messages=list(messages), **overrides)


def conversation(turns: int, result_chars: int = 5000) -> SessionState:
    """`turns` exchanges, each with one fat tool result."""
    messages: list[dict] = []
    for i in range(turns):
        messages.append(message("human", f"do thing {i}"))
        messages.append(message("ai", "", tool_calls=[{"name": "read_file", "id": f"c{i}"}]))
        messages.append(message("tool", "F" * result_chars, tool_call_id=f"c{i}"))
        messages.append(message("ai", f"done {i}"))
    return state(*messages)


# ---------------- full ----------------


async def test_full_history_sends_everything():
    session = conversation(3)
    prepared = await FullHistory().prepare(session)

    assert prepared.messages == session.messages
    assert prepared.compaction is None
    assert prepared.notes == ()


async def test_full_history_does_not_alias_the_state():
    """The caller must not be able to mutate the session by editing the view."""
    session = conversation(1)
    prepared = await FullHistory().prepare(session)

    prepared.messages.append(message("human", "injected"))

    assert len(session.messages) == 4


# ---------------- elide ----------------


async def test_elide_shortens_older_tool_results():
    session = conversation(6, result_chars=5000)
    prepared = await ElideToolResults(keep_results=2, clear_over_chars=100).prepare(session)

    tool_results = [m for m in prepared.messages if m["type"] == "tool"]
    assert len(tool_results) == 6, "no message is dropped, only shortened"
    shortened = [m for m in tool_results if len(m["data"]["content"]) < 5000]
    assert len(shortened) == 4  # six results, the last two kept whole


async def test_elide_keeps_the_most_recent_results_whole():
    session = conversation(4, result_chars=5000)
    prepared = await ElideToolResults(keep_results=2, clear_over_chars=100).prepare(session)

    tool_results = [m for m in prepared.messages if m["type"] == "tool"]
    assert len(tool_results[-1]["data"]["content"]) == 5000
    assert len(tool_results[-2]["data"]["content"]) == 5000


async def test_elide_leaves_no_partial_result_to_be_mistaken_for_a_whole_one():
    """A truncated head reads as complete, which is how an agent concludes that
    a half-finished thing succeeded. The marker must be unmistakable."""
    session = state(
        message("ai", "", tool_calls=[{"name": "read_file", "id": "c1"}]),
        message("tool", "line one\n" + "X" * 9000, tool_call_id="c1"),
        message("ai", "", tool_calls=[{"name": "read_file", "id": "c2"}]),
        message("tool", "recent", tool_call_id="c2"),
    )
    prepared = await ElideToolResults(keep_results=1, clear_over_chars=60).prepare(session)

    cleared = next(m for m in prepared.messages if m["type"] == "tool")["data"]["content"]
    assert "line one" not in cleared, "no fragment survives to look like the answer"
    assert "NOT the result" in cleared
    assert "9009" in cleared  # says how much was cleared


async def test_elide_leaves_prose_alone():
    """It only touches tool output; a conversation of text is untouched."""
    session = state(*[message("ai", "a long reply " * 500) for _ in range(10)])
    prepared = await ElideToolResults(keep_results=1, clear_over_chars=50).prepare(session)

    assert prepared.messages == session.messages
    assert prepared.notes == ()


async def test_elide_does_nothing_to_a_short_session():
    session = conversation(1, result_chars=50)
    prepared = await ElideToolResults(keep_results=6).prepare(session)

    assert prepared.messages == session.messages
    assert prepared.notes == ()


async def test_elide_says_what_it_did():
    session = conversation(6, result_chars=5000)
    prepared = await ElideToolResults(keep_results=2, clear_over_chars=100).prepare(session)

    assert prepared.notes
    assert "cleared 4" in prepared.notes[0]


async def test_elide_never_claims_to_have_shortened_a_short_result():
    """A result under the limit is left alone, and the note must not lie."""
    session = conversation(6, result_chars=10)
    prepared = await ElideToolResults(keep_results=1, clear_over_chars=1000).prepare(session)

    assert prepared.messages == session.messages
    assert prepared.notes == ()


async def test_elide_records_nothing():
    """It is a view, recomputed every turn -- there is no decision to remember."""
    session = conversation(8)
    prepared = await ElideToolResults(keep_results=1, clear_over_chars=10).prepare(session)

    assert prepared.compaction is None


@pytest.mark.parametrize("keep", [0, 1, 50])
async def test_elide_survives_any_keep_setting(keep):
    session = conversation(3)
    prepared = await ElideToolResults(keep_results=keep, clear_over_chars=10).prepare(session)

    assert len(prepared.messages) == len(session.messages)
