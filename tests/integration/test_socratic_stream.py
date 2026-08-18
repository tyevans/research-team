"""The two POST routes, over a composed application with a stubbed executor.

The executor is stubbed and the model is fake: what is under test is the route
and the frames, not judgement. Every assertion about persistence reads a row --
a 200 with a well-formed stream is compatible with nothing having been written,
because an event no projection handles counts as applied.

No fixture here opens a project: `_project` creates one over HTTP per test, so
every request in this file is the first thing to touch that project. That is
CLAUDE.md's fixture trap taken seriously -- a fixture that seeded through the
same call the route depends on could not see that call go missing.
"""

import json
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from research_team.application.socratic import SocraticFraming, SocraticPrompt
from research_team.composition import build_application
from research_team.interfaces.web import create_app

MCQ = (
    "Try this one:\n\n"
    "```component:mcq\n"
    "id: council-1\n"
    "prompt: Which council?\n"
    "options:\n"
    '  - text: "Nicaea"\n'
    "    correct: true\n"
    '  - text: "Chalcedon"\n'
    "    correct: false\n"
    "```\n"
)


class StubExecutor:
    """Frames once, then asks whatever it was handed, in order."""

    def __init__(self, prompts=None) -> None:
        # `is not None`, never `or`: an empty list is a legitimate argument and
        # `or` would silently substitute the default. Plan 1 was bitten by this
        # twice, once fatally -- see `DialogueRegistry.__bool__`.
        self._prompts = (
            list(prompts) if prompts is not None else [SocraticPrompt(prompt="Why?")]
        )
        self.calls: list[dict] = []

    async def frame(self, *, project_id, topic):
        return SocraticFraming(
            goal=f"understand {topic}",
            stopping_condition="the reader explains it unaided",
            opening_prompt="Where would you start?",
        )

    async def respond(
        self, *, project_id, history, goal, stopping_condition, reply, on_activity
    ):
        self.calls.append({"reply": reply, "goal": goal, "history": len(history)})
        return self._prompts.pop(0)


@pytest.fixture
async def client(tmp_path):
    application = build_application(
        model=FakeMessagesListChatModel(responses=[]),
        db_path=str(tmp_path / "stream.db"),
    )
    await application.start()
    stub = StubExecutor([SocraticPrompt(prompt="Why do you say that?", position=0)])
    application.socratic._executor = stub
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        socratic=application.socratic,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, application, stub
    await application.close()


async def _project(http) -> UUID:
    created = await http.post("/api/projects", json={"name": f"dlg-{uuid4()}"})
    assert created.status_code == 200
    return UUID(created.json()["id"])


def _frames(body: str) -> list[dict]:
    return [
        json.loads(line[len("data: ") :])
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


async def test_starting_a_dialogue_returns_its_id_and_writes_its_framing(client):
    """The id is the server's and is the only way back to this dialogue, so it
    has to be in the response body -- there is no registry key a browser could
    reconstruct it from.

    The row assertion is the one that matters: a 200 carrying an id is
    compatible with nothing having been written.
    """
    http, application, _stub = client
    project_id = await _project(http)

    response = await http.post(
        f"/api/projects/{project_id}/dialogues", json={"topic": "the Nicene settlement"}
    )

    assert response.status_code == 200, response.text
    dialogue_id = UUID(response.json()["dialogueId"])
    await application.dialogues.caught_up()

    row = await application.dialogues.get(dialogue_id)
    assert row is not None, "no row: the projection is not following the log"
    assert row.goal == "understand the Nicene settlement"
    assert row.opening_prompt == "Where would you start?"


async def test_a_reply_streams_the_framing_first_and_the_question_last(client):
    """Frame order is the contract Plan 3 renders against. The framing frame
    comes first so a page can show what the dialogue is for -- and which
    question is outstanding -- before the model has produced anything.
    """
    http, application, _stub = client
    project_id = await _project(http)
    started = await http.post(
        f"/api/projects/{project_id}/dialogues", json={"topic": "the Nicene settlement"}
    )
    dialogue_id = started.json()["dialogueId"]

    response = await http.post(
        f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply",
        json={"reply": "It settled Arianism."},
    )

    assert response.status_code == 200, response.text
    frames = _frames(response.text)
    assert frames[0]["type"] == "dialogue"
    assert frames[0]["dialogue_id"] == dialogue_id
    assert frames[0]["goal"] == "understand the Nicene settlement"
    assert frames[0]["stopping_condition"] == "the reader explains it unaided"
    # The question the reader was answering, not the one about to be asked.
    assert frames[0]["pending_prompt"] == "Where would you start?"
    assert frames[-1]["type"] == "prompt"
    assert frames[-1]["text"] == "Why do you say that?"
    assert frames[-1]["position"] == 0
    assert frames[-1]["concluded"] is False

    await application.dialogues.caught_up()
    turns = await application.dialogues.turns_for(UUID(dialogue_id))
    assert [(t.reply, t.prompt) for t in turns] == [
        ("It settled Arianism.", "Why do you say that?")
    ]


async def test_the_last_frame_is_typed_prompt_and_not_answer(client):
    """Plan 3 must not reuse the ask's `answer` handler for this frame: the
    last thing a dialogue turn produces is a question, and a page that rendered
    it as an answer would draw the dialogue's question in the reader's own
    column. Red against a `_socratic_frame` copy-pasted from `_ask_frame`.
    """
    http, _application, _stub = client
    project_id = await _project(http)
    started = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})
    dialogue_id = started.json()["dialogueId"]

    response = await http.post(
        f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply", json={"reply": "hello"}
    )

    assert {frame["type"] for frame in _frames(response.text)} == {"dialogue", "prompt"}


