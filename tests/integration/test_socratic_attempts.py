"""Marking an answer inside a dialogue, and what it leaves behind.

Two writes per attempt and both are asserted on stored facts, never on the 200:
a `LearnerProgress` attempt keyed on the DIALOGUE id (design §3), and a
`SocraticProgressObserved` with `evidence="attempt"` on the dialogue's own
stream. Without the second, grading in a dialogue is grading in an ask -- a
verdict shown and forgotten -- and the design's whole argument for answering
B33 here is that a marked answer is evidence toward the stopping condition.

Every test here builds its project through the HTTP route rather than through a
fixture that has already opened it, so no test in this file can be blind to a
collaborator the request path stops calling. That is CLAUDE.md's fixture trap,
and it is why `_project` posts rather than seeding.
"""

import json
from uuid import UUID, uuid4

import pytest
from eventsource import StreamId, collect
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from research_team.application.socratic import SocraticFraming, SocraticPrompt
from research_team.composition import build_application
from research_team.domain.socratic_dialogue import (
    SocraticDialogue,
    SocraticProgressObserved,
)
from research_team.interfaces.web import create_app

MCQ = (
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
    """Framing and questioning without a model.

    Substituted for `DeepAgentSocraticExecutor` because these tests are about
    what an attempt writes, not about what a model says. `opening` is a
    constructor argument for one reason only: it is what sets the parity of the
    rehydrated history, and the parity is what the grading key is derived from.
    """

    def __init__(self, prompts=None, opening="Where would you start?") -> None:
        self._prompts = list(prompts) if prompts is not None else [SocraticPrompt(prompt=MCQ)]
        self._opening = opening

    async def frame(self, *, project_id, topic):
        return SocraticFraming(
            goal=f"understand {topic}",
            stopping_condition="the reader explains it unaided",
            opening_prompt=self._opening,
        )

    async def respond(self, **_kwargs):
        return self._prompts.pop(0)


async def _app(tmp_path, executor):
    application = build_application(
        model=FakeMessagesListChatModel(responses=[]), db_path=str(tmp_path / "att.db")
    )
    await application.start()
    application.socratic._executor = executor
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        dialogues=application.dialogues,
        socratic=application.socratic,
    )
    return application, AsyncClient(transport=ASGITransport(app=api), base_url="http://test")


async def _project(http) -> UUID:
    created = await http.post("/api/projects", json={"name": f"dlg-{uuid4()}"})
    assert created.status_code == 200
    return UUID(created.json()["id"])


async def _dialogue_with_an_mcq(http, project_id) -> tuple[str, int]:
    """Ask a dialogue one question carrying an `mcq`, as a browser would.

    Returns the id **and the position the stream reported**, rather than
    letting callers assume 0. That is not tidiness: the number a page posts
    back with an attempt is the one it read off the `prompt` frame, and that
    number is `SocraticPrompt.position` -- a different quantity from
    `SocraticTurnRow.position`, which the projection counts for itself from
    `turn_count`. A test that hardcodes 0 exercises the projection's counter
    and is blind to the formula, which is what the first draft of this file did
    and why the parity test below passed under both formulas.
    """
    started = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})
    assert started.status_code == 200, started.text
    dialogue_id = started.json()["dialogueId"]
    replied = await http.post(
        f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply",
        json={"reply": "not sure"},
    )
    assert replied.status_code == 200, replied.text
    frames = [
        json.loads(line[len("data: ") :])
        for line in replied.text.splitlines()
        if line.startswith("data: ")
    ]
    prompts = [frame for frame in frames if frame["type"] == "prompt"]
    assert len(prompts) == 1, replied.text
    return dialogue_id, prompts[0]["position"]


async def _observations(application, dialogue_id: str) -> list[SocraticProgressObserved]:
    stream = StreamId(UUID(dialogue_id), SocraticDialogue.aggregate_type)
    events = [
        envelope.event
        for envelope in await collect(
            application.socratic._transcripts.event_store.read_stream(stream)
        )
    ]
    return [e for e in events if isinstance(e, SocraticProgressObserved)]


