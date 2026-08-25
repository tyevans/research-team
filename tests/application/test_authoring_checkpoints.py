"""That a phase which produced nothing fails loudly.

Every test here would pass if the checkpoint body were `return None`, which is
exactly the state this module exists to make impossible -- so each one is
proved red by emptying the file dict it is handed, not by trusting the green.

The failure being guarded against is the one CLAUDE.md names twice: an event no
projection handles counts as applied, and a silent default makes "never wired"
indistinguishable from "working". A phase that dispatched no subagents and
wrote no lesson returns a reply like any other. Only the files tell the truth.
"""

import pytest

from research_team.application.authoring_checkpoints import (
    BUILDS_TOWARD_FIELD,
    COMPONENT_FENCE,
    ESSENTIAL_QUESTIONS_HEADING,
    EVIDENCE_HEADING,
    PERFORMANCE_TASK_MARKER,
    UNDERSTANDINGS_HEADING,
    CheckpointFailed,
    check_assessment,
    check_lessons,
    check_stage_one,
    check_stage_two,
    component_counts,
    lesson_paths,
    unit_text,
)
from research_team.application.course_authoring import (
    assessment_prompt,
    desired_results_prompt,
    evidence_prompt,
    learning_plan_prompt,
)
from research_team.domain.learning_area import AreaMember, LearningArea

SLUG = "the-principate"
UNIT = f"/course/areas/{SLUG}/unit.md"

STAGE_ONE = """# The Principate

## Enduring Understandings

- Augustus kept republican forms while holding monarchic power.
- The succession problem was never solved and destroyed the system twice.

## Essential Questions

- Was the Principate a republic in form only?
- Who actually held power under Augustus?
- What made the succession unsolvable?

## Knowledge

- The settlement of 27 BC

## Skills

- Reading a constitutional claim against the acts behind it
"""

STAGE_TWO = """
## Stage 2 - Evidence

**Performance task.** Argue whether the Principate was a republic, from the
acts rather than the titles.

**Performance task.** Explain why the succession was unsolvable.
"""


def files(**paths: str) -> dict[str, dict[str, str]]:
    return {path: {"content": text} for path, text in paths.items()}


def test_stage_one_passes_on_a_complete_unit():
    check_stage_one(files(**{UNIT: STAGE_ONE}), SLUG)


def test_stage_one_fails_when_the_unit_file_is_absent():
    with pytest.raises(CheckpointFailed) as caught:
        check_stage_one({}, SLUG)
    assert caught.value.phase == "stage_one"
    assert UNIT in caught.value.reason


def test_stage_one_fails_on_one_enduring_understanding():
    """Two is the floor the prompt asks for, and one is what a model that ran
    out of corpus produces. It must not settle."""
    thin = STAGE_ONE.replace(
        "- The succession problem was never solved and destroyed the system twice.\n", ""
    )
    with pytest.raises(CheckpointFailed):
        check_stage_one(files(**{UNIT: thin}), SLUG)


def test_stage_one_fails_on_two_essential_questions():
    thin = STAGE_ONE.replace("- What made the succession unsolvable?\n", "")
    with pytest.raises(CheckpointFailed):
        check_stage_one(files(**{UNIT: thin}), SLUG)


def test_stage_two_fails_when_the_evidence_section_is_absent():
    with pytest.raises(CheckpointFailed) as caught:
        check_stage_two(files(**{UNIT: STAGE_ONE}), SLUG)
    assert caught.value.phase == "stage_two"


def test_stage_two_fails_with_fewer_tasks_than_understandings():
    """Two understandings, one task. The spec asks for one task per
    understanding, and a phase that wrote one is a phase that stopped early."""
    one_task = STAGE_TWO.replace(
        "**Performance task.** Explain why the succession was unsolvable.\n", ""
    )
    with pytest.raises(CheckpointFailed):
        check_stage_two(files(**{UNIT: STAGE_ONE + one_task}), SLUG)


def test_stage_two_passes_with_one_task_per_understanding():
    check_stage_two(files(**{UNIT: STAGE_ONE + STAGE_TWO}), SLUG)


def test_lessons_fail_when_a_lesson_file_is_missing():
    present = files(
        **{
            UNIT: STAGE_ONE + STAGE_TWO,
            f"/course/areas/{SLUG}/lesson-01.md": "builds_toward: republic\n",
        }
    )
    with pytest.raises(CheckpointFailed) as caught:
        check_lessons(present, SLUG, lesson_count=2)
    assert "lesson-02.md" in caught.value.reason


