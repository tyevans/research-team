"""That a model saved against a project reaches the turn that project runs.

This is the wiring test the co-mention channel went without, in the shape
CLAUDE.md states it: a port with one production adapter, verified on each side
and never driven end to end. Here both halves shipped and never met --
`EffectiveSettings` resolved a project's bundle correctly and
`DeepAgentTurnExecutor` held one model for the life of the process, and nothing
asked whether the resolved value ever reached the executor. It did not, for the
whole life of the settings feature.

So the assertion is on the provider the executor **actually holds** --
`app.service._executor._model_provider` -- awaited with a real `Session`, and
on the model name that comes back. Asserting on `EffectiveSettings.research`
alone would keep passing with `model_provider=turn_model` deleted from the
`DeepAgentTurnExecutor(...)` call, which is exactly the failure this file
exists to catch. Reaching a private attribute is the price, and
`test_composition_authoring_subagents.py` pays it beside this for the same
reason.
"""

from uuid import uuid4

import pytest

from research_team.domain import Session, SessionPurpose, StartSession
from research_team.domain.settings import Scope, ScopeRef
from research_team.infrastructure import config


def _session(project_id) -> Session:
    session = Session(uuid4())
    session.execute(
        StartSession(
            session_id=session.aggregate_id,
            system_prompt="be brief",
            model_name="fake",
            project_id=project_id,
            purpose=SessionPurpose.CHAT,
        )
    )
    return session


@pytest.mark.asyncio
async def test_a_project_scoped_model_reaches_the_executor_the_application_built(
    build_application,
):
    """The reported defect, end to end.

    Proved red by deleting `model_provider=turn_model` from the executor call:
    the provider is `None` and this fails at the first assertion, which is the
    line that says the two halves were never connected.
    """
    app = await build_application(model=None)
    project_id = uuid4()
    await app.settings.store.put(
        ScopeRef(Scope.PROJECT, str(project_id)), "model", "the-projects-own-model"
    )

    provider = app.service._executor._model_provider
    assert provider is not None

    resolved = await provider(_session(project_id))

    assert resolved is not None
    assert resolved.model_name == "the-projects-own-model"


@pytest.mark.asyncio
async def test_a_project_scoped_endpoint_reaches_it_too(build_application):
    """The half that produced connection errors rather than worse answers.

    A wrong `base_url` is the loud failure, and it is the one that surfaced
    from topic seeding: whatever the settings page said, every turn dialled the
    endpoint the process started with.
    """
    app = await build_application(model=None)
    project_id = uuid4()
    await app.settings.store.put(
        ScopeRef(Scope.PROJECT, str(project_id)), "base_url", "http://192.168.1.14:8080/v1/"
    )

    resolved = await app.service._executor._model_provider(_session(project_id))

    assert str(resolved.openai_api_base) == "http://192.168.1.14:8080/v1/"


@pytest.mark.asyncio
async def test_a_session_with_no_project_falls_back_to_the_process_model(build_application):
    """`state.project_id` is `| None`, so the provider has to answer for that.

    An *unstarted* session rather than `StartSession(project_id=None)`, because
    that command requires one -- which is the useful discovery here: every
    started session does have a project, so this branch guards the pre-fold
    state rather than a session type. `None` means "the executor's own model",
    the process answer; raising here would take a turn down over a state the
    aggregate passes through on its way to being valid.
    """
    app = await build_application(model=None)
    unstarted = Session(uuid4())
    assert unstarted.state.project_id is None

    assert await app.service._executor._model_provider(unstarted) is None


@pytest.mark.asyncio
async def test_an_injected_model_is_left_alone(build_application):
    """A caller who injected a model has said which model they want used.

    Every test in this suite that hands in a fake relies on it: rebuilding a
    `ChatOpenAI` from settings here would point them at a real endpoint nobody
    asked for. `_extraction_model` refuses to second-guess the same statement
    for the same reason.
    """
    app = await build_application(model=object())
    project_id = uuid4()
    await app.settings.store.put(
        ScopeRef(Scope.PROJECT, str(project_id)), "model", "ignored-because-injected"
    )

    assert await app.service._executor._model_provider(_session(project_id)) is None


@pytest.mark.asyncio
async def test_an_unconfigured_project_still_gets_the_process_model(build_application):
    """A fresh install, where nobody has saved anything.

    Separate from the projectless case because it goes through the whole
    resolve and finds nothing, where that one returns before resolving. Both
    have to land on the process answer or creating a settings database would
    change what a turn talks to.
    """
    app = await build_application(model=None)

    resolved = await app.service._executor._model_provider(_session(uuid4()))

    assert resolved.model_name == config.model_name()
