# Course Authoring Subagent Fan-Out Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the three-turn course authoring sequence with four
Python-sequenced phases, each fanning out to purpose-scoped subagents, so
lessons are planned before they are drafted and criticised before they ship.

**Architecture:** Python owns phase order and asserts on the files each phase
leaves behind; the primary agent owns the fan-out inside a phase via
deepagents' `task` tool. Subagents are selected per turn by session purpose
through a new `SubagentProvider` seam, following the three provider seams the
executor already has.

**Tech Stack:** Python 3.13, deepagents 0.7.6, langchain, pytest + pytest-asyncio, ruff.

**Spec:** `docs/superpowers/specs/2026-08-24-course-authoring-subagents-design.md`

## Global Constraints

- **Four verification gates, and passing three is not passing.** `uv run ruff
  check .`, `uv run ruff format --check .`, `uv run pytest`, and `cd frontend
  && npm run verify`. The two ruff commands run over the whole repository. This
  change touches no frontend file, so `npm run verify` should be unaffected --
  but the two ruff commands still cover every Python file you add.
- **Do not run the full pytest suite locally.** Run the test files you touched,
  plus `uv run ruff check .` and `uv run ruff format --check .`. Push and let
  CI run the rest.
- **Comments explain why, not what.** State costs and trade-offs, name what a
  test would fail on, and say when something was measured rather than reasoned.
  A comment that restates the code is worse than none.
- **If a test would pass with the change reverted, say so in its docstring.**
  Prove every test red before trusting it green.
- **Never `git checkout <file>` to undo a deliberate break** when proving a test
  red -- it discards the rest of your uncommitted edits in that file. Re-edit
  the line back by hand.
- **Work happens in this worktree** (`.claude/worktrees/authoring-subagents`,
  branch `authoring-subagents`). Do not switch branches in the primary checkout.
- **Pre-release: no backwards compatibility.** Break data, events and contracts
  rather than migrating them.

## File Structure

| File | Responsibility |
|---|---|
| `research_team/application/authoring_checkpoints.py` | **Create.** Pure functions over a files dict: does each phase's output exist and hold what it must. No I/O, no session. |
| `research_team/infrastructure/agent/authoring_subagents.py` | **Create.** The six subagent specs and the roster tuple. Beside `delegation.py`, which it mirrors. |
| `prompts/course/prose_rubric.md` | **Create.** The six prose rules, as a resolvable prompt. |
| `research_team/application/course_authoring.py` | **Modify.** Three turns become four phases; each phase asserts its checkpoint. New phase prompts. |
| `research_team/infrastructure/agent/deep_agent.py` | **Modify.** Add the `SubagentProvider` seam beside the three existing providers. |
| `research_team/composition.py` | **Modify.** Wire a provider that returns the authoring roster for `SessionPurpose.COURSE_AUTHORING` and today's behaviour otherwise. |
| `tests/application/test_authoring_checkpoints.py` | **Create.** One test per checkpoint, each proved red. |
| `tests/infrastructure/test_authoring_subagents.py` | **Create.** The roster builds through `create_deep_agent`. |
| `tests/application/test_course_authoring.py` | **Modify.** Phase ordering and fail-loud behaviour. |

---

### Task 1: Phase checkpoints as pure functions

The checkpoints are the reason this design has four phases rather than one
agent, so they are built first and everything else is arranged around them.
They take a files dict shaped like `Session.state.files` -- `{path: {"content":
str, ...}}` -- and raise on anything missing. No session, no await, no I/O.

**Files:**
- Create: `research_team/application/authoring_checkpoints.py`
- Test: `tests/application/test_authoring_checkpoints.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `class CheckpointFailed(Exception)` -- carries `.phase: str` and `.reason: str`.
  - `def check_stage_one(files: Mapping[str, Any], area_slug: str) -> None`
  - `def check_stage_two(files: Mapping[str, Any], area_slug: str) -> None`
  - `def check_lessons(files: Mapping[str, Any], area_slug: str, lesson_count: int) -> None`
  - `def check_assessment(files: Mapping[str, Any], area_slug: str, lesson_count: int) -> None`
  - `def unit_text(files: Mapping[str, Any], area_slug: str) -> str` -- the unit file's content, or `""`.
  - `def lesson_paths(area_slug: str, lesson_count: int) -> tuple[str, ...]`

- [ ] **Step 1: Write the failing tests**

Create `tests/application/test_authoring_checkpoints.py`:

```python
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
    CheckpointFailed,
    check_assessment,
    check_lessons,
    check_stage_one,
    check_stage_two,
    lesson_paths,
    unit_text,
)

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
        check_assessment(present, SLUG, lesson_count=1)
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
        check_assessment(present, SLUG, lesson_count=1)


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
    check_assessment(present, SLUG, lesson_count=1)


def test_lesson_paths_are_zero_padded_and_one_based():
    assert lesson_paths(SLUG, 2) == (
        f"/course/areas/{SLUG}/lesson-01.md",
        f"/course/areas/{SLUG}/lesson-02.md",
    )


def test_unit_text_is_empty_when_the_unit_is_absent():
    assert unit_text({}, SLUG) == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/application/test_authoring_checkpoints.py -v
