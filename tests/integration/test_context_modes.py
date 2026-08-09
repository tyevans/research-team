"""The three context modes, driven through real turns.

The claim each mode has to earn is the same one: the model is shown less, and
the log still knows everything.
"""

from typing import Any

import pytest
from langchain_core.messages import AIMessage

from research_team.domain import ConversationCompacted
from tests.conftest import ToolAwareFakeChatModel, start_session


class Recording(ToolAwareFakeChatModel):
    """Remembers turn requests, and answers summarization requests separately.

    Compaction asks the same model for a summary. A scripted fake would
    otherwise hand over the next turn's reply and lose its place, so
    summarization is recognised and answered without consuming the script --
    which is also how a real model behaves, since it has no script to lose.
    """

    calls: list[list[Any]] = []
    summaries: int = 0

    def _is_summary_request(self, messages) -> bool:
        return bool(messages) and "compacting the transcript" in str(messages[0].content)

    async def _agenerate(self, messages, *args: Any, **kwargs: Any):
        if self._is_summary_request(messages):
            Recording.summaries += 1
            from langchain_core.outputs import ChatGeneration, ChatResult

            summary = AIMessage(
                content=f"GOAL: exercise compaction. DONE: {Recording.summaries} so far.",
                id=f"sum{Recording.summaries}",
            )
            return ChatResult(generations=[ChatGeneration(message=summary)])
        Recording.calls.append(list(messages))
        return await super()._agenerate(messages, *args, **kwargs)


def chatty(turns: int, file_lines: int = 600) -> Recording:
    """Write one big file, then read it back every turn.

    Reads are what actually inflate a coding session: `write_file` answers with
    a one-line confirmation, while `read_file` answers with the whole file and
    that answer is replayed on every later turn.
    """
    responses: list[AIMessage] = [
        AIMessage(
            content="",
            id="w0",
            tool_calls=[
                {
                    "name": "write_file",
                    "args": {"file_path": "/big.py", "content": "x = 1\n" * file_lines},
                    "id": "cw",
                }
            ],
        ),
        AIMessage(content="wrote /big.py", id="w1"),
    ]
    for i in range(turns):
        responses.append(
            AIMessage(
                content="",
                id=f"a{i}",
                tool_calls=[
                    {"name": "read_file", "args": {"file_path": "/big.py"}, "id": f"c{i}"}
                ],
            )
        )
        responses.append(AIMessage(content=f"read it back ({i})", id=f"b{i}"))
    return Recording(responses=responses)


@pytest.fixture
def compact_soon(monkeypatch):
    """Thresholds low enough that a short test session trips them."""
    monkeypatch.setenv("AGENT_CONTEXT_TRIGGER", "500")
    monkeypatch.setenv("AGENT_CONTEXT_KEEP_MESSAGES", "4")


@pytest.fixture
def elide_soon(monkeypatch):
    """Aggressive enough that a handful of file reads trip it."""
    monkeypatch.setenv("AGENT_CONTEXT_KEEP_RESULTS", "1")
    monkeypatch.setenv("AGENT_CONTEXT_CLEAR_OVER", "200")


@pytest.fixture(autouse=True)
def _reset_calls():
    Recording.calls = []
    Recording.summaries = 0
    yield
    Recording.calls = []
    Recording.summaries = 0


def sent_chars(index: int = -1) -> int:
    return sum(len(str(m.content)) for m in Recording.calls[index])


# ---------------- full ----------------


async def test_full_mode_sends_the_whole_conversation(build_application):
    application = await build_application(model=chatty(8), context_mode="full")
    session_id = await start_session(application.service)

    for i in range(6):
        await application.service.run_turn(session_id, f"turn {i}")

    session = await application.service.load(session_id)
    # Every stored message reaches the model on the final turn, plus the new one.
    assert len(Recording.calls[-1]) >= len(session.state.messages) - 2
    assert session.state.compacted_through == 0


# ---------------- elide ----------------


async def test_elide_mode_sends_less_than_full_mode(build_application, db_path, elide_soon):
    """The point of the mode, measured rather than asserted."""
    full = await build_application(model=chatty(10), context_mode="full", db_path=db_path)
    session_id = await start_session(full.service)
    for i in range(5):
        await full.service.run_turn(session_id, f"turn {i}")
    full_chars = sent_chars()

    Recording.calls = []
    elided = await build_application(
        model=chatty(10), context_mode="elide", db_path=f"{db_path}.elide"
    )
    session_id = await start_session(elided.service)
    for i in range(5):
        await elided.service.run_turn(session_id, f"turn {i}")
    elided_chars = sent_chars()

    assert elided_chars < full_chars


