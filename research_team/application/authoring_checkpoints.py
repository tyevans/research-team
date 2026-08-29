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
#: A subdirectory of `/course` rather than `/course` itself. It shared that
#: directory with the workflow's stage artifacts, which were filed as
#: `NN-<artifact>.md` and enumerated to say what a run still owed; a course has
#: no stage number, so it sat under `areas/` rather than inventing one. Those
#: artifacts are gone, and the nesting stays: `authored_files.py` and the
#: console's course routes both address an area by this prefix, and flattening
#: it would rewrite every one of those paths to buy one path segment.
AREAS_DIR = "/course/areas"

#: The minimum an area's Stage 1 must carry, matching what the prompt asks for.
#:
#: Floors rather than ranges: a run that produced five understandings has not
#: failed, it has been generous, and failing it would turn a checkpoint into a
#: style rule. The ceiling is the prompt's business.
MIN_UNDERSTANDINGS = 2
MIN_ESSENTIAL_QUESTIONS = 3

#: Every literal a checkpoint searches for, and every one is interpolated into
#: the prompt meant to produce it.
#:
#: **This is one defect found three times, twice of them shipping.** A
#: checkpoint asserts on a *shape*, and a shape the prompt does not demand is a
#: shape the model has no reason to produce -- so the failure is always a
#: correct phase refused, and it is always invisible to the suite, because a
#: fixture is written by whoever wrote the checkpoint and supplies the shape by
#: hand.
#:
#: - `UNDERSTANDINGS_HEADING` / `ESSENTIAL_QUESTIONS_HEADING`:
#:   `desired_results_prompt` asked for "2-4 **enduring understandings**" and
#:   named no heading. Latent -- caught by review on 2026-08-24, and a live run
#:   the next day happened to write both headings unprompted.
#:
#: - `PERFORMANCE_TASK_MARKER`: `evidence_prompt` asked for "One **performance
#:   task** per enduring understanding" and said nothing about how to mark one;
#:   the check counted the case-insensitive phrase "performance task".
#:   **Measured, not reasoned**: a live run on 2026-08-25 over the
#:   `research-team` project's `agent-interaction-log` area wrote four correct
#:   tasks as `**PT1 —**`..`**PT4 —**` under a `### Performance tasks` heading,
#:   and the phrase occurred twice -- once in an intro sentence, once in the
#:   heading. The run died on `2 performance task(s) for 4 understanding(s)`.
#:
#: - `BUILDS_TOWARD_FIELD` / `COMPONENT_FENCE`: found by auditing for the same
#:   shape after the second. Both are named in the parent's prompt, and since
#:   the fan-out neither was named to `lesson-drafter`, which is the thing that
#:   writes them and cannot see the parent's prompt.
#:
#: The rule for anything added here: if a checkpoint greps for it, a prompt
#: must interpolate it, and
#: `test_every_marker_a_checkpoint_searches_for_is_named_in_its_prompt` must
#: hold the pair. Do not answer a miss by loosening the pattern -- a looser
#: pattern guesses at the model's formatting, which is how this failed.
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

#: Opens each performance task, counted verbatim and case-sensitively.
#:
#: The bold and the full stop are load-bearing rather than decorative: they are
#: what stops the intro sentence that killed the 2026-08-25 run ("the
#: performance task asks for something...") from counting as a task. A marker a
#: model can write by accident in prose is a marker that over-counts as readily
#: as the old pattern under-counted.
PERFORMANCE_TASK_MARKER = "**Performance task.**"

#: The frontmatter field naming the Stage 2 assessment a lesson serves.
BUILDS_TOWARD_FIELD = "builds_toward"

#: A component block's opening fence, which must start at the left margin --
#: an indented fence is a code block, and the reader meets the YAML raw.
COMPONENT_FENCE = "```component:"

