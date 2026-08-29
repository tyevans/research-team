"""That the model can be chosen per turn, not once per process.

The defect this seam closes: `build_model()` answers for the process, and
`_build_application` calls it once and hands the result to an executor that
outlives every project. So `AGENT_MODEL`, `AGENT_BASE_URL` and `AGENT_API_KEY`
saved against a project stored correctly, resolved correctly through
`/api/settings/resolved`, and were read by nothing on the turn path -- a person
could set a model, watch it save, watch it resolve, and watch every turn go to
the endpoint the process started with. Reported as connection errors from topic
seeding, which is a turn, and where a stale `base_url` fails loudly rather than
merely answering worse.

The seam is tested rather than the agent it builds, for the reason its
subagent twin gives: asserting on `create_deep_agent`'s output means reaching
into a compiled graph and couples the test to a pre-1.0 dependency's internals.
"""

from uuid import uuid4

import pytest

from research_team.domain import Session, SessionPurpose, StartSession
from research_team.infrastructure.agent.deep_agent import DeepAgentTurnExecutor

STATIC = object()
PER_TURN = object()


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
    return DeepAgentTurnExecutor(model=STATIC, **kwargs)


@pytest.mark.asyncio
async def test_the_constructed_model_is_used_when_no_provider_is_given():
    """An executor wired as every existing caller wires it -- and as every
    existing test does -- must build precisely the agent it built before this
    seam existed. This is the assertion that makes the change additive."""
    assert await executor()._turn_model(_session()) is STATIC


@pytest.mark.asyncio
async def test_the_provider_replaces_the_constructed_model():
    async def provider(session):
        return PER_TURN

    assert await executor(model_provider=provider)._turn_model(_session()) is PER_TURN


@pytest.mark.asyncio
async def test_a_provider_answering_none_falls_back_rather_than_failing():
    """`None` is the ordinary answer for a session belonging to no project, and
    for a build whose caller injected a model. It is not an error and must not
    take the turn down -- a settings lookup that finds nothing to say should
    leave the process answer standing."""

    async def provider(session):
        return None

    assert await executor(model_provider=provider)._turn_model(_session()) is STATIC


@pytest.mark.asyncio
async def test_the_provider_is_given_the_session():
    """It resolves on `session.state.project_id`, so it must see the session
    rather than a copy of some field the caller thought to pass. A provider
    handed only a session id could not reach the project, which is the whole
    key resolution is done on."""
    seen = []

    async def provider(session):
        seen.append(session)
        return PER_TURN

    session = _session()
    await executor(model_provider=provider)._turn_model(session)

    assert seen == [session]
    assert seen[0].state.project_id is not None
