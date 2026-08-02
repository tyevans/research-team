"""Hits the real endpoint. Deselected by default; run with `-m live`."""

import pytest

from research_team import runtime as rt

pytestmark = pytest.mark.live


async def test_agent_writes_a_file_against_the_real_model():
    runtime = await rt.build_runtime()
    await rt.run_turn(
        runtime,
        "Create a file /fizzbuzz.py containing a fizzbuzz function. "
        "Use the write_file tool. Do not explain.",
    )

    aggregate = await runtime.repo.load(runtime.session_id)
    assert aggregate.state.files, "agent produced no files"
    assert any("fizz" in data["content"].lower() for data in aggregate.state.files.values())
