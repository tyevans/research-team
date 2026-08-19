"""A guided dialogue over a project's gathered material.

A parallel path to `AskService`, not a caller of it: the two share a shape and
almost nothing else, and the thing that is genuinely different is the one this
module is mostly about.

**An evicted ask resumes with no history, on a fresh stream.** That is
`ConversationRegistry`'s documented behaviour and an accepted cost for an ask --
a dropped chat is a lost convenience. For a goal-directed dialogue it is a
correctness problem: a reader who comes back after lunch to a dialogue that has
forgotten its goal, its progress and its stopping condition has not resumed
anything, they have started over while believing otherwise.

So this module's registry is a cache *in front of a read model*, not the record
itself. `DialogueRegistry.get` returns `None` on a miss where
`ConversationRegistry.get` returns a fresh conversation, and the service
rehydrates from stored turns rather than minting a new stream. That one return
type is the whole difference, and `tests/application/test_socratic_resumption.py`
is what fails if it is ever copy-pasted back.

Nothing in this module may import a framework. `tests/test_architecture.py`
holds the application layer to `eventsource` alone, so everything LangChain-
shaped lives behind `SocraticExecutor` and is implemented in
`infrastructure/agent/`.

`DialogueMessage` duplicates `AskMessage` rather than importing it, and the
duplication is deliberate: a dialogue's history will want observations
interleaved into it before an ask's does, and a shared type is where that
divergence becomes a change to both surfaces. Three lines is the price.
"""

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from eventsource.application.aggregates.repository import AggregateRepository

from research_team.application.ports import ActivityNote, ActivityReporter
from research_team.domain.learner import (
    LearnerProgress,
    LearnerProgressState,
    RecordAttempt,
)
from research_team.domain.learner import initial_state as learner_initial_state
from research_team.domain.socratic_dialogue import (
    Citation,
    ConcludeSocraticDialogue,
    EvidenceKind,
    ObserveSocraticProgress,
    RecordSocraticTurn,
    SocraticDialogue,
    StartSocraticDialogue,
)

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class DialogueMessage:
    role: Role
    text: str


@dataclass(frozen=True)
class SocraticFraming:
    """What the dialogue is for, decided once from the topic.

    Produced by `SocraticExecutor.frame` and written to the stream by `begin`,
    which is what makes it survive an eviction -- a framing held only in the
    registry would be gone with it.
    """

    goal: str
    stopping_condition: str
    opening_prompt: str


@dataclass(frozen=True)
class SocraticObservation:
    observation: str
    evidence: EvidenceKind = "assessment"
    detail: str = ""


@dataclass(frozen=True)
class SocraticPrompt:
    """The dialogue's NEXT question, not a reply to anything.

    Named for what it holds -- an earlier draft called this `SocraticReply`
    with a `text` field, which put a question in a field named for the reader's
    answer and is precisely the confusion the naming ruling exists to prevent.
    """

    prompt: str
    citations: tuple[Citation, ...] = ()
    observation: SocraticObservation | None = None
    concluded: bool = False
    """The stopping condition was met by the exchange that produced this.
    `prompt` is empty when so -- there is no further question."""
    position: int = 0
    """Which exchange of this dialogue this is, zero-based -- the same number
    `SocraticTurnRow.position` stores. Counted from the rehydrated history
    *before* this turn's pair is appended, so it is the count of exchanges
    behind this one -- `len(messages) // 2`, and see `respond` for why the
    leading opening question does NOT make that `(len - 1) // 2`."""


@dataclass(frozen=True)
class SocraticDialogueOpened:
    dialogue_id: UUID
    goal: str
    stopping_condition: str
    pending_prompt: str
    """The question the reader is looking at right now: the opening one on a
    fresh dialogue, the outstanding one on a resumed dialogue. Named for what
    it is rather than `opening_prompt`, because after an eviction it is not the
    opening question and a page that labelled it so would be lying."""


SocraticNote = SocraticDialogueOpened | ActivityNote | SocraticPrompt
"""What `SocraticDialogueService.respond` yields: the framing first, then
activity as it happens, then one question last."""


