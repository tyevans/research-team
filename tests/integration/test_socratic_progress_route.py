"""Reading back what a dialogue remembered, and the framing it starts with.

B114. The attempts route has recorded against the dialogue id since 95076c9 and
nothing could read it: the only progress read route resolves its id through
`_load(session_id)` and cannot serve a dialogue id, and `progress_for` is
in-process only. So "your answers survive a refresh" -- the property that
distinguishes this surface from the ask, and the whole of design §3's argument
for a dialogue being its own principal -- was real in the event log and
invisible in the browser.

Every assertion here is on a **stored value reaching the response body**, never
on a status. An empty `items` map is the right answer for a dialogue nobody has
answered anything in, so a status-only assertion passes against a route reading
an id it was never handed -- and an event no projection handles counts as
APPLIED, so a missing subscription is a silently empty 200 rather than a
refusal.

Every test builds its project through the HTTP route rather than through a
fixture that has already opened it, which is CLAUDE.md's fixture trap: a
fixture that seeds through the same collaborator the request path depends on
cannot see that dependency go missing.
"""

import json
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from research_team.application.socratic import SocraticFraming, SocraticPrompt
from research_team.composition import build_application
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
    """Framing and questioning without a model -- `test_socratic_attempts.py`'s,
    kept as a copy rather than imported.

    A shared fixture module between two integration files is a dependency that
    makes both harder to read for one class; the class is nine lines and the
    duplication is visible from either side.
    """

    async def frame(self, *, project_id, topic):
        return SocraticFraming(
            goal=f"understand {topic}",
            stopping_condition="the reader explains it unaided",
            opening_prompt="Where would you start?",
        )

    async def respond(self, **_kwargs):
        return SocraticPrompt(prompt=MCQ)


async def _app(tmp_path):
    application = build_application(
        model=FakeMessagesListChatModel(responses=[]), db_path=str(tmp_path / "prog.db")
    )
    await application.start()
    application.socratic._executor = StubExecutor()
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
    assert created.status_code == 200, created.text
    return UUID(created.json()["id"])


async def _framed(http, project_id) -> dict:
    """Frame a dialogue and hand back the whole body, not just the id.

    The body is what `test_framing_arrives_with_the_id` asserts on; the other
    tests want only the id out of it.
    """
    started = await http.post(f"/api/projects/{project_id}/dialogues", json={"topic": "t"})
    assert started.status_code == 200, started.text
    return started.json()


async def _dialogue_with_an_mcq(http, project_id) -> str:
    """Ask a dialogue one question carrying an `mcq`, as a browser would."""
    dialogue_id = (await _framed(http, project_id))["dialogueId"]
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
    assert [f for f in frames if f["type"] == "prompt"], replied.text
    return dialogue_id


