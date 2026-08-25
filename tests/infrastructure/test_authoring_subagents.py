"""That the roster builds, and that no subagent can dispatch another.

The port-with-one-adapter shape from CLAUDE.md: the specs are data handed to a
library, and nothing else checks that the library accepts them. A malformed
entry surfaces only when an agent is constructed inside a turn, which means a
failed authoring run against a live endpoint, minutes in, naming nothing about
the roster.

A test that asserted the dicts have the right keys would look identical to this
one and would catch none of that -- it would be checking our own literal
against itself.
"""

import pytest
from deepagents import create_deep_agent
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from research_team.application.authoring_checkpoints import (
    BUILDS_TOWARD_FIELD,
    COMPONENT_FENCE,
)
from research_team.application.authoring_dispatch import AUTHORING_SUBAGENT_NAMES
from research_team.application.course_authoring import COMPONENT_GUIDE
from research_team.application.prose_rubric import critic_reporting_contract
from research_team.infrastructure.agent.authoring_subagents import (
    AUTHORING_DISPATCH_PROMPT,
    AUTHORING_SUBAGENTS,
)


def test_the_roster_has_six_subagents():
    assert len(AUTHORING_SUBAGENTS) == 6


def test_every_spec_builds_through_create_deep_agent():
    """Through `create_deep_agent`, not `SubAgentMiddleware`.

    deepagents 0.7.6 fills `model` and `tools` per spec in `graph.py` before
    compiling, so driving the middleware directly would demand fields
    production never supplies and fail on a roster that works. What production
    subscripts, and therefore raises on, is `name` and `system_prompt`.
    """
    agent = create_deep_agent(
        model=FakeListChatModel(responses=["ok"]),
        subagents=list(AUTHORING_SUBAGENTS),
    )
    assert agent is not None


def test_no_subagent_carries_orchestration_tools():
    """A subagent that could dispatch another would make the phase's fan-out
    unbounded and unobservable.

    **This would pass with deepagents replaced by a library that hands every
    subagent a `task` tool, and it should say so.** No spec in the roster has
    a `tools` key, so `spec.get("tools", ())` is always empty and every
    assertion below is about our own literal -- it fires only if someone adds
    an explicit `task` tool to a spec, which is the deliberate act, not the
    silent one. The library's guarantee (deepagents 0.7.6 builds subagents
    with plain `create_agent` and no `SubAgentMiddleware`) is asserted nowhere;
    catching a version that changed it would mean building through
    `create_deep_agent` and reading the compiled subagent's tool names, which
    is what to write if this ever matters more than it does today."""
    for spec in AUTHORING_SUBAGENTS:
        names = {getattr(tool, "name", "") for tool in spec.get("tools", ())}
        assert "task" not in names, spec["name"]


def test_every_spec_carries_a_name_and_a_system_prompt():
    """The two fields graph.py subscripts directly."""
    for spec in AUTHORING_SUBAGENTS:
        assert spec["name"]
        assert spec["system_prompt"]
        assert spec["description"]


def test_names_are_unique():
    names = [spec["name"] for spec in AUTHORING_SUBAGENTS]
    assert len(set(names)) == len(names)


@pytest.mark.parametrize("name", AUTHORING_SUBAGENT_NAMES)
def test_the_dispatch_prompt_names_every_subagent(name):
    """A subagent the primary agent is never told about is a subagent that is
    never called, and the run still settles -- so this is the assertion that
    stops a roster entry being dead weight.

    Parametrised over `AUTHORING_SUBAGENT_NAMES` rather than over a literal
    list, which is a real change and not a tidy-up: the literal was a third
    copy of the six names, and a spec renamed in two places out of three left
    this test asserting something true about a name nothing used.
    """
    assert name in AUTHORING_DISPATCH_PROMPT
    assert any(spec["name"] == name for spec in AUTHORING_SUBAGENTS)


def test_the_names_and_the_specs_agree_in_both_directions():
    """Neither list may hold a name the other does not.

    Both directions, because both fail silently and differently. A name in the
    dispatch prompt with no spec behind it is a subagent the parent tries to
    call and cannot -- deepagents has no such subagent, and what comes back is
    a tool error mid-run rather than anything naming the roster. A spec no
    prompt mentions is never dispatched at all, and the run settles with that
    phase's work simply absent, which looks exactly like a phase that had
    nothing to do.

    What it deliberately cannot catch, measured rather than assumed: renaming
    a constant fails nothing here, because the constant feeds both the spec and
    the prompt and they stay agreed. That is the point of the constants, not a
    gap in the test -- but it means this test only fires when someone
    reintroduces a literal or drops a spec. Proved red on both: a spec's `name`
    set to a divergent literal, and a spec removed from the tuple.

    Sets, not sequences: the order of `AUTHORING_SUBAGENT_NAMES` is the order
    the prompt reads in and the specs are free to be declared in any order.
    That is asserted separately in `test_names_are_unique`, which is what
    stops a set comparison hiding a duplicate.
    """
    assert set(AUTHORING_SUBAGENT_NAMES) == {spec["name"] for spec in AUTHORING_SUBAGENTS}
    assert len(AUTHORING_SUBAGENT_NAMES) == len(AUTHORING_SUBAGENTS)


