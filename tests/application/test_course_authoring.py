"""That backward design is actually enforced, and not merely requested.

The one property worth testing here is sequencing: Stage 2 must be written
*from* Stage 1's output, and Stage 3 from both. Everything else in this module
is prompt text, which no test can adjudicate.

The failure being guarded against is specific and would be invisible: a
refactor that runs the three turns concurrently, or that builds all three
prompts up front, produces a course with every section present and in the
right file, written forwards. Nothing raises and the output looks right.
"""

from uuid import UUID, uuid4

import pytest

from research_team.application.authoring_checkpoints import lesson_paths
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
    """Records every prompt in the order it was actually run."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def run(self, session_id: UUID, user_input: str) -> Outcome:
        self.prompts.append(user_input)
        return Outcome(f"REPLY-{len(self.prompts)}")


class FakeSessions:
    def __init__(self) -> None:
        self.started: list[SessionPurpose] = []
        self.attached: list[UUID] = []
        self.released: list[UUID] = []

    async def start_in_project(self, project_id: UUID, purpose: SessionPurpose) -> UUID:
        self.started.append(purpose)
        return uuid4()

    async def attach_project(self, project_id: UUID) -> None:
        self.attached.append(project_id)

    async def release_project(self, session_id: UUID) -> None:
        self.released.append(session_id)


def member(eid: str, name: str, centrality: float) -> AreaMember:
    return AreaMember(entity_id=eid, name=name, entity_type="concept", centrality=centrality)


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
    author = CourseAuthor(FakeSessions(), turns)

    await author.author_area(uuid4(), AREA, "Ancient Rome")

    assert len(turns.prompts) == 3
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
    author = CourseAuthor(FakeSessions(), turns)

    await author.author_area(uuid4(), AREA, "Ancient Rome")

    assert "REPLY-2" not in turns.prompts[2]
    assert f"{AREAS_DIR}/the-principate/unit.md" in turns.prompts[2]


@pytest.mark.asyncio
async def test_all_three_turns_share_one_session():
    """Stage 2 reads what Stage 1 wrote, and a workspace does not cross sessions."""
    turns = RecordingTurns()
    sessions = FakeSessions()

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


def test_the_learning_plan_prompt_says_why_the_plan_comes_first():
    """An order without a reason gets reordered by a model that knows better.

    This is the assertion the ordering test above cannot make. Proved red by
    deleting the sentence: the ordering test stayed green, because the acts
    were still in sequence and only the reason for the sequence was gone --
    which is exactly the edit that would look harmless in review.
    """
    prompt = learning_plan_prompt(AREA, "STAGE ONE", 3)
    assert "three ways" in prompt


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
