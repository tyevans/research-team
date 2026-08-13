"""Asking a project about the material it has gathered.

A parallel path to `SessionService`, not a caller of it. Sessions are
event-sourced, hold a project exclusively, and fork a filesystem when they
join one; an asking surface wants none of that, so it gets its own path and
persists nothing.

Nothing in this module may import a framework. `tests/test_architecture.py`
holds the application layer to `eventsource` alone, so the LangChain side of
this feature lives behind `AskExecutor` in `infrastructure/agent/ask_agent.py`.
"""

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import Literal, Protocol
from uuid import UUID

from research_team.application.ports import ActivityNote, ActivityReporter

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class AskMessage:
    role: Role
    text: str


@dataclass(frozen=True)
class Citation:
    """Something the agent opened while answering.

    `kind` is a one-member union rather than a bare `str`: a citation records a
    read, and `read_source` is the only tool the ask agent holds that opens one
    identified thing. `"topic"` was the second member until `open_topic` turned
    out to be a mutation and left the agent's allowlist -- a branch nothing can
    emit cannot be tested, and widening this back out is one word.
    """

    kind: Literal["source"]
    id: str


@dataclass(frozen=True)
class AskAnswer:
    text: str
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True)
class Conversation:
    chat_id: str
    project_id: UUID
    messages: tuple[AskMessage, ...] = ()
    used_at: float = 0.0

    def appended(self, *messages: AskMessage, at: float) -> "Conversation":
        return replace(self, messages=(*self.messages, *messages), used_at=at)


class ConversationRegistry:
    """Ephemeral conversations, bounded two ways.

    The defaults -- 64 conversations, an hour idle -- are guesses at the shape
    of a single-user console rather than measurements, and are cheap to change.
    Eviction is least-recently-used because a bound that trimmed the newest
    would throw away the chat someone is in the middle of.
    """

    def __init__(
        self,
        *,
        now: Callable[[], float],
        limit: int = 64,
        idle_seconds: float = 3_600.0,
    ) -> None:
        self._now = now
        self._limit = limit
        self._idle_seconds = idle_seconds
        self._held: OrderedDict[str, Conversation] = OrderedDict()

    def __len__(self) -> int:
        return len(self._held)

    def get(self, chat_id: str, project_id: UUID) -> Conversation:
        now = self._now()
        held = self._held.get(chat_id)
        # A chat id arrives from the browser, so the project it was opened
        # under is checked rather than trusted; a mismatch is treated as
        # absence, which is also what a guessed id deserves.
        if (
            held is None
            or held.project_id != project_id
            or now - held.used_at > self._idle_seconds
        ):
            self._held.pop(chat_id, None)
            return Conversation(chat_id=chat_id, project_id=project_id, used_at=now)
        self._held.move_to_end(chat_id)
        return held

    def put(self, conversation: Conversation) -> None:
        self._held[conversation.chat_id] = conversation
        self._held.move_to_end(conversation.chat_id)
        while len(self._held) > self._limit:
            self._held.popitem(last=False)

    def drop(self, chat_id: str) -> None:
        self._held.pop(chat_id, None)


class AskInFlight(RuntimeError):
    """Raised when a chat already has a question running.

    One answer at a time per conversation. Two streams interleaving into one
    transcript is a worse outcome for the reader than a refusal they can act
    on.
    """


class AskExecutor(Protocol):
    """Answers one question against a project's gathered material.

    Implemented in `infrastructure/agent/ask_agent.py`; the port exists so
    this layer never names LangChain.

    `on_activity` must not be called after `run` returns. `AskService._drain`
    relies on every report happening-before the executor task's completion to
    guarantee a final-step note still reaches the reader through its ordinary
    branch; a report from a background callback that outlives `run` would
    have no such guarantee and could be lost.
    """

    async def run(
        self,
        *,
        project_id: UUID,
        history: Sequence[AskMessage],
        question: str,
        on_activity: ActivityReporter,
    ) -> AskAnswer: ...


AskNote = ActivityNote | AskAnswer
"""What `AskService.ask` yields: activity as it happens, then one answer last."""


