"""That subagents can be chosen per turn, not once per process.

The executor is built once and serves every session. Without this seam the
authoring roster would be offered to every chat session in the application --
six subagents a chat turn has no use for, in every system prompt.

The seam is tested rather than the agent it builds: asserting on
`create_deep_agent`'s output means reaching into a compiled graph, which
couples the test to deepagents' internals and breaks on a minor bump. Both
dependencies here are pre-1.0 with a stated no-shim policy, so a minor is
exactly where that would land.
"""

from uuid import uuid4

import pytest

from research_team.domain import Session, SessionPurpose, StartSession
from research_team.infrastructure.agent.deep_agent import DeepAgentTurnExecutor

STATIC = [{"name": "worker", "description": "d", "system_prompt": "p"}]
PER_TURN = [{"name": "unit-critic", "description": "d", "system_prompt": "p"}]


def _session() -> Session:
    session = Session(uuid4())
    session.execute(
        StartSession(
            session_id=session.aggregate_id,
            system_prompt="be brief",
            model_name="fake",
            project_id=uuid4(),
            purpose=SessionPurpose.CHAT,
        )
    )
    return session


def executor(**kwargs):
    return DeepAgentTurnExecutor(model=None, **kwargs)


@pytest.mark.asyncio
async def test_the_static_list_is_used_when_no_provider_is_given():
    """An executor wired as it is today must build exactly what it built
    before this seam existed."""
    session = _session()
    assert await executor(subagents=STATIC)._turn_subagents(session) == STATIC


@pytest.mark.asyncio
async def test_the_provider_replaces_the_static_list():
    async def provider(session):
        return PER_TURN

    session = _session()
    ex = executor(subagents=STATIC, subagents_provider=provider)
    got = await ex._turn_subagents(session)
    assert got == PER_TURN


@pytest.mark.asyncio
async def test_the_provider_is_given_the_session():
    """It selects on purpose, so it must see the session rather than a copy of
    some field the caller thought to pass."""
    seen = []

    async def provider(session):
        seen.append(session)
        return []

    session = _session()
    await executor(subagents_provider=provider)._turn_subagents(session)
    assert seen == [session]
