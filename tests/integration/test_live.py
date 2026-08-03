"""Hits the real endpoint. Deselected by default; run with `-m live`."""

import pytest

pytestmark = pytest.mark.live


async def test_agent_writes_a_file_against_the_real_model(build_service):
    service = build_service()
    session_id = await service.create_session()
    await service.run_turn(
        session_id,
        "Create a file /fizzbuzz.py containing a fizzbuzz function. "
        "Use the write_file tool. Do not explain.",
    )

    aggregate = await service.load(session_id)
    assert aggregate.state.files, "agent produced no files"
    assert any("fizz" in data["content"].lower() for data in aggregate.state.files.values())
