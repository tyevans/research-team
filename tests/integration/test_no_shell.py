"""The agent cannot run commands, and that is load-bearing.

The README's first paragraph promises that nothing the agent does escapes the
process. That promise does not rest on the tool being absent -- deepagents
offers an `execute` tool regardless -- but on our backend not implementing the
protocol that would give it a sandbox to run in.

An invariant that subtle should fail loudly if it ever changes, whether because
the backend grows a method, a dependency changes its defaults, or someone wires
in a different backend without thinking about this.
"""

import os

import pytest
from langchain_core.messages import AIMessage

from research_team.domain import ToolResultRecorded
from tests.conftest import ToolAwareFakeChatModel

ESCAPE_MARKER = "/tmp/research_team_escape_probe"


@pytest.fixture
def shell_attempt() -> ToolAwareFakeChatModel:
    """A model that tries to write outside the process, then reports back."""
    return ToolAwareFakeChatModel(
        responses=[
            AIMessage(
                content="",
                id="a1",
                tool_calls=[
                    {
                        "name": "execute",
                        "args": {"command": f"echo escaped > {ESCAPE_MARKER}"},
                        "id": "e1",
                    }
                ],
            ),
            AIMessage(content="could not", id="a2"),
        ]
    )


@pytest.fixture(autouse=True)
def _no_marker():
    if os.path.exists(ESCAPE_MARKER):
        os.remove(ESCAPE_MARKER)
    yield
    if os.path.exists(ESCAPE_MARKER):
        os.remove(ESCAPE_MARKER)


async def test_a_shell_command_cannot_reach_the_real_filesystem(
    build_application, shell_attempt
):
    application = await build_application(model=shell_attempt)
    session_id = await application.service.create_session()

    await application.service.run_turn(session_id, "escape the sandbox")

    assert not os.path.exists(ESCAPE_MARKER), (
        "the agent wrote to the real filesystem; the process boundary is gone"
    )


async def test_the_refusal_is_recorded_rather_than_swallowed(
    build_application, shell_attempt
):
    """An attempt the log does not mention is an attempt nobody can audit."""
    application = await build_application(model=shell_attempt)
    session_id = await application.service.create_session()

    await application.service.run_turn(session_id, "escape the sandbox")

    events = await application.service.history(session_id)
    results = [e for e in events if isinstance(e, ToolResultRecorded)]
    assert results, "the attempt left no trace in the log"
    assert "not available" in str(results[0].message["data"]["content"])


async def test_the_turn_survives_the_refusal(build_application, shell_attempt):
    """A refused tool is an ordinary tool result, not a crashed turn."""
    application = await build_application(model=shell_attempt)
    session_id = await application.service.create_session()

    outcome = await application.service.run_turn(session_id, "escape the sandbox")

    assert outcome.reply == "could not"
    assert outcome.turn_index == 1