class UnknownDialogue(LookupError):
    """No dialogue by that id in that project -- or one that has concluded.

    A refusal rather than a fresh start. The three cases it covers are set out
    on `SocraticDialogueService._resume`. Two of them -- a guessed id and
    another project's -- stay one exception on purpose, because a caller has
    the same move for both and telling them apart would tell a prober which
    ids exist.

    The third no longer shares that move: see `DialogueConcluded`, which is a
    subclass so this arm still catches it.
    """


class DialogueConcluded(UnknownDialogue):
    """This dialogue exists, belongs to this project, and has finished.

    A subclass, not a sibling, so every existing `except UnknownDialogue` keeps
    catching it and no call site changes behaviour silently when a dialogue
    starts being able to conclude. That is deliberate and it has a cost: a
    caller that wants the narrower case must order its `except` arms with this
    one *first*, or the broader arm swallows it and the code reads as working.
    `reply_to_dialogue` is the one caller that does, and
    `test_replying_to_a_concluded_dialogue_says_it_finished_not_that_it_is_missing`
    is what fails -- with a 404 -- if the arms are ever swapped back.

    Why it is worth the cost: a concluded dialogue is the reader's own and its
    history is still stored. Reporting it as absent says the opposite.
    """


class DialogueInFlight(RuntimeError):
    """Raised when a dialogue already has a reply running.

    One reply at a time per dialogue, for `AskInFlight`'s reason -- and here it
    would also interleave two writes to one stream.
    """


@dataclass(frozen=True)
class LiveDialogue:
    dialogue_id: UUID
    project_id: UUID
    goal: str
    stopping_condition: str
    messages: tuple[DialogueMessage, ...] = ()
    """The conversation so far, alternating assistant/user and *starting* with
    the assistant -- the opening question is `messages[0]`. The outstanding
    question is simply `messages[-1]`, so nothing here caches it."""
    used_at: float = 0.0

    def appended(self, *messages: DialogueMessage, at: float) -> "LiveDialogue":
        return replace(self, messages=(*self.messages, *messages), used_at=at)


