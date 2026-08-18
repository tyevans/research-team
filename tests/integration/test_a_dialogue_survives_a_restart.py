"""The whole feature, over applications the composition root actually built.

Everything else about dialogues is green in a build where `composition.py`
never constructs a `SocraticDialogueRunner`: the service appends its events,
nothing is subscribed to them, and `eventsource` counts an event no projection
handles as APPLIED rather than rejected. Nothing raises, nothing logs, and
every history request answers an empty list -- and, worse than for an ask,
every resumed dialogue starts over while telling the reader it continued.

That is the failure this codebase has shipped six times, which is why every
assertion below is on a turn's *text* and a dialogue's *goal*, never on
`start()` returning or a request succeeding.

Two applications over one database file, the second standing in for the
restart, exactly as `test_ask_survives_a_restart.py` does -- a second
`build_application` over the same `tmp_path` reaches the same state, with the
first application's projection stopped and the tables re-derived or resumed by
a process that did not append the events.

**The executor is a stub, stated rather than implied.** `application.socratic`
is the composed service with the composed repository and the composed read
model behind it; only the thing that would call a model is replaced. What this
proves is that a turn appended through the composed service reaches the
composed read model and the composed resumption path -- not anything about an
agent.
"""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from research_team.application.socratic import SocraticFraming, SocraticPrompt
from research_team.composition import build_application
from research_team.interfaces.web import create_app


class StubExecutor:
    """Frames once and answers whatever it was handed, in order.

    Remembers the history and framing of its last call, which is what the
    resumption assertion reads.
    """

    def __init__(self, questions: list[str]) -> None:
        self._questions = list(questions)
        self.last: dict | None = None

    async def frame(self, *, project_id, topic):
        return SocraticFraming(
            goal=f"understand {topic}",
            stopping_condition=f"the reader explains {topic} unaided",
            opening_prompt=f"What do you make of {topic}?",
        )

    async def respond(
        self, *, project_id, history, goal, stopping_condition, reply, on_activity
    ):
        self.last = {
            "history": [(m.role, m.text) for m in history],
            "goal": goal,
            "stopping_condition": stopping_condition,
        }
        return SocraticPrompt(prompt=self._questions.pop(0))


@pytest.fixture
def db_file(tmp_path) -> str:
    return str(tmp_path / "dialogue-restart.db")


async def _application(db_file, questions):
    """A started application whose socratic executor is a stub.

    Replaced on the composed service rather than injected through
    `build_application`, which takes no such parameter -- reaching for the
    private attribute is the smaller lie than building a
    `SocraticDialogueService` by hand here, because a hand-built one would be
    exactly the thing this file is meant to prove is composed.
    """
    application = build_application(
        model=FakeMessagesListChatModel(responses=[]), db_path=db_file
    )
    await application.start()
    stub = StubExecutor(questions)
    application.socratic._executor = stub
    return application, stub


async def _project(application) -> UUID:
    api = create_app(application.service, application.feed, application.turns)
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        created = await http.post("/api/projects", json={"name": f"dlg-{uuid4()}"})
        assert created.status_code == 200
        return UUID(created.json()["id"])


async def test_a_dialogue_reaches_the_composed_read_model(db_file):
    """The assertion is on the stored text of the turn, and on the goal.

    Red against a build with no `SocraticDialogueRunner` constructed: the
    events are appended, nothing follows them, `turns_for` comes back empty,
    and this fails on the list length rather than on anything raising.
    """
    application, _stub = await _application(db_file, ["Why do you say that?"])
    try:
        project_id = await _project(application)
        dialogue_id = await application.socratic.begin(
            project_id=project_id, topic="the Nicene settlement"
        )
        async for _note in application.socratic.respond(
            project_id=project_id, dialogue_id=dialogue_id, reply="It settled Arianism."
        ):
            pass
        await application.dialogues.caught_up()

        row = await application.dialogues.get(dialogue_id)
        assert row is not None, "no row: no runner is following the log"
        assert row.goal == "understand the Nicene settlement"
        assert row.turn_count == 1
        # The dialogue's newest question, which belongs to no turn.
        assert row.pending_prompt == "Why do you say that?"

        turns = await application.dialogues.turns_for(dialogue_id)
        # A turn is the reader's reply and the question it *produced*, not the
        # question it answered -- one executor call, `reply` in and `prompt`
        # out, with the opening question living on the start event instead.
        # `domain/socratic_dialogue.py`'s module docstring sets out why, and
        # this file first asserted the other pairing and was red on it: the
        # opening question is never a turn's `prompt`, and the last turn's
        # `prompt` is always the outstanding one.
        assert [(t.reply, t.prompt) for t in turns] == [
            ("It settled Arianism.", "Why do you say that?")
        ]
        # Which is where the opening question does live, unpaired with anything.
        assert row.opening_prompt == "What do you make of the Nicene settlement?"
    finally:
        await application.close()


async def test_a_dialogue_resumes_across_a_restart_on_the_same_stream(db_file):
    """The spec's §2, over the composed pairing rather than a stub read model.

    The second application has never seen this dialogue in memory -- its
    registry is empty by construction -- so the only way the framing and the
    history can reach the executor is through the read model the first
    application's events built. Red against a composition that wires the
    service without the runner, or wires the runner and hands the service
    something else.
    """
    first, _ = await _application(db_file, ["Why do you say that?"])
    try:
        project_id = await _project(first)
        dialogue_id = await first.socratic.begin(
            project_id=project_id, topic="the Nicene settlement"
        )
        async for _note in first.socratic.respond(
            project_id=project_id, dialogue_id=dialogue_id, reply="It settled Arianism."
        ):
            pass
        await first.dialogues.caught_up()
    finally:
        await first.close()

    second, stub = await _application(db_file, ["And what follows from that?"])
    try:
        async for _note in second.socratic.respond(
            project_id=project_id,
            dialogue_id=dialogue_id,
            reply="Because the creed names the Son as of one substance.",
        ):
            pass
        await second.dialogues.caught_up()

        assert stub.last is not None
        assert stub.last["goal"] == "understand the Nicene settlement"
        assert stub.last["stopping_condition"] == (
            "the reader explains the Nicene settlement unaided"
        )
        # The dialogue speaks first, and the outstanding question is last --
        # rebuilt out of the stored `opening_prompt` and the stored turns, by a
        # process that appended none of them.
        assert stub.last["history"] == [
            ("assistant", "What do you make of the Nicene settlement?"),
            ("user", "It settled Arianism."),
            ("assistant", "Why do you say that?"),
        ]

        # One dialogue, two turns, one stream.
        row = await second.dialogues.get(dialogue_id)
        assert row.turn_count == 2
        assert row.pending_prompt == "And what follows from that?"
        assert [t.position for t in await second.dialogues.turns_for(dialogue_id)] == [0, 1]
        assert len(await second.dialogues.for_project(project_id)) == 1
    finally:
        await second.close()