async def test_a_correct_answer_is_marked_and_recorded_against_the_dialogue(tmp_path):
    """Both writes, both asserted on stored facts.

    Red against a route that grades and returns without recording -- which is
    exactly what the ask's attempts route does, deliberately, and is the shape
    someone reusing it would produce here.
    """
    application, client = await _app(tmp_path, StubExecutor())
    try:
        async with client as http:
            project_id = await _project(http)
            dialogue_id, _position = await _dialogue_with_an_mcq(http, project_id)

            response = await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/attempts",
                json={"position": 0, "component_id": "council-1", "response": 0},
            )

        assert response.status_code == 200, response.text
        assert response.json()["correct"] is True

        # Write one: progress, keyed on the dialogue id rather than a session.
        progress = await application.socratic.progress_for(UUID(dialogue_id))
        item = progress.item("turn/0", "council-1")
        assert item is not None, "no progress row: the attempt was graded and forgotten"
        assert item.correct is True

        # Write two: the dialogue's own stream, so the stopping condition has
        # something to be met by.
        observed = await _observations(application, dialogue_id)
        assert len(observed) == 1
        assert observed[0].evidence == "attempt"
        assert "council-1" in observed[0].detail
    finally:
        await application.close()


async def test_a_wrong_answer_is_a_200_and_is_still_evidence(tmp_path):
    """A wrong answer is a result, not an error -- and it is still something
    the reader demonstrated, so it is still observed. A dialogue that only
    recorded correct answers would have a stopping condition fed by a biased
    sample of the reader's attempts.
    """
    application, client = await _app(tmp_path, StubExecutor())
    try:
        async with client as http:
            project_id = await _project(http)
            dialogue_id, _position = await _dialogue_with_an_mcq(http, project_id)
            response = await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/attempts",
                json={"position": 0, "component_id": "council-1", "response": 1},
            )

        assert response.status_code == 200, response.text
        assert response.json()["correct"] is False

        observed = await _observations(application, dialogue_id)
        assert len(observed) == 1
        assert observed[0].evidence == "attempt"
    finally:
        await application.close()


async def test_the_component_is_addressed_by_position_and_a_wrong_one_is_a_404(tmp_path):
    application, client = await _app(tmp_path, StubExecutor())
    try:
        async with client as http:
            project_id = await _project(http)
            dialogue_id, _position = await _dialogue_with_an_mcq(http, project_id)

            no_such_turn = await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/attempts",
                json={"position": 7, "component_id": "council-1", "response": 0},
            )
            no_such_component = await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/attempts",
                json={"position": 0, "component_id": "nope", "response": 0},
            )

        assert no_such_turn.status_code == 404, no_such_turn.text
        assert no_such_component.status_code == 404, no_such_component.text
    finally:
        await application.close()


async def test_a_response_the_item_cannot_interpret_is_a_400(tmp_path):
    """A malformed request, unlike a wrong answer. `GradingError` is the split
    and it is the same one the ask and lesson routes make."""
    application, client = await _app(tmp_path, StubExecutor())
    try:
        async with client as http:
            project_id = await _project(http)
            dialogue_id, _position = await _dialogue_with_an_mcq(http, project_id)
            response = await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/attempts",
                json={"position": 0, "component_id": "council-1", "response": "Nicaea"},
            )

        assert response.status_code == 400, response.text
    finally:
        await application.close()


async def test_the_answer_key_never_reaches_the_reader(tmp_path):
    """Asserted end to end, over the real routes, not on a helper being called.

    Nothing forces the reply route to project through `dialogue_document` --
    inlining `project(parse_document(...), view="author")` is a one-line edit
    that renders identically to a page and ships the key. So the assertion is
    on the bytes the reader receives: `correct` must not appear anywhere, while
    the attempts route -- which parses the same turn raw, server-side -- still
    grades it. Both halves are needed; the first alone passes against a route
    that returns nothing at all.

    **Three surfaces, because this test found the key on all three and a
    projection is only real if there is nothing beside it.** Written first
    against the stream alone, it went red immediately: `blocks` correctly
    withheld `options[].correct` while a raw `text` one key to its left carried
    the whole fenced block. Fixing that and re-running found the same raw copy
    on the detail route's `prompt` and on `pending_prompt` -- which
    `read_models.py` writes from the newest turn's prompt, so it is the live
    question, on both the detail view and the index list. A page rendering
    `blocks` looked correct throughout; nothing but the bytes ever disagreed.
    """
    application, client = await _app(tmp_path, StubExecutor())
    try:
        async with client as http:
            project_id = await _project(http)
            started = await http.post(
                f"/api/projects/{project_id}/dialogues", json={"topic": "t"}
            )
            dialogue_id = started.json()["dialogueId"]
            streamed = await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/reply",
                json={"reply": "not sure"},
            )
            assert streamed.status_code == 200, streamed.text
            body = streamed.text
            marked = await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/attempts",
                json={"position": 0, "component_id": "council-1", "response": 0},
            )
            detail = await http.get(f"/api/projects/{project_id}/dialogues/{dialogue_id}")
            listed = await http.get(f"/api/projects/{project_id}/dialogues")
            assert detail.status_code == 200, detail.text
            assert listed.status_code == 200, listed.text

        # The component did reach the reader -- otherwise the absence below
        # would be the absence of everything.
        assert "council-1" in body
        assert "Nicaea" in body
        # And the server still knows which option was right.
        assert marked.status_code == 200, marked.text
        assert marked.json()["correct"] is True

        # Every surface that hands back the same utterance, because the stream
        # is not the only way a reader sees it: a refresh reads the detail
        # route, and an index page reads the list route, and both carried
        # `pending_prompt` raw -- which `read_models.py` writes from the newest
        # turn's prompt, so both shipped the live question's key.
        assert "council-1" in detail.text
        for surface, payload in (
            ("stream", body),
            ("detail", detail.text),
            ("list", listed.text),
        ):
            # Not a bare `"correct" not in payload`: the projection *announces*
            # what it dropped, as `"withheld": ["options[].correct", ...]`, and
            # that string is the projection working rather than failing. What
            # must not appear is a correctness *value* -- in the fence's YAML
            # or in JSON -- or the raw fence that would carry one.
            assert "correct: true" not in payload, f"{surface} ships the fence's answer key"
            assert '"correct": true' not in payload, f"{surface} ships the key as JSON"
            assert "```component:" not in payload, f"{surface} ships the raw component source"
    finally:
        await application.close()