```

Expected: every test errors at collection with
`ModuleNotFoundError: No module named 'research_team.application.authoring_checkpoints'`.

- [ ] **Step 3: Write the implementation**

Create `research_team/application/authoring_checkpoints.py`:

```python
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
good; nothing here can, and `prompts/course/prose_rubric.md` plus the
`prose-critic` are where that judgement lives.
"""

import re
from collections.abc import Mapping
from typing import Any

from research_team.application.course_authoring import AREAS_DIR

#: The minimum an area's Stage 1 must carry, matching what the prompt asks for.
#:
#: Floors rather than ranges: a run that produced five understandings has not
#: failed, it has been generous, and failing it would turn a checkpoint into a
#: style rule. The ceiling is the prompt's business.
MIN_UNDERSTANDINGS = 2
MIN_ESSENTIAL_QUESTIONS = 3

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
    return tuple(f"{area_dir(area_slug)}/lesson-{n:02d}.md" for n in range(1, lesson_count + 1))


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
    understandings = _bullets(_section(text, "## Enduring Understandings"))
    if understandings < MIN_UNDERSTANDINGS:
        raise CheckpointFailed(
            "stage_one",
            f"{understandings} enduring understanding(s), wanted {MIN_UNDERSTANDINGS}",
        )
    questions = _bullets(_section(text, "## Essential Questions"))
    if questions < MIN_ESSENTIAL_QUESTIONS:
        raise CheckpointFailed(
            "stage_one",
            f"{questions} essential question(s), wanted {MIN_ESSENTIAL_QUESTIONS}",
        )


def understanding_count(files: Mapping[str, Any], area_slug: str) -> int:
    return _bullets(_section(unit_text(files, area_slug), "## Enduring Understandings"))


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


def check_assessment(files: Mapping[str, Any], area_slug: str, lesson_count: int) -> None:
    """Phase 4 left a component in every lesson and a unit review."""
    for path in lesson_paths(area_slug, lesson_count):
        if not _COMPONENT.search(_content(files, path)):
            raise CheckpointFailed("assessment", f"{path} carries no component block")
    if not _content(files, review_path(area_slug)).strip():
        raise CheckpointFailed("assessment", f"{review_path(area_slug)} was not written")
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/application/test_authoring_checkpoints.py -v
```

Expected: all pass.

- [ ] **Step 5: Prove two checks red by hand**

Edit `check_stage_one`'s body to `return None`, re-run, and confirm four tests
fail. Then edit `check_lessons`'s body to `return None`, re-run, and confirm
three fail. Restore both by re-typing the bodies — **do not `git checkout` the
file**, which would discard the whole task's work.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add research_team/application/authoring_checkpoints.py tests/application/test_authoring_checkpoints.py
git commit -m "A phase that wrote nothing fails, rather than settling

The checkpoints assert on files, never on the turn. A phase that dispatched no
subagents still returns a reply and still appends AssistantMessageAdded, so an
assertion that the turn succeeded passes with the whole phase removed -- the
failure this repository has already met in the co-mention channel and the
interaction log.

Two checks are weaker than the design asked for, and the weakness is written
down rather than hidden. check_stage_two counts the phrase 'performance task'
instead of parsing structure, because the prompt fixes no heading and anything
stricter would fail correct output. check_lessons checks that builds_toward is
present rather than that it resolves to a real Stage 2 item: resolution means
matching prose against prose, where a near-match fails good work and a
substring match passes anything. The prose critic reads what these cannot."
```

---

### Task 2: The prose rubric as a resolvable prompt

**Files:**
- Create: `prompts/course/prose_rubric.md`
- Test: `tests/application/test_prose_rubric.py`

**Interfaces:**
- Consumes: `research_team.application.prompts.load_prompts`, `DEFAULT_PROMPT_ROOT`.
- Produces: prompt ref `prompts/course/prose_rubric`, loadable from the default
  prompt root. Task 3 and Task 6 read its text.

**Before you start:** `prompts/` is loaded wholesale by `load_prompts`, every
file needs frontmatter carrying `prompt_ref`, `version`, `kind`, `methodology`
and `summary`, and `kind` is `Literal["generator", "critic"]`. There is also an
`orphaned_refs()` in `application/prompts.py` that lists prompt files no preset
names. **Step 4 checks whether anything asserts on it.** If something does, the
rubric moves out of `prompts/` rather than being allowlisted -- it is a rubric,
not a preset stage prompt, and bending the orphan rule to admit it would blunt
a check that exists to catch renamed stages.

- [ ] **Step 1: Write the failing test**

Create `tests/application/test_prose_rubric.py`:

```python
"""The rubric is a file the prompt library can resolve, not a string literal.

It matters that this is a file: the `prose-critic` cites the rule it failed by
number, and a rule you can edit without touching Python is a rule you will
actually iterate on after reading a bad lesson.

