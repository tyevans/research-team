"""The summarizing strategy: what it sends, and what it writes down."""

from uuid import uuid4

from langchain_core.messages import AIMessage

from research_team.domain import SessionState
from research_team.infrastructure.agent.compaction import SummarizingStrategy
from tests.conftest import ToolAwareFakeChatModel


def message(kind: str, content: str, **data) -> dict:
    return {"type": kind, "data": {"content": content, **data}}


def conversation(turns: int, chars: int) -> SessionState:
    messages: list[dict] = []
    for i in range(turns):
        messages.append(message("human", f"request {i}: " + "u" * chars))
        messages.append(message("ai", f"reply {i}: " + "a" * chars))
    return SessionState(session_id=uuid4(), messages=messages)


def summarizer(text: str = "GOAL: ship it. DONE: some of it.") -> ToolAwareFakeChatModel:
    return ToolAwareFakeChatModel(responses=[AIMessage(content=text, id="s1")])


# ---------------- below the trigger ----------------


async def test_a_small_conversation_is_sent_whole():
    session = conversation(3, chars=10)
    strategy = SummarizingStrategy(summarizer(), trigger_tokens=10_000, keep_messages=2)

    prepared = await strategy.prepare(session)

    assert prepared.messages == session.messages
    assert prepared.compaction is None


async def test_a_long_conversation_of_few_messages_is_left_alone():
    """Nothing is gained by summarizing what we were going to keep anyway."""
    session = conversation(2, chars=50_000)
    strategy = SummarizingStrategy(summarizer(), trigger_tokens=250, keep_messages=20)

    prepared = await strategy.prepare(session)

    assert prepared.compaction is None


# ---------------- above the trigger ----------------


async def test_the_older_part_is_replaced_by_a_summary():
    session = conversation(20, chars=500)
    strategy = SummarizingStrategy(
        summarizer("GOAL: build the thing."), trigger_tokens=250, keep_messages=6
    )

    prepared = await strategy.prepare(session)

    assert prepared.compaction is not None
    assert prepared.compaction.through_index == 40 - 6
    # One summary message, then the untouched tail.
    assert len(prepared.messages) == 7
    assert "GOAL: build the thing." in prepared.messages[0]["data"]["content"]
    assert prepared.messages[1:] == session.messages[-6:]


async def test_the_recent_tail_is_never_summarized():
    """Recent detail is what the agent is actively using."""
    session = conversation(20, chars=500)
    strategy = SummarizingStrategy(summarizer(), trigger_tokens=250, keep_messages=6)

    prepared = await strategy.prepare(session)

    assert prepared.messages[-1] == session.messages[-1]
    assert prepared.messages[-6] == session.messages[-6]


async def test_the_compaction_is_reported_for_recording():
    session = conversation(20, chars=500)
    strategy = SummarizingStrategy(
        summarizer("a summary"), trigger_tokens=250, keep_messages=6
    )

    prepared = await strategy.prepare(session)

    assert prepared.compaction.summary == "a summary"
    assert prepared.notes and "compacted" in prepared.notes[0]


async def test_an_already_compacted_session_sends_the_summary_and_the_rest():
    """The stored summary stands in for the messages it covers, every turn."""
    session = conversation(10, chars=100).model_copy(
        update={"compacted_through": 12, "compaction_summary": "what happened before"}
    )
    strategy = SummarizingStrategy(summarizer(), trigger_tokens=10_000, keep_messages=4)

    prepared = await strategy.prepare(session)

    assert prepared.compaction is None, "already recorded; do not pay for it again"
    assert "what happened before" in prepared.messages[0]["data"]["content"]
    assert prepared.messages[1:] == session.messages[12:]


