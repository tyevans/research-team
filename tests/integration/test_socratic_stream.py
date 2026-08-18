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
from eventsource import StreamId, collect
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from research_team.application.ports import ActivityRemark
from research_team.application.socratic import SocraticFraming, SocraticPrompt
from research_team.composition import build_application
from research_team.domain.socratic_dialogue import (
    SocraticDialogue,
    SocraticDialogueConcluded,
)
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
        # Public, because a test that needs a *particular* next prompt (a
        # concluding one, say) reassigns it after the fixture has built the
        # stub: `stub.prompts = [...]`.
        self.prompts = (
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
        return self.prompts.pop(0)


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
        dialogues=application.dialogues,
        socratic=application.socratic,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, application, stub
    await application.close()


async def _events(application, dialogue_id):
    # Four lines repeated from `test_a_dialogue_concludes.py` rather than
    # imported: a shared helper across integration modules would be a
    # dependency carrying one `collect` call.
    stream = StreamId(dialogue_id, SocraticDialogue.aggregate_type)
    return [
        envelope.event
        for envelope in await collect(
            application.socratic._transcripts.event_store.read_stream(stream)
        )
    ]


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
    # Blocks rather than a raw string, on both frames: `pending_prompt` is
    # written from the newest turn's prompt, so on a resumed dialogue it is a
    # component-bearing question and a raw copy shipped its answer key beside
    # the projection that withheld it. Measured by
    # `test_the_answer_key_never_reaches_the_reader`, not reasoned.
    assert frames[0]["pending_blocks"] == [
        {"kind": "markdown", "text": "Where would you start?"}
    ]
    assert frames[-1]["type"] == "prompt"
    assert frames[-1]["blocks"] == [{"kind": "markdown", "text": "Why do you say that?"}]
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
            dialogues=application.dialogues,
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
    """The other half of the split this file's concluded-dialogue test makes,
    so that split cannot be implemented by turning every refusal into a 409. A
    guessed id must stay indistinguishable from another project's: confirming
    that an id a caller cannot use does exist tells a prober which ids exist.
    A concluded dialogue is the case where that reasoning stops applying, and
    it is the only one that moved.

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
    special-case.

    The precondition is established by an `Event` the executor sets on entry,
    never by a sleep. A sleep here is CLAUDE.md's B4 shape exactly: under load
    the first request may not have reached the executor yet, the second gets a
    200, and the test fails against correct code while looking like flakiness.
    Waiting on `entered` is the same claim made deterministically -- the first
    reply is provably in flight before the second is sent.
    """
    import asyncio

    http, application, _stub = client
    project_id = await _project(http)
    started = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})
    dialogue_id = started.json()["dialogueId"]

    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowExecutor(StubExecutor):
        async def respond(self, **kwargs):
            entered.set()
            await release.wait()
            return SocraticPrompt(prompt="Why?")

    application.socratic._executor = SlowExecutor()
    first = asyncio.create_task(
        http.post(
            f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply",
            json={"reply": "one"},
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=5)
    second = await http.post(
        f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply", json={"reply": "two"}
    )
    release.set()
    await first

    assert second.status_code == 409, second.text


async def test_a_framing_the_model_botched_is_a_502_and_not_a_400(client):
    """502 and not 400, and this test is the only thing keeping it that way.

    `parse_framing` refuses rather than defaulting -- an empty stopping
    condition is a dialogue that can never stop -- and it refuses with a
    `ValueError`. The route has to turn that into an upstream failure, because
    the request was fine: the reader typed a topic and there is nothing they
    could have typed differently. 400 looks right to anyone reading only the
    `except` clause who does not know where the framing came from, which is why
    the status is asserted here rather than left to the comment.

    Red against `status_code=400`, and against no `except ValueError` at all
    (a 500 from the unhandled raise).
    """
    http, application, _stub = client
    project_id = await _project(http)

    class BotchedFraming(StubExecutor):
        async def frame(self, *, project_id, topic):
            raise ValueError("no stopping condition in the model's reply")

    application.socratic._executor = BotchedFraming()
    response = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})

    assert response.status_code == 502, response.text
    # The reason travels: a reader told only "502" cannot tell an unreachable
    # model from one that answered in the wrong shape.
    assert "no stopping condition" in response.json()["detail"]


async def test_a_remark_reaches_the_page_with_its_text(client):
    """An `ActivityRemark` carries text and no `message_id`, and an earlier
    draft of `_socratic_frame` emitted an empty payload for it -- which renders
    as an empty assistant bubble and loses the only thing the note is.

    Red against that draft: the frame was present and `payload` was `{}`.
    """
    http, application, _stub = client
    project_id = await _project(http)
    started = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})
    dialogue_id = started.json()["dialogueId"]

    class RemarkingExecutor(StubExecutor):
        async def respond(self, *, on_activity, **kwargs):
            on_activity(ActivityRemark(text="two documents were left out"))
            return SocraticPrompt(prompt="Why?")

    application.socratic._executor = RemarkingExecutor()
    response = await http.post(
        f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply", json={"reply": "hi"}
    )

    remarks = [
        frame
        for frame in _frames(response.text)
        if frame["type"] == "message" and frame["kind"] == "remark"
    ]
    assert remarks, "the remark was dropped or drawn as something else"
    assert remarks[0]["payload"]["text"] == "two documents were left out"


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


