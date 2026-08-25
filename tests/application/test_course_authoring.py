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
from research_team.application.components import REGISTRY
from research_team.application.course_authoring import (
    AREAS_DIR,
    COMPONENT_GUIDE,
    PROMPT_ANCHORS,
    CourseAuthor,
    assessment_prompt,
    desired_results_prompt,
    learning_plan_prompt,
    path_overview_prompt,
)
from research_team.domain import SessionPurpose
from research_team.domain.learning_area import (
    AreaMember,
    LearningArea,
    LearningPath,
    PrerequisiteEdge,
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

    Stage 2's prompt must contain Stage 1's *reply*, not merely a reference to
    the file it wrote. A turn told to go and read the file will sometimes not,
    and will then design assessments from the entity list -- forward design
    with the file names of backward design.
    """
    turns = RecordingTurns()
    author = CourseAuthor(FakeSessions(turns.files), turns)

    await author.author_area(uuid4(), AREA, "Ancient Rome")

    assert len(turns.prompts) == 4
    assert "REPLY-1" in turns.prompts[1]
    assert "REPLY-1" in turns.prompts[2]


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
    assert len(turns.prompts) == 1, "the run continued past a failed phase"


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
    assert "REPLY-1" in turns.prompts[1]  # stage 2 given stage 1's reply
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


def test_the_prompt_caps_how_many_anchors_it_names():
    """An area with sixty members does not become a better unit by listing
    sixty; it becomes a unit with no focus."""
    prompt = desired_results_prompt(AREA, "Ancient Rome")

    named = [m.name for m in AREA.members if f"{m.name} (" in prompt]
    assert len(named) == PROMPT_ANCHORS


def test_the_prompt_names_the_most_central_entities():
    """Ranked by centrality, so the twelve named are the twelve the graph says
    the area is about -- not the twelve that sorted first by id."""
    prompt = desired_results_prompt(AREA, "Ancient Rome")

    assert "Entity 0" in prompt
    assert "Entity 19" not in prompt


def test_the_prompt_carries_entity_ids():
    """Six of the ten component types resolve against the project's graph. A
    `definition` block with no entity id renders unavailable forever, and
    nothing warns the author."""
    prompt = desired_results_prompt(AREA, "Ancient Rome")

    assert "`e0`" in prompt


def test_the_path_writeup_is_handed_its_reasoning_rather_than_asked_for_it():
    """A model invited to explain an order it did not compute invents a
    pedagogical rationale that sounds better than the derived one and is
    unfalsifiable."""
    other = LearningArea(slug="the-republic", members=AREA.members[:4])
    path = LearningPath(
        slug="complete",
        title="The complete path",
        area_slugs=("the-republic", "the-principate"),
        edges=(
            PrerequisiteEdge(
                before="the-republic",
                after="the-principate",
                weight=0.8,
                reason="its dated entities come earlier",
                contested=True,
            ),
        ),
    )

    prompt = path_overview_prompt(path, {"the-republic": other, "the-principate": AREA})

    assert "its dated entities come earlier" in prompt
    assert "contested" in prompt
    assert "do not re-order" in prompt


def test_the_guide_names_the_id_field_of_every_type_that_has_one():
    """The prompt-vs-registry agreement nothing was asking for.

    Defect 1 was not a bug in any function: `COMPONENT_GUIDE` told the model to
    copy entity ids exactly and never named a field to put them in, while the
    registry it was describing had `entity_id` on two types and no id field at
    all on three. The model wrote ids into `compare.entities`, which validates
    as a plain string list and renders raw to the reader.

    This is deliberately an agreement test and not a text assertion. It reads
    the same registry the guide is generated from, so it fails if a type grows
    or loses an `entity_id` and the paragraph stops being true -- which is the
    only failure worth catching. It cannot fail on wording, and would not have
    been worth writing if it could: a test comparing the guide against a
    literal copy of itself is a second place to edit, not a check.

    Proved red by generating the guide with the paragraph empty: `entity_id:`
    appears nowhere else in it, so that assertion is the one that catches a
    guide which stopped naming the field.
    """
    named = {name for name, spec in REGISTRY.items() if "entity_id" in spec.fields}
    assert named, "the registry has no id field; this test is now about nothing"
    for name in named:
        assert f"`{name}`" in COMPONENT_GUIDE
    assert "`entity_id:`" in COMPONENT_GUIDE

    # And the other half: a resolved type with no id field must be named as
    # taking none, or the model puts one where there is no home for it.
    nameless = {
        name
        for name, spec in REGISTRY.items()
        if spec.resolved and not {"entity_id", "sources"} & set(spec.fields)
    }
    assert nameless
    for name in nameless:
        assert f"`{name}`" in COMPONENT_GUIDE
    assert "no id at all" in COMPONENT_GUIDE


def test_the_learning_plan_prompt_orders_planning_before_drafting():
    """Anecdotes gathered after drafting are decoration; gathered before, they
    are the opening. The prompt has to say which comes first, because a model
    reading a list of things to do will do the cheapest one first.

    Weak by nature, and worth saying plainly: this is an assertion about where
    three literal strings sit in a template, not about what a model does with
    them. It catches the acts being reordered in the source; it cannot catch a
    prompt that states the order and is ignored. The reason for the order is
    carried by `test_the_learning_plan_prompt_says_why_the_plan_comes_first`,
    which is the half a model actually obeys.
    """
    prompt = learning_plan_prompt(AREA, "STAGE ONE", 3)
    assert prompt.index("anecdote-hunter") < prompt.index("lesson-drafter")
    assert prompt.index("lesson-drafter") < prompt.index("prose-critic")


def test_the_learning_plan_prompt_fixes_the_shared_decisions_before_fan_out():
    """The four decisions that must be made once or get made three times.

    Same weakness as above -- these are substring checks -- but the failure
    they catch is real and has a shape: someone trimming the prompt drops one
    of the four from the slot template, three drafters then answer it
    independently, and the unit reads like three people wrote it with nothing
    raising anywhere.
    """
    prompt = learning_plan_prompt(AREA, "STAGE ONE", 3)
    for shared in ("voice", "assume", "opening move", "claim"):
        assert shared in prompt


@pytest.mark.parametrize("lesson_count", [2, 5])
def test_the_learning_plan_prompt_says_why_the_plan_comes_first(lesson_count):
    """An order without a reason gets reordered by a model that knows better.

    This is the assertion the ordering test above cannot make. Proved red by
    deleting the reason: the ordering test stayed green, because the acts were
    still in sequence and only the reason for the sequence was gone -- which is
    exactly the edit that would look harmless in review.

    Parametrised over two counts, neither of them 3, and that is the whole
    point of the parametrisation rather than tidiness. This test first asserted
    the literal `"three ways"`, ran at `lesson_count=3`, and thereby held in
    place a hardcoded "Three drafters ... three ways" sentence sitting beside
    interpolated clauses -- correct at exactly the one value the test used, and
    self-contradicting at every other. That is CLAUDE.md's `SocraticPrompt`
    shape: the input and the text were chosen by the same person in the same
    hour, and the input sampled the case the text already handled. Anchoring on
    the interpolated phrase at two counts is what separates the two candidates.
    """
    prompt = learning_plan_prompt(AREA, "STAGE ONE", lesson_count)
    assert f"reads like {lesson_count} people wrote it" in prompt
    assert f"because {lesson_count} did" in prompt


@pytest.mark.parametrize("lesson_count", [2, 5])
def test_the_learning_plan_prompt_spells_no_count_it_was_not_given(lesson_count):
    """No bare numeral in this prompt may disagree with `lesson_count`.

    The general form of the defect above, and the reason it is a separate test:
    the one above would pass again the moment someone adds a *different*
    hardcoded number, because it only checks that the interpolated phrases are
    present. This checks the absence.

    Deliberately narrow, and narrower than the first draft. It bans the
    spelled-out numerals only where they modify a noun whose count *is*
    `lesson_count` -- "drafters" and "ways" -- and only in the acts paragraph,
    not in `COMPONENT_GUIDE` or the roster, where "two fields", "three counts"
    and "six subagents" are fixed facts about the schema and the roster.

    The first draft also banned "N lessons" and failed on correct text: Act 2's
    "two lessons opening on the same incident" is a statement about any two
    lessons, not about how many there are. That failure is the honest limit of
    this test -- it can only ban numerals beside nouns nobody uses generically,
    which is a short list, so it catches the defect that occurred rather than
    the whole class.
    """
    spelled = {2: "two", 3: "three", 4: "four", 5: "five"}
    acts = prompt_acts(learning_plan_prompt(AREA, "STAGE ONE", lesson_count))
    for count, word in spelled.items():
        if count == lesson_count:
            continue
        assert f"{word} drafters" not in acts
        assert f"{word} ways" not in acts


def test_the_learning_plan_prompt_allows_exactly_one_critique_round():
    """Act 4's one-round rule, which nothing was asserting.

    `test_the_first_phase_allows_exactly_one_critique_round` covers
    `desired_results_prompt` and not this one. Without this, someone trimming
    Act 4's paragraph while leaving the four act names in sequence keeps the
    ordering test green and ships a critic-to-drafter loop that sands every
    lesson flat -- the same "reason deleted, sequence left standing" edit the
    test above exists for, on the other end of the prompt.
    """
    prompt = learning_plan_prompt(AREA, "STAGE ONE", 3)
    assert "Exactly one round" in prompt
    assert "cleaner and emptier" in prompt


def test_the_learning_plan_prompt_permits_an_empty_hunt():
    """A slot with no anecdote falls back; it does not get drama invented for it.

    The hunter's own prompt already says it may return nothing. This asserts
    the parent was told the same thing, because a parent that reads an empty
    hunt as a failure re-dispatches until it gets something, and what it gets
    on the third try is manufactured.
    """
    prompt = learning_plan_prompt(AREA, "STAGE ONE", 3)
    assert "may return nothing" in prompt
    assert "Never invent drama" in prompt


def test_the_assessment_prompt_is_given_the_lessons_as_written():
    """Items written from a plan test what was planned. The whole reason phase
    4 is separate is that the prose exists by the time it runs.

    The path assertions are the load-bearing half: they fail if this prompt
    ever grows its own `lesson-NN.md` format string instead of calling
    `lesson_paths`, which is the fourth-copy failure CLAUDE.md records against
    `AREAS_DIR`.
    """
    prompt = assessment_prompt(AREA, 2)
    assert "as they are written" in prompt
    assert "lesson-01.md" in prompt and "lesson-02.md" in prompt


def test_the_assessment_prompt_names_every_lesson_it_was_given():
    """Every path the checkpoint will look for is a path the prompt named.

    Honest about what this cannot do: it will not separate `lesson_paths` from
    a correct hand-written copy of the same format string, because a correct
    copy produces the same paths. What it does catch is the pattern *moving* --
    a rename of the directory or of the `lesson-NN.md` shape that updates
    `authoring_checkpoints` and not this prompt. The expectation is derived
    from `lesson_paths` rather than written out, so the two cannot drift apart
    silently, and the drift is the failure: `check_assessment` looks for a
    component in a path the `quiz-writer` was never sent to.
    """
    prompt = assessment_prompt(AREA, 10)
    for path in lesson_paths(AREA.slug, 10):
        assert path in prompt


def test_the_first_phase_allows_exactly_one_critique_round():
    """Weak by nature: substring checks over prompt text.

    `"once"` is the weakest assertion in this file -- it matches any sentence
    containing the word. It is kept because the sentence it stands for is the
    one that stops a parent looping the critic, and something naming it is
    better than nothing. `unit-critic` is the assertion with teeth: it fails
    if the dispatch is dropped.
    """
    prompt = desired_results_prompt(AREA, "Rome")
    assert "unit-critic" in prompt
    assert "once" in prompt
    assert "blander, not truer" in prompt
