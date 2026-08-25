"""What each authoring phase must have left behind, asserted on the files.

The whole reason course authoring runs as four phases rather than as one agent
holding a `task` tool is that "it stopped" and "it finished" become different
observable states. That distinction only exists if a missing file raises, so
every function here raises rather than warns.

**Every check is on content, never on the turn.** A phase that dispatched no
subagents and wrote nothing still returns a reply, still appends
`AssistantMessageAdded`, and still looks exactly like a phase that worked. This
repository has met that failure twice already -- the co-mention channel that
produced nothing from the day it merged, and the interaction log whose no-op
default made "never wired" identical to "working". Asserting that the turn
returned would reproduce it.

**The counts are floors, not shapes.** `check_stage_one` wants two
understandings because the prompt asks for two to four, and a model that has
run out of corpus writes one. It does not check that the understandings are
good; nothing here can, and `research_team/application/prose_rubric.md` plus
the `prose-critic` are where that judgement lives. (That path was written as
`prompts/course/prose_rubric.md` until 2026-08-24, against a plan the branch
abandoned: `test_no_prompt_file_is_orphaned` refuses a file under `prompts/`
that no prompt names, and `prose_rubric.py`'s docstring records why the rubric
sits beside its loader instead.)

**The headings the checks search for are constants, and the prompts
interpolate them.** `check_stage_one` is a `str.find` for a literal heading, so
a heading the prompt never asked for makes correct output read as zero bullets
and aborts phase 1. That shipped: the two headings below were hard-coded here
and named nowhere in `desired_results_prompt`, and no test could see it because
every fixture in this repository hand-writes them --
`test_every_heading_a_checkpoint_searches_for_is_named_in_its_prompt` is the
one assertion that ties the pair together.
"""

import re
from collections.abc import Mapping
from typing import Any

#: The directory every generated course lives under.
#:
#: Moved here from `course_authoring.py` rather than duplicated: this module
#: cannot import `AREAS_DIR` from there, because a later task makes
#: `course_authoring` import *this* module for the checkpoints, and a mutual
#: import is a circular one. `course_authoring.py` now re-exports this name so
#: `authored_files.py` and everything else that already resolves it from
#: `course_authoring` keeps working -- CLAUDE.md's rule about `AREAS_DIR`
#: already having three independent copies applies here too: a fourth
#: resolver, even a re-export, is only safe if there is exactly one
#: definition behind it.
#:
#: Beside `/course`'s stage artifacts rather than inside them. A stage artifact
#: is named for its position in a preset (`artifacts.artifact_path` builds
#: `NN-<artifact>.md`), and a course written here has no position in any preset
#: -- filing it under the same scheme would mean inventing a stage number for
#: something no stage produced, and `application/course.py` reads that scheme
#: to say which artifacts a run still owes. A course appearing there as an
#: unexplained extra would make that view wrong.
AREAS_DIR = "/course/areas"

#: The minimum an area's Stage 1 must carry, matching what the prompt asks for.
#:
#: Floors rather than ranges: a run that produced five understandings has not
#: failed, it has been generous, and failing it would turn a checkpoint into a
#: style rule. The ceiling is the prompt's business.
MIN_UNDERSTANDINGS = 2
MIN_ESSENTIAL_QUESTIONS = 3

#: The three headings a checkpoint searches for by literal text.
#:
#: Constants rather than literals at the `find` call because the prompt that is
#: meant to produce each one interpolates the same name. A heading typed twice
#: is a heading that drifts in one place, and the drift is silent in the worst
#: direction: `_section` returns `""` for an absent heading, so a phase that
#: did exactly what it was asked reads as a phase that produced nothing.
#:
#: `EVIDENCE_HEADING` is a prefix of what `evidence_prompt` asks for
#: (`## Stage 2 — Evidence`) rather than the whole of it. Deliberate: the em
#: dash and the word after it are the prompt's business, and matching on the
#: stage number is what makes a model that wrote `## Stage 2: Evidence` pass.
UNDERSTANDINGS_HEADING = "## Enduring Understandings"
ESSENTIAL_QUESTIONS_HEADING = "## Essential Questions"
EVIDENCE_HEADING = "## Stage 2"

