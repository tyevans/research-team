"""The whole feature, over applications the composition root actually built.

Everything else about persisted asks is green in a build where
`composition.py` never constructs an `AskConversationRunner`: the service
appends its events, nothing is subscribed to them, and `eventsource` counts an
event no projection handles as APPLIED rather than rejected. Nothing raises,
nothing logs, and every history request answers an empty list. That is the
failure this codebase has shipped six times and this file exists to catch --
which is why every assertion below is on a turn's *text*, never on `start()`
returning or a request succeeding.

Two applications over one database file, the second standing in for the
restart. Not the crash-shaped fixture `test_accept_reconciliation.py` builds
on the media branch: that file is not on this branch, and a second
`build_application` over the same `tmp_path` reaches the same state -- the
first application's projection is stopped and its tables are re-derived, or
resumed, by a process that did not append the events.

**The executor is a stub, stated rather than implied.** `application.ask` is
the composed service, with the composed repository behind it; only the thing
that would call a model is replaced. What this file proves is that a turn
appended through the composed service reaches the composed read model and the
route -- not anything about the agent that produces an answer.
"""

import json
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

from research_team.application.ask import AskAnswer, AskConversationOpened, Citation
from research_team.composition import build_application
from research_team.interfaces.web import create_app


class StubExecutor:
    """Answers whatever it was handed, in order, without a model."""

    def __init__(self, answers: list[AskAnswer]) -> None:
        self._answers = list(answers)

    async def run(self, *, project_id, history, question, on_activity):
        return self._answers.pop(0)


@pytest.fixture
def db_file(tmp_path) -> str:
    return str(tmp_path / "restart.db")


async def _application(db_file, answers):
    """A started application whose ask executor is a stub.

    The executor is replaced on the composed service rather than injected
    through `build_application`, which takes no such parameter -- reaching for
    the private attribute is the smaller lie than building an `AskService` by
    hand here, because a hand-built one would be exactly the thing this file
    is meant to prove is composed.
    """
    application = build_application(
        model=FakeMessagesListChatModel(responses=[]), db_path=db_file
    )
    await application.start()
    application.ask._executor = StubExecutor(answers)
    return application


async def _ask(application, project_id, question) -> UUID:
    """Ask, and return the conversation id the stream announced.

    Read off the stream rather than out of the registry: the id reaching the
    client is what makes a stored conversation resumable, and taking it from
    `application.ask._conversations` would pass in a build that minted an id
    and never told anybody.
    """
    conversation_id = None
    async for note in application.ask.ask(
        project_id=project_id, chat_id="c", question=question
    ):
        if isinstance(note, AskConversationOpened):
            conversation_id = note.conversation_id
    assert conversation_id is not None, "the ask stream never announced a conversation id"
    return conversation_id


async def test_a_conversation_survives_a_restart(db_file, project_id):
    """The whole feature. The first application asks twice; the second reads
    the turns back, in order, with the citations attached to the turn that
    produced them."""
    first = await _application(
        db_file,
        [
            AskAnswer(text="one", citations=(Citation(kind="source", id="s1"),)),
            AskAnswer(text="two", citations=(Citation(kind="source", id="s2"),)),
        ],
    )
    try:
        conversation_id = await _ask(first, project_id, "first?")
        await _ask(first, project_id, "second?")
    finally:
        await first.close()

    restarted = await _application(db_file, [])
    try:
        await restarted.asks.caught_up()
        turns = await restarted.asks.turns_for(conversation_id)

        assert [turn.question for turn in turns] == ["first?", "second?"]
        assert [turn.answer for turn in turns] == ["one", "two"]
        assert [turn.citations for turn in turns] == [
            [{"kind": "source", "id": "s1"}],
            [{"kind": "source", "id": "s2"}],
        ]
    finally:
        await restarted.close()


