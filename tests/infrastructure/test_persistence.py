"""Sessions outlive the process: the point of moving off the in-memory store."""

from uuid import uuid4

from eventsource import StreamId
from eventsource.ports.positions import ExpectedVersion
from langchain_core.messages import AIMessage
from redstring.events.document import DocumentExtracted
from redstring.events.streams import document_stream

from research_team.application.session_service import NO_SEARCH_CLAUSE, project_context
from research_team.application.topics import TOPICS_PROMPT
from research_team.domain import StartSession, StoreSourceDocument
from research_team.domain.learner import LearnerChecklistRecorded
from research_team.domain.project import AdvanceStage, CreateProject, SelectWorkflow
from research_team.domain.topic import OpenTopic
from research_team.infrastructure.agent.corpus_tools import CORPUS_PROMPT
from research_team.infrastructure.agent.fetch import FETCH_CORPUS_PROMPT, FETCH_PROMPT
from research_team.infrastructure.agent.knowledge_tools import KNOWLEDGE_PROMPT
from research_team.infrastructure.persistence import (
    SNAPSHOT_THRESHOLD,
    EventStoreSessionRepository,
    build_aggregate_repository,
    build_corpus_repository,
)
from research_team.infrastructure.persistence.event_store import build_topic_repository
from research_team.workflows import hybrid_default
from tests.conftest import start_session


async def test_session_survives_a_closed_store(fake_model, db_path, build_service, repository):
    first = await build_service(model=fake_model, db_path=db_path)
    session_id = await start_session(first)
    await first.run_turn(session_id, "remember this")
    await first.close()

    await build_service(model=fake_model, db_path=db_path)
    aggregate = await repository.load(session_id)
    assert aggregate.state.turn_index == 1
    assert aggregate.state.messages[0]["data"]["content"] == "remember this"


async def test_reopening_appends_no_second_session_started(fake_model, db_path, build_service):
    first = await build_service(model=fake_model, db_path=db_path)
    session_id = await start_session(first)
    before = len(await first.history(session_id))
    await first.close()

    reopened = await build_service(model=fake_model, db_path=db_path)
    assert len(await reopened.history(session_id)) == before


async def test_reopened_session_continues_the_same_stream(
    fake_model, db_path, build_service, repository
):
    fake_model.responses = [
        AIMessage(content="one", id="a1"),
        AIMessage(content="two", id="a2"),
    ]
    first = await build_service(model=fake_model, db_path=db_path)
    session_id = await start_session(first)
    await first.run_turn(session_id, "first")
    await first.close()

    reopened = await build_service(model=fake_model, db_path=db_path)
    await reopened.run_turn(session_id, "second")

    aggregate = await repository.load(session_id)
    assert aggregate.state.turn_index == 2


async def test_reopening_keeps_the_stored_system_prompt(fake_model, db_path, build_service):
    first = await build_service(model=fake_model, db_path=db_path, system_prompt="ORIGINAL")
    # Named rather than left to `start_session`'s per-call default, because the
    # stored prompt now ends with the project's name and the assertion has to
    # be able to spell it. The default is derived from a `uuid4`, which this
    # test has no handle on.
    session_id = await start_session(first, name="a named project")
    await first.close()

    reopened = await build_service(
        model=fake_model, db_path=db_path, system_prompt="DIFFERENT"
    )
    session = await reopened.load(session_id)
    # Composition appends capability clauses (fetch always, and "no search"
    # because none is configured here) to whatever system_prompt it is given,
    # `start_in_project` appends the knowledge prompt on top, and
    # `project_context` names the project last -- so the stored value is the
    # first process's prompt plus all of those, not "DIFFERENT" plus the
    # second's. The project name rides the *stored* prompt deliberately: a
    # session resumed after a rename runs under the name it started with.
    assert session.state.system_prompt == (
        "ORIGINAL"
        + FETCH_PROMPT
        + NO_SEARCH_CLAUSE
        + KNOWLEDGE_PROMPT
        + CORPUS_PROMPT
        + FETCH_CORPUS_PROMPT
        + TOPICS_PROMPT
        + project_context("a named project")
    )


async def test_files_survive_a_reopen(fake_model, db_path, build_service, repository):
    fake_model.responses = [
        AIMessage(
            content="",
            id="a1",
            tool_calls=[
                {
                    "name": "write_file",
                    "args": {"file_path": "/kept.py", "content": "kept\n"},
                    "id": "t1",
                }
            ],
        ),
        AIMessage(content="wrote", id="a2"),
    ]
    first = await build_service(model=fake_model, db_path=db_path)
    session_id = await start_session(first)
    await first.run_turn(session_id, "write it")
    await first.close()

    await build_service(model=fake_model, db_path=db_path)
    aggregate = await repository.load(session_id)
    assert aggregate.state.files["/kept.py"]["content"] == "kept\n"