def test_lessons_fail_when_builds_toward_is_absent():
    """A lesson that names no assessment is the forward-designed lesson UbD
    exists to prevent, and it looks identical to a correct one."""
    present = files(
        **{
            UNIT: STAGE_ONE + STAGE_TWO,
            f"/course/areas/{SLUG}/lesson-01.md": "# A lesson\n\nProse.\n",
        }
    )
    with pytest.raises(CheckpointFailed):
        check_lessons(present, SLUG, lesson_count=1)


def test_lessons_pass_when_every_lesson_names_an_assessment():
    present = files(
        **{
            UNIT: STAGE_ONE + STAGE_TWO,
            f"/course/areas/{SLUG}/lesson-01.md": "builds_toward: republic\n\nProse.\n",
        }
    )
    check_lessons(present, SLUG, lesson_count=1)


def test_assessment_fails_when_the_review_file_is_absent():
    present = files(
        **{
            UNIT: STAGE_ONE + STAGE_TWO,
            f"/course/areas/{SLUG}/lesson-01.md": (
                "builds_toward: republic\n\n```component:mcq\nid: a\n```\n"
            ),
        }
    )
    with pytest.raises(CheckpointFailed) as caught:
        check_assessment(present, SLUG, lesson_count=1, before=(0,))
    assert "review.md" in caught.value.reason


def test_assessment_fails_when_a_lesson_carries_no_component():
    present = files(
        **{
            UNIT: STAGE_ONE + STAGE_TWO,
            f"/course/areas/{SLUG}/lesson-01.md": "builds_toward: republic\n\nProse.\n",
            f"/course/areas/{SLUG}/review.md": "# Unit review\n",
        }
    )
    with pytest.raises(CheckpointFailed):
        check_assessment(present, SLUG, lesson_count=1, before=(0,))


def test_assessment_passes_with_a_component_in_every_lesson_and_a_review():
    present = files(
        **{
            UNIT: STAGE_ONE + STAGE_TWO,
            f"/course/areas/{SLUG}/lesson-01.md": (
                "builds_toward: republic\n\n```component:mcq\nid: a\n```\n"
            ),
            f"/course/areas/{SLUG}/review.md": "# Unit review\n",
        }
    )
    check_assessment(present, SLUG, lesson_count=1, before=(0,))


def test_assessment_fails_when_phase_four_added_nothing_to_a_lesson():
    """The one assertion in this file that is about phase 4 rather than phase 3.

    Until 2026-08-24 `check_assessment` asked only whether a `component:` fence
    existed -- which `learning_plan_prompt` already requires of every drafter,
    so a run in which every `quiz-writer` did nothing passed as long as
    `unit-reviewer` left a `review.md`. This is that run: the lesson carries
    exactly the one component phase 3 left, and `before` says so.

    Proved red by reverting the growth comparison in `check_assessment`, not
    by trusting the green: with only the fence check in place this input
    passes.
    """
    lesson = "builds_toward: republic\n\n```component:mcq\nid: a\n```\n"
    present = files(
        **{
            UNIT: STAGE_ONE + STAGE_TWO,
            f"/course/areas/{SLUG}/lesson-01.md": lesson,
            f"/course/areas/{SLUG}/review.md": "# Unit review\n",
        }
    )
    before = component_counts(present, SLUG, lesson_count=1)
    assert before == (1,)

    with pytest.raises(CheckpointFailed) as caught:
        check_assessment(present, SLUG, lesson_count=1, before=before)
    assert "lesson-01.md" in caught.value.reason


def test_assessment_passes_when_a_lesson_gained_a_component():
    """The other side of the growth check: the same lesson, one item appended."""
    lesson = "builds_toward: republic\n\n```component:mcq\nid: a\n```\n"
    present = files(
        **{
            UNIT: STAGE_ONE + STAGE_TWO,
            f"/course/areas/{SLUG}/lesson-01.md": (
                lesson + "\n```component:cloze\nid: b\n```\n"
            ),
            f"/course/areas/{SLUG}/review.md": "# Unit review\n",
        }
    )
    check_assessment(present, SLUG, lesson_count=1, before=(1,))