This test would pass with the rubric's *content* replaced by anything at all.
It checks resolvability and the rule count, which is what a later rename or a
truncated file would break; it cannot check that the rules are good ones.
"""

from research_team.application.prompts import DEFAULT_PROMPT_ROOT, load_prompts

REF = "prompts/course/prose_rubric"


def test_the_rubric_resolves_from_the_default_prompt_root():
    assert REF in load_prompts(DEFAULT_PROMPT_ROOT)


def test_the_rubric_is_a_critic_prompt():
    assert load_prompts(DEFAULT_PROMPT_ROOT)[REF].kind == "critic"


def test_the_rubric_states_six_numbered_rules():
    """Six, because the critic cites them by number and a dropped rule would
    silently stop being checked while every other rule still passed."""
    text = load_prompts(DEFAULT_PROMPT_ROOT)[REF].text
    for n in range(1, 7):
        assert f"{n}." in text, f"rule {n} is missing"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/application/test_prose_rubric.py -v
```

Expected: `KeyError: 'prompts/course/prose_rubric'` on the first test.

- [ ] **Step 3: Write the rubric**

Create `prompts/course/prose_rubric.md`. Match the frontmatter shape of an
existing prompt (read `prompts/ubd/stage1_generate.md` first and copy its field
order and value style exactly):

```markdown
---
prompt_ref: prompts/course/prose_rubric
version: 1
kind: critic
methodology: ubd
summary: The six rules a lesson's prose must satisfy, cited by number.
---

Six rules. Each is pass or fail. Judge only these, and cite the number of every
rule you fail.

There is no score. A five-point scale asks for a judgement nobody can defend
and gets a 4 for everything.

1. **Opens with a problem, not a thesis.** The first 80 words carry a specific
   moment: a failure, a measured number that surprised somebody, or two
   plausible answers that disagree. The concept is named after it, not before.
   "A system that records what happens has a choice about where to record it"
   fails: it is a topic sentence, nothing is at risk, and there is no reason to
   read the second sentence.

2. **Something is withheld.** At least one question is raised and left open for
   a paragraph or more before it is answered. A lesson that answers each
   question in the sentence that asks it leaves the reader holding nothing.

3. **One stated cost.** The lesson says what breaks if the learner gets this
   wrong, with evidence from the corpus. "A leak in one does not expose the
   other" fails: it is abstract, and the lesson never shows the leak.

4. **No quote-then-gloss chains.** At most one block quote followed by
   restatement, in the whole lesson. Claim, quote, "that sentence has two
   halves", gloss -- repeated in every section -- is the shape that makes a
   lesson predictable by its third paragraph.

5. **Second person with a task.** The reader is doing something. "A learner who
   understands them can answer..." fails; "You are about to add an event.
   Which file does it go in?" passes.

6. **Varied section shape.** No two consecutive sections are built the same
   way. Parallel lists of bolded nouns only where the parallelism is
   load-bearing, never as decoration.

Report each failure as the rule number, the sentence or passage that fails it,
and one line saying why. Report nothing else. Do not rewrite the lesson, do not
praise what worked, and do not suggest wording -- the drafter holds the plan
slot and the material, and will revise better than you can from outside it.

If a lesson passes all six, say so in one line.
```

- [ ] **Step 4: Run the test, and check the orphan rule**

```bash
uv run pytest tests/application/test_prose_rubric.py -v
uv run pytest tests/application -k "prompt" -v
```

Expected: the rubric tests pass. If any existing prompt-library test now fails
because the rubric is an orphaned ref, **stop and move the rubric** to
`research_team/application/prose_rubric.md`, read it with `Path(__file__).parent`,
and rewrite this task's test against that. Record the move and the reason in the
commit message. Do not add it to `ALLOWED_CROSS_STAGE_REFS`; that allowlist is
for prompts two presets legitimately share.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add prompts/course/prose_rubric.md tests/application/test_prose_rubric.py
git commit -m "The prose rubric is a file, so it can be edited after reading a bad lesson

Six binary rules rather than a scale: a local model asked to score gives
everything a 4. The critic cites rule numbers, which makes a finding actionable
by the drafter instead of a paragraph of taste.

The rubric is the drafter's brief as well as the critic's standard. Handing the
drafter something vaguer and the critic something sharp produces a revision
round that could have been a first draft.

What it cannot do, stated because the design depends on it: it can force a
lesson to open with an incident and cannot make the incident interesting. A
corpus with no incidents yields manufactured drama, which is worse than a flat
opening -- which is why the anecdote hunter is allowed to return nothing."
```

---

### Task 3: The subagent roster

**Files:**
- Create: `research_team/infrastructure/agent/authoring_subagents.py`
- Test: `tests/infrastructure/test_authoring_subagents.py`

**Interfaces:**
- Consumes: `prompts/course/prose_rubric` (Task 2) -- the `lesson-drafter` and
  `prose-critic` prompts embed its text.
- Produces:
  - `AUTHORING_SUBAGENTS: tuple[dict, ...]` -- six specs.
  - `UNIT_CRITIC`, `ANECDOTE_HUNTER`, `LESSON_DRAFTER`, `PROSE_CRITIC`,
    `QUIZ_WRITER`, `UNIT_REVIEWER` -- the individual dicts.
  - `AUTHORING_DISPATCH_PROMPT: str` -- the suffix appended to an authoring
    turn's system prompt, naming the six and when to use them.

**Read `research_team/infrastructure/agent/delegation.py` first.** Every spec
here follows `WORKER`'s prompt shape -- OBJECTIVE, BOUNDARIES, TOOLS, OUTPUT --
and the module docstring should say why the constructive subagents are an
exception to that module's own guidance.

- [ ] **Step 1: Write the failing test**

Create `tests/infrastructure/test_authoring_subagents.py`:

```python
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
    unbounded and unobservable. deepagents builds subagents without
    SubAgentMiddleware, so this is the library's guarantee -- asserted here
    because the design depends on it and a future version could change it."""
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


@pytest.mark.parametrize(
    "name",
    [
        "unit-critic",
        "anecdote-hunter",
        "lesson-drafter",
        "prose-critic",
        "quiz-writer",
        "unit-reviewer",
    ],
)
def test_the_dispatch_prompt_names_every_subagent(name):
    """A subagent the primary agent is never told about is a subagent that is
    never called, and the run still settles -- so this is the assertion that
    stops a roster entry being dead weight."""
    assert name in AUTHORING_DISPATCH_PROMPT
    assert any(spec["name"] == name for spec in AUTHORING_SUBAGENTS)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/infrastructure/test_authoring_subagents.py -v