async def test_list_sessions_reports_every_session_newest_first(
    fake_model, db_path, build_service
):
    service = await build_service(model=fake_model, db_path=db_path)
    session_id = await start_session(service)
    await service.run_turn(session_id, "the first one")
    second = await start_session(service)

    summaries = await service.list_sessions()
    assert len(summaries) == 2
    assert summaries[0].session_id == second
    assert summaries[0].started_at >= summaries[1].started_at


async def test_session_summary_describes_the_session(fake_model, db_path, build_service):
    service = await build_service(model=fake_model, db_path=db_path)
    session_id = await start_session(service)
    await service.run_turn(session_id, "a memorable opening line")

    summary = next(s for s in await service.list_sessions() if s.session_id == session_id)
    assert summary.turns == 1
    assert summary.first_message == "a memorable opening line"


async def test_starting_a_session_leaves_the_previous_one_alone(
    fake_model, db_path, build_service, repository
):
    """A second session is a second stream, not a reset of the store.

    Two projects rather than one, which is the only way to have two live
    sessions now -- a project holds one at a time and would reject the second.
    That rejection is the project rule and is tested where it lives; the claim
    here is about the store, so the sessions are kept out of each other's way.
    """
    service = await build_service(model=fake_model, db_path=db_path)
    original = await start_session(service)
    new_id = await start_session(service)

    assert new_id != original
    assert (await repository.load(original)).version >= 1


async def test_sessions_are_isolated_from_each_other(
    fake_model, db_path, build_service, repository
):
    service = await build_service(model=fake_model, db_path=db_path)
    first = await start_session(service)
    await service.run_turn(first, "in the first session")
    second = await start_session(service)

    assert (await repository.load(second)).state.messages == []


def test_aggregate_repository_snapshots_are_configured(store, snapshot_store):
    """Snapshotting is what keeps loads cheap as a session's log grows."""
    aggregates = build_aggregate_repository(store, snapshot_store=snapshot_store)
    assert aggregates.snapshot_threshold == SNAPSHOT_THRESHOLD == 50
    assert aggregates.has_snapshot_support


async def test_read_since_carries_topic_events(tmp_path):
    """The research page's whole live path starts here.

    `open_topic` appends to this log, and both `seeding.py` and `ResearchView`
    tell the reader that a client sees new topics by invalidating on those
    frames. Until this test existed the feed filtered every `Topic` stream out,
    so no topic event ever reached the SSE connection and a topic only appeared
    on a reload. Asserting the aggregate type, not just the count: an entry
    that arrives labelled `Session` sends the browser looking for a
    session that does not exist.
    """
    repository = EventStoreSessionRepository.open(str(tmp_path / "sessions.db"))
    try:
        topics = build_topic_repository(repository.store)
        topic = topics.create_new(uuid4())
        topic.execute(
            OpenTopic(
                topic_id=topic.aggregate_id,
                project_id=uuid4(),
                question="Does spacing help?",
                rationale="the syllabus asserts it without a citation",
            )
        )
        await topics.save(topic)

        entries = await repository.read_since(None)

        assert [(entry.aggregate_id, entry.aggregate_type) for entry in entries] == [
            (topic.aggregate_id, "Topic")
        ]
    finally:
        await repository.close()


async def test_read_since_ignores_events_from_other_aggregate_types(tmp_path):
    """A shared store carries foreign streams; the feed must not see them.

    The foreign stream was `Project` until the feed was taught to carry it,
    which made this test assert the opposite of the one beside it. It is
    `LearnerProgress` now -- the exclusion `UNROUTED_AGGREGATE_TYPES` documents
    and the guard checks -- so the two tests agree, and this one still fails if
    the scoping is dropped in favour of an unfiltered read.
    """
    repository = EventStoreSessionRepository.open(str(tmp_path / "sessions.db"))
    try:
        session_id = uuid4()
        session = repository.create(session_id)
        session.execute(
            StartSession(
                session_id=session.aggregate_id,
                system_prompt="p",
                model_name="m",
                project_id=uuid4(),
            )
        )
        await repository.save(session)

        learner_id = uuid4()
        await repository.store.append(
            StreamId(aggregate_id=learner_id, category="LearnerProgress"),
            [
                LearnerChecklistRecorded(
                    aggregate_id=learner_id,
                    path="lesson.md",
                    component_id="check-1",
                    checked=[0],
                )
            ],
            ExpectedVersion.any_(),
        )

        entries = await repository.read_since(None)

        assert entries, "the session's own events should still arrive"
        assert all(entry.aggregate_id == session_id for entry in entries)
    finally:
        await repository.close()


