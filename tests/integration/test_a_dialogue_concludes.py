"""A dialogue that ends, over the composed application.

The write path has existed since Plan 2 -- `_record` has always had
`if asked.concluded:` -- and has never once fired, because the executor
returned the default. So every assertion here is on a stored event: a green
call proves nothing, and "the endpoint answered" is compatible with the branch
still being dead.
"""

from uuid import UUID, uuid4

import pytest
from eventsource import StreamId, collect
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from research_team.composition import build_application
from research_team.domain.socratic_dialogue import (
    SocraticDialogue,
    SocraticDialogueConcluded,
    SocraticProgressObserved,
    SocraticTurnRecorded,
)
from research_team.interfaces.web import create_app
from tests.conftest import ToolAwareFakeChatModel

FRAMING = AIMessage(
    content=(
        "```yaml\ngoal: |\n  understand the settlement\n"
        "stopping_condition: |\n  the reader separates it from the politics\n"
        "opening_prompt: |\n  What do you think it settled?\n```\n"
    )
)
CONTINUING = AIMessage(
    content=(
        "```yaml\nconcluded: false\nobservation: |\n  named both parties\n"
        "prompt: |\n  What divided them?\n```\n"
    )
)
CONCLUDING = AIMessage(
    content=(
        "```yaml\nconcluded: true\nobservation: |\n"
        '  separated the settlement from the politics, unaided\nprompt: ""\n```\n'
    )
)


async def _application(tmp_path, responses):
    application = build_application(
        model=ToolAwareFakeChatModel(responses=responses),
        db_path=str(tmp_path / "concluding.db"),
    )
    await application.start()
    return application


async def _project(application) -> UUID:
    api = create_app(application.service, application.feed, application.turns)
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        created = await http.post("/api/projects", json={"name": f"dlg-{uuid4()}"})
        assert created.status_code == 200
        return UUID(created.json()["id"])


async def _events(application, dialogue_id):
    stream = StreamId(dialogue_id, SocraticDialogue.aggregate_type)
    return [
        envelope.event
        for envelope in await collect(
            application.socratic._transcripts.event_store.read_stream(stream)
        )
    ]


async def test_a_dialogue_the_model_concludes_is_concluded_on_its_stream(tmp_path):
    """The headline, as a stored fact.

    Red against the executor as it shipped in Plan 2: `concluded` is the
    default `False`, `_record`'s branch never fires, and the stream ends on a
    turn. Nothing raises in that build -- the request succeeds and the reader
    is simply asked another question forever -- which is why this asserts on
    the event list and not on a status code.
    """
    application = await _application(tmp_path, [FRAMING, CONCLUDING])
    try:
        project_id = await _project(application)
        dialogue_id = await application.socratic.begin(
            project_id=project_id, topic="the settlement"
        )
        async for _note in application.socratic.respond(
            project_id=project_id,
            dialogue_id=dialogue_id,
            reply="It was about the politics.",
        ):
            pass

        events = await _events(application, dialogue_id)
        assert [type(event) for event in events][-1] is SocraticDialogueConcluded
        assert events[-1].reason == "met"
    finally:
        await application.close()


async def test_the_model_s_own_reading_is_recorded_as_an_assessment(tmp_path):
    """The second half of a judgement, and the half that keeps the evidence
    honest. `evidence="assessment"` and never `"attempt"`: this is the model's
    opinion of prose, which is weaker than a marked answer, and a stopping
    condition met entirely by these is a dialogue that graded its own homework.

    Red against a `respond` that returns `concluded` and drops `observation` --
    the dialogue would end with no record of what it ended on.
    """
    application = await _application(tmp_path, [FRAMING, CONTINUING])
    try:
        project_id = await _project(application)
        dialogue_id = await application.socratic.begin(
            project_id=project_id, topic="the settlement"
        )
        async for _note in application.socratic.respond(
            project_id=project_id,
            dialogue_id=dialogue_id,
            reply="Arius and Athanasius.",
        ):
            pass

        events = await _events(application, dialogue_id)
        observed = [e for e in events if isinstance(e, SocraticProgressObserved)]
        assert len(observed) == 1
        assert observed[0].observation == "named both parties"
        assert observed[0].evidence == "assessment"
        # And the turn is still recorded, in the order `_record` writes them.
        assert [type(e) for e in events[1:]] == [
            SocraticTurnRecorded,
            SocraticProgressObserved,
        ]
    finally:
        await application.close()


async def test_a_concluding_turn_records_its_empty_question_rather_than_inventing_one(
    tmp_path,
):
    """A finished dialogue has nothing further to ask, so the last turn's
    `prompt` is empty and `pending_prompt` clears with it.

    Red against an executor that falls back to `last_text(final)` when the
    parsed prompt is empty: the reader would be shown the raw YAML block as the
    dialogue's closing question.
    """
    application = await _application(tmp_path, [FRAMING, CONCLUDING])
    try:
        project_id = await _project(application)
        dialogue_id = await application.socratic.begin(
            project_id=project_id, topic="the settlement"
        )
        async for _note in application.socratic.respond(
            project_id=project_id, dialogue_id=dialogue_id, reply="It separated them."
        ):
            pass
        await application.dialogues.caught_up()

        turns = await application.dialogues.turns_for(dialogue_id)
        assert turns[-1].prompt == ""
        row = await application.dialogues.get(dialogue_id)
        assert row.status == "concluded"
        assert row.concluded_reason == "met"
        assert row.pending_prompt == ""
    finally:
        await application.close()


async def test_a_reply_to_a_concluded_dialogue_is_refused_before_the_model_is_called(
    tmp_path,
):
    """`_resume`'s third refusal, reachable for the first time.

    It has been in the code since Plan 1 and has never fired, because nothing
    could conclude a dialogue. `decide` would refuse the turn anyway -- but only
    after the model had been called and paid for, which is the whole reason the
    check is in `_resume`.

    The model list has exactly two responses, so a build that reached the
    executor raises `IndexError` from the fake rather than the refusal below.
    That is the assertion doing work: it distinguishes "refused" from "answered
    a third time".
    """
    from research_team.application.socratic import UnknownDialogue

    application = await _application(tmp_path, [FRAMING, CONCLUDING])
    try:
        project_id = await _project(application)
        dialogue_id = await application.socratic.begin(
            project_id=project_id, topic="the settlement"
        )
        async for _note in application.socratic.respond(
            project_id=project_id, dialogue_id=dialogue_id, reply="It separated them."
        ):
            pass
        application.socratic.forget(dialogue_id)
        await application.dialogues.caught_up()

        with pytest.raises(UnknownDialogue, match="concluded"):
            async for _note in application.socratic.respond(
                project_id=project_id, dialogue_id=dialogue_id, reply="one more?"
            ):
                pass
    finally:
        await application.close()