async def test_compacting_again_builds_on_the_previous_summary():
    """Otherwise each compaction forgets what the last one had condensed."""
    seen: list[str] = []

    class Recording(ToolAwareFakeChatModel):
        async def ainvoke(self, messages, *args, **kwargs):
            seen.append(str(messages[-1].content))
            return AIMessage(content="second summary", id="s2")

    session = conversation(30, chars=500).model_copy(
        update={"compacted_through": 10, "compaction_summary": "the first summary"}
    )
    strategy = SummarizingStrategy(
        Recording(responses=[]), trigger_tokens=250, keep_messages=6
    )

    prepared = await strategy.prepare(session)

    assert "the first summary" in seen[0]
    assert prepared.compaction.summary == "second summary"
    assert prepared.compaction.through_index == 60 - 6


async def test_the_messages_themselves_are_never_discarded():
    """Compaction is a view. The session still remembers everything."""
    session = conversation(20, chars=500)
    before = list(session.messages)
    strategy = SummarizingStrategy(summarizer(), trigger_tokens=250, keep_messages=6)

    await strategy.prepare(session)

    assert session.messages == before


# ---------------- when the summarizer is no help ----------------


async def test_an_empty_summary_is_refused():
    """A blank summary would stand in, forever, for messages it does not describe.

    Sending a long context is the lesser problem, so nothing is recorded and
    the next turn can try again.
    """
    session = conversation(20, chars=500)
    strategy = SummarizingStrategy(
        summarizer("   "), trigger_tokens=250, keep_messages=6
    )

    prepared = await strategy.prepare(session)

    assert prepared.compaction is None
    assert prepared.messages == session.messages
    assert prepared.notes == ()


async def test_a_refused_compaction_can_be_retried():
    session = conversation(20, chars=500)
    failing = SummarizingStrategy(summarizer(""), trigger_tokens=250, keep_messages=6)
    assert (await failing.prepare(session)).compaction is None

    working = SummarizingStrategy(
        summarizer("a real summary"), trigger_tokens=250, keep_messages=6
    )
    assert (await working.prepare(session)).compaction is not None


# ---------------- the boundary ----------------


def interleaved(turns: int, chars: int) -> SessionState:
    """A conversation where every turn is user / call / result / reply."""
    messages: list[dict] = []
    for i in range(turns):
        messages.append(message("human", f"do {i}: " + "u" * chars))
        messages.append(
            message("ai", "", tool_calls=[{"name": "read_file", "id": f"c{i}"}])
        )
        messages.append(message("tool", "R" * chars, tool_call_id=f"c{i}"))
        messages.append(message("ai", f"done {i}"))
    return SessionState(session_id=uuid4(), messages=messages)


async def test_the_boundary_never_orphans_a_tool_result():
    """A result whose call was summarized away is a malformed request: an
    answer to a question the model cannot see itself having asked."""
    for keep in range(1, 12):
        session = interleaved(12, chars=400)
        strategy = SummarizingStrategy(
            summarizer(), trigger_tokens=100, keep_messages=keep
        )

        prepared = await strategy.prepare(session)

        tail = prepared.messages[1:] if prepared.compaction else prepared.messages
        assert tail[0]["type"] != "tool", (
            f"keep={keep} left a tool result at the head of the kept tail"
        )


async def test_the_boundary_only_ever_moves_earlier():
    """Snapping backwards summarizes strictly more, which is always safe."""
    session = interleaved(12, chars=400)
    strategy = SummarizingStrategy(summarizer(), trigger_tokens=100, keep_messages=5)

    prepared = await strategy.prepare(session)

    assert prepared.compaction.through_index <= len(session.messages) - 5


async def test_every_kept_tool_result_still_has_its_call():
    session = interleaved(12, chars=400)
    strategy = SummarizingStrategy(summarizer(), trigger_tokens=100, keep_messages=7)

    prepared = await strategy.prepare(session)
    tail = prepared.messages[1:]

    answered = {
        m["data"]["tool_call_id"] for m in tail if m["type"] == "tool"
    }
    asked = {
        call["id"]
        for m in tail
        if m["type"] == "ai"
        for call in (m["data"].get("tool_calls") or [])
    }
    assert answered <= asked