```

Expected: `ModuleNotFoundError` at collection.

If `FakeListChatModel` cannot be imported from that path, find the fake this
repo already uses — `grep -rn "FakeListChatModel\|FakeChatModel" tests/ | head`
— and use that instead. Do not invent one.

- [ ] **Step 3: Write the roster**

Create `research_team/infrastructure/agent/authoring_subagents.py`. Structure it
as: module docstring, a shared prompt preamble, the six specs, the tuple, then
`AUTHORING_DISPATCH_PROMPT`.

The docstring must carry this reasoning:

```python
"""The six subagents an authoring turn can dispatch, and when.

`delegation.py` argues that delegation belongs on investigation rather than
construction, quoting Cognition: subagents that each produce part of an
artifact make conflicting implicit decisions the parent must then reconcile.
Three of these six construct, so this module is a deliberate exception to that
guidance and owes an answer for it.

The answer is the lesson plan. Every decision that must be shared across
lessons -- voice, what each lesson may assume from the ones before it, which
anecdote belongs to which lesson, the exact claim each lesson owns -- is fixed
by the parent *before* any drafter is dispatched. A drafter fills a slot; it
does not choose. Anything the plan leaves open, three drafters will answer
three ways, and the unit will read like three people wrote it, because three
did.

The second half of the answer is one writer per path, per phase. No two
subagents here write the same file. Two subagents editing one file is the
reconciliation problem in its worst form and there is no reason to accept it.

None of the six gets the `task` tool, and that costs nothing to arrange:
deepagents builds each subagent with plain `create_agent` and no
`SubAgentMiddleware`, so nesting is impossible by construction in 0.7.6.
"""
```

Each spec follows this shape. Write all six; the drafter is given in full
because it is the one carrying the most reasoning:

```python
_SUBAGENT_PREAMBLE = (
    "You are a subagent. You cannot see the conversation that dispatched you, "
    "so work only from these instructions and from what you can read in the "
    "workspace. Do not take on adjacent work you think would help: it is work "
    "the caller cannot see, may be doing itself, and did not ask for.\n\n"
)

LESSON_DRAFTER = {
    "name": "lesson-drafter",
    "description": (
        "Writes one lesson file from a plan slot and the anecdotes assigned to "
        "it. Dispatch one per lesson, in parallel. Give it the slot verbatim, "
        "its anecdotes, the enduring understandings, and the prose rules; it "
        "can see none of them otherwise."
    ),
    "system_prompt": (
        _SUBAGENT_PREAMBLE
        + "OBJECTIVE. Write exactly one lesson file at the path you were "
        "given. You own that file and nothing else writes it.\n\n"
        "THE SLOT IS NOT A SUGGESTION. You were given a claim to teach, an "
        "opening move, and what the reader already knows from earlier "
        "lessons. Those were decided across the whole unit, and changing one "
        "makes your lesson disagree with its neighbours in ways nobody will "
        "notice until a reader hits both.\n\n"
        "THE RULES ARE THE BRIEF. The prose rules below are what to write, "
        "not a standard to clear afterwards. A draft that ignores them and "
        "gets corrected is a wasted round.\n\n"
        + "PROSE RULES.\n{prose_rules}\n\n"
        "GROUNDING. Quote the corpus where the corpus says it better, with a "
        "citation. Carry at least two components, of which at least one "
        "resolves against the project.\n\n"
        "OUTPUT. Reply with the path you wrote and nothing else. Do not "
        "summarise the lesson back; the caller can read it."
    ),
}
```

`{prose_rules}` is filled at import from `prompts/course/prose_rubric.md` via
`load_prompts(DEFAULT_PROMPT_ROOT)["prompts/course/prose_rubric"].text`, so the
rubric has exactly one copy. If Task 2 moved the rubric out of `prompts/`, read
it from wherever Task 2 put it.

Write the other five to the same shape:

- **`unit-critic`** — reads `unit.md` and the corpus; returns findings on
  whether each understanding is arguable, central, and corpus-supported.
  Writes nothing. Output is findings only, one line each.
- **`anecdote-hunter`** — searches corpus and graph for concrete incidents,
  surprising measurements, and contradictions between sources. Returns each
  with a citation and the understanding it serves. **Must be told it may return
  nothing**, in those words: a hunter that pads produces manufactured drama,
  which is worse than a flat opening. Writes nothing.
- **`prose-critic`** — reads one lesson, judges it against the same rubric
  text, returns rule numbers and the passages that fail them. Writes nothing.
  Told explicitly not to rewrite or suggest wording.
- **`quiz-writer`** — appends check-for-understanding components to one lesson,
  written from the lesson as it stands rather than from any plan. Told that an
  item answerable from general knowledge is testing the model, not the course.
- **`unit-reviewer`** — reads every lesson and the Stage 2 tasks, writes
  `review.md`, one assessment across the unit.

Then:

```python
AUTHORING_SUBAGENTS = (
    UNIT_CRITIC,
    ANECDOTE_HUNTER,
    LESSON_DRAFTER,
    PROSE_CRITIC,
    QUIZ_WRITER,
    UNIT_REVIEWER,
)
```

And `AUTHORING_DISPATCH_PROMPT`, which must name all six by name (Task 6 relies
on it, and the test above asserts it).

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/infrastructure/test_authoring_subagents.py -v
```

- [ ] **Step 5: Prove the build test red**

Delete `"system_prompt"` from one spec, re-run, and confirm
`test_every_spec_builds_through_create_deep_agent` fails. Restore it by
re-typing — **not** with `git checkout`.

If it does *not* fail, the test is worthless as written: `graph.py` may have
tolerated the omission. Say so in the commit message and change the test to
break something the library does reject, rather than keeping a green test that
proves nothing.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add research_team/infrastructure/agent/authoring_subagents.py tests/infrastructure/test_authoring_subagents.py
git commit -m "Six authoring subagents, and the plan that keeps them from disagreeing

