"""What a successful ask leaves behind, and what a failed one does not.

Asserts on the events on the conversation's own stream rather than on `ask()`
having returned: an event no projection handles still counts as applied
(`eventsource.replay`'s docstring, and `CLAUDE.md`), so "the call worked" is
compatible with nothing having been written at all.
"""

from collections.abc import Sequence
from uuid import UUID, uuid4

import pytest
from eventsource import StreamId, collect
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.testing import InMemoryTestHarness

from research_team.application.ask import (
    AskAnswer,
    AskService,
    Citation,
    ConversationRegistry,
)
from research_team.application.ports import ActivityReporter
from research_team.domain.ask_conversation import (
    AskConversation,
    AskConversationStarted,
    AskTurnRecorded,
)


class FakeExecutor:
    """Answers, or raises what it was given instead."""

    def __init__(self, answer=AskAnswer(text="an answer"), fail=None):  # noqa: B008
        self.answer = answer
        self.fail = fail

    async def run(
        self, *, project_id, history: Sequence, question, on_activity: ActivityReporter
    ):
        if self.fail is not None:
            raise self.fail
        return self.answer


@pytest.fixture
def transcripts() -> AggregateRepository[AskConversation]:
    return AggregateRepository(InMemoryTestHarness().event_store, AskConversation)


def service(executor, transcripts) -> AskService:
    return AskService(
        executor=executor,
        conversations=ConversationRegistry(now=lambda: 0.0),
        now=lambda: 0.0,
        transcripts=transcripts,
    )


async def drain(iterator):
    return [note async for note in iterator]


async def events_on(transcripts, conversation_id: UUID):
    stream = StreamId(conversation_id, AskConversation.aggregate_type)
    return [
        envelope.event
        for envelope in await collect(transcripts.event_store.read_stream(stream))
    ]


async def all_events(transcripts):
    """Every `AskConversation` event in the store, whatever its id.

    Used where the point is that *nothing* was written -- reading one stream
    could only prove that one id is empty, and the id under suspicion in the
    failure case is one no test knows.
    """
    return [
        envelope.event
        for envelope in await collect(
            transcripts.event_store.read_category(AskConversation.aggregate_type)
        )
    ]


async def test_a_successful_ask_appends_a_turn(transcripts):
    """The conversation's stream carries the start and the turn, with citations.

    Asserts the events, not that `ask()` returned -- an event no projection
    handles still counts as applied, so a green call proves nothing.
    """
    answer = AskAnswer(text="an answer", citations=(Citation(kind="source", id="s1"),))
    ask = service(FakeExecutor(answer=answer), transcripts)
    project = uuid4()

    await drain(ask.ask(project_id=project, chat_id="c", question="why?"))

    conversation_id = ask._conversations.get("c", project).conversation_id
    events = await events_on(transcripts, conversation_id)
    assert [type(event) for event in events] == [AskConversationStarted, AskTurnRecorded]
    assert events[0].project_id == project
    assert events[1].question == "why?"
    assert events[1].answer == "an answer"
    assert events[1].citations == [("source", "s1")]


async def test_a_second_turn_appends_to_the_same_stream(transcripts):
    """One conversation, not one per question -- and the start happens once.

    Fails if `_record` starts a fresh aggregate per turn, which would be
    invisible to the single-turn test above and would give the history pane a
    conversation of one question each.
    """
    ask = service(FakeExecutor(), transcripts)
    project = uuid4()

    await drain(ask.ask(project_id=project, chat_id="c", question="first?"))
    await drain(ask.ask(project_id=project, chat_id="c", question="second?"))

    conversation_id = ask._conversations.get("c", project).conversation_id
    events = await events_on(transcripts, conversation_id)
    assert [type(event) for event in events] == [
        AskConversationStarted,
        AskTurnRecorded,
        AskTurnRecorded,
    ]
    assert [event.question for event in events[1:]] == ["first?", "second?"]


