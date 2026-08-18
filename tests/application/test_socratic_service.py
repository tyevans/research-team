"""What the service does around the executor, other than resume.

Resumption is in `test_socratic_resumption.py`, alone, because it is the
requirement the spec says to write first and a file named for it is harder to
delete by accident than four assertions among twenty.

Every assertion about persistence reads the stream. "The call returned" is
compatible with nothing having been written -- an event no projection handles
counts as applied, so there is no layer below this that would have complained.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eventsource import StreamId, collect
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.testing import InMemoryTestHarness

from research_team.application.socratic import (
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


@pytest.fixture
def transcripts():
    return AggregateRepository(InMemoryTestHarness().event_store, SocraticDialogue)


def build(executor, transcripts, read_model=None):
    return SocraticDialogueService(
        executor=executor,
        dialogues=DialogueRegistry(now=lambda: 0.0),
        read_model=read_model or EmptyReadModel(),
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
