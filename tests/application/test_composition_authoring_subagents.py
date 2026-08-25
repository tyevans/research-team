"""That authoring sessions get the roster and chat sessions do not.

This is the wiring test the entity-definitions work went without: a build where
`EntityDefinitionRunner` was never constructed served every request as an empty
cache miss, and every test that "confirmed the endpoint worked" passed, because
none of them checked for a stored row. The equivalent here is a roster defined,
tested, and never reaching an authoring turn.

So the assertions below are on the provider the executor actually holds --
`app.service._executor._subagents_provider` -- awaited with a real `Session`,
not on `_subagents_for` alone. `_subagents_for` is a pure function and would
keep passing with the `subagents_provider=` argument deleted from the
`DeepAgentTurnExecutor(...)` call, which is precisely the failure this file is
here to catch. Reaching a private attribute is the price: the executor is built
inside `build_application` and is not otherwise exposed, and
`Application.tools` (composition.py) already reaches `service._executor` for
the same reason.

The chat direction has one trap worth naming. Under this project's real
configuration -- `AGENT_CONTEXT=elide` in `.env` -- `_context_parts` returns an
empty subagent tuple, so `assert chat_roster == ()` would pass with the whole
feature deleted. It is therefore asserted against whatever `_context_parts`
returned for the mode under test, and the `delegate` case below is what gives
the chat direction teeth: there the default is non-empty and demonstrably
distinct from the authoring roster.
"""

import inspect
from uuid import uuid4

import pytest
from deepagents import create_deep_agent

from research_team.application.authoring_dispatch import (
    AUTHORING_SUBAGENT_NAMES,
)
from research_team.composition import _context_parts, _subagents_for
from research_team.domain import Session, SessionPurpose, StartSession


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


def _default_for(mode: str) -> tuple[dict, ...]:
    """The static roster `_context_parts` hands the executor for `mode`.

    Read rather than written down, so this file cannot drift from the mapping
    it is checking against. `model` is `None` because no branch of
    `_context_parts` calls the model to decide a roster -- only `compact`
    holds one at all, and it only stores it.
    """
    _, subagents, _ = _context_parts(mode, None, "be brief")
    return subagents


@pytest.mark.parametrize("mode", ["elide", "compact", "delegate"])
def test_an_authoring_session_gets_the_six_names_whatever_the_context_mode(mode):
    """Named concretely, not compared against `AUTHORING_SUBAGENTS`.

    Comparing the returned object to the constant it returns is an identity
    check that would survive the constant being emptied. The six names are the
    contract the authoring prompts already name, so they are what is asserted.
    """
    roster = _subagents_for(_session(SessionPurpose.COURSE_AUTHORING), _default_for(mode))
    assert tuple(spec["name"] for spec in roster) == AUTHORING_SUBAGENT_NAMES
    assert AUTHORING_SUBAGENT_NAMES == (
        "unit-critic",
        "anecdote-hunter",
        "lesson-drafter",
        "prose-critic",
        "quiz-writer",
        "unit-reviewer",
    )


@pytest.mark.parametrize("mode", ["elide", "compact", "delegate"])
def test_a_chat_session_gets_the_modes_own_roster_and_no_authoring_one(mode):
    """The direction that fails if the purpose check is dropped.

    Under `elide` and `compact` the mode's roster is empty, so this is a weak
    assertion on its own -- it would pass against a build that returned `()`
    unconditionally. `delegate` is the case with teeth: its default is
    non-empty and shares no name with the authoring six.
    """
    default = _default_for(mode)
    assert _subagents_for(_session(SessionPurpose.CHAT), default) == default
    names = {spec["name"] for spec in default}
    assert names.isdisjoint(AUTHORING_SUBAGENT_NAMES)
    if mode == "delegate":
        assert names, "the delegate roster has gone empty; this test lost its teeth"


@pytest.mark.asyncio
async def test_the_roster_reaches_the_executor_the_application_built(build_application):
    """The assertion the entity-definitions failure was missing.

    `_subagents_for` passing proves nothing about the running system: the
    provider must be the one bound to the executor. This fails if
    `subagents_provider=` is removed from the `DeepAgentTurnExecutor(...)`
    call, which no other test in this file would notice.

    Built with `context_mode="delegate"` so the chat direction is checked
    against a non-empty default here too.
    """
    app = await build_application(model=None, context_mode="delegate")
    executor = app.service._executor

    authoring = await executor._turn_subagents(_session(SessionPurpose.COURSE_AUTHORING))
    assert tuple(spec["name"] for spec in authoring) == AUTHORING_SUBAGENT_NAMES

    chat = await executor._turn_subagents(_session(SessionPurpose.CHAT))
    assert tuple(chat) == _default_for("delegate")


def test_general_purpose_cannot_be_disabled_through_create_deep_agent():
    """A tripwire on the decision recorded beside `_subagents_for`.

    deepagents 0.7.6 takes no `general_purpose_subagent` argument -- it is a
    field on the harness profile chosen from the *model*, so a caller cannot
    reach it, and the only caller-side override is supplying an explicit spec
    named `general-purpose`. Measured against the installed package on
    2026-08-24, not read from the docstring that names the argument
    (`graph.py:404`, which describes an API this version does not expose).

    This fails on a version that adds the argument, which is the moment to
    re-take the decision to leave the seventh subagent in place.
    """
    assert "general_purpose_subagent" not in inspect.signature(create_deep_agent).parameters