async def test_a_recorded_attempt_is_readable_back(tmp_path):
    """The property the attempts route was built for, asserted through the
    route a browser would use.

    Red against a build with no such route at all -- 404 -- and, more usefully,
    red against one that resolves its id through `_load(session_id)`: a dialogue
    id is not a session id and that path 404s too. The assertion is the stored
    verdict rather than the status, because the empty map a wrong id produces is
    a well-formed 200.
    """
    application, client = await _app(tmp_path)
    try:
        async with client as http:
            project_id = await _project(http)
            dialogue_id = await _dialogue_with_an_mcq(http, project_id)
            marked = await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/attempts",
                json={"position": 0, "component_id": "council-1", "response": 0},
            )
            assert marked.status_code == 200, marked.text

            response = await http.get(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/progress"
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["scope"] == "dialogue"
        assert body["dialogueId"] == dialogue_id
        # Keyed by the utterance and then the component, which is the third
        # shape's whole reason: a component id is unique only within one turn.
        assert body["items"]["turn/0"]["council-1"]["correct"] is True
        assert body["items"]["turn/0"]["council-1"]["attempts"] == 1
    finally:
        await application.close()


async def test_a_wrong_answer_is_read_back_as_a_wrong_answer(tmp_path):
    """Not merely "a row exists".

    `item_view` answers a zeroed record for an item nobody has touched, and a
    zeroed record has `correct: False` -- so a test that only asserted a wrong
    answer reads back false would pass against a route serving zeros for
    everything. The attempt count is what separates the two, and it is asserted
    here for that reason.
    """
    application, client = await _app(tmp_path)
    try:
        async with client as http:
            project_id = await _project(http)
            dialogue_id = await _dialogue_with_an_mcq(http, project_id)
            await http.post(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/attempts",
                json={"position": 0, "component_id": "council-1", "response": 1},
            )

            response = await http.get(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/progress"
            )

        assert response.status_code == 200, response.text
        item = response.json()["items"]["turn/0"]["council-1"]
        assert item["correct"] is False
        assert item["attempts"] == 1
    finally:
        await application.close()


async def test_a_dialogue_from_another_project_is_a_404(tmp_path):
    """Ownership, checked the way both neighbouring routes check it.

    Two projects in one application, so the dialogue genuinely exists and the
    404 is about who may read it rather than about an id nothing minted -- which
    a `uuid4()` would not distinguish. Red against a route that reads
    `progress_for` without looking at `row.project_id`: that answers 200 with
    another reader's answers in it.
    """
    application, client = await _app(tmp_path)
    try:
        async with client as http:
            mine = await _project(http)
            theirs = await _project(http)
            dialogue_id = await _dialogue_with_an_mcq(http, mine)
            await http.post(
                f"/api/projects/{mine}/dialogues/{dialogue_id}/attempts",
                json={"position": 0, "component_id": "council-1", "response": 0},
            )

            # The same id, under the wrong project.
            trespass = await http.get(
                f"/api/projects/{theirs}/dialogues/{dialogue_id}/progress"
            )
            # And it is readable under the right one, so the 404 above is about
            # ownership and not about a route that 404s on everything.
            owned = await http.get(f"/api/projects/{mine}/dialogues/{dialogue_id}/progress")

        assert trespass.status_code == 404, trespass.text
        assert owned.status_code == 200, owned.text
        assert owned.json()["items"]["turn/0"]["council-1"]["correct"] is True
    finally:
        await application.close()


async def test_an_untouched_dialogue_answers_an_empty_map_not_a_404(tmp_path):
    """Nobody has answered anything yet is a fact about the reader, not the id.

    A 404 here would make a page opening a fresh dialogue show an error before
    the reader had done anything wrong. Deliberately the one test in this file
    whose pass is a status plus an empty body -- and it is only meaningful
    beside the two above, which prove the same route can carry a value.
    """
    application, client = await _app(tmp_path)
    try:
        async with client as http:
            project_id = await _project(http)
            dialogue_id = (await _framed(http, project_id))["dialogueId"]

            response = await http.get(
                f"/api/projects/{project_id}/dialogues/{dialogue_id}/progress"
            )

        assert response.status_code == 200, response.text
        assert response.json()["items"] == {}
    finally:
        await application.close()


async def test_a_dialogue_nothing_minted_is_a_404(tmp_path):
    """A guessed id, on a project the fixture HAS opened -- so the 404 comes
    from the dialogue lookup rather than from the project one."""
    application, client = await _app(tmp_path)
    try:
        async with client as http:
            project_id = await _project(http)
            response = await http.get(
                f"/api/projects/{project_id}/dialogues/{uuid4()}/progress"
            )

        assert response.status_code == 404, response.text
    finally:
        await application.close()


async def test_framing_arrives_with_the_id(tmp_path):
    """The reader's first sight of the dialogue is its goal, and it arrives on
    the framing response.

    Red against `POST /dialogues` returning `{"dialogueId"}` alone, which is
    what it returned for three commits while its own docstring claimed
    otherwise: a freshly framed dialogue drew an empty framing block and an
    empty thread until the reader answered a question they could not see.

    The opening question is asserted as **blocks**, not as a raw prompt: no
    dialogue surface carries raw prompt text, because the raw copy ships the
    fenced component's `correct: true` beside a projection that withheld it.

    This also pins the read-after-write this route depends on. The projection
    follows the log through `InMemoryEventBus`, which dispatches synchronously
    by default -- if that becomes background, `dialogues.get` here answers
    `None` and the route 502s, which this test reports rather than tolerates.
    """
    application, client = await _app(tmp_path)
    try:
        async with client as http:
            project_id = await _project(http)
            body = await _framed(http, project_id)

        assert body["dialogueId"]
        assert body["goal"] == "understand t"
        assert body["stoppingCondition"] == "the reader explains it unaided"
        assert [block["text"] for block in body["openingBlocks"]] == ["Where would you start?"]
    finally:
        await application.close()