async def test_a_chat_id_reused_under_another_project_starts_its_own_stream(transcripts):
    """B's question must not land on the conversation A started.

    `RecordAskTurn` carries no `project_id`, so `decide` has nothing to
    compare and cannot refuse this -- the check lives one layer out, in
    `ConversationRegistry.get`, which treats a project mismatch as absence
    because the chat id came from the browser. That guard used to protect a
    cache; it now decides which *stream* a turn is appended to, which is the
    stronger job, and this test is what says so.

    Absence rather than refusal, matching today's behaviour: B gets a fresh
    conversation on a fresh stream. A's stream is left with exactly the one
    turn it earned.
    """
    ask = service(FakeExecutor(), transcripts)
    project_a, project_b = uuid4(), uuid4()

    await drain(ask.ask(project_id=project_a, chat_id="c", question="a's question"))
    conversation_a = ask._conversations.get("c", project_a).conversation_id
    await drain(ask.ask(project_id=project_b, chat_id="c", question="b's question"))

    on_a = await events_on(transcripts, conversation_a)
    assert [getattr(event, "question", None) for event in on_a] == [None, "a's question"]
    # And B's turn did land somewhere -- on its own stream, under its own
    # project. Without this, deleting the append entirely would pass the half
    # above.
    started = [
        event
        for event in await all_events(transcripts)
        if event.aggregate_id != conversation_a
    ]
    assert [
        event.project_id for event in started if isinstance(event, AskConversationStarted)
    ] == [project_b]


async def test_a_failed_ask_appends_nothing(transcripts):
    """The executor raises: no conversation started, no turn recorded.

    A turn is a fact about an answer that was given. Reads the whole category
    rather than one stream, because the id a failed ask would have used is one
    this test never learns.

    **This one passes with the change reverted**, and is kept anyway: it is
    the regression guard for someone later moving the append out of the
    success branch -- into a `finally`, or before `await running` -- to close
    a window that the comment above `_record`'s call site says does not
    exist. The other four in this file are the ones that went red.
    """
    ask = service(FakeExecutor(fail=RuntimeError("no model")), transcripts)

    with pytest.raises(RuntimeError):
        await drain(ask.ask(project_id=uuid4(), chat_id="c", question="why?"))

    assert await all_events(transcripts) == []


async def test_the_conversation_id_is_not_the_browser_s_chat_id(transcripts):
    """The spec's ruling: a browser-minted string must not become an aggregate id.

    Fails if `chat_id` is threaded straight through -- which is the shape the
    registry has always had, and is adequate only while the string is a key
    into a bounded in-memory dict. Asserting the stream is a UUID and not that
    string is the whole of the check: an aggregate id, a row key and a URL
    segment cannot be whatever the caller says.
    """
    ask = service(FakeExecutor(), transcripts)
    project = uuid4()

    await drain(ask.ask(project_id=project, chat_id="chat-from-the-browser", question="why?"))

    started = (await all_events(transcripts))[0]
    assert isinstance(started.aggregate_id, UUID)
    assert str(started.aggregate_id) != "chat-from-the-browser"
    # And the id the registry holds for that chat is the one the stream used,
    # so a second turn can find it.
    assert (
        ask._conversations.get("chat-from-the-browser", project).conversation_id
        == started.aggregate_id
    )


async def test_a_failed_append_fails_the_ask(transcripts):
    """The cost the spec takes explicitly: asking is now a write.

    The in-memory registry could not fail this way. Swallowing the failure
    would show a reader an answer no history pane will ever list, so the
    error reaches them instead.
    """

    class Broken:
        def create_new(self, aggregate_id):
            raise RuntimeError("the store is gone")

    ask = service(FakeExecutor(), Broken())

    with pytest.raises(RuntimeError, match="the store is gone"):
        await drain(ask.ask(project_id=uuid4(), chat_id="c", question="why?"))
