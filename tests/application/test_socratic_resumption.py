"""The one requirement whose absence looks exactly like working software.

`ConversationRegistry` is 64 entries and an hour idle, and a `Conversation`
mints a fresh `conversation_id` per registry entry -- so an evicted ask resumes
with no history on a new stream. For an ask that is an accepted cost. For a
goal-directed dialogue it is a correctness bug: a reader who comes back after
lunch to a dialogue that has forgotten its goal has not resumed anything, they
have started over while believing otherwise.

Every assertion here is on what the executor was *handed* and on which stream
the events landed on. "The call returned" is compatible with a service that
silently began a second dialogue, which is precisely the failure.

**Every name from `research_team.application.socratic` is imported inside the
function that uses it, and every test here is `xfail(strict=True)`.** The
module does not exist until Task 3, and a module-level import of it is a
*collection* error -- which interrupts the entire pytest run, so a suite that
cannot be collected is a suite in which no other failure can be read. The
deferred import keeps the file collectable; the strict xfail is what keeps it
honestly red rather than quietly excused.

**Task 3 removes the markers; it does not touch the assertions.** `strict=True`
means the suite goes RED on an unexpected *pass*, so the moment the service
works these tests fail as XPASS and whoever wrote it has to delete the markers
deliberately. That is the whole point of this shape -- a plain `xfail` or a
`skip` would let a working feature sit behind a permanently-excused test that
nobody looks at again.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from eventsource import StreamId, collect
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.testing import InMemoryTestHarness

from research_team.domain.socratic_dialogue import (
    SocraticDialogue,
    SocraticDialogueStarted,
    SocraticTurnRecorded,
)

PROJECT_ID = uuid4()

UNTIL_TASK_3 = (
    "research_team.application.socratic does not exist until Task 3. "
    "strict=True so this goes red on an unexpected PASS -- Task 3 deletes the "
    "marker deliberately rather than leaving a permanently-excused test."
)
"""One constant, four markers, so Task 3's deletion is one edit rather than
four. Four copies is three chances to leave one behind, and a marker left
behind on a working test is precisely what `strict=True` exists to prevent."""


class RecordingExecutor:
    """Asks fixed questions and remembers exactly what it was asked with.

    The list it is constructed with is a list of the *next questions* it will
    ask, because under this surface's naming the executor's output is a prompt
    -- the system asks, the reader answers. See the ruling in the plan.

    The history it received is the assertion: a service that resumed by
    starting over would call this with an empty history and a fresh goal, and
    every other observable -- the question it then asks, the returned id, the
    status code a route would give -- would be identical.
    """

    def __init__(self, questions: list[str]) -> None:
        self._questions = list(questions)
        self.calls: list[dict] = []

    async def frame(self, *, project_id, topic):
        from research_team.application.socratic import SocraticFraming

        self.calls.append({"kind": "frame", "topic": topic})
        return SocraticFraming(
            goal=f"understand {topic}",
            stopping_condition=f"the reader explains {topic} in their own words",
            opening_prompt=f"What do you already believe about {topic}?",
        )

    async def respond(
        self, *, project_id, history, goal, stopping_condition, reply, on_activity
    ):
        from research_team.application.socratic import SocraticPrompt

        self.calls.append(
            {
                "kind": "respond",
                "history": [(m.role, m.text) for m in history],
                "goal": goal,
                "stopping_condition": stopping_condition,
                "reply": reply,
            }
        )
        return SocraticPrompt(prompt=self._questions.pop(0))


class StubReadModel:
    """The read model the service rehydrates from, without a projection.

    Hand-held rows rather than a started `SocraticDialogueRunner`: this file is
    about the service's resumption logic, and standing up a real projection
    here would make it fail for reasons that belong in
    `tests/infrastructure/test_socratic_read_model.py`. The *composed* pairing
    is proved in `tests/integration/test_a_dialogue_survives_a_restart.py`,
    which is the file that would catch a runner nobody constructed.

    `SimpleNamespace` and not a dict, deliberately: `DialogueReadModel` is a
    structural Protocol satisfied by `SocraticDialogueRow`, so `_resume` reads
    `row.goal` and `turn.reply` as *attributes*. A dict fixture would fail on
    `AttributeError` and read as a bug in the service rather than in the test.
    """

    def __init__(self) -> None:
        self.dialogues: dict[UUID, SimpleNamespace] = {}
        self.turns: dict[UUID, list[SimpleNamespace]] = {}

    def add(self, dialogue_id: UUID, **fields) -> None:
        self.dialogues[dialogue_id] = SimpleNamespace(**fields)

    def answered(self, dialogue_id: UUID, *pairs: tuple[str, str]) -> None:
        """`(reply, prompt)` per turn -- the reader's answer and the response
        it drew, which is the order `SocraticTurnRecorded` stores them in."""
        self.turns[dialogue_id] = [
            SimpleNamespace(position=index, reply=reply, prompt=prompt)
            for index, (reply, prompt) in enumerate(pairs)
        ]

    async def get(self, dialogue_id: UUID):
        return self.dialogues.get(dialogue_id)

    async def turns_for(self, dialogue_id: UUID):
        return list(self.turns.get(dialogue_id, []))


@pytest.fixture
def transcripts() -> AggregateRepository[SocraticDialogue]:
    return AggregateRepository(InMemoryTestHarness().event_store, SocraticDialogue)


def build(executor, transcripts, read_model, registry=None):
    from research_team.application.socratic import (
        DialogueRegistry,
        SocraticDialogueService,
    )

    return SocraticDialogueService(
        executor=executor,
        dialogues=registry or DialogueRegistry(now=lambda: 0.0),
        read_model=read_model,
        now=lambda: 0.0,
        transcripts=transcripts,
        clock=lambda: datetime(2026, 8, 17, tzinfo=UTC),
    )


async def drain(iterator):
    return [note async for note in iterator]


async def events_on(transcripts, dialogue_id: UUID):
    stream = StreamId(dialogue_id, SocraticDialogue.aggregate_type)
    return [
        envelope.event
        for envelope in await collect(transcripts.event_store.read_stream(stream))
    ]


async def all_dialogue_ids(transcripts) -> set[UUID]:
    """Every dialogue id anything was written under.

    `read_category`, matching `test_ask_persistence.py`'s `all_events`. The
    point of several assertions below is that there is exactly ONE id, which
    reading a single known stream could never establish -- the id under
    suspicion in the failure case is the one no test knows.
    """
    return {
        envelope.event.aggregate_id
        for envelope in await collect(
            transcripts.event_store.read_category(SocraticDialogue.aggregate_type)
        )
    }


@pytest.mark.xfail(strict=True, reason=UNTIL_TASK_3)
async def test_an_evicted_dialogue_resumes_on_the_same_stream(transcripts):
    """The whole feature, in one test.

    Red three distinct ways, and only the first is obvious:

    1. A `DialogueRegistry.get` that mints a fresh entry on a miss, the way
       `ConversationRegistry.get` does -- a second dialogue id appears and
       `all_dialogue_ids` comes back with two.
    2. A rehydrate that restores history but not the framing -- `goal` and
       `stopping_condition` arrive as empty strings and the executor is asked
       to continue toward nothing.
    3. A rehydrate that restores the framing but not the turns -- the executor
       is handed an empty history and asks its opening question again, which
       reads to a reader as the dialogue having forgotten the conversation
       while still knowing the topic.
    4. A rehydrate that restores the turns but drops the *opening* question --
       the history then starts with the reader answering something nobody
       asked. The opening question lives on the start event rather than on any
       turn (see `SocraticTurnRecorded`), so it is the one utterance a
       turns-only rehydrate silently loses.

    Each of those looks like working software until an hour has passed.
    """
    from research_team.application.socratic import DialogueRegistry

    executor = RecordingExecutor(["Why do you think that?", "And what follows from it?"])
    read_model = StubReadModel()
    registry = DialogueRegistry(now=lambda: 0.0)
    service = build(executor, transcripts, read_model, registry)

    dialogue_id = await service.begin(project_id=PROJECT_ID, topic="the Nicene settlement")
    await drain(
        service.respond(
            project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="It settled Arianism."
        )
    )

    # Stand in for the projection having caught up, which in a composed build
    # is what makes the stored turns readable. Hand-fed here so this file tests
    # the service and not the subscription.
    read_model.add(
        dialogue_id,
        project_id=PROJECT_ID,
        goal="understand the Nicene settlement",
        stopping_condition="the reader explains the Nicene settlement in their own words",
        status="started",
        # The opening question, which lives on the start event because it
        # precedes every turn -- and is therefore the one utterance a
        # turns-only rehydrate would lose.
        opening_prompt="What do you already believe about the Nicene settlement?",
    )
    read_model.answered(dialogue_id, ("It settled Arianism.", "Why do you think that?"))

    # An hour passes, or 65 other dialogues happen. Same thing.
    registry.drop(dialogue_id)

    await drain(
        service.respond(
            project_id=PROJECT_ID,
            dialogue_id=dialogue_id,
            reply="Because the creed names the Son as of one substance.",
        )
    )

    resumed = executor.calls[-1]
    assert resumed["kind"] == "respond"
    # The goal and the stopping condition survived the eviction.
    assert resumed["goal"] == "understand the Nicene settlement"
    assert (
        resumed["stopping_condition"]
        == "the reader explains the Nicene settlement in their own words"
    )
    # And so did the exchange, in order -- the dialogue speaking first, because
    # that is the direction this surface runs in. The opening question comes
    # from the start event and every pair after it from a turn, which is what
    # makes the history alternate correctly with nothing stored twice.
    assert resumed["history"] == [
        ("assistant", "What do you already believe about the Nicene settlement?"),
        ("user", "It settled Arianism."),
        ("assistant", "Why do you think that?"),
    ]

    # The same stream, and only that stream. This is the assertion a service
    # that started over would fail while every other observable agreed.
    assert await all_dialogue_ids(transcripts) == {dialogue_id}
    recorded = await events_on(transcripts, dialogue_id)
    assert [type(event) for event in recorded] == [
        SocraticDialogueStarted,
        SocraticTurnRecorded,
        SocraticTurnRecorded,
    ]
    # The exchange: what the reader answered, and what the dialogue said back.
    # Two fields, not three -- the question this answered is the *previous*
    # turn's `prompt`, already in the log once.
    assert recorded[2].reply == "Because the creed names the Son as of one substance."
    assert recorded[2].prompt == "And what follows from it?"


@pytest.mark.xfail(strict=True, reason=UNTIL_TASK_3)
async def test_a_dialogue_still_in_the_registry_is_not_re_read(transcripts):
    """The registry is still a cache, and must still be one.

    Rehydrating on every turn would be correct and would cost a read-model
    round trip per exchange -- and worse, would make the cache untested, since
    every test would pass with it removed. Red against a service that reads
    through unconditionally.
    """
    executor = RecordingExecutor(["Why?", "And?"])
    read_model = StubReadModel()
    service = build(executor, transcripts, read_model)

    dialogue_id = await service.begin(project_id=PROJECT_ID, topic="Arianism")
    await drain(service.respond(project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="first"))
    await drain(
        service.respond(project_id=PROJECT_ID, dialogue_id=dialogue_id, reply="second")
    )

    # The read model was never consulted: the stub holds nothing, so a service
    # that read through it would have found no dialogue at all.
    assert read_model.dialogues == {}
    assert executor.calls[-1]["history"] == [
        ("assistant", "What do you already believe about Arianism?"),
        ("user", "first"),
        ("assistant", "Why?"),
    ]


@pytest.mark.xfail(strict=True, reason=UNTIL_TASK_3)
async def test_a_dialogue_that_was_never_stored_is_refused_rather_than_invented(
    transcripts,
):
    """A miss in both the registry and the read model.

    Refused, and not started fresh. A guessed or stale id that quietly became a
    new dialogue would hand the reader a blank conversation under a URL they
    thought they knew -- and would write to a stream nobody asked for. Red
    against a service that falls back to `begin`.
    """
    from research_team.application.socratic import UnknownDialogue

    executor = RecordingExecutor([])
    service = build(executor, transcripts, StubReadModel())

    with pytest.raises(UnknownDialogue):
        await drain(
            service.respond(project_id=PROJECT_ID, dialogue_id=uuid4(), reply="hello?")
        )

    assert await all_dialogue_ids(transcripts) == set()


@pytest.mark.xfail(strict=True, reason=UNTIL_TASK_3)
async def test_a_dialogue_is_not_resumable_from_another_project(transcripts):
    """The aggregate carries `project_id` and that is the boundary (spec §7).

    `RecordSocraticTurn` carries no project id, so `decide` has nothing to
    compare -- this check is the only line of defence, exactly as
    `ConversationRegistry.get`'s project check is for an ask. Refused rather
    than treated as absence, unlike the ask: an ask's chat id is a browser
    string and a mismatch is ordinary, where a dialogue id is a server-minted
    UUID and a mismatch is either a bug or a probe.
    """
    from research_team.application.socratic import UnknownDialogue

    executor = RecordingExecutor(["Why?"])
    read_model = StubReadModel()
    service = build(executor, transcripts, read_model)

    dialogue_id = await service.begin(project_id=PROJECT_ID, topic="Arianism")
    read_model.add(
        dialogue_id,
        project_id=PROJECT_ID,
        goal="g",
        stopping_condition="s",
        status="started",
        opening_prompt="p",
    )
    read_model.answered(dialogue_id)

    with pytest.raises(UnknownDialogue):
        await drain(
            service.respond(project_id=uuid4(), dialogue_id=dialogue_id, reply="hello?")
        )