def test_the_two_rubric_carrying_prompts_hold_the_rules_themselves():
    """Not that they mention a rubric -- that the six rules are in the text.

    The drafter and the critic are given the rubric inline because neither can
    read a file the caller did not name. An interpolation that silently
    produced an empty string would leave every other test in this file green:
    the spec still builds, the names are still unique, and the run still
    answers, having judged nothing.

    The counter is the second half of that: a filter inside a loop with no
    counter passes when the filter matches nothing, so renaming a spec or
    dropping one from the tuple would skip the body and stay green.
    """
    checked = 0
    for spec in AUTHORING_SUBAGENTS:
        if spec["name"] in {"lesson-drafter", "prose-critic"}:
            checked += 1
            assert "Opens with a problem, not a thesis" in spec["system_prompt"]
            assert "Varied section shape" in spec["system_prompt"]
    assert checked == 2


def test_only_the_critic_is_given_the_critics_reporting_contract():
    """The drafter gets the rules; it must not get the tail that follows them.

    The tail says to judge the lesson, to report nothing else, and not to
    rewrite it. In a drafter's prompt those fight the one instruction it has,
    and its OUTPUT clause competes with the real one below it -- the likely
    result being a critique where a lesson should be. Nothing else here would
    notice: a drafter handed the whole file still builds, still has a unique
    name, and still holds all six rules.
    """
    contract = critic_reporting_contract()
    assert contract.strip()
    drafter = next(s for s in AUTHORING_SUBAGENTS if s["name"] == "lesson-drafter")
    critic = next(s for s in AUTHORING_SUBAGENTS if s["name"] == "prose-critic")
    assert contract not in drafter["system_prompt"]
    assert "Report nothing else" not in drafter["system_prompt"]
    assert contract in critic["system_prompt"]


def test_neither_prompt_carries_the_rubrics_editors_note():
    """The HTML comment at the top of the rubric names both subagents and what
    each is given. A drafter told what the critic receives has been told
    something it can only act on wrongly, and it is maintenance prose either
    way -- tokens spent on nothing the subagent does."""
    for spec in AUTHORING_SUBAGENTS:
        assert "<!--" not in spec["system_prompt"], spec["name"]
        assert "whoever edits the file" not in spec["system_prompt"], spec["name"]


def test_the_drafter_carries_the_component_guide():
    """The drafter is the only thing writing lesson components since the fan-out.

    Before this, its whole instruction on the subject was "Carry at least two
    components, of which at least one resolves against the project" -- no fence
    syntax, no list of the ten types, and no `entity:`/`entity_id:` split,
    which is the distinction `COMPONENT_GUIDE` exists for and which
    `course_authoring` records as its defect 1. A subagent cannot read a file
    the caller did not name, so a guide it does not carry is a guide it does
    not have.

    Asserts the guide's generated tail, not only its opening line: an
    interpolation that produced the template with an empty `{id_fields}` would
    leave every other test in this file green.

    Proved red by removing the `COMPONENT_GUIDE` interpolation from
    `LESSON_DRAFTER`'s system prompt.
    """
    drafter = next(s for s in AUTHORING_SUBAGENTS if s["name"] == "lesson-drafter")
    assert COMPONENT_GUIDE in drafter["system_prompt"]
    assert "`entity_id:` is the id, copied exactly" in drafter["system_prompt"]


#: Which subagent writes which checkpointed marker, since the fan-out.
#:
#: `quiz-writer` is on this list because of `check_assessment`'s growth rule,
#: which is newer than the roster: it requires every lesson's component count
#: to rise in phase 4, so the fence stopped being style advice and became a
#: gate. The final review graded the writer's missing syntax "genuinely minor
#: -- it can copy the fence style from the lesson it reads", which was true
#: while nothing gated it and is a guess about the model's formatting now that
#: something does.
_MARKER_WRITERS = {
    "lesson-drafter": (BUILDS_TOWARD_FIELD, COMPONENT_FENCE),
    "quiz-writer": (COMPONENT_FENCE,),
}


@pytest.mark.parametrize(
    ("name", "marker"),
    [(name, marker) for name, markers in _MARKER_WRITERS.items() for marker in markers],
)
def test_the_writers_are_told_the_markers_their_checkpoints_search_for(name, marker):
    """The parent's prompts name all of these; since the fan-out the parent
    writes no lesson and appends no item.

    `check_lessons` greps each lesson for `builds_toward` and
    `check_assessment` for the component fence, twice over -- once for
    presence, once for growth. The things that satisfy those are subagents that
    cannot see the prompt the requirements were stated in. That is the C1/C2
    shape one layer down, and the fourth instance of it was written into
    `check_assessment` by the fix wave that closed the first three: the growth
    rule shipped a day before `quiz-writer` was told what a component fence
    looks like.

    Proved red by removing the FRONTMATTER FIRST clause and each
    `COMPONENT_GUIDE` interpolation in turn.
    """
    spec = next(s for s in AUTHORING_SUBAGENTS if s["name"] == name)
    assert marker in spec["system_prompt"]


def test_the_quiz_writer_is_told_the_floor_the_checkpoint_enforces():
    """The fence is half of it; the other half is that zero items fails.

    `assessment_prompt` lets the parent say how many items to add and, before
    2026-08-25, nothing told either the parent or the writer that a lesson
    gaining nothing aborts the phase. A writer that judged a short lesson
    already well covered would have failed a run that produced usable output.
    """
    writer = next(s for s in AUTHORING_SUBAGENTS if s["name"] == "quiz-writer")
    assert "APPEND AT LEAST ONE ITEM." in writer["system_prompt"]
