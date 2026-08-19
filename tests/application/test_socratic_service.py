"""What the service does around the executor, other than resume.

Resumption is in `test_socratic_resumption.py`, alone, because it is the
requirement the spec says to write first and a file named for it is harder to
delete by accident than four assertions among twenty.

Every assertion about persistence reads the stream. "The call returned" is
compatible with nothing having been written -- an event no projection handles
counts as applied, so there is no layer below this that would have complained.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from eventsource import StreamId, collect
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.testing import InMemoryTestHarness

from research_team.application.socratic import (
    DialogueConcluded,
    DialogueInFlight,
    DialogueRegistry,
    LiveDialogue,
    SocraticDialogueOpened,
    SocraticDialogueService,
    SocraticFraming,
    SocraticObservation,
    SocraticPrompt,
)
from research_team.domain.socratic_dialogue import (
    SocraticDialogue,
    SocraticDialogueConcluded,
    SocraticDialogueStarted,
    SocraticProgressObserved,
    SocraticTurnRecorded,
    StartSocraticDialogue,
)

PROJECT_ID = uuid4()


class StubExecutor:
    def __init__(self, questions=None, fail=None):
        self._questions = list(questions or [SocraticPrompt(prompt="why?")])
        self.fail = fail

    async def frame(self, *, project_id, topic):
        return SocraticFraming(
            goal="understand it",
            stopping_condition="the reader states it plainly",
            opening_prompt="what do you think?",
        )

    async def respond(
        self, *, project_id, history, goal, stopping_condition, reply, on_activity
    ):
        if self.fail is not None:
            raise self.fail
        return self._questions.pop(0)


class EmptyReadModel:
    async def get(self, dialogue_id):
        return None

    async def turns_for(self, dialogue_id):
        return []


class StoredReadModel:
    """One hand-held row, for the paths that need a registry miss to land
    somewhere. `SimpleNamespace` for `test_socratic_resumption.py`'s reason:
    `DialogueReadModel` is structural, so `_resume` reads attributes."""

    def __init__(self, dialogue_id, *, turns=(), **fields):
        self._rows = {dialogue_id: SimpleNamespace(**fields)}
        self._turns = [
            SimpleNamespace(position=index, reply=reply, prompt=prompt)
            for index, (reply, prompt) in enumerate(turns)
        ]

    async def get(self, dialogue_id):
        return self._rows.get(dialogue_id)

    async def turns_for(self, dialogue_id):
        return list(self._turns) if dialogue_id in self._rows else []


@pytest.fixture
def transcripts():
    return AggregateRepository(InMemoryTestHarness().event_store, SocraticDialogue)


def build(executor, transcripts, read_model=None):
    return SocraticDialogueService(
        executor=executor,
        dialogues=DialogueRegistry(now=lambda: 0.0),
        # `is not None`, never `or`. A falsy collaborator silently substitutes
        # the default and the test then exercises an object the code under test
        # never saw -- which is not hypothetical here: the same `or` in
        # `test_socratic_resumption.py`'s `build` made the eviction test pass
        # against a broken registry, because `DialogueRegistry` defines
        # `__len__` and an empty one is falsy. No read model defines `__len__`
        # today; that was true of the registry too, right up until it wasn't.
        read_model=read_model if read_model is not None else EmptyReadModel(),
        now=lambda: 0.0,
        transcripts=transcripts,
        clock=lambda: datetime(2026, 8, 17, tzinfo=UTC),
    )


async def drain(iterator):
    return [note async for note in iterator]


async def events_on(transcripts, dialogue_id):
    stream = StreamId(dialogue_id, SocraticDialogue.aggregate_type)
    return [
        envelope.event
        for envelope in await collect(transcripts.event_store.read_stream(stream))
    ]


async def test_beginning_a_dialogue_writes_the_framing_the_model_chose(transcripts):
    """The goal and the stopping condition are set once, at the start, by the
    model -- and are then the reader's to see (spec §5). This asserts they
    reach the stream, which is the only place the resumption path can find
    them again. Red against a service that holds the framing in the registry
    and never records it.
    """
    service = build(StubExecutor(), transcripts)

    dialogue_id = await service.begin(project_id=PROJECT_ID, topic="the creed")

    recorded = await events_on(transcripts, dialogue_id)
    assert [type(e) for e in recorded] == [SocraticDialogueStarted]
    assert recorded[0].project_id == PROJECT_ID
    assert recorded[0].topic == "the creed"
    assert recorded[0].goal == "understand it"
    assert recorded[0].stopping_condition == "the reader states it plainly"
    assert recorded[0].opening_prompt == "what do you think?"


async def test_the_first_note_names_the_dialogue_and_what_it_is_for(transcripts):
    """`SocraticDialogueOpened` carries the framing as well as the id, so the
    page can show the reader what this dialogue is aiming at before they have
    typed anything. A reader who disagrees with the goal should be able to see
    that they disagree before spending twenty minutes on it (spec §5).
    """
    service = build(StubExecutor(), transcripts)
    dialogue_id = await service.begin(project_id=PROJECT_ID, topic="the creed")

    notes = await drain(
        service.respond(project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="hello")
    )

    assert isinstance(notes[0], SocraticDialogueOpened)
    assert notes[0].dialogue_id == dialogue_id
    assert notes[0].goal == "understand it"
    assert notes[0].stopping_condition == "the reader states it plainly"
    # The question the reader is answering, which on a fresh dialogue is the
    # opening one. On a resumed dialogue it is whatever was outstanding, which
    # is why the field is not called `opening_prompt`.
    assert notes[0].pending_prompt == "what do you think?"


async def test_a_failed_turn_records_nothing(transcripts):
    """`SocraticTurnRecorded` is a fact about an exchange that happened, not an
    attempt that was made -- the same rule `AskTurnRecorded` follows. Red
    against a service that appends before awaiting the executor.
    """
    service = build(StubExecutor(fail=RuntimeError("the model is down")), transcripts)
    dialogue_id = await service.begin(project_id=PROJECT_ID, topic="the creed")

    with pytest.raises(RuntimeError, match="model is down"):
        await drain(
            service.respond(project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="hello")
        )

    assert [type(e) for e in await events_on(transcripts, dialogue_id)] == [
        SocraticDialogueStarted
    ]


async def test_an_observation_the_executor_reported_is_recorded_beside_the_turn(
    transcripts,
):
    """Two events from one exchange, in that order: the turn happened, and then
    something was demonstrated in it. Red against a service that folds the
    observation into the turn event, which would make progress unreadable
    without re-parsing every reply.
    """
    service = build(
        StubExecutor(
            [
                SocraticPrompt(
                    prompt="what makes you say that?",
                    observation=SocraticObservation(
                        observation="named both parties",
                        evidence="assessment",
                    ),
                )
            ]
        ),
        transcripts,
    )
    dialogue_id = await service.begin(project_id=PROJECT_ID, topic="the creed")

    await drain(
        service.respond(
            project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="Arius and Athanasius"
        )
    )

    assert [type(e) for e in await events_on(transcripts, dialogue_id)] == [
        SocraticDialogueStarted,
        SocraticTurnRecorded,
        SocraticProgressObserved,
    ]


async def test_a_reply_that_concludes_the_dialogue_ends_it_as_met(transcripts):
    """The stopping condition, actually stopping something. Red against a
    service that carries `concluded` to the browser and never writes it: the
    dialogue would look finished and would accept a further turn on reload.
    """
    service = build(
        StubExecutor([SocraticPrompt(prompt="", concluded=True)]),
        transcripts,
    )
    dialogue_id = await service.begin(project_id=PROJECT_ID, topic="the creed")

    await drain(
        service.respond(project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="one substance")
    )

    recorded = await events_on(transcripts, dialogue_id)
    assert [type(e) for e in recorded] == [
        SocraticDialogueStarted,
        SocraticTurnRecorded,
        SocraticDialogueConcluded,
    ]
    assert recorded[2].reason == "met"


async def test_two_replies_at_once_on_one_dialogue_are_refused(transcripts):
    """One reply at a time per dialogue, for `AskInFlight`'s reason: two
    streams interleaving into one transcript is worse for the reader than a
    refusal they can act on -- and here it would also interleave two writes to
    one stream.
    """
    import asyncio

    started = asyncio.Event()
    release = asyncio.Event()

    class SlowExecutor(StubExecutor):
        async def respond(self, **kwargs):
            started.set()
            await release.wait()
            return SocraticPrompt(prompt="why?")

    service = build(SlowExecutor(), transcripts)
    dialogue_id = await service.begin(project_id=PROJECT_ID, topic="the creed")

    first = asyncio.create_task(
        drain(service.respond(project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="a"))
    )
    await started.wait()
    with pytest.raises(DialogueInFlight):
        await drain(service.respond(project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="b"))
    release.set()
    await first


async def test_a_concluded_dialogue_is_refused_before_the_model_is_called(
    transcripts,
):
    """The third of `_resume`'s refusals, and the only one whose cost is money
    rather than correctness.

    `decide` refuses a turn against a concluded dialogue anyway -- so the
    dialogue is safe either way, and that is why this is not the resumption
    file's business. What `decide` cannot do is refuse it *before* the executor
    has been paid for. The executor here raises if it is called at all, so the
    exception type is the assertion: `DialogueConcluded` means the refusal
    happened at the read model, and `RuntimeError` would mean the model ran
    first and the aggregate cleaned up after.

    The narrower type, not its `UnknownDialogue` base, and that is the whole
    point of the split: the base would pass just as well against a `_resume`
    that had lost the concluded branch and was failing to find the row at all,
    which is the same refusal for the wrong reason.

    Red against a `_resume` with the `status == "concluded"` branch deleted --
    checked by deleting it, and this raised RuntimeError.
    """
    dialogue_id = uuid4()
    service = build(
        StubExecutor(fail=RuntimeError("the model was called")),
        transcripts,
        StoredReadModel(
            dialogue_id,
            project_id=PROJECT_ID,
            goal="understand it",
            stopping_condition="the reader states it plainly",
            status="concluded",
            opening_prompt="what do you think?",
        ),
    )

    with pytest.raises(DialogueConcluded):
        await drain(
            service.respond(
                project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="one more thing"
            )
        )


async def test_each_turn_is_numbered_from_the_exchanges_behind_it(transcripts):
    """`position` is the grading key's half the browser cannot derive, and both
    parities of the history have to number correctly.

    The formula is `len(messages) // 2`, the same as `AskAnswer.position`. It
    was written here as `(len(messages) - 1) // 2` for a whole commit, on the
    reasoning that a dialogue's history opens with a question nobody has
    answered where an ask's is pairs. **That reasoning is right and the
    arithmetic it produced is wrong**, which is why this test asserts two
    dialogues rather than two turns of one:

    * with the opening question present the history is ODD before every turn,
      and the two formulas agree exactly. A multi-turn test on this path passes
      under both and proves nothing -- the first draft of this test was exactly
      that.
    * `SocraticDialogueStarted.opening_prompt` may be empty (it is defaulted for
      schema evolution), so a resumed dialogue can have an EVEN history. There
      `(len - 1) // 2` undercounts by one and numbers the second exchange as the
      first, which would collide with the first turn's grading key.

    Red against `(len - 1) // 2` on the second half only. The first half is red
    against reading the count *after* `put`.
    """
    service = build(
        StubExecutor([SocraticPrompt(prompt="why?"), SocraticPrompt(prompt="and?")]),
        transcripts,
    )
    dialogue_id = await service.begin(project_id=PROJECT_ID, topic="the creed")

    first = await drain(
        service.respond(project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="a")
    )
    second = await drain(
        service.respond(project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="b")
    )

    assert isinstance(first[-1], SocraticPrompt)
    assert first[-1].position == 0
    assert second[-1].position == 1

    # A dialogue resumed from a row whose opening question was never recorded:
    # one stored exchange, so a two-message history, so this turn is the second
    # and must be numbered 1.
    older = uuid4()
    resumed = build(
        StubExecutor([SocraticPrompt(prompt="go on?")]),
        transcripts,
        StoredReadModel(
            older,
            project_id=PROJECT_ID,
            goal="understand it",
            stopping_condition="the reader states it plainly",
            status="started",
            opening_prompt="",
            turns=[("a", "why?")],
        ),
    )
    # The stream has to exist for `_record`'s load, and `begin` is the only
    # thing that starts one -- so this row stands for a dialogue whose events
    # predate `opening_prompt`, which is what the empty string means.
    aggregate = transcripts.create_new(older)
    aggregate.execute(
        StartSocraticDialogue(
            dialogue_id=older,
            project_id=PROJECT_ID,
            topic="the creed",
            goal="understand it",
            stopping_condition="the reader states it plainly",
            opening_prompt="",
            opened_at=datetime(2026, 8, 17, tzinfo=UTC),
        )
    )
    await transcripts.save(aggregate)

    notes = await drain(resumed.respond(project_id=PROJECT_ID, dialogue_id=older, reply="b"))
    assert notes[-1].position == 1


def test_the_registry_returns_nothing_on_a_miss_rather_than_a_fresh_dialogue():
    """The one line that differs from `ConversationRegistry`, tested on its own.

    `ConversationRegistry.get` returns a brand-new `Conversation` on a miss,
    which is why an evicted ask silently starts over on a new stream. Returning
    `None` here is what forces the caller to decide, and there is nowhere for
    that decision to be made silently.

    Red against a copy-paste of `ConversationRegistry.get`, which is exactly
    how this would be written by someone reusing the neighbour.
    """
    registry = DialogueRegistry(now=lambda: 0.0)
    dialogue_id = uuid4()

    assert registry.get(dialogue_id, PROJECT_ID) is None

    registry.put(
        LiveDialogue(
            dialogue_id=dialogue_id,
            project_id=PROJECT_ID,
            goal="g",
            stopping_condition="s",
        )
    )
    assert registry.get(dialogue_id, PROJECT_ID) is not None
    # Another project's id is a miss, not a hit on someone else's dialogue.
    assert registry.get(dialogue_id, uuid4()) is None

    registry.drop(dialogue_id)
    assert registry.get(dialogue_id, PROJECT_ID) is None


def test_an_idle_dialogue_is_evicted_and_a_busy_one_is_not():
    """The bound that makes resumption necessary in the first place. A clock
    the test drives, so this does not sleep."""
    clock = {"t": 0.0}
    registry = DialogueRegistry(now=lambda: clock["t"], idle_seconds=10.0)
    dialogue_id = uuid4()
    registry.put(
        LiveDialogue(
            dialogue_id=dialogue_id,
            project_id=PROJECT_ID,
            goal="g",
            stopping_condition="s",
            used_at=0.0,
        )
    )

    clock["t"] = 9.0
    assert registry.get(dialogue_id, PROJECT_ID) is not None
    clock["t"] = 11.0
    assert registry.get(dialogue_id, PROJECT_ID) is None
