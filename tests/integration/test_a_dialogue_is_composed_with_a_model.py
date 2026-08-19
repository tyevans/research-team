"""The executor the composition root actually built, over a fake model.

`test_a_dialogue_survives_a_restart.py` replaces `application.socratic._executor`
with a stub, which is right for what it proves and means it would stay green
against a build whose real executor was never constructed -- or was constructed
with the ask's prompt. This file is the one that would not.

The model is the shared `ToolAwareFakeChatModel` -- langchain's own fake plus
the `bind_tools` deepagents requires -- so nothing here asserts anything about
a language model's judgement. What it asserts is that a composed `begin` reaches
a model at all, that what comes back is parsed into the three framing strings,
and that those strings land on the stream.
"""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage

from research_team.composition import build_application
from research_team.interfaces.web import create_app
from tests.conftest import ToolAwareFakeChatModel

FRAMING = AIMessage(
    content=(
        "```yaml\n"
        "goal: |\n"
        "  why the creed's wording mattered politically\n"
        "stopping_condition: |\n"
        "  the reader separates the settlement from the politics\n"
        "opening_prompt: |\n"
        "  What do you already believe the creed settled?\n"
        "```\n"
    )
)


@pytest.fixture
async def application(tmp_path):
    built = build_application(
        model=ToolAwareFakeChatModel(responses=[FRAMING]),
        db_path=str(tmp_path / "composed.db"),
    )
    await built.start()
    yield built
    await built.close()


async def _project(application) -> UUID:
    api = create_app(application.service, application.feed, application.turns)
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        created = await http.post("/api/projects", json={"name": f"dlg-{uuid4()}"})
        assert created.status_code == 200
        return UUID(created.json()["id"])


async def test_the_composed_executor_frames_a_dialogue_onto_the_stream(application):
    """Red three ways, and the middle one is the reason this file exists:

    1. The placeholder executor Plan 1 left in `composition.py` still wired --
       `NotImplementedError`. Named obliquely on purpose: that class is gone,
       and spelling it here would keep `grep` for it returning a hit forever.
    2. The real executor wired with `ASK_PROMPT` -- this passes, because a
       fake model ignores its prompt. See the prompt tests for that half; this
       file cannot cover it and says so rather than implying it can.
    3. A `parse_framing` that defaults missing fields -- the goal below comes
       back empty and the assertion names which field.
    """
    project_id = await _project(application)

    dialogue_id = await application.socratic.begin(
        project_id=project_id, topic="the Nicene settlement"
    )
    await application.dialogues.caught_up()

    row = await application.dialogues.get(dialogue_id)
    assert row is not None, "no row: the dialogue projection is not following the log"
    assert row.goal == "why the creed's wording mattered politically"
    assert row.stopping_condition == "the reader separates the settlement from the politics"
    assert row.opening_prompt == "What do you already believe the creed settled?"
    assert row.pending_prompt == row.opening_prompt
    assert row.turn_count == 0


async def test_a_framing_the_model_botched_fails_the_begin_rather_than_the_dialogue(
    tmp_path,
):
    """A model that answered with prose instead of YAML. The dialogue is not
    created at all -- better a failed click than a dialogue with no stopping
    condition, which would look normal until the reader gave up.

    Asserts on the *absence* of a stream, not just on the raise: a `begin` that
    saved the aggregate before framing would leave a goalless dialogue behind
    and still raise.
    """
    from eventsource import collect

    from research_team.domain.socratic_dialogue import SocraticDialogue

    application = build_application(
        model=ToolAwareFakeChatModel(
            responses=[AIMessage(content="I'd be happy to explore that with you!")]
        ),
        db_path=str(tmp_path / "botched.db"),
    )
    await application.start()
    try:
        project_id = await _project(application)

        with pytest.raises(ValueError, match="framing"):
            await application.socratic.begin(project_id=project_id, topic="anything")

        store = application.socratic._transcripts.event_store
        written = await collect(store.read_category(SocraticDialogue.aggregate_type))
        assert written == [], "a dialogue was created without a stopping condition"
    finally:
        await application.close()