async def test_the_history_route_answers_from_the_composed_application(db_file, project_id):
    """The route, over the application `web.py` builds. A second
    `AskConversationRunner` constructed at the call site would answer an empty
    list here while every unit test stayed green."""
    application = await _application(db_file, [AskAnswer(text="one")])
    try:
        conversation_id = await _ask(application, project_id, "why?")
        await application.asks.caught_up()
        app = create_app(
            service=None, feed=None, turns=None, ask=application.ask, asks=application.asks
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http:
            listed = await http.get(f"/api/projects/{project_id}/asks")
            one = await http.get(f"/api/projects/{project_id}/asks/{conversation_id}")
            missing = await http.get(f"/api/projects/{project_id}/asks/{uuid4()}")
    finally:
        await application.close()

    assert [row["conversationId"] for row in listed.json()] == [str(conversation_id)]
    assert listed.json()[0]["firstQuestion"] == "why?"
    body = one.json()
    assert body["conversationId"] == str(conversation_id)
    assert [turn["question"] for turn in body["turns"]] == ["why?"]
    # The prose reached through `blocks`, because there is no raw `answer` key
    # -- see `read_ask` for why it was removed rather than projected.
    assert [turn["blocks"][0]["text"] for turn in body["turns"]] == ["one"]
    assert missing.status_code == 404


async def test_a_stored_turn_is_parsed_the_same_way_as_a_live_one(db_file, project_id):
    """A reader reopening a conversation gets working widgets, not code
    blocks. Red against `read_ask` returning only `answer`."""
    mcq_answer = (
        "```component:mcq\n"
        "id: q1\n"
        "prompt: Which year?\n"
        "options:\n"
        '  - text: "1974"\n'
        "    correct: true\n"
        '  - text: "1975"\n'
        "    correct: false\n"
        "```\n"
    )
    application = await _application(db_file, [AskAnswer(text=mcq_answer)])
    try:
        conversation_id = await _ask(application, project_id, "quiz me")
        await application.asks.caught_up()
        app = create_app(
            service=None, feed=None, turns=None, ask=application.ask, asks=application.asks
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http:
            body = (
                await http.get(f"/api/projects/{project_id}/asks/{conversation_id}")
            ).json()
    finally:
        await application.close()

    assert [block["kind"] for block in body["turns"][0]["blocks"]] == ["component"]
    # The component did reach the reader -- otherwise the absence below would
    # be the absence of everything.
    payload = json.dumps(body)
    assert "Which year?" in payload

    # **And no answer key came with it.** The `kind` assertion above was the
    # whole of this test until 2026-08-18, and it passed while the route
    # shipped `"answer": turn.answer` -- the stored markdown, fences and all --
    # one key to the left of blocks that correctly withheld
    # `options[].correct`. Measured: restore that field and the three
    # assertions below go red together while every other assertion in this
    # file stays green. BACKLOG B106 stated this route withheld the key and
    # rested on exactly the `kind` check; the claim is what stopped anyone
    # looking.
    #
    # Not a bare `"correct" not in payload`: the projection *announces* what it
    # dropped, as `"withheld": ["options[].correct", ...]`, and that string is
    # the projection working rather than failing. What must not appear is a
    # correctness *value*, or the raw fence that would carry one.
    assert "correct: true" not in payload, "the stored turn ships the fence's answer key"
    assert '"correct": true' not in payload, "the stored turn ships the key as JSON"
    assert "```component:" not in payload, "the stored turn ships the raw component source"


async def test_one_projects_history_does_not_list_anothers(db_file, project_id):
    """The spec asks for it directly, and a route that dropped its
    `project_id` predicate would pass every other test in this file."""
    other = uuid4()
    application = await _application(db_file, [AskAnswer(text="mine"), AskAnswer(text="th")])
    try:
        await _ask(application, project_id, "mine?")
        # A second chat id: one id under two projects is the registry's
        # mismatch path, which starts a fresh conversation anyway -- this is
        # the ordinary case of two projects being asked separately.
        async for _ in application.ask.ask(project_id=other, chat_id="d", question="theirs?"):
            pass
        await application.asks.caught_up()
        app = create_app(
            service=None, feed=None, turns=None, ask=application.ask, asks=application.asks
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http:
            listed = await http.get(f"/api/projects/{project_id}/asks")
    finally:
        await application.close()

    assert [row["firstQuestion"] for row in listed.json()] == ["mine?"]