_BULLET = re.compile(r"^\s*[-*]\s+\S", re.MULTILINE)
_COMPONENT = re.compile(r"^```component:", re.MULTILINE)
_PERFORMANCE_TASK = re.compile(r"performance task", re.IGNORECASE)


class CheckpointFailed(Exception):
    """A phase did not leave behind what the next phase needs.

    Carries the phase rather than only a message so a caller can record which
    phase failed without parsing prose -- `CourseAuthoringFailed` wants the
    stage, and a string that has to be scraped is a string that drifts.
    """

    def __init__(self, phase: str, reason: str) -> None:
        super().__init__(f"{phase}: {reason}")
        self.phase = phase
        self.reason = reason


def area_dir(area_slug: str) -> str:
    return f"{AREAS_DIR}/{area_slug}"


def unit_path(area_slug: str) -> str:
    return f"{area_dir(area_slug)}/unit.md"


def review_path(area_slug: str) -> str:
    return f"{area_dir(area_slug)}/review.md"


def lesson_paths(area_slug: str, lesson_count: int) -> tuple[str, ...]:
    """The paths phase 3 is expected to have written.

    Zero-padded and one-based because that is what `learning_plan_prompt` has
    always asked for and what `authored_files` reads back. Deriving them here
    rather than globbing is deliberate: a glob finds whatever is there and
    cannot tell a missing lesson from a lesson never planned.
    """
    return tuple(
        f"{area_dir(area_slug)}/lesson-{n:02d}.md" for n in range(1, lesson_count + 1)
    )


def _content(files: Mapping[str, Any], path: str) -> str:
    entry = files.get(path)
    if not isinstance(entry, Mapping):
        return ""
    value = entry.get("content")
    return value if isinstance(value, str) else ""


def unit_text(files: Mapping[str, Any], area_slug: str) -> str:
    """The unit file's content, or empty when it was never written."""
    return _content(files, unit_path(area_slug))


def _section(text: str, heading: str) -> str:
    """Everything from `heading` to the next heading of the same level."""
    start = text.find(heading)
    if start == -1:
        return ""
    rest = text[start + len(heading) :]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def _bullets(text: str) -> int:
    return len(_BULLET.findall(text))


def check_stage_one(files: Mapping[str, Any], area_slug: str) -> None:
    """Phase 1 wrote a unit with understandings and essential questions."""
    text = unit_text(files, area_slug)
    if not text.strip():
        raise CheckpointFailed("stage_one", f"{unit_path(area_slug)} was not written")
    understandings = _bullets(_section(text, UNDERSTANDINGS_HEADING))
    if understandings < MIN_UNDERSTANDINGS:
        raise CheckpointFailed(
            "stage_one",
            f"{understandings} enduring understanding(s), wanted {MIN_UNDERSTANDINGS}",
        )
    questions = _bullets(_section(text, ESSENTIAL_QUESTIONS_HEADING))
    if questions < MIN_ESSENTIAL_QUESTIONS:
        raise CheckpointFailed(
            "stage_one",
            f"{questions} essential question(s), wanted {MIN_ESSENTIAL_QUESTIONS}",
        )


def understanding_count(files: Mapping[str, Any], area_slug: str) -> int:
    return _bullets(_section(unit_text(files, area_slug), UNDERSTANDINGS_HEADING))


