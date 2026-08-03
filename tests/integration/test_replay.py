import pytest
from langchain_core.messages import AIMessage

from research_team.domain import CodingSession


@pytest.fixture
def scripted_model(fake_model):
    fake_model.responses = [
        AIMessage(
            content="",
            id="a1",
            tool_calls=[
                {
                    "name": "write_file",
                    "args": {"file_path": "/app.py", "content": "x = 1\n"},
                    "id": "t1",
                }
            ],
        ),
        AIMessage(content="created app.py", id="a2"),
        AIMessage(
            content="",
            id="a3",
            tool_calls=[
                {
                    "name": "edit_file",
                    "args": {"file_path": "/app.py", "old_string": "1", "new_string": "2"},
                    "id": "t2",
                }
            ],
        ),
        AIMessage(content="updated app.py", id="a4"),
    ]
    return fake_model


async def test_refolding_reproduces_state_exactly(build_service, store, db_path, scripted_model):
    service = build_service(model=scripted_model, db_path=db_path)
    session_id = await service.create_session()
    await service.run_turn(session_id, "create app.py")
    await service.run_turn(session_id, "change 1 to 2")

    live = await service.load(session_id)

    # Rebuild from event zero with a repository that has no snapshot cache.
    from eventsource.application.aggregates.repository import AggregateRepository

    cold_repo = AggregateRepository(store, CodingSession)
    replayed = await cold_repo.load(session_id)

    assert replayed.version == live.version
    assert replayed.state == live.state


async def test_replay_reproduces_file_content(build_service, store, db_path, scripted_model):
    service = build_service(model=scripted_model, db_path=db_path)
    session_id = await service.create_session()
    await service.run_turn(session_id, "create app.py")
    await service.run_turn(session_id, "change 1 to 2")

    from eventsource.application.aggregates.repository import AggregateRepository

    cold_repo = AggregateRepository(store, CodingSession)
    replayed = await cold_repo.load(session_id)

    assert replayed.state.files["/app.py"]["content"] == "x = 2\n"


async def test_replay_is_deterministic_across_repeats(
    build_service, store, db_path, scripted_model
):
    service = build_service(model=scripted_model, db_path=db_path)
    session_id = await service.create_session()
    await service.run_turn(session_id, "create app.py")

    from eventsource.application.aggregates.repository import AggregateRepository

    first = await AggregateRepository(store, CodingSession).load(session_id)
    second = await AggregateRepository(store, CodingSession).load(session_id)

    assert first.state == second.state


async def test_fork_diverges_without_affecting_original(
    build_service, repository, db_path, scripted_model
):
    service = build_service(model=scripted_model, db_path=db_path)
    session_id = await service.create_session()
    await service.run_turn(session_id, "create app.py")
    await service.run_turn(session_id, "change 1 to 2")

    original_state = (await service.load(session_id)).state
    forked_id = await service.fork(session_id, at=2)
    forked = await repository.load(forked_id)

    assert forked.state != original_state
    assert (await service.load(session_id)).state == original_state
