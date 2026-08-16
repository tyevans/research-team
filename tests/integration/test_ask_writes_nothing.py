"""Asking a project must leave the *project's* record exactly where it found it.

**This file used to assert something strictly stronger, and the weakening is
deliberate.** Both tests read `latest_position()` -- `MAX(global_position)` over
the whole events table -- and required it unchanged, so the ask path could
append nothing at all. `docs/superpowers/specs/2026-08-16-ask-persistence-design.md`
overturns that: an ask is now persisted as an `AskConversation` aggregate with
its own stream, so the global tip *does* move and the old assertion cannot hold.
What the old assertion was standing in for -- that asking a project does not
pollute the project's own record -- is what is asserted here instead, and the
docstrings below say so one test at a time, per `CLAUDE.md`'s rule that a
deliberate break is written down rather than deleted.

What neither form catches, and did not before either: a write that bypasses
`eventsource` entirely -- a row inserted straight into SQLite, a snapshot, a
vector-store write -- is invisible to both the stream read and the feed read.
"""

from uuid import uuid4

from eventsource import StreamId, collect
from langchain_core.messages import AIMessage

from research_team.application.ask import AskAnswer
from research_team.domain import CreateProject, Project
from research_team.domain.corpus import StoreSourceDocument
from tests.conftest import ToolAwareFakeChatModel


async def project_stream(application, project_id):
    """Every event on the project's own aggregate stream, oldest first."""
    store = application.service._repository._store
    stream = StreamId(project_id, Project.aggregate_type)
    return [envelope.event for envelope in await collect(store.read_stream(stream))]


async def test_asking_appends_nothing_to_the_project_s_stream_or_feed(build_application):
    """The design's remaining promise: no session, and nothing on the project.

    Renamed and reworked from `test_asking_appends_no_events`, which asserted
    the store's global position was unmoved. The ask now appends -- one
    `AskConversationStarted` and one `AskTurnRecorded` per successful turn --
    so the global tip moves and that assertion is gone. It appends only under
    the `AskConversation` aggregate type, which is in
    `UNROUTED_AGGREGATE_TYPES`, and the two assertions below are what that
    buys: nothing on the project's stream, and nothing admitted to the
    project's feed.
    """

    class Stub:
        async def run(self, *, project_id, history, question, on_activity):
            return AskAnswer(text="an answer")

    application = await build_application()
    # The wired executor would open a graph and call a model; what is under
    # test is the path around it, so only the model call is stood in for.
    application.ask._executor = Stub()
    project = uuid4()
    before = await application.service._repository.latest_position()
    stream_before = await project_stream(application, project)

    notes = [
        note
        async for note in application.ask.ask(
            project_id=project, chat_id="c", question="what did we find?"
        )
    ]

    assert await project_stream(application, project) == stream_before
    assert await application.service._repository.read_since(before) == []
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
    That reason survives the rewrite unchanged and is why this is the more
    valuable of the two tests.

    Only the chat model is faked, and only because a real one needs the
    network. The graph really opens: `opened` fails this test if a refactor
    ever makes the ask path skip it, at which point the assertions below would
    be passing for the wrong reason.

    Read the claim no further than it goes. It observed `MAX(global_position)`
    until the ask became a write; it now observes the project's own stream and
    the project's feed, which is a *weaker* claim -- an append under any other
    aggregate type passes here and would have failed before. That is the
    deliberate trade the spec takes, and the ask's own `AskConversation` events
    are what it was taken for. A write to the snapshot store or the vector
    store leaves both readings identical, as it always did. And the graph store
    defaults to "memory" under test, so what is genuinely exercised here is the
    replay-and-open path against the real SQLite log.
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
    stream_before = await project_stream(application, project)

    notes = [
        note
        async for note in application.ask.ask(
            project_id=project, chat_id="c", question="what did we find?"
        )
    ]

    assert opened == [project], "the graph was never opened; this proves nothing"
    assert isinstance(notes[-1], AskAnswer)
    assert await project_stream(application, project) == stream_before
    assert await application.service._repository.read_since(before) == []