def check_stage_two(files: Mapping[str, Any], area_slug: str) -> None:
    """Phase 2 wrote one performance task per enduring understanding.

    Counting the phrase rather than parsing structure, on purpose: the prompt
    asks for a paragraph per task and does not fix a heading, so anything
    stricter would fail correct output. What it does catch is the real failure
    -- a phase that wrote the section and one task and stopped.
    """
    text = unit_text(files, area_slug)
    evidence = _section(text, EVIDENCE_HEADING)
    if not evidence.strip():
        raise CheckpointFailed(
            "stage_two", f"no '{EVIDENCE_HEADING}' section in {unit_path(area_slug)}"
        )
    tasks = len(_PERFORMANCE_TASK.findall(evidence))
    wanted = understanding_count(files, area_slug)
    if tasks < wanted:
        raise CheckpointFailed(
            "stage_two", f"{tasks} performance task(s) for {wanted} understanding(s)"
        )


def check_lessons(files: Mapping[str, Any], area_slug: str, lesson_count: int) -> None:
    """Phase 3 wrote every lesson, and every lesson names an assessment.

    `builds_toward` is checked for presence, not for resolution against a real
    Stage 2 item. Resolving it means matching prose against prose, and a match
    that is nearly right would fail correct output while a substring match
    passes anything -- so the honest check is that the field is there and the
    prose critic reads the rest. This is weaker than the spec's wording and the
    weakness is deliberate.
    """
    for path in lesson_paths(area_slug, lesson_count):
        text = _content(files, path)
        if not text.strip():
            raise CheckpointFailed("lessons", f"{path} was not written")
        if "builds_toward" not in text:
            raise CheckpointFailed("lessons", f"{path} names no assessment in builds_toward")


def component_counts(
    files: Mapping[str, Any], area_slug: str, lesson_count: int
) -> tuple[int, ...]:
    """Each lesson's component-fence count, for `check_assessment` to compare against.

    Taken after phase 3 and handed to phase 4's checkpoint, because a count is
    only evidence of phase 4 having done something if there is an earlier count
    to hold it against. A lesson that was never written counts 0, which is the
    right reading: phase 4 adding the first component to it is still growth.
    """
    return tuple(
        len(_COMPONENT.findall(_content(files, path)))
        for path in lesson_paths(area_slug, lesson_count)
    )


def check_assessment(
    files: Mapping[str, Any],
    area_slug: str,
    lesson_count: int,
    *,
    before: tuple[int, ...],
) -> None:
    """Phase 4 added components to every lesson and wrote the unit review.

    **`before` is what makes this a check on phase 4 rather than on phase 3.**
    Until 2026-08-24 this asked only whether each lesson carried a
    `component:` fence -- which `learning_plan_prompt` already requires of every
    drafter, so a run in which every `quiz-writer` was skipped, failed or wrote
    nothing passed unchanged provided `unit-reviewer` left a `review.md`. The
    docstring claimed otherwise. Requiring growth against the counts taken
    after `check_lessons` is the cheapest thing that can fail on phase 4's own
    subject.

    The cost, stated plainly: a `quiz-writer` that *replaced* a drafter's
    components rather than appending to them now fails a run that produced
    usable output. That is accepted because appending is the only thing its
    prompt permits ("Append only. Do not edit the lesson's prose"), so the
    replacement case is a subagent that already disobeyed.

    What it still cannot see, and this is the honest residue: it cannot tell a
    `quiz-writer` from the parent writing the items itself. Nothing in the
    files distinguishes them -- `assessment_prompt`'s docstring says the same.
    """
    counts = component_counts(files, area_slug, lesson_count)
    for path, count, prior in zip(
        lesson_paths(area_slug, lesson_count), counts, before, strict=True
    ):
        if count == 0:
            raise CheckpointFailed("assessment", f"{path} carries no component block")
        if count <= prior:
            raise CheckpointFailed(
                "assessment",
                f"{path} carries {count} component(s), the same {prior} phase 3 left",
            )
    if not _content(files, review_path(area_slug)).strip():
        raise CheckpointFailed("assessment", f"{review_path(area_slug)} was not written")
