"""Asking a project must leave its log exactly where it found it.

This is what makes the ask page ephemeral in fact rather than by intention.
It fails the moment anything on that path appends an event.
"""

from uuid import uuid4

from langchain_core.messages import AIMessage

from research_team.application.ask import AskAnswer
from research_team.domain import CreateProject
from research_team.domain.corpus import StoreSourceDocument
from tests.conftest import ToolAwareFakeChatModel


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

    notes = [
        note
        async for note in application.ask.ask(
            project_id=uuid4(), chat_id="c", question="what did we find?"
        )
    ]

    assert await application.service._repository.latest_position() == before
    # Both halves, because a generator that yielded nothing would satisfy the
    # position assertion perfectly and prove nothing about the ask.
    assert notes == [AskAnswer(text="an answer")]


async def test_the_real_executor_opens_a_graph_and_still_appends_nothing(build_application):
    """The same claim with `DeepAgentAskExecutor` wired, not stubbed.

    The test above stands in for the executor, which is the one component that
    opens the redstring graph -- and that graph is backed by the same SQLite
    file, event store and snapshot store the sessions live in. So the strongest
    candidate for an accidental write is exactly what the stub hides: a replay
    on open, a consolidation, a snapshot written as a side effect of reading.

    Only the chat model is faked, and only because a real one needs the
    network. The graph really opens: `opened` fails this test if a refactor
    ever makes the ask path skip it, at which point the assertion below would
    be passing for the wrong reason.
    """
    project = uuid4()
    application = await build_application(
        model=ToolAwareFakeChatModel(responses=[AIMessage(content="an answer", id="a1")])
    )
    aggregate = application.service.projects.create_new(project)
    aggregate.execute(CreateProject(project_id=project, name="tollers"))
    await application.service.projects.save(aggregate)
    # Attached only to reach the corpus repository below, which composition
    # builds on the attached path. Everything this costs -- and any event it
    # writes -- happens before the position is read, so it cannot mask a write
    # the ask makes.
    await application.attach_project(project)
    # Material, so the graph has something to open over rather than being a
    # bare tenant -- an empty project could take a shortcut that a real one
    # does not, and it is the loaded path this claim has to hold on.
    corpus = await application.knowledge._corpus.load_or_create(project)
    corpus.execute(
        StoreSourceDocument(
            corpus_id=project,
            source_id="s1",
            text="Tollers were bred in Yarmouth County.",
            uri="https://example.invalid/toller",
            title="The breed",
        )
    )
    await application.knowledge._corpus.save(corpus)

    executor = application.ask._executor
    opened: list = []
    open_graph = executor._open_graph

    async def watched(target_project_id):
        result = await open_graph(target_project_id)
        opened.append(target_project_id)
        return result

    executor._open_graph = watched
    before = await application.service._repository.latest_position()

    notes = [
        note
        async for note in application.ask.ask(
            project_id=project, chat_id="c", question="what did we find?"
        )
    ]

    assert opened == [project], "the graph was never opened; this proves nothing"
    assert isinstance(notes[-1], AskAnswer)
    assert await application.service._repository.latest_position() == before
