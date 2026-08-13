"""Asking a project must leave its log exactly where it found it.

This is what makes the ask page ephemeral in fact rather than by intention.
It fails the moment anything on that path appends an event.
"""

from uuid import uuid4

from research_team.application.ask import AskAnswer


async def test_asking_appends_no_events(build_application):
    """The whole design rests on this: no session, no events, no tip moved."""

    class Stub:
        async def run(self, *, project_id, history, question, on_activity):
            return AskAnswer(text="an answer")

    application = await build_application()
    # The wired executor would open a graph and call a model; what is under
    # test is the path around it, so only the model call is stood in for.
    application.ask._executor = Stub()
    before = await application.service._repository.latest_position()

    async for _ in application.ask.ask(
        project_id=uuid4(), chat_id="c", question="what did we find?"
    ):
        pass

    assert await application.service._repository.latest_position() == before
