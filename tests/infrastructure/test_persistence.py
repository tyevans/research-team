"""Sessions outlive the process: the point of moving off the in-memory store."""

from uuid import uuid4

from eventsource import StreamId
from eventsource.ports.positions import ExpectedVersion
from langchain_core.messages import AIMessage

from research_team.application.session_service import NO_SEARCH_CLAUSE
from research_team.application.topics import TOPICS_PROMPT
from research_team.domain import StartSession
from research_team.domain.project import ProjectCreated
from research_team.infrastructure.agent.corpus_tools import CORPUS_PROMPT
from research_team.infrastructure.agent.fetch import FETCH_CORPUS_PROMPT, FETCH_PROMPT
from research_team.infrastructure.agent.knowledge_tools import KNOWLEDGE_PROMPT
from research_team.infrastructure.persistence import (
    SNAPSHOT_THRESHOLD,
    EventStoreSessionRepository,
    build_aggregate_repository,
)
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
    session_id = await start_session(first)
    await first.close()

    reopened = await build_service(
        model=fake_model, db_path=db_path, system_prompt="DIFFERENT"
    )
    session = await reopened.load(session_id)
    # Composition appends capability clauses (fetch always, and "no search"
    # because none is configured here) to whatever system_prompt it is given,
    # and `start_in_project` appends the knowledge prompt on top -- so the
    # stored value is the first process's prompt plus both suffixes, not
    # "DIFFERENT" plus the second's.
    assert session.state.system_prompt == (
        "ORIGINAL"
        + FETCH_PROMPT
        + NO_SEARCH_CLAUSE
        + KNOWLEDGE_PROMPT
        + CORPUS_PROMPT
        + FETCH_CORPUS_PROMPT
        + TOPICS_PROMPT
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


async def test_read_since_ignores_events_from_other_aggregate_types(tmp_path):
    """A shared store carries foreign streams; the session feed must not see them."""
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

        project_id = uuid4()
        await repository.store.append(
            StreamId(aggregate_id=project_id, category="Project"),
            [ProjectCreated(aggregate_id=project_id, name="research")],
            ExpectedVersion.any_(),
        )

        entries = await repository.read_since(None)

        assert entries, "the session's own events should still arrive"
        assert all(entry.session_id == session_id for entry in entries)
    finally:
        await repository.close()
