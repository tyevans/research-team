"""Sessions outlive the process: the point of moving off the in-memory store."""

import pytest
from langchain_core.messages import AIMessage

from research_team import runtime as rt


async def test_session_survives_a_closed_store(fake_model, db_path):
    first = await rt.build_runtime(model=fake_model, db_path=db_path)
    await rt.run_turn(first, "remember this")
    session_id = first.session_id
    await first.close()

    reopened = await rt.build_runtime(
        model=fake_model, db_path=db_path, session_id=session_id
    )
    aggregate = await reopened.repo.load(session_id)
    assert aggregate.state.turn_index == 1
    assert aggregate.state.messages[0]["data"]["content"] == "remember this"


async def test_resuming_appends_no_second_session_started(fake_model, db_path):
    first = await rt.build_runtime(model=fake_model, db_path=db_path)
    session_id = first.session_id
    before = len(await rt.history(first))
    await first.close()

    resumed = await rt.build_runtime(
        model=fake_model, db_path=db_path, session_id=session_id
    )
    assert len(await rt.history(resumed)) == before


async def test_resumed_session_continues_the_same_stream(fake_model, db_path):
    fake_model.responses = [
        AIMessage(content="one", id="a1"),
        AIMessage(content="two", id="a2"),
    ]
    first = await rt.build_runtime(model=fake_model, db_path=db_path)
    await rt.run_turn(first, "first")
    session_id = first.session_id
    await first.close()

    resumed = await rt.build_runtime(
        model=fake_model, db_path=db_path, session_id=session_id
    )
    await rt.run_turn(resumed, "second")

    aggregate = await resumed.repo.load(session_id)
    assert aggregate.state.turn_index == 2


async def test_resuming_keeps_the_stored_system_prompt(fake_model, db_path):
    first = await rt.build_runtime(
        model=fake_model, db_path=db_path, system_prompt="ORIGINAL"
    )
    session_id = first.session_id
    await first.close()

    resumed = await rt.build_runtime(
        model=fake_model, db_path=db_path, session_id=session_id
    )
    assert resumed.system_prompt == "ORIGINAL"


async def test_files_survive_a_reopen(fake_model, db_path):
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
    first = await rt.build_runtime(model=fake_model, db_path=db_path)
    await rt.run_turn(first, "write it")
    session_id = first.session_id
    await first.close()

    reopened = await rt.build_runtime(
        model=fake_model, db_path=db_path, session_id=session_id
    )
    aggregate = await reopened.repo.load(session_id)
    assert aggregate.state.files["/kept.py"]["content"] == "kept\n"


async def test_list_sessions_reports_every_session_newest_first(fake_model, db_path):
    runtime = await rt.build_runtime(model=fake_model, db_path=db_path)
    await rt.run_turn(runtime, "the first one")
    second = await rt.start_session(runtime)

    summaries = await rt.list_sessions(runtime)
    assert len(summaries) == 2
    assert summaries[0].session_id == second
    assert summaries[0].started_at >= summaries[1].started_at


async def test_session_summary_describes_the_session(fake_model, db_path):
    runtime = await rt.build_runtime(model=fake_model, db_path=db_path)
    await rt.run_turn(runtime, "a memorable opening line")

    summary = next(
        s for s in await rt.list_sessions(runtime) if s.session_id == runtime.session_id
    )
    assert summary.turns == 1
    assert summary.first_message == "a memorable opening line"


async def test_start_session_switches_the_runtime(fake_model, db_path):
    runtime = await rt.build_runtime(model=fake_model, db_path=db_path)
    original = runtime.session_id
    new_id = await rt.start_session(runtime)

    assert runtime.session_id == new_id != original
    assert (await runtime.repo.load(original)).version >= 1


async def test_sessions_are_isolated_from_each_other(fake_model, db_path):
    runtime = await rt.build_runtime(model=fake_model, db_path=db_path)
    await rt.run_turn(runtime, "in the first session")
    await rt.start_session(runtime)

    assert (await runtime.repo.load(runtime.session_id)).state.messages == []
