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
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from eventsource.application.aggregates.repository import AggregateRepository

from research_team.curriculum.application.learner_progress import (
    LearnerProgressService,
    LearnerProgressState,
)
from research_team.curriculum.domain import LearnerProgress
from research_team.dialogue.application.socratic_models import (
    DialogueConcluded,
    DialogueInFlight,
    DialogueMessage,
    DialogueReadModel,
    DialogueRegistry,
    LiveDialogue,
    Role,
    SocraticDialogueOpened,
    SocraticExecutor,
    SocraticFraming,
    SocraticNote,
    SocraticObservation,
    SocraticPrompt,
    UnknownDialogue,
)
from research_team.dialogue.domain.socratic import (
    ConcludeSocraticDialogue,
    ObserveSocraticProgress,
    RecordSocraticTurn,
    SocraticDialogue,
    StartSocraticDialogue,
)
from research_team.platform.shared.ports import ActivityNote


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
        progress: AggregateRepository[LearnerProgress] | LearnerProgressService | None = None,
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
        # without a read model resumes wrongly and cannot.
        if isinstance(progress, LearnerProgressService):
            self._learner_progress = progress
        else:
            self._learner_progress = LearnerProgressService(progress)
        self._running: set[UUID] = set()

    @property
    def _progress(self) -> AggregateRepository[LearnerProgress] | None:
        return self._learner_progress.repository

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
                topic=topic,
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

    def is_running(self, dialogue_id: UUID) -> bool:
        """Whether a given dialogue_id currently has a reply running."""
        return dialogue_id in self._running

    @property
    def running_dialogues(self) -> frozenset[UUID]:
        """All dialogue_ids currently running a reply."""
        return frozenset(self._running)

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
                topic=dialogue.topic,
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
        return await self._learner_progress.get_progress(dialogue_id)

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

        return await self._learner_progress.record_attempt(
            dialogue_id,
            path=f"turn/{position}",
            component_id=component_id,
            component_type=component_type,
            digest=digest,
            response=response,
            correct=correct,
            score=score,
        )

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
            topic=getattr(row, "topic", ""),
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


__all__ = [
    "DialogueConcluded",
    "DialogueInFlight",
    "DialogueMessage",
    "DialogueReadModel",
    "DialogueRegistry",
    "LiveDialogue",
    "Role",
    "SocraticDialogueOpened",
    "SocraticDialogueService",
    "SocraticExecutor",
    "SocraticFraming",
    "SocraticNote",
    "SocraticObservation",
    "SocraticPrompt",
    "UnknownDialogue",
]