async def test_read_since_carries_knowledge_graph_events(tmp_path):
    """The graph pane's live path starts here, the way the topic list's did.

    redstring writes `DocumentExtracted` into this same log, and the graph the
    research page draws is exactly what that event added. Until this test the
    feed admitted only `Session` and `Topic`, so an extraction that ran
    while a tab was open reached the browser through nothing at all and the
    entities appeared on the next reload.

    Asserting the aggregate type rather than only the count: `Document` is what
    tells `_sse` to write a graph frame instead of a session one, and an entry
    arriving as `Session` would send the session tree after an aggregate
    that is a document. Asserting the tenant for the same reason -- the frame
    is addressed to a project, and the event is the only place that project id
    exists on this path.
    """
    repository = EventStoreSessionRepository.open(str(tmp_path / "sessions.db"))
    try:
        project_id = uuid4()
        stream = document_stream(tenant_id=project_id, source_id="paper-1")
        await repository.store.append(
            stream,
            [
                DocumentExtracted(
                    aggregate_id=stream.aggregate_id,
                    tenant_id=project_id,
                    source_id="paper-1",
                    model_version="test-model",
                )
            ],
            ExpectedVersion.any_(),
        )

        entries = await repository.read_since(None)

        assert [entry.aggregate_type for entry in entries] == ["Document"]
        assert entries[0].event.tenant_id == project_id
    finally:
        await repository.close()


async def test_read_since_carries_corpus_events(tmp_path):
    """The documents pane's live path, and the reason it is not the graph's.

    A document is stored on the `Corpus` aggregate *before* it is extracted,
    and an extraction that fails leaves the document stored and emits nothing
    on redstring's streams at all. So `Document`/`Consolidation` frames cannot
    stand in for this one: a pane refreshed only on those would miss every
    source whose extraction failed, which is exactly the case a reader most
    wants to see listed.

    A corpus shares its project's UUID, so the entry's `aggregate_id` is the
    project id -- which is what lets `_sse` address the frame without reading
    anything. Asserting it here rather than only the type: the whole frame
    depends on that identity holding.
    """
    repository = EventStoreSessionRepository.open(str(tmp_path / "sessions.db"))
    try:
        project_id = uuid4()
        corpus = build_corpus_repository(repository.store)
        aggregate = await corpus.load_or_create(project_id)
        aggregate.execute(
            StoreSourceDocument(
                corpus_id=project_id, source_id="paper-1", text="Ada worked with Charles."
            )
        )
        await corpus.save(aggregate)

        entries = await repository.read_since(None)

        assert [(entry.aggregate_id, entry.aggregate_type) for entry in entries] == [
            (project_id, "Corpus")
        ]
    finally:
        await repository.close()


async def test_read_since_carries_project_events(tmp_path):
    """The course page's live path, and the fourth instance of one bug.

    `advance_stage` appends `ProjectStageAdvanced` to this log and the rail on the
    course page *is* what that event moved. Until this test the feed admitted
    `Session`, `Topic`, `Corpus` and redstring's categories and nothing
    else, so a stage advance reached the browser through nothing at all and the
    rail only moved on a reload -- the same shape as topics before `c4d81a9`
    and the graph before #70.

    Asserting the aggregate type rather than only the count, for the reason
    `test_read_since_carries_topic_events` gives: an entry arriving labelled
    `Session` sends the session tree after an aggregate that is a
    project. Asserting the aggregate id too, because a project's aggregate id
    *is* the project id and that identity is the whole of how `_sse` addresses
    the frame -- there is no lookup behind it.

    Both events, not just the advance. `ProjectWorkflowSelected` is what turns the
    course page from a 409 into a rail, so a feed that carried the advance and
    not the selection would leave the page reading "no course to show" until a
    reload -- the same defect one event earlier.
    """
    repository = EventStoreSessionRepository.open(str(tmp_path / "sessions.db"))
    try:
        project_id = uuid4()
        project = repository.projects.create_new(project_id)
        project.execute(CreateProject(project_id=project_id, name="Spacing"))
        project.execute(SelectWorkflow(preset=hybrid_default))
        project.execute(
            AdvanceStage(
                preset=hybrid_default,
                to_stage="hybrid.step1.framing",
                decided_by="human",
                gate_decision="approve",
            )
        )
        await repository.projects.save(project)

        entries = await repository.read_since(None)

        assert [(entry.aggregate_id, entry.aggregate_type) for entry in entries] == [
            (project_id, "Project"),
            (project_id, "Project"),
            (project_id, "Project"),
        ]
        assert [type(entry.event).__name__ for entry in entries] == [
            "ProjectCreated",
            "ProjectWorkflowSelected",
            "ProjectStageAdvanced",
        ]
    finally:
        await repository.close()