delegation.py argues delegation belongs on investigation rather than
construction, because subagents that each produce part of an artifact make
conflicting implicit decisions. Three of these six construct, so this is a
deliberate exception and the module says so.

The answer is the lesson plan: every shared decision -- voice, what each lesson
may assume, which anecdote belongs to whom, the claim each lesson owns -- is
fixed before any drafter is dispatched. A drafter fills a slot. The second half
is one writer per path per phase; no two subagents here write the same file.

The build test goes through create_deep_agent rather than SubAgentMiddleware.
deepagents 0.7.6 fills model and tools per spec in graph.py before compiling,
so a test on the raw middleware would demand fields production never supplies
and fail on a roster that works."
```

---

### Task 4: The `SubagentProvider` seam

Authoring subagents must not appear in every session. The executor already has
three per-turn provider seams (`middleware_provider`, `tools_provider`,
`sources_provider`) built for exactly this shape; this adds a fourth.

**Files:**
- Modify: `research_team/infrastructure/agent/deep_agent.py` (type alias beside
  `SourcesProvider` at line ~81; constructor ~line 270; the resolver beside
  `_turn_sources` at ~line 500; the `create_deep_agent` call at ~line 413)
- Test: `tests/infrastructure/test_deep_agent_subagent_provider.py`

**Interfaces:**
- Consumes: `AUTHORING_SUBAGENTS` (Task 3) in its test only.
- Produces:
  - `SubagentProvider = Callable[[Session], Awaitable[Sequence[dict]]]`
  - `DeepAgentTurnExecutor(..., subagents_provider: SubagentProvider | None = None)`
  - `async def _turn_subagents(self, session: Session) -> Sequence[dict]`

- [ ] **Step 1: Write the failing test**

Create `tests/infrastructure/test_deep_agent_subagent_provider.py`:

```python
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

import pytest

from research_team.domain.session import Session
from research_team.infrastructure.agent.deep_agent import DeepAgentTurnExecutor

STATIC = [{"name": "worker", "description": "d", "system_prompt": "p"}]
PER_TURN = [{"name": "unit-critic", "description": "d", "system_prompt": "p"}]


def executor(**kwargs):
    return DeepAgentTurnExecutor(model=None, **kwargs)


@pytest.mark.asyncio
async def test_the_static_list_is_used_when_no_provider_is_given():
    """An executor wired as it is today must build exactly what it built
    before this seam existed."""
    session = Session.start()
    assert await executor(subagents=STATIC)._turn_subagents(session) == STATIC


@pytest.mark.asyncio
async def test_the_provider_replaces_the_static_list():
    async def provider(session):
        return PER_TURN

    session = Session.start()
    got = await executor(subagents=STATIC, subagents_provider=provider)._turn_subagents(session)
    assert got == PER_TURN


@pytest.mark.asyncio
async def test_the_provider_is_given_the_session():
    """It selects on purpose, so it must see the session rather than a copy of
    some field the caller thought to pass."""
    seen = []

    async def provider(session):
        seen.append(session)
        return []

    session = Session.start()
    await executor(subagents_provider=provider)._turn_subagents(session)
    assert seen == [session]
