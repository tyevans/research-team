"""That backward design is actually enforced, and not merely requested.

The one property worth testing here is sequencing: Stage 2 must be written
*from* Stage 1's output, and Stage 3 from both. Everything else in this module
is prompt text, which no test can adjudicate.

The failure being guarded against is specific and would be invisible: a
refactor that runs the four turns concurrently, or that builds all four
prompts up front, produces a course with every section present and in the
right file, written forwards. Nothing raises and the output looks right.
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
    COMPONENT_GUIDE,
    PROMPT_ANCHORS,
    RETRY_PREFACE,
    CourseAuthor,
    learning_plan_prompt,
)
from research_team.domain import SessionPurpose
from research_team.domain.learning_area import (
    AreaMember,
    LearningArea,
)


class Outcome:
    def __init__(self, reply: str) -> None:
        self.reply = reply


class RecordingTurns:
    """Records every prompt in the order it was actually run.

    Also writes checkpoint-passing content into `files` after every turn, for
    `AREA` at `lesson_count=3` -- the values every test in this file that uses
    it happens to call `author_area` with. These tests predate the four
    checkpoints and are about prompt content and turn ordering, not about what
    a phase must leave behind; without this, `author_area` would raise
    `CheckpointFailed` after phase one on every one of them, for a reason none
    of them are testing. `test_a_phase_that_wrote_nothing_fails_the_run` is
    where an empty workspace is the point.
    """

    def __init__(self, files: dict[str, dict[str, str]] | None = None) -> None:
        self.prompts: list[str] = []
        self.files = files if files is not None else {}

    async def run(self, session_id: UUID, user_input: str) -> Outcome:
        self.prompts.append(user_input)
        n = len(self.prompts)
        unit_path = f"{AREAS_DIR}/{AREA.slug}/unit.md"
        if n == 1:
            self.files[unit_path] = {
                "content": (
                    "## Enduring Understandings\n- a\n- b\n\n"
                    "## Essential Questions\n- a\n- b\n- c\n"
                )
            }
        elif n == 2:
            self.files[unit_path]["content"] += (
                f"\n## Stage 2 — Evidence\n"
                f"{PERFORMANCE_TASK_MARKER} One.\n{PERFORMANCE_TASK_MARKER} Two.\n"
            )
        elif n == 3:
            for path in lesson_paths(AREA.slug, 3):
                self.files[path] = {"content": "builds_toward: x\n"}
        elif n == 4:
            for path in lesson_paths(AREA.slug, 3):
                self.files[path]["content"] += "\n```component:mcq\n```\n"
            self.files[f"{AREAS_DIR}/{AREA.slug}/review.md"] = {"content": "Review.\n"}
        return Outcome(f"REPLY-{n}")


class FakeState:
    def __init__(self, files: dict[str, dict[str, str]]) -> None:
        self.files = files


class FakeSession:
    def __init__(self, files: dict[str, dict[str, str]]) -> None:
        self.state = FakeState(files)


class FakeSessions:
    """`SessionService`'s slice `CourseAuthor` uses, over an in-memory dict.

    `files` is the same dict a `WritingTurns` fake writes into, shared rather
    than copied, so `load` always reads what the turn runner just wrote --
    `author_area` re-reads the workspace after every phase, and a snapshot
    taken at construction would answer every checkpoint from an empty
    workspace no matter what ran.
    """

    def __init__(self, files: dict[str, dict[str, str]] | None = None) -> None:
        self.started: list[SessionPurpose] = []
        self.attached: list[UUID] = []
        self.released: list[UUID] = []
        self.files = files if files is not None else {}

    async def start_in_project(self, project_id: UUID, purpose: SessionPurpose) -> UUID:
        self.started.append(purpose)
        return uuid4()

    async def attach_project(self, project_id: UUID) -> None:
        self.attached.append(project_id)

    async def release_project(self, session_id: UUID) -> None:
        self.released.append(session_id)

    async def load(self, session_id: UUID) -> FakeSession:
        return FakeSession(self.files)


def member(eid: str, name: str, centrality: float) -> AreaMember:
    return AreaMember(entity_id=eid, name=name, entity_type="concept", centrality=centrality)


def prompt_acts(prompt: str) -> str:
    """The four-acts body, with `COMPONENT_GUIDE` and the roster cut off.

    Both tails carry fixed numerals -- "two fields", "six subagents" -- that
    have nothing to do with `lesson_count`, and a numeral ban applied to them
    would fail correct text.

    Partitioned on `COMPONENT_GUIDE`'s own opening rather than on a copy of its
    first sentence, and it raises rather than returning the whole prompt when
    the marker is missing. The literal copy failed *open*: `str.split` on an
    absent separator returns one element, so a reword of the guide silently
    widened this slice to the entire prompt with nothing going red. Today that
    would still pass -- neither tail contains "N drafters" or "N ways" -- which
    is exactly the problem, because the boundary test would have stopped
    testing a boundary and said nothing. A prefix, not the whole constant, so
    the marker survives a change to the guide's body.
    """
    marker = COMPONENT_GUIDE[:40]
    head, found, _ = prompt.partition(marker)
    if not found:
        raise AssertionError(
            f"the prompt does not carry COMPONENT_GUIDE's opening: {marker!r}"
        )
    return head


AREA = LearningArea(
    slug="the-principate",
    members=tuple(member(f"e{i}", f"Entity {i}", float(20 - i)) for i in range(20)),
)


@pytest.mark.asyncio
async def test_stage_two_is_written_from_stage_one():
    """The turn that makes backward design real.

    Stages 2 and 3 must be handed Stage 1's understandings verbatim, not
    merely a reference to the file holding them. A turn told to go and read
    the file will sometimes not, and will then design assessments from the
    entity list -- forward design with the file names of backward design.

    **What is handed over is the file, and it used to be the reply.** That
    changed on the branch that bounded a parent's research: on every run this
    could be measured against, phase 1 finished with an empty reply, so "Stage
    1 produced this" would have introduced nothing. The file is also the
    artifact the later phases are supposed to stay faithful to -- a model that
    wrote `unit.md` and then summarised it differently in prose left two Stage
    1s with nothing choosing between them. `stage_one_text` is where the slice
    at the Stage 2 heading is argued.

    This test would pass against the old code too, on this fixture, because
    `RecordingTurns` writes both -- which is why the assertion is on a string
    only the *file* carries.
    """
    turns = RecordingTurns()
    author = CourseAuthor(FakeSessions(turns.files), turns)

    await author.author_area(uuid4(), AREA, "Ancient Rome")

    assert len(turns.prompts) == 4
    assert "## Enduring Understandings" in turns.prompts[1]
    assert "## Enduring Understandings" in turns.prompts[2]
    assert "REPLY-1" not in turns.prompts[1]


@pytest.mark.asyncio
async def test_stage_three_is_not_given_stage_two_verbatim():
    """Stage 3 reads Stage 2 off the file rather than being handed it.

    Deliberate and worth pinning, because it looks like an omission. Stage 2's
    reply is a chat reply about assessments it *wrote to a file*; pasting it
    into Stage 3 would hand the model a paraphrase of the assessments to
    build toward instead of the assessments, and the lessons would then serve
    items that do not exist in the unit.
    """
    turns = RecordingTurns()
    author = CourseAuthor(FakeSessions(turns.files), turns)

    await author.author_area(uuid4(), AREA, "Ancient Rome")

    assert "REPLY-2" not in turns.prompts[2]
    assert f"{AREAS_DIR}/the-principate/unit.md" in turns.prompts[2]


@pytest.mark.asyncio
async def test_all_four_phases_share_one_session():
    """Stage 2 reads what Stage 1 wrote, and a workspace does not cross sessions."""
    turns = RecordingTurns()
    sessions = FakeSessions(turns.files)

    await CourseAuthor(sessions, turns).author_area(uuid4(), AREA, "Ancient Rome")

    assert sessions.started == [SessionPurpose.COURSE_AUTHORING]
    assert len(sessions.released) == 1


@pytest.mark.asyncio
async def test_the_project_is_released_even_when_a_turn_fails():
    """A run that dies holding the project locks out every later turn, over a
    crash that produced nothing."""

    class Failing(RecordingTurns):
        async def run(self, session_id: UUID, user_input: str) -> Outcome:
            await super().run(session_id, user_input)
            raise RuntimeError("model endpoint refused")

    sessions = FakeSessions()
    with pytest.raises(RuntimeError):
        await CourseAuthor(sessions, Failing()).author_area(uuid4(), AREA, "Rome")

    assert len(sessions.released) == 1


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

    async def run(self, session_id: UUID, user_input: str) -> Outcome:
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
    author = CourseAuthor(FakeSessions(turns.files), turns)

    with pytest.raises(CheckpointFailed) as caught:
        await author.author_area(uuid4(), AREA, "Rome")

    assert caught.value.phase == "stage_one"
    # Two turns, not one: `_phase` retries a refused phase once in the same
    # session. Both are phase 1 -- the assertion that matters is that the
    # second is a *retry* and not phase 2, because "kept going anyway" and
    # "tried again" produce the same count and only one of them is the bug
    # this test has always been about.
    assert len(turns.prompts) == 2, "the run continued past a failed phase"
    assert turns.prompts[1].startswith(RETRY_PREFACE[:40])
    assert "Stage 2" not in turns.prompts[1]


@pytest.mark.asyncio
async def test_the_four_phases_run_in_order():
    """Each phase is asserted checkpoint-valid before the next is dispatched,
    and phases 1-3's prompts each carry a fragment of what the phase before
    them wrote -- the same backward-design guarantee the sequencing tests
    above pin.

    Would pass if the phases ran in the wrong order but each still happened to
    produce checkpoint-valid content in isolation; what it actually catches is
    a later phase's prompt losing the earlier phase's output, which is the
    edit that looks like a harmless prompt-builder refactor.

    Phase 4's assertion is weaker and deliberately so: `assessment_prompt`
    builds its lesson paths from `lesson_paths(area.slug, lesson_count)` --
    computed from arguments already in hand, not carried from phase 3's
    reply -- so this assertion holds even with phase 3 removed entirely.
    `check_lessons` is what actually connects phase 3's output to phase 4;
    this test only checks that phase 4 named the right paths, which
    `assessment_prompt`'s own docstring already says needs nothing from phase
    3's reply.
    """
    unit_path = f"{AREAS_DIR}/{AREA.slug}/unit.md"
    stage_one = (
        "## Enduring Understandings\n- a\n- b\n\n## Essential Questions\n- a\n- b\n- c\n"
    )
    stage_two = (
        stage_one
        + "\n## Stage 2 — Evidence\n"
        + f"{PERFORMANCE_TASK_MARKER} One.\n{PERFORMANCE_TASK_MARKER} Two.\n"
    )
    lesson_01, lesson_02, lesson_03 = lesson_paths(AREA.slug, 3)
    lessons_written = "builds_toward: x\n"
    turns = WritingTurns(
        [
            {unit_path: stage_one},
            {unit_path: stage_two},
            {
                lesson_01: lessons_written,
                lesson_02: lessons_written,
                lesson_03: lessons_written,
            },
            {
                lesson_01: lessons_written + "\n```component:mcq\n```\n",
                lesson_02: lessons_written + "\n```component:mcq\n```\n",
                lesson_03: lessons_written + "\n```component:mcq\n```\n",
                f"{AREAS_DIR}/{AREA.slug}/review.md": "Review.\n",
            },
        ]
    )
    author = CourseAuthor(FakeSessions(turns.files), turns)

    await author.author_area(uuid4(), AREA, "Rome")

    assert len(turns.prompts) == 4
    # Phase 1 has no prior stage to be faithful to. Asserted as the absence of
    # any earlier *reply* rather than of the heading text: since 2026-08-24
    # `desired_results_prompt` names `## Enduring Understandings` itself, so
    # the old assertion on the heading would now fail on correct output.
    assert "REPLY-" not in turns.prompts[0]
    # Stage 2 is given Stage 1's *file*, not its reply -- see
    # `test_stage_two_is_written_from_stage_one` for why that changed.
    assert "REPLY-1" not in turns.prompts[1]
    assert "## Enduring Understandings" in turns.prompts[1]
    assert unit_path in turns.prompts[2]  # stage 3 reads stage 2 off the file
    assert lesson_01 in turns.prompts[3]  # phase 4 named the lessons it expects, by path


@pytest.mark.asyncio
async def test_the_project_is_released_when_a_checkpoint_fails():
    """The `finally` that already guards a crash must also guard a refusal.

    A run that dies holding the project locks out every later turn, and a
    checkpoint failure is a much more likely death than an exception from the
    model."""
    turns = WritingTurns([{}, {}, {}, {}])
    sessions = FakeSessions(turns.files)
    author = CourseAuthor(sessions, turns)

    with pytest.raises(CheckpointFailed):
        await author.author_area(uuid4(), AREA, "Rome")

    assert sessions.released, "a failed checkpoint left the project locked"


def test_act_three_hands_every_drafter_the_anchor_ids():
    """A drafter that was not given the ids invents them, and the widget is dead.

    `COMPONENT_GUIDE` is in `lesson-drafter`'s own system prompt, but the ids
    are per-area and only the parent has them: Act 3's "give it **nothing
    else**" was written to keep one lesson's slot away from another drafter,
    and before 2026-08-24 it also withheld the anchor list, because the anchors
    live in `_area_header` and Act 3 did not list them. The result is
    `course_authoring`'s own defect 1 one layer down -- an invented id renders
    `unavailable` forever and nothing warns.

    Asserts the ids reach the acts body, not the tail: `prompt_acts` cuts
    `COMPONENT_GUIDE` and the roster off, so this cannot pass on the guide's
    mention of ids.

    Proved red by deleting the `_anchor_lines(area)` interpolation from Act 3.
    """
    acts = prompt_acts(learning_plan_prompt(AREA, "STAGE ONE", 3))
    named = [m for m in AREA.members if f"id `{m.entity_id}`" in acts]
    assert named, "Act 3 named no entity id"
    assert len(named) == PROMPT_ANCHORS
    assert AREA.members[0].name in acts