@pytest.mark.parametrize("opening", ["Where would you start?", ""])
async def test_the_grading_key_survives_a_dialogue_with_no_opening_question(tmp_path, opening):
    """The position-formula parity case, made visible.

    `SocraticPrompt.position` is `len(messages) // 2`. It was `(len - 1) // 2`
    for a commit, and the two agree on every ODD history -- which is what a
    dialogue with an opening question always has. They differ only when
    `_resume` finds an empty `opening_prompt`, which `SocraticDialogueStarted`
    permits and older streams therefore produce.

    **The position posted here is the one the stream reported, and that is the
    whole of what makes this test able to fail.** The route looks the body's
    `position` up against `SocraticTurnRow.position`, which the projection
    counts for itself from `turn_count` and which the formula never touches --
    so a test that posts a hardcoded 0 passes under both formulas and proves
    nothing. It is the browser that carries the formula's answer from the
    `prompt` frame to the attempts route, and it is that round trip which
    breaks: with `(len - 1) // 2` and an empty opening question the frame
    reports position -1, the page posts -1, and the reader's answer 404s
    against a turn that does not exist.

    Parametrised over both parities for that reason. The first case passes
    under either formula and is here to prove the second is not passing by
    accident. Proved red on 2026-08-18 by making that substitution: the empty
    case failed with a 404 and the `Where would you start?` case still passed.
    """
    application, client = await _app(tmp_path, StubExecutor(opening=opening))
    try:
        async with client as http:
            project_id = await _project(http)
            dialogue_id, position = await _dialogue_with_an_mcq(http, project_id)

            response = await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/attempts",
                json={"position": position, "component_id": "council-1", "response": 0},
            )

        assert response.status_code == 200, response.text
        # The exchange the reader actually saw is the dialogue's first, under
        # either parity -- so the key is `turn/0` and not `turn/{position}`.
        # Asserting the literal is what makes an off-by-one visible rather than
        # self-consistent.
        assert position == 0
        progress = await application.socratic.progress_for(UUID(dialogue_id))
        assert progress.item("turn/0", "council-1") is not None
    finally:
        await application.close()


async def test_the_verdict_carries_the_progress_the_page_has_to_draw(tmp_path):
    """`progress` on the response body, so a page does not have to re-fetch.

    Asserted on the counted attempts rather than on the key's presence: an
    `item_view` handed the wrong path answers 200 with a zeroed record, which
    reads exactly like a first attempt.
    """
    application, client = await _app(tmp_path, StubExecutor())
    try:
        async with client as http:
            project_id = await _project(http)
            dialogue_id, _position = await _dialogue_with_an_mcq(http, project_id)
            await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/attempts",
                json={"position": 0, "component_id": "council-1", "response": 1},
            )
            second = await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/attempts",
                json={"position": 0, "component_id": "council-1", "response": 0},
            )

        assert second.status_code == 200, second.text
        progress = json.loads(second.text)["progress"]
        assert progress["path"] == "turn/0"
        assert progress["attempts"] == 2
        assert progress["correct"] is True
    finally:
        await application.close()
