"""Asking a project about the material it has gathered.

A parallel path to `SessionService`, not a caller of it. Sessions are
event-sourced, hold a project exclusively, and fork a filesystem when they
join one; an asking surface wants none of that, so it gets its own path.

It used to persist nothing, and that sentence stood here. It now appends to
an `AskConversation` stream per conversation --
`docs/superpowers/specs/2026-08-16-ask-persistence-design.md` -- which is off
the project's stream and off its feed, so the property this module was built
around still holds where it was actually wanted.

Nothing in this module may import a framework. `tests/test_architecture.py`
holds the application layer to `eventsource` alone, so the LangChain side of
this feature lives behind `AskExecutor` in `infrastructure/agent/ask_agent.py`.
"""

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID, uuid4

from eventsource.application.aggregates.repository import AggregateRepository

from research_team.application.ports import ActivityNote, ActivityReporter
from research_team.domain.ask_conversation import (
    AskConversation,
    RecordAskTurn,
    StartAskConversation,
)

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
class AskConversationOpened:
    """The stream this ask is being recorded on, told to whoever asked.

    The id is minted server-side (see `Conversation.conversation_id`) and
    nothing else would ever return it: the registry is keyed by the browser's
    `chat_id`, and a client that only ever saw its own string could read a
    stored conversation back only by guessing. Persisting an ask that no
    client can name again is half a feature.

    Yielded **first**, before any activity, rather than carried on the answer:
    a conversation whose second turn fails still has a first turn on disk, and
    a reader who walked away mid-answer still has the link. The cost is that a
    client can be handed an id for a stream with nothing on it yet -- a failed
    first turn appends nothing -- so the id is a name for a conversation, not
    a promise that a row exists.

    Echoing it back to resume a conversation is the frontend's work and is not
    built here: `AskService.ask` takes no conversation id, and a browser that
    wants to continue one gets what it gets from the registry today.
    """

    conversation_id: UUID


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
    #: The stream this conversation is recorded on. Minted here, by the
    #: server, and deliberately *not* `chat_id`: that string arrives from the
    #: browser, and while a checked key into a bounded in-memory dict can be
    #: whatever the caller says, an aggregate id, a row key and a URL segment
    #: cannot -- the identical hazard as letting a model pick an id, which
    #: this codebase has already ruled against once.
    #:
    #: A fresh `Conversation` therefore gets a fresh stream. That is what
    #: eviction means now: a chat the registry dropped resumes with no
    #: history and records onto a new stream, exactly as it lost its history
    #: before. Making eviction re-read the old stream is the read-through
    #: cache the spec declined; the registry stays a cache in front.
    conversation_id: UUID = field(default_factory=uuid4)

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
        #
        # **This check now decides which stream a turn is appended to, not
        # just which cache entry is returned.** `RecordAskTurn` carries no
        # `project_id`, so `AskConversation.decide` has nothing to compare and
        # cannot refuse a turn recorded onto another project's conversation --
        # there is no second line of defence behind this one. Absence is kept
        # as the answer rather than a refusal because it is what happens today
        # and the caller has an obvious next move: the mismatched chat starts
        # a fresh conversation on a fresh stream, and the other project's
        # stream is untouched.
        # `test_a_chat_id_reused_under_another_project_starts_its_own_stream`
        # fails if this clause goes -- checked by deleting it, and B's
        # question landed on A's stream.
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


AskNote = AskConversationOpened | ActivityNote | AskAnswer
"""What `AskService.ask` yields: the conversation id first, then activity as
it happens, then one answer last."""


class AskService:
    def __init__(
        self,
        *,
        executor: AskExecutor,
        conversations: ConversationRegistry,
        now: Callable[[], float],
        transcripts: AggregateRepository[AskConversation],
    ) -> None:
        self._executor = executor
        self._conversations = conversations
        self._now = now
        # Required rather than defaulted to None: an ask that silently stops
        # persisting because a call site forgot an argument is the failure
        # this codebase has shipped six times -- a component built, green, and
        # connected to nothing. A missing repository is a TypeError at
        # composition, which is the earliest anyone can be told.
        self._transcripts = transcripts
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
            # Announced before anything else happens, including before the
            # executor is started -- see `AskConversationOpened`. A reader who
            # walks away during the answer has still been told where to find
            # the turns that were already recorded.
            yield AskConversationOpened(conversation_id=conversation.conversation_id)
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
            # The append shares that window and that reasoning: it is the same
            # statement, promoted from "the only record" to "the durable one".
            # A failure here fails the ask, and that is the cost the spec takes
            # explicitly -- the in-memory registry could not fail this way.
            # Swallowing it would mean a reader shown an answer the history
            # pane will never list, which is worse than an error they can
            # retry.
            await self._record(conversation, question=question, answer=answer)
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

    async def _record(
        self, conversation: Conversation, *, question: str, answer: AskAnswer
    ) -> None:
        """Append this exchange to the conversation's own stream.

        Whether to start the stream is decided from the registry's copy rather
        than by loading and inspecting the aggregate: an empty `messages` is
        exactly "no turn has been recorded under this id", because the id is
        minted with the `Conversation` and dies with it. Loading first would
        cost a replay per turn to learn something the caller already holds,
        and `decide` refuses a double start anyway if that ever stops being
        true.
        """
        if conversation.messages:
            aggregate = await self._transcripts.load(conversation.conversation_id)
        else:
            aggregate = self._transcripts.create_new(conversation.conversation_id)
            aggregate.execute(
                StartAskConversation(
                    conversation_id=conversation.conversation_id,
                    project_id=conversation.project_id,
                    opened_at=datetime.now(UTC),
                )
            )
        aggregate.execute(
            RecordAskTurn(
                conversation_id=conversation.conversation_id,
                question=question,
                answer=answer.text,
                citations=tuple((c.kind, c.id) for c in answer.citations),
            )
        )
        await self._transcripts.save(aggregate)

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
