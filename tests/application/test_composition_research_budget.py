"""That the research budget reaches the executor an authoring turn runs on.

The wiring assertion, written for the reason
`test_composition_authoring_subagents.py` opens with: a middleware defined,
unit-tested and never installed passes every test in
`tests/infrastructure/test_research_budget.py`, and the running system spirals
exactly as it did before. CLAUDE.md's Events section calls this shape the one
where "never wired" and "working" are indistinguishable.

So the assertions are on the provider the executor actually holds --
`app.service._executor._middleware_provider` -- awaited with a real `Session`.
Reaching a private attribute is the price, and the file beside this one already
pays it for the same reason.
"""

from uuid import uuid4

import pytest

from research_team.domain import Session, SessionPurpose, StartSession
from research_team.infrastructure.agent.research_budget import ResearchBudget


def _session(purpose: SessionPurpose) -> Session:
    session = Session(uuid4())
    session.execute(
        StartSession(
            session_id=session.aggregate_id,
            system_prompt="be brief",
            model_name="fake",
            project_id=uuid4(),
            purpose=purpose,
        )
    )
    return session


async def _budgets(app, purpose: SessionPurpose) -> list[ResearchBudget]:
    installed = await app.service._executor._middleware_provider(_session(purpose))
    return [m for m in installed if isinstance(m, ResearchBudget)]


@pytest.mark.asyncio
async def test_an_authoring_turn_is_bounded_and_a_chat_turn_is_not(build_application):
    """Both directions. Asserting only that authoring gets one passes a build
    that installs it on every session -- which would silently bound a person
    typing in the console, where reading widely is the entire point."""
    app = await build_application(model=None)

    assert len(await _budgets(app, SessionPurpose.COURSE_AUTHORING)) == 1
    assert await _budgets(app, SessionPurpose.CHAT) == []


@pytest.mark.asyncio
async def test_every_turn_gets_its_own_budget(build_application):
    """Two calls, two instances. One shared instance would leave phase 4 of a
    four-phase run with whatever phases 1-3 spent, so it would begin with no
    reading at all -- and every test in
    `tests/infrastructure/test_research_budget.py` would still pass, because
    they construct their own."""
    app = await build_application(model=None)

    first = await _budgets(app, SessionPurpose.COURSE_AUTHORING)
    second = await _budgets(app, SessionPurpose.COURSE_AUTHORING)

    assert first[0] is not second[0]


@pytest.mark.asyncio
async def test_the_bound_can_be_turned_off(build_application, monkeypatch):
    """`AGENT_AUTHORING_ROUNDS=0` installs nothing.

    The escape hatch the README documents, and worth pinning because it is the
    only recourse for a corpus the measured default is wrong about. A build
    that read the knob and then installed the middleware anyway would look
    identical from every surface.
    """
    monkeypatch.setenv("AGENT_AUTHORING_ROUNDS", "0")
    app = await build_application(model=None)

    assert await _budgets(app, SessionPurpose.COURSE_AUTHORING) == []