#: Which phase's prompt must name which marker, as one object a test reads.
#:
#: The list was six hand-written pairs inside the test until 2026-08-25, and a
#: seventh marker added without a prompt would have been missed silently --
#: which is how the fourth instance of this defect got in, at the end of the
#: very wave that fixed the first three. `test_the_marker_registry_covers_every
#: _literal_constant` closes that: it compares this mapping against the
#: module's own string constants by introspection, so a new one fails at
#: collection rather than waiting to be remembered.
#:
#: The checkpoints keep reading the named constants rather than indexing this
#: -- a checkpoint that reached in by phase and position would be less legible
#: and no safer. This is a registry for the contract test, and the honest limit
#: is that it says which prompt must *name* a marker, not that the prompt uses
#: it correctly.
CHECKPOINT_MARKERS: Mapping[str, tuple[str, ...]] = {
    "stage_one": (UNDERSTANDINGS_HEADING, ESSENTIAL_QUESTIONS_HEADING),
    "stage_two": (EVIDENCE_HEADING, PERFORMANCE_TASK_MARKER),
    "lessons": (BUILDS_TOWARD_FIELD, COMPONENT_FENCE),
    "assessment": (COMPONENT_FENCE,),
}

#: String constants here that no checkpoint greps for, and so owe no prompt.
#: Named rather than inferred, because "not a marker" is a judgement and the
#: completeness test must not be able to make it for you.
NON_MARKER_CONSTANTS = frozenset({"AREAS_DIR"})

_BULLET = re.compile(r"^\s*[-*]\s+\S", re.MULTILINE)
_COMPONENT = re.compile(rf"^{re.escape(COMPONENT_FENCE)}", re.MULTILINE)


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


def stage_one_text(files: Mapping[str, Any], area_slug: str) -> str:
    """The unit file as Stage 1 left it: everything above the Stage 2 section.

    **Phases 2 and 3 used to be handed phase 1's model *reply* instead**, and
    that is the half of the crash this fixes. Measured on the owner's database
    on 2026-08-29: in the three `mid-2000s` runs the parent finished phase 1
    with `content: ""` -- eighteen model calls, thirty tool calls, no file --
    so "Stage 1 produced this" would have introduced an empty block had the run
    got that far. The reply is also the wrong artifact on the runs that *do*
    work: what the later phases must stay faithful to is the document, and a
    model that wrote the file and then summarised it differently in prose had
    two Stage 1s with nothing choosing between them.

    Sliced at `EVIDENCE_HEADING` rather than returned whole because phase 2
    appends Stage 2 to this same file: handing the whole file to phase 3 as
    "Stage 1" would show it the evidence section twice, once mislabelled, and
    `learning_plan_prompt` already tells it to read Stage 2 off disk.

    Returns `""` when the file was never written, which is the same thing
    `unit_text` returns and is what `check_stage_one` will already have
    refused -- this is never reached with an unwritten unit except by a caller
    that skipped the checkpoint.
    """
    text = unit_text(files, area_slug)
    cut = text.find(EVIDENCE_HEADING)
    return text if cut == -1 else text[:cut]


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

    Counting one marker the prompt demands verbatim, rather than parsing
    structure: the prompt asks for a paragraph per task and fixes no heading,
    so anything that reasoned about document shape would fail correct output.
    What it catches is the real failure -- a phase that wrote the section, one
    task, and stopped.

    **It counted the case-insensitive phrase "performance task" until
    2026-08-25, and that refused a correct run.** See the note above
    `PERFORMANCE_TASK_MARKER`: four tasks written, two counted, both of the two
    in prose rather than on a task. The fix is that `evidence_prompt` now
    interpolates the marker and this counts it; the fix that was rejected is a
    cleverer regex, which guesses at a format the prompt never specified and
    fails again the next time a model picks a different one.
    """
    text = unit_text(files, area_slug)
    evidence = _section(text, EVIDENCE_HEADING)
    if not evidence.strip():
        raise CheckpointFailed(
            "stage_two", f"no '{EVIDENCE_HEADING}' section in {unit_path(area_slug)}"
        )
    tasks = evidence.count(PERFORMANCE_TASK_MARKER)
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
        if BUILDS_TOWARD_FIELD not in text:
            raise CheckpointFailed(
                "lessons", f"{path} names no assessment in {BUILDS_TOWARD_FIELD}"
            )


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