class DialogueRegistry:
    """Live dialogues, bounded two ways -- and only a cache.

    The defaults match `ConversationRegistry`'s (64 entries, an hour idle) and
    are guesses at a single-user console rather than measurements.

    **`get` returns `None` on a miss.** That is the one line that differs from
    the neighbour this is otherwise modelled on, and it is the whole of §2 of
    the design. `ConversationRegistry.get` hands back a fresh `Conversation`
    with a fresh stream id, so an evicted ask starts over silently; here the
    caller is made to decide, and the only honest decisions are "rehydrate" and
    "refuse".
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
        self._held: OrderedDict[UUID, LiveDialogue] = OrderedDict()

    def __len__(self) -> int:
        return len(self._held)

    def __bool__(self) -> bool:
        """Always true. A registry exists or it does not; it is never absent
        for being empty.

        Without this, `__len__` makes a fresh registry falsy, and every
        `registry or DialogueRegistry(...)` default -- the obvious way to write
        an optional collaborator -- silently substitutes a private one. That is
        not hypothetical: it is what the first draft of
        `test_socratic_resumption.py`'s `build` did, and it made the eviction
        test pass against a `get` copy-pasted from `ConversationRegistry`.
        `ConversationRegistry` carries the same hazard and has not been
        changed; this is the surface where a swapped-out registry is a
        correctness bug rather than a lost chat.
        """
        return True

    def get(self, dialogue_id: UUID, project_id: UUID) -> LiveDialogue | None:
        now = self._now()
        held = self._held.get(dialogue_id)
        # A mismatched project is a miss rather than a hit on someone else's
        # dialogue. Unlike the ask's, this is not the only line of defence --
        # `_resume` checks the stored row's `project_id` too -- but a cached
        # entry never reaches that check, so dropping this clause would let a
        # cross-project turn through for exactly as long as the cache holds.
        if (
            held is None
            or held.project_id != project_id
            or now - held.used_at > self._idle_seconds
        ):
            self._held.pop(dialogue_id, None)
            return None
        self._held.move_to_end(dialogue_id)
        return held

    def put(self, dialogue: LiveDialogue) -> None:
        self._held[dialogue.dialogue_id] = dialogue
        self._held.move_to_end(dialogue.dialogue_id)
        # Least-recently-used, for `ConversationRegistry`'s reason: a bound
        # that trimmed the newest would evict the dialogue someone is in.
        while len(self._held) > self._limit:
            self._held.popitem(last=False)

    def drop(self, dialogue_id: UUID) -> None:
        self._held.pop(dialogue_id, None)


class SocraticExecutor(Protocol):
    """Frames a dialogue, and takes one turn in it.

    Two methods rather than one because they happen at different times and want
    different things: `frame` runs once, from a topic, and produces the goal and
    stopping condition that everything after it is measured against; `respond`
    runs per exchange and is handed that framing rather than deriving it.

    Keeping the framing out of `respond` is what makes the stopping condition
    testable. The agent is built fresh per turn with no checkpointer -- a
    `MemorySaver` was tried on the ask path and raised, because `astream`
    passes no `thread_id` -- so a stopping condition held in the model's context
    would not survive a turn boundary, let alone an eviction. It lives in the
    aggregate, which is the right place for it anyway: a stopping condition
    decided inside an LLM's context is one nothing can test.

    `on_activity` must not be called after `respond` returns, for the reason
    `AskExecutor` states at length -- the drain loop relies on every report
    happening-before the executor task's completion.
    """

    async def frame(self, *, project_id: UUID, topic: str) -> SocraticFraming: ...

    async def respond(
        self,
        *,
        project_id: UUID,
        history: Sequence[DialogueMessage],
        goal: str,
        stopping_condition: str,
        reply: str,
        on_activity: ActivityReporter,
    ) -> SocraticPrompt: ...


class DialogueReadModel(Protocol):
    """Where a dropped dialogue is read back from.

    Typed over `Any` deliberately: the application layer cannot name
    `SocraticDialogueRow` without importing infrastructure, and the service
    reads only `.project_id`, `.goal`, `.stopping_condition`, `.status`,
    `.opening_prompt`, `.prompt` and `.reply`. Structural typing is what lets
    `SocraticDialogueRunner` satisfy this with no adapter.
    """

    async def get(self, dialogue_id: UUID) -> Any | None: ...

    async def turns_for(self, dialogue_id: UUID) -> list[Any]: ...


class SocraticDialogueService:
    def __init__(
        self,
        *,
        executor: SocraticExecutor,
        dialogues: DialogueRegistry,
        read_model: DialogueReadModel,
        now: Callable[[], float],
        transcripts: AggregateRepository[SocraticDialogue],
        clock: Callable[[], datetime],
        progress: AggregateRepository[LearnerProgress] | None = None,
    ) -> None:
        self._executor = executor
        self._dialogues = dialogues
        # Required rather than defaulted to None, for `AskService`'s reason: a
        # surface that silently stops resuming because a call site forgot an
        # argument is the failure this codebase has shipped repeatedly. A
        # missing collaborator is a TypeError at composition time, which is the
        # earliest anyone can be told.
        self._read_model = read_model
        self._now = now
        self._transcripts = transcripts
        self._clock = clock
        # Optional, unlike `read_model`: a build without it grades and does not
        # remember, which is a degradation a reader can live with, where a build
        # without a read model resumes wrongly and cannot. Checked with
        # `is not None` at every use -- an `or` here is the shape that has
        # already cost this feature two debugging sessions, and see
        # `DialogueRegistry.__bool__` for the one that shipped.
        self._progress = progress
        self._running: set[UUID] = set()

    async def begin(self, *, project_id: UUID, topic: str) -> UUID:
        """Frame a dialogue and start its stream.

        The id is minted here, by the server, for `AskConversation`'s reason:
        an aggregate id, a row key and a URL segment cannot be a string a
        browser chose.

        The framing is written to the stream before it is cached, because the
        stream is what the resumption path reads. A `begin` that only populated
        the registry would work for an hour.
        """
        framing = await self._executor.frame(project_id=project_id, topic=topic)
        dialogue_id = uuid4()
        aggregate = self._transcripts.create_new(dialogue_id)
        aggregate.execute(
            StartSocraticDialogue(
                dialogue_id=dialogue_id,
                project_id=project_id,
                topic=topic,
                goal=framing.goal,
                stopping_condition=framing.stopping_condition,
                opening_prompt=framing.opening_prompt,
                opened_at=self._clock(),
            )
        )
        await self._transcripts.save(aggregate)
        self._dialogues.put(
            LiveDialogue(
                dialogue_id=dialogue_id,
                project_id=project_id,
                goal=framing.goal,
                stopping_condition=framing.stopping_condition,
                # Guarded exactly as `_resume` guards it, and the two must
                # agree: `SocraticDialogueStarted` permits an empty
                # `opening_prompt` (older streams predate the field), and a
                # framing may return one. Unconditional, the live path handed
                # the executor a history opening with an EMPTY assistant
                # utterance while the resumed path omitted it -- the same
                # dialogue, two different model inputs, differing only after an
                # eviction. `position` survives either way (`1//2 == 0//2`), so
                # no grading key collides and nothing raises; what changes is
                # only the model's answers, which is why Plan 2's real executor
                # is where this would have bitten and where it would have been
                # unattributable.
                messages=(
                    (DialogueMessage(role="assistant", text=framing.opening_prompt),)
                    if framing.opening_prompt
                    else ()
                ),
                used_at=self._now(),
            )
        )
        return dialogue_id

    def forget(self, dialogue_id: UUID) -> None:
        """Drop the cache entry. Not a deletion -- the next reply rehydrates.

        Which is the difference from `AskService.forget`, where forgetting is
        forgetting; here it is a way to force the read-through path and is what
        the resumption test uses to stand in for an hour passing.
        """
        self._dialogues.drop(dialogue_id)

    async def respond(
        self, *, project_id: UUID, dialogue_id: UUID, reply: str
    ) -> AsyncIterator[SocraticNote]:
        if dialogue_id in self._running:
            raise DialogueInFlight(f"dialogue {dialogue_id} already has a reply running")
        self._running.add(dialogue_id)
        try:
            dialogue = await self._resume(project_id, dialogue_id)
            # Announced before the executor is started, as `AskConversationOpened`
            # is: a reader who walks away mid-answer has still been told what
            # this dialogue is aimed at and which question is outstanding.
            yield SocraticDialogueOpened(
                dialogue_id=dialogue.dialogue_id,
                goal=dialogue.goal,
                stopping_condition=dialogue.stopping_condition,
                pending_prompt=dialogue.messages[-1].text if dialogue.messages else "",
            )
            notes: asyncio.Queue[ActivityNote] = asyncio.Queue()
            running = asyncio.create_task(
                self._executor.respond(
                    project_id=project_id,
                    history=dialogue.messages,
                    goal=dialogue.goal,
                    stopping_condition=dialogue.stopping_condition,
                    reply=reply,
                    on_activity=notes.put_nowait,
                )
            )
            try:
                async for note in self._drain(notes, running):
                    yield note
                asked = await running
            finally:
                # An abandoned reader -- an SSE client disconnecting is the
                # ordinary case -- closes this generator at whichever `yield` it
                # was parked on, and nothing else would retrieve the executor's
                # result. See `AskService.ask` for the full reasoning; the cost
                # is that a nearly-finished question is thrown away rather than
                # recorded, and there is no one left to show it to.
                if not running.done():
                    running.cancel()
                    with suppress(asyncio.CancelledError):
                        await running

            # Read before `put`, which appends this exchange's two messages, so
            # this is the count of exchanges *behind* this one. Reading after
            # would report the next turn's index and nothing in a single-turn
            # test would notice.
            #
            # `// 2` on the whole length, exactly as `AskAnswer.position` does,
            # and this was `(len - 1) // 2` for a whole commit on the reasoning
            # that a dialogue's history carries a leading opening question the
            # ask's does not. That reasoning is right and the arithmetic it
            # produced is wrong: with the opening question present the length is
            # odd and the two formulas agree, and when `_resume` finds an empty
            # `opening_prompt` -- which `SocraticDialogueStarted` permits, so
            # older streams do it -- the history is EVEN and `(len - 1) // 2`
            # undercounts by one, numbering a second turn as the first.
            # `test_each_turn_is_numbered_from_the_exchanges_behind_it` covers
            # both parities for that reason; the odd case alone cannot tell the
            # two apart, which is how the wrong one survived being reviewed.
            asked = replace(asked, position=len(dialogue.messages) // 2)
            # Recorded before the yield, for `AskService.ask`'s reason: there is
            # no suspension point between these statements for a cancellation to
            # land in, and recording afterwards would silently lose an exchange
            # the reader did see when an SSE route closes after its last frame.
            await self._record(dialogue, reply=reply, asked=asked)
            self._dialogues.put(
                dialogue.appended(
                    DialogueMessage(role="user", text=reply),
                    DialogueMessage(role="assistant", text=asked.prompt),
                    at=self._now(),
                )
            )
            yield asked
        finally:
            # Freed last, so the guard means what its docstring says: the slot
            # is held until the question has actually been handed over.
            self._running.discard(dialogue_id)

    async def progress_for(self, dialogue_id: UUID) -> LearnerProgressState:
        """What this reader has answered in this dialogue.

        Keyed on the dialogue id, which is the design's §3 in one line: a
        dialogue has a durable id, survives eviction, and means exactly "one
        reader working toward one goal" -- the thing `LearnerProgress` needs and
        an ask does not have. This answers B33 **for this surface only**; an ask
        still records nothing, and generalising this is a separate decision with
        a separate argument.
        """
        if self._progress is None:
            return learner_initial_state()
        aggregate = await self._progress.load_or_create(dialogue_id)
        return aggregate.state

    async def record_attempt(
        self,
        *,
        project_id: UUID,
        dialogue_id: UUID,
        position: int,
        component_id: str,
        component_type: str,
        digest: str,
        response: Any = None,
        correct: bool = False,
        score: float = 0.0,
        observation: str = "",
    ) -> LearnerProgressState:
        """Record one marked answer, twice.

        **Two writes, and the second is the reason this method exists rather
        than a call to `SessionService.record_attempt`.** The first is the
        ordinary progress attempt, keyed on the dialogue. The second is a
        `SocraticProgressObserved` with `evidence="attempt"` on the dialogue's
        own stream, which is what lets a stopping condition be met by something
        the reader *did* rather than by the model's opinion of what they said.
        Drop it and grading here is grading in an ask: a verdict shown and
        forgotten. `test_a_correct_answer_is_marked_and_recorded_against_the_dialogue`
        asserts both writes on stored facts and fails on either being dropped.

        `path` is `turn/{position}` because `LearnerProgress.decide` refuses an
        empty path and a dialogue has no file. The progress id is already the
        dialogue, so what `path` disambiguates is which exchange -- see
        `SocraticPrompt.position` for why that number is `len(messages) // 2`
        and what the other formula costs here specifically.

        The observation is written even for a wrong answer. A stopping condition
        fed only by correct attempts is fed by a biased sample of what the
        reader actually did.

        `project_id` is taken and not used: the dialogue id is the whole key on
        both writes, and the route has already checked the row belongs to the
        project. It is in the signature so that a later per-project scope is a
        change to this method rather than to every call site -- the cost is an
        argument a reader has to look up, which this paragraph pays.
        """
        # The dialogue's own stream FIRST, the progress attempt second, and the
        # order is deliberate rather than incidental.
        #
        # These are two aggregates and there is no transaction across them, so
        # one of the two can land alone. Which one is the survivable half is the
        # whole question. Observation-then-attempt leaves a dialogue that knows
        # the reader answered something and a progress record that never got
        # written -- the reader loses a tick and the stopping condition still
        # has its evidence. Attempt-then-observation leaves the opposite: a
        # progress row nothing points at, and a stopping condition missing the
        # one thing that was supposed to feed it, with the reader's screen
        # showing the answer marked. The second failure is invisible and
        # permanent; the first is visible and costs a tick. Swapping these two
        # statements is the "simplification" to refuse.
        #
        # `observation` defaults with `or` here and that is safe, unlike the
        # collaborator defaults elsewhere in this module: the fallback is a
        # *string*, an empty one carries no information, and there is no object
        # being silently substituted. See `DialogueRegistry.__bool__` for the
        # case where this idiom was genuinely wrong.
        observed = ObserveSocraticProgress(
            dialogue_id=dialogue_id,
            observation=observation
            or f"answered {component_id} {'correctly' if correct else 'incorrectly'}",
            evidence="attempt",
            detail=f"{component_type} {component_id} at turn {position}: "
            f"{'correct' if correct else 'incorrect'}",
        )
        aggregate = await self._transcripts.load(dialogue_id)
        aggregate.execute(observed)
        await self._transcripts.save(aggregate)

        if self._progress is None:
            return learner_initial_state()
        progress = await self._progress.load_or_create(dialogue_id)
        progress.execute(
            RecordAttempt(
                progress_id=dialogue_id,
                path=f"turn/{position}",
                component_id=component_id,
                component_type=component_type,
                digest=digest,
                response=response,
                correct=correct,
                score=score,
            )
        )
        await self._progress.save(progress)
        return progress.state

    async def end(self, *, project_id: UUID, dialogue_id: UUID) -> None:
        """Stop a dialogue because the reader said so.

        `reason="abandoned"` is the stored value and is accurate about why it
        ended, but nothing the reader sees says it: a reader who wants to stop
        should be able to, and a conversation with no way to close it is a worse
        experience than the one this plan is fixing.

        **`forget` is not tidying.** `_resume` returns a cached `LiveDialogue`
        before it reads the row, so its concluded refusal cannot see a dialogue
        still in the registry. Without this line a reader who ends a dialogue and
        types is answered -- the model call runs in full and `decide` refuses
        only at save, as a `CommandRejectedError` the reply route does not catch,
        which reaches the browser as an in-band `error` frame on a 200 stream
        after the tokens are spent.
        `test_ending_a_dialogue_drops_its_live_entry` is 200 rather than 409 with
        it removed -- measured, not reasoned.

        `load`, never `load_or_create`: an id that names nothing must die at the
        repository rather than open a stream and immediately conclude it. That is
        `_record`'s rule and it holds here for the same reason.

        `project_id` is taken and not used, exactly as `record_attempt` takes it:
        the route has already checked the row belongs to the project, and the
        argument is here so a later per-project scope is a change to this method
        rather than to every call site.
        """
        aggregate = await self._transcripts.load(dialogue_id)
        aggregate.execute(
            ConcludeSocraticDialogue(dialogue_id=dialogue_id, reason="abandoned")
        )
        await self._transcripts.save(aggregate)
        self.forget(dialogue_id)

    async def _resume(self, project_id: UUID, dialogue_id: UUID) -> LiveDialogue:
        """The live dialogue, from the cache or from the read model.

        The read-through the ask path deliberately declined. Three refusals are
        folded in here and each is a different bug if it is missed:

        * no row at all -- a guessed, stale or deleted id. Refused rather than
          started fresh: a dialogue that quietly became a new one would hand
          the reader a blank conversation under a URL they thought they knew.
        * a row belonging to another project. `RecordSocraticTurn` carries no
          project id, so `decide` has nothing to compare and this is the only
          line of defence -- exactly as `ConversationRegistry.get`'s project
          check is for an ask.
        * a concluded dialogue. `decide` would refuse the turn anyway, but only
          after the model had been called and paid for. Refused as
          `DialogueConcluded` -- a subclass, so this bullet is still one of
          three `UnknownDialogue` cases, but a caller that can say something
          more useful than "missing" is able to.

        The turns are folded back into `messages` in stored `position` order,
        which is why `SocraticTurnRow.position` is a column rather than
        insertion order: a rehydrated history in the wrong order is a
        conversation the model is asked to continue from a jumbled transcript,
        and it will do so without complaint. `turns_for` is what sorts; this
        fold trusts the order it is handed.

        **The opening question comes first and comes from the start event.** A
        turn is `(reply, prompt)` -- the reader's answer and the response it
        drew -- so folding the turns alone produces a history that begins with
        the reader answering something nobody asked. `opening_prompt` is the
        missing first utterance, and it is on the dialogue row rather than any
        turn because it precedes them all.

        The result alternates assistant/user/assistant/... and ends on the
        dialogue's newest utterance, which is exactly the question the reader
        is now answering. Nothing is read twice and nothing is inferred.
        """
        cached = self._dialogues.get(dialogue_id, project_id)
        if cached is not None:
            return cached
        row = await self._read_model.get(dialogue_id)
        if row is None or row.project_id != project_id:
            raise UnknownDialogue(f"no dialogue {dialogue_id} in project {project_id}")
        # `getattr` rather than `row.status`, because `DialogueReadModel` is a
        # structural Protocol over rows this layer cannot name: an older row
        # without the column reads as "not concluded", which is what a dialogue
        # written before conclusions existed in fact was.
        if getattr(row, "status", "started") == "concluded":
            raise DialogueConcluded(f"dialogue {dialogue_id} has already concluded")
        messages: list[DialogueMessage] = []
        if row.opening_prompt:
            messages.append(DialogueMessage(role="assistant", text=row.opening_prompt))
        for turn in await self._read_model.turns_for(dialogue_id):
            messages.append(DialogueMessage(role="user", text=turn.reply))
            messages.append(DialogueMessage(role="assistant", text=turn.prompt))
        return LiveDialogue(
            dialogue_id=dialogue_id,
            project_id=project_id,
            goal=row.goal,
            stopping_condition=row.stopping_condition,
            messages=tuple(messages),
            used_at=self._now(),
        )

    async def _record(
        self, dialogue: LiveDialogue, *, reply: str, asked: SocraticPrompt
    ) -> None:
        """Append this exchange, and anything it demonstrated.

        The exchange is `(reply, asked.prompt)`: what the reader typed, and
        what the dialogue said back. The question the reader was answering is
        already in the log -- as the previous turn's `prompt`, or as
        `opening_prompt` -- so it is not written again here. See
        `SocraticTurnRecorded` for why that pairing rather than the other one.

        Always a `load`, never a `create_new`: `begin` is the only thing that
        starts a stream, so by the time anything reaches here the stream
        exists. That is simpler than `AskService._record`, which has to infer
        the same fact from an empty message list -- and it is simpler for the
        reason this whole module exists, that a dialogue's identity outlives
        its cache entry.

        **It is also the second line of defence behind `_resume`, and that is
        not a side effect to be traded away.** Because this loads and never
        creates, an id that `_resume` fabricated or got wrong dies here at the
        repository -- `AggregateNotFoundError` -- rather than quietly opening a
        second stream and recording onto it. Adding `AskService._record`'s
        `create_new` fallback would remove exactly that protection, and it is
        the obvious edit for someone reusing the neighbour, which is why this
        paragraph exists.

        Measured on 2026-08-17, not reasoned. A throwaway sabotage returning a
        fresh `uuid4()` from `_resume` with the framing otherwise intact never
        reached any assertion: it raised here. Adding a `create_new` fallback
        alongside it did reach one, and failed it --
        `test_an_evicted_dialogue_resumes_on_the_same_stream`'s
        `assert await all_dialogue_ids(transcripts) == {dialogue_id}`, with the
        fabricated id as an extra item. That test is the one to look at if this
        paragraph is ever in doubt.
        """
        aggregate = await self._transcripts.load(dialogue.dialogue_id)
        aggregate.execute(
            RecordSocraticTurn(
                dialogue_id=dialogue.dialogue_id,
                reply=reply,
                prompt=asked.prompt,
                citations=asked.citations,
            )
        )
        if asked.observation is not None:
            aggregate.execute(
                ObserveSocraticProgress(
                    dialogue_id=dialogue.dialogue_id,
                    observation=asked.observation.observation,
                    evidence=asked.observation.evidence,
                    detail=asked.observation.detail,
                )
            )
        if asked.concluded:
            aggregate.execute(
                ConcludeSocraticDialogue(dialogue_id=dialogue.dialogue_id, reason="met")
            )
        await self._transcripts.save(aggregate)

    @staticmethod
    async def _drain(
        notes: "asyncio.Queue[ActivityNote]", running: "asyncio.Task[SocraticPrompt]"
    ) -> AsyncIterator[ActivityNote]:
        """Activity, until the executor is done owing any.

        The same loop as `AskService._drain` and it rests on the same contract:
        `SocraticExecutor.respond` must not report after it returns, so a note
        put during the call always wakes a getter scheduled before the task's
        completion callback and arrives through the branch above. See that
        method for the 216-permutation measurement behind it.
        """
        while True:
            getter = asyncio.ensure_future(notes.get())
            done, _ = await asyncio.wait(
                {getter, running}, return_when=asyncio.FIRST_COMPLETED
            )
            if getter in done:
                yield getter.result()
                continue
            getter.cancel()
            return