async def test_replying_to_a_concluded_dialogue_says_it_finished_not_that_it_is_missing(
    client,
):
    """A defect this feature *creates*, fixed in the slice that creates it.

    `_resume` raised `UnknownDialogue` for a concluded dialogue and the route
    turned that into 404 "no dialogue ... in project". That branch could not
    fire before this plan -- nothing could conclude -- so the wrong status was
    free.

    It is not free now. A reader who finishes a dialogue, refreshes, and types
    is told it does not exist, when it exists and it finished. 404 and 409 are
    a character apart in a log and say opposite things about whether the
    reader's own history is still there.

    409 rather than 410: the dialogue is not gone, it is in a state that
    refuses this request -- the same status `post_dialogue_attempt` already
    answers for an attempt against a concluded dialogue, so the page has one
    rule for both.

    `forget` drops the cache entry so the second reply takes the read-through
    path, which is where the refusal lives; without it the cached
    `LiveDialogue` is returned and the concluded row is never read. Measured
    red against the route before `DialogueConcluded` existed: 404, not 409.
    """
    http, application, stub = client
    project_id = await _project(http)
    started = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})
    dialogue_id = started.json()["dialogueId"]
    stub.prompts = [SocraticPrompt(prompt="", concluded=True)]
    await http.post(
        f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply", json={"reply": "done"}
    )
    application.socratic.forget(UUID(dialogue_id))
    await application.dialogues.caught_up()

    response = await http.post(
        f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply", json={"reply": "more?"}
    )

    assert response.status_code == 409, response.text
    assert "concluded" in response.json()["detail"]


async def test_a_reader_can_end_a_dialogue_and_the_reason_says_who_ended_it(client):
    """The other half of `ConclusionReason`, which nothing produced.

    Asserted on the stored event and not on the 200: `end` is one command, and a
    route that swallowed it would answer 200 with nothing written -- the exact
    shape CLAUDE.md's "Events" section describes, where an event no projection
    handles counts as APPLIED and silence is not refusal.

    `reason == "abandoned"` and not `"met"`, because a dialogue the reader
    stopped is not one the reader finished, and a stopping condition that could
    be satisfied by giving up would be worth nothing.
    """
    http, application, _stub = client
    project_id = await _project(http)
    started = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})
    dialogue_id = started.json()["dialogueId"]

    ended = await http.post(f"/api/projects/{project_id}/dialogues/{dialogue_id}/end")

    assert ended.status_code == 200, ended.text
    events = await _events(application, UUID(dialogue_id))
    assert type(events[-1]) is SocraticDialogueConcluded
    assert events[-1].reason == "abandoned"

    # And the projection, read back over HTTP, because the event alone proves
    # only that something was written. An event no projection handles counts as
    # APPLIED, so a `concluded_reason` column nothing filled would look identical
    # from the stream. This is also what B120's missing read port would recover
    # `endedByReader` from after a refresh -- the reason is already served, and
    # the gap is that no console port fetches one dialogue whole.
    await application.dialogues.caught_up()
    view = await http.get(f"/api/projects/{project_id}/dialogues/{dialogue_id}")
    assert view.status_code == 200, view.text
    assert view.json()["status"] == "concluded"
    assert view.json()["concludedReason"] == "abandoned"


async def test_ending_a_dialogue_drops_its_live_entry(client):
    """**The line this task exists around.**

    `_resume` returns a cached `LiveDialogue` BEFORE it reads the row, so its
    concluded refusal cannot see a dialogue still in the registry -- the
    `cached is not None` early return sits above the `status == "concluded"`
    check. A reader who ends a dialogue and then types would be answered: the
    whole model call runs, and `decide` refuses only at save, as a
    `CommandRejectedError` that `reply_to_dialogue` does not catch. That reaches
    the browser as an in-band `error` frame on a 200 stream, after the tokens
    are spent.

    So `end` calls `forget`, and this test is what fails if that line is removed
    as redundant. Red against an `end` that writes the event and leaves the
    cache: the status below is 200, not 409.
    """
    http, application, _stub = client
    project_id = await _project(http)
    started = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})
    dialogue_id = started.json()["dialogueId"]
    await http.post(f"/api/projects/{project_id}/dialogues/{dialogue_id}/end")
    await application.dialogues.caught_up()

    response = await http.post(
        f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply", json={"reply": "more?"}
    )

    assert response.status_code == 409, response.text
    assert "concluded" in response.json()["detail"]


async def test_ending_a_dialogue_twice_is_refused_rather_than_written_twice(client):
    """`decide` refuses every command against a concluded dialogue, so a second
    `end` is a `CommandRejectedError`. Caught as 409 rather than left to become a
    500 -- a double-clicked button is not a server fault -- and asserted on the
    event count too, because a route that answered 409 while appending a second
    `SocraticDialogueConcluded` would look identical from the status alone.
    """
    http, application, _stub = client
    project_id = await _project(http)
    started = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})
    dialogue_id = started.json()["dialogueId"]
    await http.post(f"/api/projects/{project_id}/dialogues/{dialogue_id}/end")

    again = await http.post(f"/api/projects/{project_id}/dialogues/{dialogue_id}/end")

    assert again.status_code == 409, again.text
    events = await _events(application, UUID(dialogue_id))
    assert [type(e) for e in events].count(SocraticDialogueConcluded) == 1


async def test_ending_a_dialogue_in_another_project_is_a_404(client):
    """The project check is the route's, not the command's:
    `ConcludeSocraticDialogue` carries no project id, so `decide` has nothing to
    compare -- the same gap `_resume`'s second refusal exists for. Without this
    check a guessed id ends someone else's dialogue and answers 200.
    """
    http, _application, _stub = client
    project_id = await _project(http)
    other = await _project(http)
    started = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})
    dialogue_id = started.json()["dialogueId"]

    response = await http.post(f"/api/projects/{other}/dialogues/{dialogue_id}/end")

    assert response.status_code == 404, response.text