AREA = LearningArea(
    slug=SLUG,
    members=(
        AreaMember(entity_id="e1", name="Augustus", entity_type="person", centrality=1.0),
    ),
)


@pytest.mark.parametrize(
    ("marker", "phase"),
    [
        (UNDERSTANDINGS_HEADING, "stage_one"),
        (ESSENTIAL_QUESTIONS_HEADING, "stage_one"),
        (EVIDENCE_HEADING, "stage_two"),
        (PERFORMANCE_TASK_MARKER, "stage_two"),
        (BUILDS_TOWARD_FIELD, "lessons"),
        (COMPONENT_FENCE, "lessons"),
    ],
)
def test_every_marker_a_checkpoint_searches_for_is_named_in_its_prompt(marker, phase):
    """One defect, found three times: a checkpoint asserting on a shape no
    prompt demands.

    A shape the prompt does not ask for is a shape the model has no reason to
    produce, so the failure is a *correct* phase refused -- and no fixture can
    see it, because the fixture is written by whoever wrote the checkpoint and
    supplies the shape by hand. C1 (the two Stage 1 headings) was latent; C2
    (`PERFORMANCE_TASK_MARKER`) killed a live run on 2026-08-25.

    This asserts the constants reach the prompts, not that the prompts are
    good. It fails on the edit that caused all three: a literal typed at the
    `find` call, or a prompt that stops interpolating it.

    Proved red per case by dropping each interpolation in turn.

    `lesson-drafter` carries the last two as well and is asserted separately in
    `tests/infrastructure/test_authoring_subagents.py` -- since the fan-out it
    writes the lessons, and this file cannot reach infrastructure's roster.
    """
    prompts = {
        "stage_one": desired_results_prompt(AREA, "Ancient Rome"),
        "stage_two": evidence_prompt(AREA, "STAGE ONE"),
        "lessons": learning_plan_prompt(AREA, "STAGE ONE", 3),
        "assessment": assessment_prompt(AREA, 3),
    }
    assert marker in prompts[phase]


def test_stage_two_refuses_the_shape_that_killed_the_live_run():
    """The measured input, not an invented one.

    Taken from a live authoring run on 2026-08-25 against the `research-team`
    project's `agent-interaction-log` area: phase 2 wrote four correct tasks as
    `**PT1 —**`..`**PT4 —**` under a `### Performance tasks` heading, and the
    old case-insensitive grep for "performance task" found two -- one in the
    intro sentence, one in the heading. `2 performance task(s) for 4
    understanding(s)`, on output that was right.

    What this pins is the *refusal*, not the old false negative. The run is
    still refused, because the marker the prompt now demands is absent, and
    that is the correct reading: the counting rule and the instruction agree,
    so a model that follows the prompt passes. Asserting that the old shape now
    passes would mean the pattern had been loosened to guess at formatting,
    which is the fix that was rejected.

    The first half would pass with the old grep restored, for the wrong reason
    -- it counts 2 and also refuses. The half with teeth is the second: the
    same content, marked as the prompt asks, passes.
    """
    understandings = "\n".join(f"- Understanding {n}." for n in range(1, 5))
    written = (
        f"{UNDERSTANDINGS_HEADING}\n{understandings}\n\n"
        f"{ESSENTIAL_QUESTIONS_HEADING}\n- One?\n- Two?\n- Three?\n\n"
        f"{EVIDENCE_HEADING} — Evidence\n\n"
        "For each, the performance task asks for something a learner who had "
        "merely memorised the material could not do.\n\n"
        "### Performance tasks\n\n"
        + "\n".join(f"**PT{n} —** A paragraph.\n" for n in range(1, 5))
    )
    with pytest.raises(CheckpointFailed) as caught:
        check_stage_two(files(**{UNIT: written}), SLUG)
    assert caught.value.reason == "0 performance task(s) for 4 understanding(s)"

    marked = written
    for n in range(1, 5):
        marked = marked.replace(f"**PT{n} —**", PERFORMANCE_TASK_MARKER)
    check_stage_two(files(**{UNIT: marked}), SLUG)


def test_lesson_paths_are_zero_padded_and_one_based():
    assert lesson_paths(SLUG, 2) == (
        f"/course/areas/{SLUG}/lesson-01.md",
        f"/course/areas/{SLUG}/lesson-02.md",
    )


def test_unit_text_is_empty_when_the_unit_is_absent():
    assert unit_text({}, SLUG) == ""