async def test_a_component_in_a_question_arrives_parsed_and_withheld(tmp_path):
    """Parsed on the server for `components.py`'s four reasons, of which the
    second binds: withholding is only real if the projection happens before the
    bytes leave. Red against a frame that ships `text` alone and lets the
    browser parse -- the key travels either way, and the blocks are what the
    page renders.
    """
    application = build_application(
        model=FakeMessagesListChatModel(responses=[]), db_path=str(tmp_path / "cmp.db")
    )
    await application.start()
    try:
        application.socratic._executor = StubExecutor([SocraticPrompt(prompt=MCQ)])
        api = create_app(
            application.service,
            application.feed,
            application.turns,
            socratic=application.socratic,
        )
        transport = ASGITransport(app=api)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            project_id = await _project(http)
            started = await http.post(
                f"/api/projects/{project_id}/dialogues", json={"topic": "t"}
            )
            dialogue_id = started.json()["dialogueId"]
            response = await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply",
                json={"reply": "Nicaea, I think"},
            )

        last = _frames(response.text)[-1]
        kinds = [block["kind"] for block in last["blocks"]]
        assert kinds == ["markdown", "component"]
        component = last["blocks"][1]
        assert component["type"] == "mcq"
        assert component["withheld"], "the answer key reached the browser"
        assert "correct" not in json.dumps(component["data"])
    finally:
        await application.close()


async def test_a_dialogue_that_does_not_exist_is_a_404_not_a_new_one(client):
    """`UnknownDialogue` covers a guessed id, a stale one and a concluded one,
    and all three are 404 -- telling a caller that an id they cannot use does
    exist is the distinction not worth drawing.

    404 and not a stream carrying an error frame: this is raised by `_resume`
    before any note is yielded, so it can still be a status code, which is the
    same split `ask_project` makes for `AskInFlight`.
    """
    http, _application, _stub = client
    project_id = await _project(http)

    response = await http.post(
        f"/api/projects/{project_id}/dialogues/{uuid4()}/reply", json={"reply": "hello?"}
    )

    assert response.status_code == 404, response.text


async def test_a_second_reply_while_one_is_running_is_a_409(client):
    """`DialogueInFlight`, raised before streaming begins, so it can be a
    status code the page can act on rather than an error frame it has to
    special-case."""
    import asyncio

    http, application, _stub = client
    project_id = await _project(http)
    started = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})
    dialogue_id = started.json()["dialogueId"]

    release = asyncio.Event()

    class SlowExecutor(StubExecutor):
        async def respond(self, **kwargs):
            await release.wait()
            return SocraticPrompt(prompt="Why?")

    application.socratic._executor = SlowExecutor()
    first = asyncio.create_task(
        http.post(
            f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply",
            json={"reply": "one"},
        )
    )
    await asyncio.sleep(0.05)
    second = await http.post(
        f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply", json={"reply": "two"}
    )
    release.set()
    await first

    assert second.status_code == 409, second.text


async def test_an_unconfigured_build_says_so_rather_than_answering(tmp_path):
    """503 when the service is unwired, matching `ask_project`. A build with no
    `socratic=` is not a build with no dialogues -- it is one that cannot hold
    them, and the two must not look alike."""
    application = build_application(
        model=FakeMessagesListChatModel(responses=[]), db_path=str(tmp_path / "bare.db")
    )
    await application.start()
    try:
        api = create_app(application.service, application.feed, application.turns)
        transport = ASGITransport(app=api)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            project_id = await _project(http)
            response = await http.post(
                f"/api/projects/{project_id}/dialogues", json={"topic": "t"}
            )
            assert response.status_code == 503, response.text
    finally:
        await application.close()
