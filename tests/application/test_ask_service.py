"""What the ask service guarantees around an executor it does not trust.

Streaming order, the one-at-a-time rule, and the fact that a failed answer
leaves no half-conversation behind.
"""

import asyncio
from collections.abc import Sequence
from uuid import uuid4

import pytest

from research_team.application.ask import (
    AskAnswer,
    AskInFlight,
    AskMessage,
    AskService,
    Citation,
    ConversationRegistry,
)
from research_team.application.ports import ActivityDelta, ActivityReporter


class FakeExecutor:
    """Records what it was asked, reports the notes it was told to, answers."""

    def __init__(self, notes=(), answer=AskAnswer(text="an answer"), fail=None):  # noqa: B008
        self.notes = list(notes)
        self.answer = answer
        self.fail = fail
        self.calls: list[tuple[Sequence[AskMessage], str]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def run(self, *, project_id, history, question, on_activity: ActivityReporter):
        self.calls.append((tuple(history), question))
        self.started.set()
        await self.release.wait()
        for note in self.notes:
            on_activity(note)
        if self.fail is not None:
            raise self.fail
        return self.answer


def service(executor, **kwargs) -> AskService:
    return AskService(
        executor=executor,
        conversations=ConversationRegistry(now=lambda: 0.0, **kwargs),
        now=lambda: 0.0,
    )


async def drain(iterator):
    return [note async for note in iterator]


async def test_activity_is_yielded_before_the_answer():
    """A page that only saw the answer would have nothing to stream."""
    delta = ActivityDelta(message_id="m1", text="think")
    ask = service(FakeExecutor(notes=[delta]))

    notes = await drain(ask.ask(project_id=uuid4(), chat_id="c", question="why?"))

    assert notes[0] == delta
    assert notes[-1] == AskAnswer(text="an answer")


async def test_the_next_question_sees_the_previous_exchange():
    """'And the second one?' is the reason conversations are held at all."""
    executor = FakeExecutor(answer=AskAnswer(text="two papers"))
    ask = service(executor)
    project = uuid4()

    await drain(ask.ask(project_id=project, chat_id="c", question="what did we find?"))
    await drain(ask.ask(project_id=project, chat_id="c", question="and the second?"))

    history, question = executor.calls[1]
    assert question == "and the second?"
    assert history == (
        AskMessage(role="user", text="what did we find?"),
        AskMessage(role="assistant", text="two papers"),
    )


async def test_a_second_question_on_the_same_chat_is_refused_while_one_runs():
    """Two answers interleaving into one transcript is worse than a refusal."""
    executor = FakeExecutor()
    executor.release.clear()
    ask = service(executor)
    project = uuid4()

    first = asyncio.create_task(
        drain(ask.ask(project_id=project, chat_id="c", question="one"))
    )
    await executor.started.wait()

    with pytest.raises(AskInFlight):
        await drain(ask.ask(project_id=project, chat_id="c", question="two"))

    executor.release.set()
    await first


async def test_a_different_chat_may_ask_while_one_is_running():
    """The bound is per conversation; two tabs are not each other's problem."""
    executor = FakeExecutor()
    executor.release.clear()
    ask = service(executor)
    project = uuid4()

    first = asyncio.create_task(
        drain(ask.ask(project_id=project, chat_id="a", question="one"))
    )
    await executor.started.wait()
    executor.release.set()

    notes = await drain(ask.ask(project_id=project, chat_id="b", question="two"))

    assert notes[-1] == AskAnswer(text="an answer")
    await first


async def test_a_failed_answer_leaves_the_question_out_of_the_history():
    """Half an exchange would make the next answer reference a reply nobody saw."""
    executor = FakeExecutor(fail=RuntimeError("model fell over"))
    ask = service(executor)
    project = uuid4()

    with pytest.raises(RuntimeError):
        await drain(ask.ask(project_id=project, chat_id="c", question="one"))

    executor.fail = None
    await drain(ask.ask(project_id=project, chat_id="c", question="two"))
    history, _ = executor.calls[1]
    assert history == ()


async def test_a_failure_releases_the_chat_for_the_next_question():
    """A crash that left the slot held would need a page reload to clear."""
    executor = FakeExecutor(fail=RuntimeError("model fell over"))
    ask = service(executor)
    project = uuid4()

    with pytest.raises(RuntimeError):
        await drain(ask.ask(project_id=project, chat_id="c", question="one"))

    executor.fail = None
    notes = await drain(ask.ask(project_id=project, chat_id="c", question="two"))
    assert notes[-1] == AskAnswer(text="an answer")


async def test_citations_travel_with_the_answer():
    """The page renders them beside the reply, so they arrive together."""
    answer = AskAnswer(text="two papers", citations=(Citation(kind="source", id="s1"),))
    ask = service(FakeExecutor(answer=answer))

    notes = await drain(ask.ask(project_id=uuid4(), chat_id="c", question="why?"))

    assert notes[-1].citations == (Citation(kind="source", id="s1"),)


async def test_forgetting_a_chat_clears_its_history():
    """'New chat' has to mean the next question starts from nothing."""
    executor = FakeExecutor()
    ask = service(executor)
    project = uuid4()

    await drain(ask.ask(project_id=project, chat_id="c", question="one"))
    ask.forget("c")
    await drain(ask.ask(project_id=project, chat_id="c", question="two"))

    history, _ = executor.calls[1]
    assert history == ()
