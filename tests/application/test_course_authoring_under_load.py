"""That a large topic does not end the run, and that the parent stays small.

The regression guard for a failure that is in the owner's log rather than in
anyone's imagination. Of 22 course-authoring sessions in
`~/.research-team/sessions.db` on 2026-08-29, **four completed all four phases
and eighteen did not**. The mechanism, read off sessions `67838bd5`,
`3569666e` and `8519cab4` -- the same `mid-2000s` area of the Star Trek project
run three times with byte-identical results -- is a parent that spent eighteen
model calls and thirty tool calls on graph and corpus queries, twelve of them
near-identical rephrasings of one question, then called `ls` on its own output
directory, got `No files found`, and returned `content: ""` with no tool calls.
`check_stage_one` refused at `unit.md was not written` and the area was thrown
away whole.

**It is not a context-window overflow, and that was the first guess.** Replaying
`ElideToolResults` as `.env` configures it over every one of those 22 sessions,
the largest request any authoring turn has ever built is ~42k tokens against a
64k-context model; the three runs above peaked at 7,275. Bounding what a turn
*re-sends* would have changed nothing. What was unbounded is the number of tool
rounds inside one phase.

Two halves of the fix, and this file holds the second:

* `ResearchBudget` withdraws the reading tools past a measured number of model
  calls -- `tests/infrastructure/test_research_budget.py`.
* `CourseAuthor._phase` retries a refused phase once in the same session, so a
  phase 3 that fails does not discard the two phases behind it, and no phase
  prompt grows with what the lessons contain.

**Everything here is parametrised over the property that distinguishes the
failing case** -- corpus size, lesson count, lesson length, which phase fails --
rather than over a representative example. A test written at one area size
cannot see a prompt that grows with the corpus, because there is nothing for it
to grow relative to.
"""

from uuid import UUID, uuid4

import pytest

from research_team.application.authoring_checkpoints import (
    PERFORMANCE_TASK_MARKER,
    CheckpointFailed,
    lesson_paths,
)
from research_team.application.course_authoring import (
    AREAS_DIR,
    PROMPT_ANCHORS,
    RETRY_PREFACE,
    CourseAuthor,
)
from research_team.domain import SessionPurpose
from research_team.domain.learning_area import AreaMember, LearningArea


class Outcome:
    def __init__(self, reply: str) -> None:
        self.reply = reply


class FakeState:
    def __init__(self, files):
        self.files = files


class FakeSession:
    def __init__(self, files):
        self.state = FakeState(files)


class FakeSessions:
    """`SessionService`'s slice `CourseAuthor` uses, over the turn runner's
    own dict -- shared rather than copied, so `load` reads what the turn just
    wrote. A snapshot taken at construction would answer every checkpoint from
    an empty workspace no matter what ran."""

    def __init__(self, files) -> None:
        self.files = files
        self.released: list[UUID] = []

    async def start_in_project(self, project_id: UUID, purpose: SessionPurpose) -> UUID:
        return uuid4()

    async def attach_project(self, project_id: UUID) -> None:
        return None

    async def release_project(self, session_id: UUID) -> None:
        self.released.append(session_id)

    async def load(self, session_id: UUID) -> FakeSession:
        return FakeSession(self.files)


def area_of(size: int) -> LearningArea:
    return LearningArea(
        slug="the-principate",
        members=tuple(
            AreaMember(
                entity_id=f"e{i}",
                name=f"Entity {i}",
                entity_type="concept",
                centrality=float(size - i),
            )
            for i in range(size)
        ),
    )


