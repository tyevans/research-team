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
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from eventsource.application.aggregates.repository import AggregateRepository

from research_team.dialogue.domain.ask import (
    AskConversation,
    RecordAskTurn,
    StartAskConversation,
)
from research_team.platform.shared.ports import ActivityNote, ActivityReporter
from research_team.platform.shared.registry_cache import ExpiringLruCache

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class AskMessage:
    role: Role
    text: str


@dataclass(frozen=True)
class Citation:
    """Something the agent opened while answering.

    `kind` names either a corpus source or an opened topic (B52).
    """

    kind: Literal["source", "topic"]
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
    #: Which turn of this conversation this answer is, zero-based -- the same
    #: number `AskTurnRow.position` stores, and the half of the grading key the
    #: browser cannot derive. Taken from the registry's message count rather
    #: than by loading the aggregate: two messages are appended per turn, and
    #: the count is read *before* this turn's pair is added.
    position: int = 0


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
        self._cache: ExpiringLruCache[str, Conversation] = ExpiringLruCache(
            now=now,
            limit=limit,
            idle_seconds=idle_seconds,
            get_used_at=lambda c: c.used_at,
            get_project_id=lambda c: c.project_id,
        )
        self._held: OrderedDict[str, Conversation] = self._cache._held

    def __len__(self) -> int:
        return len(self._cache)

    def __bool__(self) -> bool:
        """Always true. A registry exists or it does not; it is never absent
        for being empty.
        """
        return True

    def __contains__(self, chat_id: str) -> bool:
        return chat_id in self._cache

    def contains(self, chat_id: str, project_id: UUID | None = None) -> bool:
        """Check whether a chat is currently active in memory and unexpired."""
        return self._cache.contains(chat_id, project_id)

    def get(self, chat_id: str, project_id: UUID) -> Conversation:
        now = self._now()
        held = self._cache.get(chat_id, project_id, now=now)
        # A chat id arrives from the browser, so the project it was opened
        # under is checked rather than trusted; a mismatch is treated as
        # absence, which is also what a guessed id deserves.
        if held is None:
            return Conversation(chat_id=chat_id, project_id=project_id, used_at=now)
        return held

    def get_by_conversation_id(
        self, conversation_id: UUID, project_id: UUID
    ) -> Conversation | None:
        """Find a cached conversation by its server-minted conversation_id."""
        now = self._now()
        for chat_id, conv in list(self._held.items()):
            if conv.conversation_id == conversation_id:
                if conv.project_id != project_id or (now - conv.used_at) > self._idle_seconds:
                    self._cache.drop(chat_id)
                    return None
                self._cache.get(chat_id, project_id)
                return conv
        return None

    def put(self, conversation: Conversation) -> None:
        self._cache.put(conversation.chat_id, conversation)

    def drop(self, chat_id: str) -> None:
        self._cache.drop(chat_id)

    def clear(self) -> None:
        """Evict all cached conversations."""
        self._cache.clear()

    def evict_idle(self, now: float | None = None) -> int:
        """Explicitly prune all conversations that exceeded idle_seconds."""
        return self._cache.evict_idle(now)

    def active_chat_ids(self, project_id: UUID | None = None) -> list[str]:
        """List active, non-expired chat IDs currently held in cache."""
        return self._cache.active_keys(project_id)


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


class AskReadModel(Protocol):
    """Where an evicted or existing ask conversation can be read back from.

    Typed over `Any` structurally, following `DialogueReadModel`.
    """

    async def get(self, conversation_id: UUID) -> Any | None: ...

    async def turns_for(self, conversation_id: UUID) -> list[Any]: ...


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
        read_model: AskReadModel | None = None,
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
        self._read_model = read_model
        self._running: set[str] = set()

    def forget(self, chat_id: str) -> None:
        self._conversations.drop(chat_id)

    def is_running(self, chat_id: str) -> bool:
        """Whether a given chat_id currently has a question running."""
        return chat_id in self._running

    @property
    def running_chats(self) -> frozenset[str]:
        """All chat_ids currently running a question."""
        return frozenset(self._running)

    async def resume(
        self,
        *,
        project_id: UUID,
        conversation_id: UUID,
        chat_id: str | None = None,
    ) -> Conversation:
        """Resume an existing conversation from cache or read model."""
        target_chat_id = chat_id or str(conversation_id)
        cached = self._conversations.get_by_conversation_id(conversation_id, project_id)
        if cached is not None:
            return cached
        if self._read_model is None:
            raise LookupError(
                f"cannot resume ask conversation {conversation_id}: no read model configured"
            )
        row = await self._read_model.get(conversation_id)
        if row is None or row.project_id != project_id:
            raise LookupError(f"no conversation {conversation_id} in project {project_id}")
        turns = await self._read_model.turns_for(conversation_id)
        messages: list[AskMessage] = []
        for turn in turns:
            messages.append(AskMessage(role="user", text=turn.question))
            messages.append(AskMessage(role="assistant", text=turn.answer))
        conversation = Conversation(
            chat_id=target_chat_id,
            project_id=project_id,
            conversation_id=conversation_id,
            messages=tuple(messages),
            used_at=self._now(),
        )
        self._conversations.put(conversation)
        return conversation

    async def ask(
        self,
        *,
        project_id: UUID,
        chat_id: str,
        question: str,
        conversation_id: UUID | None = None,
    ) -> AsyncIterator[AskNote]:
        if not question or not question.strip():
            raise ValueError("question must not be empty")
        if chat_id in self._running:
            raise AskInFlight(f"chat {chat_id} already has a question running")
        self._running.add(chat_id)
        try:
            if conversation_id is not None:
                try:
                    conversation = await self.resume(
                        project_id=project_id,
                        conversation_id=conversation_id,
                        chat_id=chat_id,
                    )
                except LookupError:
                    conversation = self._conversations.get(chat_id, project_id)
            else:
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
            # Read before `put`, which appends this turn's two messages: the
            # position of *this* answer is the count of completed turns behind
            # it. Reading after would report the next turn's index and nothing
            # in a single-turn test would notice.
            answer = replace(answer, position=len(conversation.messages) // 2)
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
