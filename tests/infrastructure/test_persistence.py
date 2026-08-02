"""Sessions outlive the process: the point of moving off the in-memory store."""

from langchain_core.messages import AIMessage

from research_team.infrastructure.persistence import (
    SNAPSHOT_THRESHOLD,
    build_aggregate_repository,
)


async def test_session_survives_a_closed_store(fake_model, db_path, build_service, repository):
    first = await build_service(model=fake_model, db_path=db_path)
    await first.run_turn("remember this")
    session_id = first.session_id
    await first.close()

    await build_service(model=fake_model, db_path=db_path, session_id=session_id)
    aggregate = await repository.load(session_id)
    assert aggregate.state.turn_index == 1
    assert aggregate.state.messages[0]["data"]["content"] == "remember this"


async def test_resuming_appends_no_second_session_started(fake_model, db_path, build_service):
    first = await build_service(model=fake_model, db_path=db_path)
    session_id = first.session_id
    before = len(await first.history())
    await first.close()

    resumed = await build_service(
        model=fake_model, db_path=db_path, session_id=session_id
    )
    assert len(await resumed.history()) == before


async def test_resumed_session_continues_the_same_stream(
    fake_model, db_path, build_service, repository
):
    fake_model.responses = [
        AIMessage(content="one", id="a1"),
        AIMessage(content="two", id="a2"),
    ]
    first = await build_service(model=fake_model, db_path=db_path)
    await first.run_turn("first")
    session_id = first.session_id
    await first.close()

    resumed = await build_service(
        model=fake_model, db_path=db_path, session_id=session_id
    )
    await resumed.run_turn("second")

    aggregate = await repository.load(session_id)
    assert aggregate.state.turn_index == 2


async def test_resuming_keeps_the_stored_system_prompt(fake_model, db_path, build_service):
    first = await build_service(
        model=fake_model, db_path=db_path, system_prompt="ORIGINAL"
    )
    session_id = first.session_id
    await first.close()

    resumed = await build_service(
        model=fake_model, db_path=db_path, session_id=session_id
    )
    assert resumed.system_prompt == "ORIGINAL"


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
    await first.run_turn("write it")
    session_id = first.session_id
    await first.close()

    await build_service(model=fake_model, db_path=db_path, session_id=session_id)
    aggregate = await repository.load(session_id)
    assert aggregate.state.files["/kept.py"]["content"] == "kept\n"


async def test_list_sessions_reports_every_session_newest_first(
    fake_model, db_path, build_service
):
    service = await build_service(model=fake_model, db_path=db_path)
    await service.run_turn("the first one")
    second = await service.start_session()

    summaries = await service.list_sessions()
    assert len(summaries) == 2
    assert summaries[0].session_id == second
    assert summaries[0].started_at >= summaries[1].started_at


async def test_session_summary_describes_the_session(fake_model, db_path, build_service):
    service = await build_service(model=fake_model, db_path=db_path)
    await service.run_turn("a memorable opening line")

    summary = next(
        s for s in await service.list_sessions() if s.session_id == service.session_id
    )
    assert summary.turns == 1
    assert summary.first_message == "a memorable opening line"


async def test_start_session_switches_the_service(
    fake_model, db_path, build_service, repository
):
    service = await build_service(model=fake_model, db_path=db_path)
    original = service.session_id
    new_id = await service.start_session()

    assert service.session_id == new_id != original
    assert (await repository.load(original)).version >= 1


async def test_sessions_are_isolated_from_each_other(
    fake_model, db_path, build_service, repository
):
    service = await build_service(model=fake_model, db_path=db_path)
    await service.run_turn("in the first session")
    await service.start_session()

    assert (await repository.load(service.session_id)).state.messages == []


def test_aggregate_repository_snapshots_are_configured(store, db_path):
    """Snapshotting is what keeps loads cheap as a session's log grows."""
    aggregates = build_aggregate_repository(store, db_path)
    assert aggregates.snapshot_threshold == SNAPSHOT_THRESHOLD == 50
    assert aggregates.has_snapshot_support