```

`Session.start()` may not be the constructor this repo uses. Before writing the
test, run `grep -n "def start\|Session(" research_team/domain/session.py | head`
and `grep -rn "Session" tests/infrastructure/*.py | head` and use whatever the
existing tests build a session with. Do not invent a constructor.

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/infrastructure/test_deep_agent_subagent_provider.py -v
```

Expected: `AttributeError: '_turn_subagents'` or `TypeError` on the unexpected
`subagents_provider` keyword.

- [ ] **Step 3: Add the seam**

In `deep_agent.py`, beside the `SourcesProvider` alias (~line 81):

```python
SubagentProvider = Callable[[Session], Awaitable[Sequence[dict]]]
"""The subagents this turn may dispatch, chosen from the session.

The fourth of the executor's per-turn seams, and it exists for a reason the
other three do not have: a subagent appears in the system prompt whether or not
it is ever called. A roster built for course authoring, offered to every chat
turn, is six paragraphs of instruction about work that turn cannot do -- so the
cost of a static list is paid on every session, not just on the ones that would
have used it.

Defaults to nothing, so an executor wired without one builds precisely the
agent it built before this existed.
"""
```

In `__init__`, after `sources_provider`:

```python
subagents_provider: SubagentProvider | None = None,
```
```python
self._subagents_provider = subagents_provider
```

Beside `_turn_sources` (~line 500):

```python
async def _turn_subagents(self, session: Session) -> Sequence[dict]:
    if self._subagents_provider is None:
        return self._subagents
    return await self._subagents_provider(session)
```

At the `create_deep_agent` call (~line 413), replace
`subagents=self._subagents or None,` with:

```python
# Per turn rather than per executor: see `SubagentProvider`. The `or None`
# is deepagents' own contract -- an empty sequence and `None` are not the
# same thing to it.
subagents=list(await self._turn_subagents(session)) or None,
```

Update the comment above that line so it still says subagents share the
backend, and add that the roster is now chosen per turn.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/infrastructure/test_deep_agent_subagent_provider.py -v
uv run pytest tests/infrastructure -k "deep_agent or delegation" -v
```

Both must pass. The second run is the one that proves today's `delegate` mode
is untouched.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add research_team/infrastructure/agent/deep_agent.py tests/infrastructure/test_deep_agent_subagent_provider.py
git commit -m "Subagents are chosen per turn, because a roster costs every session

The executor is built once and serves every session, so a static roster puts
the authoring subagents in every chat turn's system prompt. That cost is
different in kind from the other three provider seams: a tool that is never
called costs a line, and a subagent that is never called costs a paragraph of
instruction about work the turn cannot do.

The seam is tested rather than the agent it builds. Asserting on
create_deep_agent's output means reaching into a compiled graph, and both
deepagents and eventsource-py are pre-1.0 with a stated no-shim policy -- a
minor bump is exactly where that assertion would break for no reason."
```

---

### Task 5: Four phases in `CourseAuthor`

**Files:**
- Modify: `research_team/application/course_authoring.py` (`CourseAuthor.author_area`)
- Modify: `tests/application/test_course_authoring.py`

**Interfaces:**
- Consumes: `check_stage_one`, `check_stage_two`, `check_lessons`,
  `check_assessment`, `CheckpointFailed` (Task 1); the phase prompts are
  written in Task 6 and stubbed here.
- Produces: `CourseAuthor.author_area` running four turns and raising
  `CheckpointFailed` on any phase that did not leave its files.

**The caller reads files through the session service.** `SessionService.load(session_id)`
returns a `Session` whose `.state.files` is the dict the checkpoints take. The
existing `FakeSessions` in the test file has no `load`; add one that returns an
object with `.state.files`, and have `RecordingTurns` write into it so a phase
can be made to succeed or fail.

- [ ] **Step 1: Write the failing tests**

Add to `tests/application/test_course_authoring.py`. Keep every existing test in
the file — the ordering guarantee they protect is unchanged and still matters.

```python
class WritingTurns:
    """A turn runner that writes whatever the test says each phase writes.

    Files rather than replies, because the checkpoints read files. A fake that
    only returned replies would let every checkpoint pass on an empty
    workspace, which is the exact failure they exist to catch.
    """

    def __init__(self, writes: list[dict[str, str]]) -> None:
        self.writes = writes
        self.prompts: list[str] = []
        self.files: dict[str, dict[str, str]] = {}

    async def run(self, session_id, user_input):
        self.prompts.append(user_input)
        for path, content in self.writes[len(self.prompts) - 1].items():
            self.files[path] = {"content": content}
        return Outcome(f"REPLY-{len(self.prompts)}")


@pytest.mark.asyncio
async def test_a_phase_that_wrote_nothing_fails_the_run():
    """The whole reason for four phases instead of one agent.

    This test passes with every subagent removed from the roster and with the
    dispatch prompt deleted -- it is not testing that delegation happened. It
    tests that a phase producing no files stops the run instead of settling,
    which is the difference between "it stopped" and "it finished" being
    observable at all.
    """
    turns = WritingTurns([{}, {}, {}, {}])
    author = CourseAuthor(FakeSessions(files=turns.files), turns)

    with pytest.raises(CheckpointFailed) as caught:
        await author.author_area(uuid4(), AREA, "Rome")

    assert caught.value.phase == "stage_one"
    assert len(turns.prompts) == 1, "the run continued past a failed phase"


@pytest.mark.asyncio
async def test_the_four_phases_run_in_order():
    ...


@pytest.mark.asyncio
async def test_the_project_is_released_when_a_checkpoint_fails():
    """The `finally` that already guards a crash must also guard a refusal.

    A run that dies holding the project locks out every later turn, and a
    checkpoint failure is a much more likely death than an exception from the
    model."""
    ...
```

Fill in the two elided bodies with the same `WritingTurns` shape: the ordering
test asserts four prompts in order and that each later prompt contains a
fragment of the earlier phase's file; the release test asserts
`FakeSessions.released` is non-empty after the raise.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/application/test_course_authoring.py -v
```

Expected: the new tests fail (three turns, no checkpoints); the existing ones
still pass.

- [ ] **Step 3: Rewrite `author_area`**

```python
async def author_area(
    self,
    project_id: UUID,
    area: LearningArea,
    subject: str,
    *,
    lesson_count: int = 3,
    run_id: UUID | None = None,
) -> AuthoredCourse:
    """Four phases, in order, each asserted on before the next begins.

    The phase boundary is the whole point. A single agent holding the `task`
    tool would end when it stopped talking, and a run that dispatched two
    drafters instead of five, or skipped the prose critic, produces a
    complete-looking unit and the same settled event. Between phases there is
    somewhere for Python to look.

    The parent's lesson plan is not persisted, and that is a real cost: a
    phase 3 that dies re-plans from scratch, possibly differently. Writing it
    to a file would buy resumability and reintroduce the shared-pool problem
    for anything later that reads it. A phase 3 that dies has usually left a
    half-written unit worth discarding anyway.
    """
    run_id = run_id or uuid4()
    session_id = await self._session.start_in_project(
        project_id, SessionPurpose.COURSE_AUTHORING
    )
    replies: list[str] = []
    try:
        await self._session.attach_project(project_id)

        first = await self._turns.run(session_id, desired_results_prompt(area, subject))
        replies.append(first.reply)
        check_stage_one(await self._files(session_id), area.slug)

        second = await self._turns.run(session_id, evidence_prompt(area, first.reply))
        replies.append(second.reply)
        check_stage_two(await self._files(session_id), area.slug)

        third = await self._turns.run(
            session_id, learning_plan_prompt(area, first.reply, lesson_count)
        )
        replies.append(third.reply)
        check_lessons(await self._files(session_id), area.slug, lesson_count)

        fourth = await self._turns.run(
            session_id, assessment_prompt(area, lesson_count)
        )
        replies.append(fourth.reply)
        check_assessment(await self._files(session_id), area.slug, lesson_count)
    finally:
        await self._session.release_project(session_id)

    return AuthoredCourse(
        area_slug=area.slug,
        project_id=project_id,
        session_id=session_id,
        run_id=run_id,
        replies=tuple(replies),
    )


async def _files(self, session_id: UUID) -> dict[str, Any]:
    """This session's workspace, re-read after every phase.

    Re-read rather than accumulated, because the subagents wrote through the
    same backend and their writes are on the session, not in anything this
    object holds.
    """
    session = await self._session.load(session_id)
    return dict(session.state.files)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/application/test_course_authoring.py tests/application/test_authoring_checkpoints.py -v
```

- [ ] **Step 5: Prove the fail-loud test red**

Comment out the `check_stage_one(...)` line, re-run, and confirm
`test_a_phase_that_wrote_nothing_fails_the_run` fails. Restore by re-typing.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add research_team/application/course_authoring.py tests/application/test_course_authoring.py
git commit -m "Authoring runs four phases, and stops at the first that produced nothing

Three turns become four, with a checkpoint between each. The phase boundary is
the design: a single agent holding the task tool ends when it stops talking, so
a run that skipped the prose critic produces a complete-looking unit and the
same settled event.

The new tests pass with every subagent removed from the roster. That is
deliberate and said in their docstrings -- they test that a phase producing no
files stops the run, not that delegation happened. Nothing in pytest can test
the second thing.

The existing ordering tests are kept unchanged. What they guard is unchanged:
a model given all three UbD stages at once writes the lessons first and
reverse-engineers understandings to match, with every section present."
```

---

### Task 6: The phase prompts

**Files:**
- Modify: `research_team/application/course_authoring.py`
- Modify: `tests/application/test_course_authoring.py`

**Interfaces:**
- Consumes: `AUTHORING_DISPATCH_PROMPT` (Task 3); `AREAS_DIR`, `COMPONENT_GUIDE`.
- Produces:
  - `def learning_plan_prompt(area, stage_one, lesson_count) -> str` — rewritten
    to instruct planning, anecdote-hunting, drafting and critique as one turn.
  - `def assessment_prompt(area, lesson_count) -> str` — new, phase 4.

Phase 1 and 2 prompts are unchanged except that phase 1 gains the `unit-critic`
dispatch and the one-round rule.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_learning_plan_prompt_orders_planning_before_drafting():
    """Anecdotes gathered after drafting are decoration; gathered before, they
    are the opening. The prompt has to say which comes first, because a model
    reading a list of things to do will do the cheapest one first."""
    prompt = learning_plan_prompt(AREA, "STAGE ONE", 3)
    assert prompt.index("anecdote-hunter") < prompt.index("lesson-drafter")
    assert prompt.index("lesson-drafter") < prompt.index("prose-critic")


def test_the_learning_plan_prompt_fixes_the_shared_decisions_before_fan_out():
    prompt = learning_plan_prompt(AREA, "STAGE ONE", 3)
    for shared in ("voice", "assume", "opening move", "claim"):
        assert shared in prompt


def test_the_assessment_prompt_is_given_the_lessons_as_written():
    """Items written from a plan test what was planned. The whole reason phase
    4 is separate is that the prose exists by the time it runs."""
    prompt = assessment_prompt(AREA, 2)
    assert "as they are written" in prompt
    assert "lesson-01.md" in prompt and "lesson-02.md" in prompt


def test_the_first_phase_allows_exactly_one_critique_round():
    prompt = desired_results_prompt(AREA, "Rome")
    assert "unit-critic" in prompt
    assert "once" in prompt
```

- [ ] **Step 2: Run to verify they fail**

```bash
uv run pytest tests/application/test_course_authoring.py -k "prompt" -v
```

- [ ] **Step 3: Write the prompts**

`learning_plan_prompt` becomes the plan-then-draft turn. It must, in this order:

1. Tell the model to write the lesson plan **first, in its reply, before
   dispatching anything** — one slot per lesson with title, `builds_toward`,
   the one claim it owns, its opening move, and what it may assume from earlier
   lessons.
2. Then dispatch `anecdote-hunter`s over the area, and assign each returned
   anecdote to exactly one slot. Say plainly that a hunter may return nothing
   and that a slot without an anecdote falls back to a surprising number or a
   disagreement — **never to invented drama.**
3. Then dispatch one `lesson-drafter` per slot, in parallel, handing each its
   slot, its anecdotes, the understandings, and nothing else.
4. Then one `prose-critic` per lesson, and re-dispatch the drafter to revise its
   own file. **Exactly one round.**

Include `COMPONENT_GUIDE` as it does today. Add a paragraph explaining *why*
the plan comes first — that three drafters given an open decision answer it
three ways — because a prompt that gives an order without a reason gets
reordered by a model that thinks it knows better.

`assessment_prompt(area, lesson_count)` dispatches one `quiz-writer` per lesson
against the lessons **as they are written**, then one `unit-reviewer` over all
of them to write `review.md`. It names the lesson paths explicitly (use
`lesson_paths` from Task 1 rather than rebuilding the format string — a fourth
copy of that pattern is a fourth chance for a rename to produce an empty page).

Add `AUTHORING_DISPATCH_PROMPT` to `desired_results_prompt` along with: the
`unit-critic` dispatch, and "revise once and stop; a second round makes the
understandings blander, not truer."

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/application/test_course_authoring.py -v
```

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add research_team/application/course_authoring.py tests/application/test_course_authoring.py
git commit -m "The plan is written before anything is dispatched, and the prompt says why

Anecdotes gathered after drafting are decoration; gathered before, they are the
opening. The prompts assert the order because a model reading a list of things
to do will do the cheapest first, and a prompt that gives an order without a
reason gets reordered by a model that thinks it knows better.

The assessment phase is separate so its items are written from the lessons as
they stand rather than from a plan. Today's items are written in Stage 2,
before any lesson exists, which is why they read as furniture.

The hunter is told it may return nothing, in those words. A corpus with no
incidents yields manufactured drama, which is worse than a flat opening."
```

---

### Task 7: Wire the roster to the authoring purpose

**Files:**
- Modify: `research_team/composition.py` (near `_context_parts`, and the
  `DeepAgentTurnExecutor(...)` construction at ~line 2415)
- Test: `tests/application/test_composition_authoring_subagents.py`

**Interfaces:**
- Consumes: `AUTHORING_SUBAGENTS` (Task 3), `SubagentProvider` (Task 4).
- Produces: a `subagents_provider` passed to the executor, returning
  `AUTHORING_SUBAGENTS` when `session.state.purpose is SessionPurpose.COURSE_AUTHORING`
  and the mode's static roster otherwise.

- [ ] **Step 1: Write the failing test**

```python
"""That authoring sessions get the roster and chat sessions do not.

This is the wiring test the entity-definitions work went without: a build where
`EntityDefinitionRunner` was never constructed served every request as an empty
cache miss, and every test that "confirmed the endpoint worked" passed, because
none of them checked for a stored row. The equivalent here is a roster defined,
tested, and never reaching an authoring turn.
"""
```

Assert both directions: a `COURSE_AUTHORING` session yields the six names, and
a `CHAT` session yields whatever `_context_parts` returned for the configured
mode. Testing only the first direction would pass with the purpose check
deleted.

Build the provider through whatever `build_application` exposes; if it is not
reachable from outside, extract the provider into a named module-level function
in `composition.py` and test that function directly rather than reaching into a
built application.

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Wire it**

Add near `_context_parts`:

```python
def _subagents_for(session: Session, default: Sequence[dict]) -> Sequence[dict]:
    """The roster this turn may dispatch.

    Authoring is the only purpose with its own roster, and the check is on
    purpose rather than on the presence of a course directory: a session's
    purpose is fixed when it starts, where a directory appears partway through
    the first phase, which would give phase 1 a different roster from phase 2.
    """
    if session.state.purpose is SessionPurpose.COURSE_AUTHORING:
        return AUTHORING_SUBAGENTS
    return default
```

and pass an `async def` wrapper as `subagents_provider=` to the executor.

**Decide the general-purpose question here and record it.** `create_deep_agent`
inserts a `general-purpose` subagent, so the roster is seven at runtime.

**This paragraph used to say it could be disabled with
`general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)`. That
keyword does not exist in deepagents 0.7.6** — measured by reading
`inspect.signature(create_deep_agent)`, not reasoned. It comes from the
library's own docstring, which advertises a parameter the function does not
take; the spec and this plan both repeated it from there. The only lever is
that `graph.py` skips the auto-insert when the roster already contains a spec
named `general-purpose` — which is still a seventh subagent. Keep theirs, say
why in the commit message, and write down the cost: an undescribed seventh
subagent carrying the main agent's capabilities, sitting beside six the prompts
describe by name, is an invitation to route work around them.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/application/test_composition_authoring_subagents.py tests/application/test_course_authoring.py -v
```

- [ ] **Step 5: Prove it red**

Change the purpose check to `return default` unconditionally and confirm the
authoring-direction test fails. Restore by re-typing.

- [ ] **Step 6: Lint and commit**

---

### Task 8: Verification and pull request

- [ ] **Step 1: Run the Python gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/application tests/infrastructure -q
```

All three must pass. Do not run the whole suite locally; CI is faster.

- [ ] **Step 2: Confirm the frontend is untouched**

```bash
git diff --stat main...HEAD -- frontend/
```

Expected: empty. If it is not, something went wrong — stop and report it.

- [ ] **Step 3: Update `BACKLOG.md`**

Add an entry recording the two measurements the first live run owes, because
neither is a test and both will otherwise be forgotten:

- How many lesson slots received a real anecdote versus fell back to a number
  or a disagreement. Near zero means the design's central bet is wrong.
- Whether the four-phase run's lessons actually read better than the three-turn
  run's. The old output is in the event log for comparison; `/tmp/lessons` is
  not durable.

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin authoring-subagents
```

The PR body must carry: what changed, the reasoning for Python-owned phases
against model-owned fan-out, the costs stated in the spec (plan not persisted,
no test asserts prose quality, the central bet unverified), and the two
measurements owed. Link the spec and this plan.

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: the roster to Task 3, the
four phases and their checkpoints to Tasks 1 and 5, the prose rubric to Task 2,
the testing section to the tests inside Tasks 1, 3, 4, 5 and 7, and the
per-turn selection the spec implied but did not name to Task 4. The live run
and the anecdote-yield measurement are Task 8 Step 3, recorded in `BACKLOG.md`
rather than pretended to be automatable.

**One gap, deliberate.** The spec's phase 3 checkpoint says every
`builds_toward` resolves to a real Stage 2 item. Task 1 implements presence
only, and says why in both the docstring and the commit message: resolving
prose against prose fails good work on a near-miss and passes anything on a
substring match. If a later run shows lessons naming assessments that do not
exist, that is the moment to revisit it with a real example in hand.

**Two tasks carry an unverified assumption, and both say so inline rather than
hiding it.** Task 2 assumes `prompts/` tolerates a file no preset references,
with an explicit fallback if it does not. Task 4 assumes `Session` can be
constructed in a test the way that test shows, with an instruction to check how
the existing tests do it first. Neither could be settled without running code,
and a plan that stated them as fact would be the more dangerous document.