def four_phase_writes(area_slug: str, lesson_count: int, body: str = "") -> list[dict]:
    """What each phase must leave behind for its own checkpoint to pass."""
    unit = f"{AREAS_DIR}/{area_slug}/unit.md"
    stage_one = (
        "## Enduring Understandings\n- a\n- b\n\n## Essential Questions\n- a\n- b\n- c\n"
    )
    drafted = dict.fromkeys(
        lesson_paths(area_slug, lesson_count),
        f"builds_toward: x\n{body}\n```component:mcq\n```\n",
    )
    return [
        {unit: stage_one},
        {
            unit: stage_one
            + f"\n## Stage 2 — Evidence\n{PERFORMANCE_TASK_MARKER} One.\n"
            + f"{PERFORMANCE_TASK_MARKER} Two.\n"
        },
        dict(drafted),
        {
            **{path: text + "```component:cloze\n```\n" for path, text in drafted.items()},
            f"{AREAS_DIR}/{area_slug}/review.md": "Review.\n",
        },
    ]


class Turns:
    """Writes each phase's files, optionally refusing one phase once.

    `refuse` names a phase rather than meaning "fail somewhere", so a test can
    assert the retry went back to *that* phase rather than to the start of the
    area -- which is the whole distinction between resuming and restarting, and
    the two produce identical prompt counts if you only count.
    """

    def __init__(self, writes: list[dict], refuse: int | None = None) -> None:
        self.writes = writes
        self.refuse = refuse
        self.prompts: list[str] = []
        self.files: dict[str, dict[str, str]] = {}
        self._phase = 0
        self._refused = False

    async def run(self, session_id: UUID, user_input: str) -> Outcome:
        self.prompts.append(user_input)
        if self._phase == self.refuse and not self._refused:
            # Writes nothing and replies with nothing: exactly how the three
            # `mid-2000s` runs ended phase 1.
            self._refused = True
            return Outcome("")
        for path, content in self.writes[self._phase].items():
            self.files[path] = {"content": content}
        self._phase += 1
        return Outcome(f"REPLY-{self._phase}")


@pytest.mark.asyncio
@pytest.mark.parametrize("refuse", [0, 1, 2, 3])
async def test_a_refused_phase_is_retried_from_where_it_stopped(refuse):
    """The run survives a refusal in any phase, and resumes at that phase.

    Parametrised over *which* phase fails rather than run once at phase 1,
    because the phases differ in what they are handed: 2 and 3 carry Stage 1's
    file, 4 carries component counts read before it ran. A retry that
    re-derived any of those from the failed turn would work at phase 1 and be
    wrong later, and a test at one phase could not tell.

    Would fail with `_phase`'s retry removed: `author_area` raises
    `CheckpointFailed` instead of returning a course.
    """
    area = area_of(20)
    turns = Turns(four_phase_writes(area.slug, 3), refuse=refuse)
    author = CourseAuthor(FakeSessions(turns.files), turns)

    course = await author.author_area(uuid4(), area, "Rome")

    assert len(turns.prompts) == 5, "one turn per phase, plus exactly one retry"
    assert turns.prompts[refuse + 1].startswith(RETRY_PREFACE[:40])
    assert len(course.replies) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("refuse", [0, 2])
async def test_a_retry_is_told_what_the_checkpoint_actually_said(refuse):
    """The complaint is interpolated from `CheckpointFailed.reason`, not
    paraphrased -- the same rule as the marker constants, applied to the
    failure. A retry told only "that did not work" is a retry that repeats the
    turn, which is what the model already did."""
    area = area_of(20)
    turns = Turns(four_phase_writes(area.slug, 3), refuse=refuse)
    author = CourseAuthor(FakeSessions(turns.files), turns)

    await author.author_area(uuid4(), area, "Rome")

    retry = turns.prompts[refuse + 1]
    assert "was not written" in retry or "component" in retry
    # And the phase's own instructions again, because by the retry they are
    # twenty tool results back behind an `elide` placeholder.
    assert turns.prompts[refuse] in retry


@pytest.mark.asyncio
async def test_a_phase_refused_twice_gives_up_rather_than_looping():
    """One retry, not a loop. A phase failing for a reason another turn cannot
    fix -- a corpus too thin to carry two enduring understandings -- would
    otherwise spend a local model's evening rediscovering that. The second
    refusal is chained to the first so a traceback still shows the retry
    happened; a run reporting one failure and two turns of elapsed time has
    nothing joining them."""
    area = area_of(20)
    turns = Turns([{}, {}, {}, {}])
    author = CourseAuthor(FakeSessions(turns.files), turns)

    with pytest.raises(CheckpointFailed) as caught:
        await author.author_area(uuid4(), area, "Rome")

    assert caught.value.phase == "stage_one"
    assert isinstance(caught.value.__cause__, CheckpointFailed)
    assert len(turns.prompts) == 2