async def test_elide_mode_records_no_extra_events(build_application, elide_soon):
    """It is a view: the log looks exactly as it would have without it."""
    application = await build_application(model=chatty(8), context_mode="elide")
    session_id = await start_session(application.service)

    for i in range(5):
        await application.service.run_turn(session_id, f"turn {i}")

    events = await application.service.history(session_id)
    assert not any(isinstance(e, ConversationCompacted) for e in events)
    session = await application.service.load(session_id)
    assert len(session.state.messages) == 5 * 4  # user, ai, tool, ai per turn


async def test_elide_mode_keeps_every_message_in_the_log(build_application, elide_soon):
    application = await build_application(model=chatty(8), context_mode="elide")
    session_id = await start_session(application.service)

    for i in range(5):
        await application.service.run_turn(session_id, f"turn {i}")

    session = await application.service.load(session_id)
    stored = [m for m in session.state.messages if m["type"] == "tool"]
    assert all("cleared to save context" not in str(m["data"]["content"]) for m in stored), (
        "the log must hold the real tool output, not the shortened view"
    )


# ---------------- compact ----------------


async def test_compact_mode_records_a_compaction_event(build_application, compact_soon):
    application = await build_application(model=chatty(12), context_mode="compact")
    session_id = await start_session(application.service)

    for i in range(6):
        await application.service.run_turn(session_id, f"turn {i}")

    events = await application.service.history(session_id)
    compactions = [e for e in events if isinstance(e, ConversationCompacted)]
    assert compactions, "a long session should have compacted at least once"
    assert compactions[0].strategy == "compact"


async def test_compact_mode_keeps_the_original_messages_in_the_log(
    build_application, compact_soon
):
    """The summary is what the model sees; the log keeps what actually happened."""
    application = await build_application(model=chatty(12), context_mode="compact")
    session_id = await start_session(application.service)
    for i in range(6):
        await application.service.run_turn(session_id, f"turn {i}")

    session = await application.service.load(session_id)
    assert session.state.compacted_through > 0
    assert len(session.state.messages) == 6 * 4, "nothing was dropped from the log"
    assert session.state.messages[0]["data"]["content"] == "turn 0"


async def test_time_travel_predates_the_compaction(build_application, compact_soon):
    """Folding to before the compaction shows the conversation uncompacted."""
    application = await build_application(model=chatty(12), context_mode="compact")
    session_id = await start_session(application.service)
    for i in range(6):
        await application.service.run_turn(session_id, f"turn {i}")

    events = await application.service.history(session_id)
    first = next(
        i for i, e in enumerate(events, start=1) if isinstance(e, ConversationCompacted)
    )

    before = await application.service.state_at(session_id, first - 1)
    after = await application.service.state_at(session_id, first)

    assert before.state.compacted_through == 0
    assert after.state.compacted_through > 0


# ---------------- delegate ----------------


async def test_delegate_mode_offers_the_agent_a_worker(build_application):
    """The subagent has to be reachable, or the mode is decoration."""
    application = await build_application(model=chatty(4), context_mode="delegate")
    assert application.context_mode == "delegate"

    session_id = await start_session(application.service)
    session = await application.service.load(session_id)
    assert "worker" in session.state.system_prompt
    assert "task" in session.state.system_prompt


async def test_delegate_mode_leaves_the_history_untouched(build_application):
    """It prevents growth rather than treating it -- no view transform at all."""
    application = await build_application(model=chatty(8), context_mode="delegate")
    session_id = await start_session(application.service)

    for i in range(4):
        await application.service.run_turn(session_id, f"turn {i}")

    events = await application.service.history(session_id)
    assert not any(isinstance(e, ConversationCompacted) for e in events)
    assert application.service.context_strategy == "full"


async def test_delegation_guidance_says_when_not_to_delegate(build_application):
    """A guard on evidence, not on wording.

    The two documented ways this pattern fails are subagents duplicating work
    when their scope is vague, and one coherent change split across workers who
    cannot see each other. Both are addressed by instructions rather than by
    code, so nothing but a test stops them being edited away -- and the failure
    would only show up as an agent quietly behaving worse.
    """
    application = await build_application(model=chatty(4), context_mode="delegate")
    session_id = await start_session(application.service)
    prompt = (await application.service.load(session_id)).state.system_prompt

    assert "not delegate" in prompt, "the prompt must say when to keep the work"
    assert "cannot see each other" in prompt, "the splitting failure must be named"