class AskService:
    def __init__(
        self,
        *,
        executor: AskExecutor,
        conversations: ConversationRegistry,
        now: Callable[[], float],
    ) -> None:
        self._executor = executor
        self._conversations = conversations
        self._now = now
        self._running: set[str] = set()

    def forget(self, chat_id: str) -> None:
        self._conversations.drop(chat_id)

    async def ask(
        self, *, project_id: UUID, chat_id: str, question: str
    ) -> AsyncIterator[AskNote]:
        if chat_id in self._running:
            raise AskInFlight(f"chat {chat_id} already has a question running")
        self._running.add(chat_id)
        try:
            conversation = self._conversations.get(chat_id, project_id)
            # The queue is what turns a callback-shaped reporter into an
            # iterator: the executor pushes notes from whatever task it runs
            # on, and the loop below drains them while awaiting the answer.
            notes: asyncio.Queue[ActivityNote] = asyncio.Queue()
            running = asyncio.create_task(
                self._executor.run(
                    project_id=project_id,
                    history=conversation.messages,
                    question=question,
                    on_activity=notes.put_nowait,
                )
            )
            try:
                async for note in self._drain(notes, running):
                    yield note
                answer = await running
            finally:
                # A reader that walks away -- an SSE client disconnecting is
                # the ordinary case -- closes this generator at whichever
                # `yield` it was parked on, and nothing else would ever
                # retrieve the executor's result. Left alone that is a model
                # call still burning tokens for nobody, plus a "Task exception
                # was never retrieved" warning if it fails. The cost of
                # cancelling here is that a nearly-finished answer is thrown
                # away rather than recorded; the reader has already gone, so
                # there is no one it could be shown to.
                if not running.done():
                    running.cancel()
                    with suppress(asyncio.CancelledError):
                        await running

            # Recorded only on success, and deliberately *before* the yield
            # rather than after. Moving it after was tried, to close the window
            # where a reader vanishes between the record and the delivery: that
            # window does not exist, because there is no suspension point
            # between these two statements for a cancellation to land in, and
            # by the time the generator parks on this `yield` the consumer is
            # holding the answer. Recording afterwards only changes the case
            # where a reader takes the answer and stops iterating -- an SSE
            # route closing after its last frame is exactly that -- and there
            # it silently loses an exchange the reader did see, which
            # `test_an_answer_the_reader_kept_is_remembered_even_if_it_stops_there`
            # fails on.
            self._conversations.put(
                conversation.appended(
                    AskMessage(role="user", text=question),
                    AskMessage(role="assistant", text=answer.text),
                    at=self._now(),
                )
            )
            yield answer
        finally:
            # Freed last, so the guard means what its docstring says: the slot
            # is held until the answer has actually been handed over.
            self._running.discard(chat_id)

    @staticmethod
    async def _drain(
        notes: "asyncio.Queue[ActivityNote]", running: "asyncio.Task[AskAnswer]"
    ) -> AsyncIterator[ActivityNote]:
        while True:
            getter = asyncio.ensure_future(notes.get())
            done, _ = await asyncio.wait(
                {getter, running}, return_when=asyncio.FIRST_COMPLETED
            )
            if getter in done:
                yield getter.result()
                continue
            # The executor finished with nothing left owed. This relies on
            # `AskExecutor.run`'s contract (see its docstring) that
            # `on_activity` is not called after `run` returns: every report
            # made *during* `run` has its `put_nowait` happen-before the
            # executor task's completion, so the getter it wakes is always
            # scheduled before that task's completion callback runs, and the
            # note arrives through the branch above instead. This is a
            # consequence of that ordering, not of `asyncio.wait` itself --
            # `asyncio.wait` can resume with the queue non-empty and the woken
            # getter not yet stepped, so a report made *after* `run` returns
            # would strand here. This was checked rather than reasoned -- 216
            # permutations of when the executor reports and returns, plus a
            # `call_soon` and a cross-thread reporter, and the queue was
            # empty here every time
            # (`test_a_note_queued_as_the_executor_returns_still_reaches_the_reader`
            # pins the case that matters). A drain loop lived here for that
            # reason and was removed as unreachable; if `_drain` ever grows a
            # second consumer, that assumption is what breaks first.
            getter.cancel()
            return