@pytest.mark.asyncio
async def test_the_project_is_released_even_when_the_retry_fails_too():
    """The `finally` has to survive the extra turn. A run that dies holding the
    project locks out every later turn, and the retry put a second way to die
    inside the block it guards."""
    area = area_of(20)
    turns = Turns([{}, {}, {}, {}])
    sessions = FakeSessions(turns.files)
    author = CourseAuthor(sessions, turns)

    with pytest.raises(CheckpointFailed):
        await author.author_area(uuid4(), area, "Rome")

    assert len(sessions.released) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("lesson_count", [1, 3, 8])
@pytest.mark.parametrize("area_size", [4, 20, 120])
async def test_no_phase_prompt_carries_a_lesson_body(lesson_count, area_size):
    """The bound this whole change argues for: the parent's context grows with
    the *number* of units, not with their contents.

    Two things are varied because each is a way the bound could break without
    the other noticing -- the corpus (does an area of 120 send more than one of
    4?) and the fan-out (does an eight-lesson unit cost more per lesson than a
    one-lesson unit?). The lesson bodies are 40,000 characters each, which is
    larger than the whole 64k-token window once there are three of them: a
    phase that read the lessons back would not merely be wasteful, it would be
    the crash.

    A character ceiling was rejected as the assertion. A ceiling passes for
    whatever reason happens to hold today, says nothing about why, and needs
    re-tuning every time a prompt gains a sentence.
    """
    area = area_of(area_size)
    body = "L" * 40_000
    turns = Turns(four_phase_writes(area.slug, lesson_count, body))
    author = CourseAuthor(FakeSessions(turns.files), turns)

    await author.author_area(uuid4(), area, "Rome", lesson_count=lesson_count)

    for index, prompt in enumerate(turns.prompts):
        assert body not in prompt, f"phase {index + 1} was handed a lesson body"


@pytest.mark.asyncio
@pytest.mark.parametrize("area_size", [PROMPT_ANCHORS, 60, 400])
async def test_the_corpus_cannot_inflate_a_phase_prompt(area_size):
    """An area six times larger names the same twelve entities.

    `PROMPT_ANCHORS` predates this branch, so this passes with everything on it
    reverted -- said plainly rather than left as reassurance. It is here
    because the fix above would be worthless beside a prompt that still grew
    with the graph, and nothing else asserted the two properties together.
    """
    area = area_of(area_size)
    turns = Turns(four_phase_writes(area.slug, 3))
    author = CourseAuthor(FakeSessions(turns.files), turns)

    await author.author_area(uuid4(), area, "Rome")

    assert f"Entity {PROMPT_ANCHORS - 1}" in turns.prompts[0]
    assert f"Entity {PROMPT_ANCHORS}" not in turns.prompts[0]


@pytest.mark.asyncio
async def test_stage_one_is_handed_over_without_stage_two_attached():
    """Phase 2 appends its evidence to the same `unit.md`, so a phase 3 handed
    the whole file would meet the evidence section twice, once labelled "Stage
    1 produced this". `stage_one_text` slices at the Stage 2 heading.

    Would pass against a version that handed over phase 1's *reply* instead --
    which is what this code did until this branch -- so the assertion is on the
    file's own text, and on the marker only phase 2 writes.
    """
    area = area_of(20)
    turns = Turns(four_phase_writes(area.slug, 3))
    author = CourseAuthor(FakeSessions(turns.files), turns)

    await author.author_area(uuid4(), area, "Rome")

    assert "## Enduring Understandings" in turns.prompts[2]
    assert PERFORMANCE_TASK_MARKER not in turns.prompts[2]
