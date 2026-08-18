"""The dialogue history routes, over a composed application.

Two claims, and they are different: that a dialogue written through the service
is readable over HTTP with its goal intact, and that these routes answer for a
project no fixture has opened. The second is CLAUDE.md's fixture trap -- a
fixture that seeds through the same call the code under test depends on cannot
see that dependency go missing.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from research_team.application.socratic import SocraticFraming, SocraticPrompt
from research_team.composition import build_application
from research_team.interfaces.web import create_app


class StubExecutor:
    """Framing and questioning without a model.

    The composed build's real executor is `DeepAgentSocraticExecutor`, which
    calls a model. Substituted here because these tests are about the routes:
    what a request returns, and what a refusal looks like. That the composed
    one is real, reaches a model and parses what comes back is
    `test_a_dialogue_is_composed_with_a_model.py`'s job, and this file would
    stay green if it were not -- which is why that file exists.
    """

    async def frame(self, *, project_id, topic):
        return SocraticFraming(
            goal=f"understand {topic}",
            stopping_condition="the reader explains it unaided",
            opening_prompt="Where would you start?",
        )

    async def respond(
        self, *, project_id, history, goal, stopping_condition, reply, on_activity
    ):
        return SocraticPrompt(prompt="What makes you say that?", citations=(("source", "s1"),))


@pytest.fixture
async def app(tmp_path):
    application = build_application(
        model=FakeMessagesListChatModel(responses=[]), db_path=str(tmp_path / "routes.db")
    )
    await application.start()
    application.socratic._executor = StubExecutor()
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        ask=application.ask,
        asks=application.asks,
        dialogues=application.dialogues,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http, application
    await application.close()


async def _project(http) -> UUID:
    created = await http.post("/api/projects", json={"name": f"dlg-{uuid4()}"})
    assert created.status_code == 200, created.text
    return UUID(created.json()["id"])


async def test_a_dialogue_is_readable_with_its_goal_and_its_turns(app):
    """The assertion is on the goal and the turn text, not on the status code.

    Red against a build with no runner: this route would answer 200 with an
    empty list for `/dialogues` and 404 here, and only an assertion on the
    *content* distinguishes that from a project nobody has talked to.
    """
    http, application = app
    project_id = await _project(http)
    dialogue_id = await application.socratic.begin(
        project_id=project_id, topic="the Nicene settlement"
    )
    async for _note in application.socratic.respond(
        project_id=project_id, dialogue_id=dialogue_id, reply="It settled Arianism."
    ):
        pass
    await application.dialogues.caught_up()

    response = await http.get(f"/api/projects/{project_id}/dialogues/{dialogue_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dialogueId"] == str(dialogue_id)
    assert body["goal"] == "understand the Nicene settlement"
    assert body["stoppingCondition"] == "the reader explains it unaided"
    assert body["status"] == "started"
    # A turn pairs the reader's answer with the question it PRODUCED, not the
    # question it answered -- so `prompt` here is the dialogue's *second*
    # utterance, and the opening question is on the dialogue, not on any turn.
    # `prompt` being the dialogue's and `reply` the reader's is the inverse of
    # `read_ask`'s question/answer, and a swap would still read as a
    # conversation, which is why it is asserted by text rather than by shape.
    assert body["turns"] == [
        {
            "position": 0,
            "prompt": "What makes you say that?",
            "reply": "It settled Arianism.",
            "citations": [{"kind": "source", "id": "s1"}],
            "recordedAt": body["turns"][0]["recordedAt"],
        }
    ]
    # The transcript's first utterance, which is on no turn above. Red against
    # a view that omits it: the page would draw a reader answering something
    # nobody asked.
    assert body["openingPrompt"] == "Where would you start?"
    # And the question now outstanding. Red against a view that omits it: the
    # page would render a transcript ending on the reader's own words with
    # nothing asking them anything.
    assert body["pendingPrompt"] == "What makes you say that?"


async def test_the_list_shows_this_project_s_dialogues_and_what_they_are_for(app):
    """A reader picking a dialogue back up needs to know which one it was, and
    the topic alone does not say what it was aiming at. Red against a list view
    that carries only ids and timestamps."""
    http, application = app
    project_id = await _project(http)
    await application.socratic.begin(project_id=project_id, topic="the Nicene settlement")
    await application.dialogues.caught_up()

    response = await http.get(f"/api/projects/{project_id}/dialogues")

    assert response.status_code == 200, response.text
    listed = response.json()
    assert [row["topic"] for row in listed] == ["the Nicene settlement"]
    assert listed[0]["goal"] == "understand the Nicene settlement"
    assert listed[0]["turnCount"] == 0
    # The three fields a list-only client would otherwise never see. Red
    # against a `_dialogue_view` that carried them in the detail body only --
    # and `openingPrompt` is the one that matters, because the index page is
    # where a reader picks a dialogue back up and it is the transcript's
    # missing first utterance.
    assert listed[0]["openingPrompt"] == "Where would you start?"
    assert listed[0]["stoppingCondition"] == "the reader explains it unaided"
    assert listed[0]["observations"] == []
    assert listed[0]["concludedReason"] == ""


async def test_the_list_puts_the_most_recently_opened_dialogue_first(app):
    """`for_project` orders `opened_at desc` and `list_dialogues` promises "most
    recent first"; with one row in the table a flipped `order_direction` passes.

    The timestamps are explicit and a full day apart rather than two clock
    reads, because `opened_at desc` breaks a tie with nothing -- two
    `datetime.now(UTC)` calls microseconds apart can collide, and a test that
    closed this hole by seeding two rows from the clock would buy a rare flake
    in exchange. Task 2 hit exactly that.

    Red against `order_direction="asc"`: the two topics come back swapped.
    """
    http, application = app
    project_id = await _project(http)
    opened = iter(
        [datetime(2026, 8, 15, 12, 0, tzinfo=UTC), datetime(2026, 8, 16, 12, 0, tzinfo=UTC)]
    )
    application.socratic._clock = lambda: next(opened)
    await application.socratic.begin(project_id=project_id, topic="the older one")
    await application.socratic.begin(project_id=project_id, topic="the newer one")
    await application.dialogues.caught_up()

    response = await http.get(f"/api/projects/{project_id}/dialogues")

    assert response.status_code == 200, response.text
    assert [row["topic"] for row in response.json()] == ["the newer one", "the older one"]


async def test_a_dialogue_from_another_project_is_a_404_not_a_read(app):
    """404 covers both "no such dialogue" and "that dialogue belongs to another
    project", deliberately the same answer as the ask routes give: the second
    is a guessed id, and telling a caller that an id they cannot read does
    exist is the distinction not worth drawing."""
    http, application = app
    mine = await _project(http)
    theirs = await _project(http)
    dialogue_id = await application.socratic.begin(project_id=mine, topic="t")
    await application.dialogues.caught_up()

    response = await http.get(f"/api/projects/{theirs}/dialogues/{dialogue_id}")

    assert response.status_code == 404, response.text


async def test_the_list_answers_for_a_project_nothing_has_opened(app):
    """CLAUDE.md's fixture trap. Every other test here creates a dialogue
    first, which opens whatever the dialogue path opens -- so a route that
    reached for a reader without opening the project would be invisible from
    all of them and answer 503 exactly once per project.

    An empty list is the right answer and the assertion is that it is 200 with
    an empty body, not merely `!= 503`: this route has one honest answer for a
    project nobody has talked to.
    """
    http, _application = app
    project_id = await _project(http)

    response = await http.get(f"/api/projects/{project_id}/dialogues")

    assert response.status_code == 200, response.text
    assert response.json() == []


async def test_an_unconfigured_build_says_so_rather_than_answering_empty(tmp_path):
    """503 when the projection is unwired, not an empty 200 -- the same ruling
    `list_asks` makes, and it matters for the same reason: an empty list is the
    right answer for a project nobody has talked to, and a dialogue appends
    whether or not anything follows the log, so the two are indistinguishable
    unless the route says so.
    """
    application = build_application(
        model=FakeMessagesListChatModel(responses=[]), db_path=str(tmp_path / "bare.db")
    )
    await application.start()
    api = create_app(application.service, application.feed, application.turns)
    transport = ASGITransport(app=api)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            project_id = await _project(http)
            response = await http.get(f"/api/projects/{project_id}/dialogues")
            assert response.status_code == 503, response.text
            # The detail route's identical guard. Covered separately because
            # it is a separate `if`: deleting it turns this into a 404, which
            # is a plausible-looking answer for an unwired build and says
            # nothing about the projection being absent.
            detail = await http.get(f"/api/projects/{project_id}/dialogues/{uuid4()}")
            assert detail.status_code == 503, detail.text
    finally:
        await application.close()
