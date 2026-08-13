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


class LateNoteExecutor:
    """Reports its note only once the drain loop is already parked.

    The ordinary `FakeExecutor` cannot reach the drain loop's re-yield branch:
    its release event is pre-set, so it runs to completion before the pending
    `notes.get()` is ever polled and the note arrives by the ordinary path.
    Here the note is queued in the same step as the return, exercising the
    tightest gap between the two: the `put_nowait` and the `return` happen in
    the same step of `run`, so the note still reaches the reader through the
    ordinary branch -- the woken getter is scheduled to run before the
    executor task's completion is observed by `asyncio.wait`.
    """

    def __init__(self) -> None:
        self.note = ActivityDelta(message_id="m1", text="a last thought")
        self.parked = asyncio.Event()

    async def run(self, *, project_id, history, question, on_activity: ActivityReporter):
        await self.parked.wait()
        on_activity(self.note)
        return AskAnswer(text="an answer")


async def test_a_note_queued_as_the_executor_returns_still_reaches_the_reader():
    """The last thing an agent says is usually the one worth reading.

    Pins that an executor which reports in its final step -- queuing its last
    note in the same step it returns -- still delivers that note to the
    reader, through the ordinary drain-loop branch rather than any special
    handling: `put_nowait` wakes the pending `notes.get()` before the
    executor task's own done-callback can run, so the woken getter always
    gets its turn first.
    """
    executor = LateNoteExecutor()
    ask = service(executor)
    iterator = ask.ask(project_id=uuid4(), chat_id="c", question="why?")

    pending = asyncio.create_task(anext(iterator))
    # Let the drain loop reach its `await`, so the getter is genuinely parked
    # on an empty queue before anything is put into it.
    for _ in range(5):
        await asyncio.sleep(0)
    executor.parked.set()

    first = await asyncio.wait_for(pending, timeout=2.0)
    rest = await asyncio.wait_for(drain(iterator), timeout=2.0)

    assert first == executor.note
    assert rest == [AskAnswer(text="an answer")]


class AbandonedExecutor:
    """Reports one note, then parks forever unless someone cancels it.

    A second call answers at once, so the same executor can show that
    abandonment left the service usable rather than wedged.
    """

    def __init__(self) -> None:
        self.note = ActivityDelta(message_id="m1", text="think")
        self.cancelled = False
        self.calls: list[tuple[Sequence[AskMessage], str]] = []

    async def run(self, *, project_id, history, question, on_activity: ActivityReporter):
        self.calls.append((tuple(history), question))
        if len(self.calls) > 1:
            return AskAnswer(text="an answer")
        on_activity(self.note)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("the executor was never cancelled")  # pragma: no cover


async def test_abandoning_the_stream_cancels_the_executor_and_records_nothing():
    """A closed SSE connection must not leave a model call running for nobody.

    Three claims, all of which fail against the pre-fix code: the executor
    task is cancelled rather than orphaned; the exchange is not written to the
    history, because the reader never received the reply; and the chat slot is
    free for the next question.
    """
    executor = AbandonedExecutor()
    ask = service(executor)
    project = uuid4()

    iterator = ask.ask(project_id=project, chat_id="c", question="one")
    assert await asyncio.wait_for(anext(iterator), timeout=2.0) == executor.note
    await asyncio.wait_for(iterator.aclose(), timeout=2.0)

    assert executor.cancelled

    notes = await asyncio.wait_for(
        drain(ask.ask(project_id=project, chat_id="c", question="two")), timeout=2.0
    )
    assert notes[-1] == AskAnswer(text="an answer")
    history, _ = executor.calls[1]
    assert history == ()


async def test_an_answer_the_reader_kept_is_remembered_even_if_it_stops_there():
    """A route that closes its stream after the last frame still had the answer.

    This is why the exchange is recorded before the final yield rather than
    after: a reader holding the answer has been served, whether or not it ever
    asks the generator for another item. Recording afterwards passes every
    other test in this file and loses this one.
    """
    executor = FakeExecutor(answer=AskAnswer(text="two papers"))
    ask = service(executor)
    project = uuid4()

    iterator = ask.ask(project_id=project, chat_id="c", question="one")
    answer = None
    async for note in iterator:
        if isinstance(note, AskAnswer):
            answer = note
            break
    await iterator.aclose()

    assert answer == AskAnswer(text="two papers")
    await drain(ask.ask(project_id=project, chat_id="c", question="two"))
    history, _ = executor.calls[1]
    assert history == (
        AskMessage(role="user", text="one"),
        AskMessage(role="assistant", text="two papers"),
    )


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
    """Two answers interleaving into one transcript is worse than a refusal.

    The refusal is pinned to the *first* `__anext__`, not merely to somewhere
    in the stream: the route turns it into a 409 before any body is written,
    which it cannot do if notes have already gone out.

    Every wait here is bounded because a broken guard does not fail this test,
    it hangs it -- the second question would block on the un-released executor
    and CI would time out with nothing to read. Two seconds is far longer than
    anything this test does (no I/O, no sleeps) and short enough to report.
    """
    executor = FakeExecutor()
    executor.release.clear()
    ask = service(executor)
    project = uuid4()

    first = asyncio.create_task(
        drain(ask.ask(project_id=project, chat_id="c", question="one"))
    )
    await asyncio.wait_for(executor.started.wait(), timeout=2.0)

    second = ask.ask(project_id=project, chat_id="c", question="two")
    with pytest.raises(AskInFlight):
        await asyncio.wait_for(anext(second), timeout=2.0)

    executor.release.set()
    await asyncio.wait_for(first, timeout=2.0)


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
