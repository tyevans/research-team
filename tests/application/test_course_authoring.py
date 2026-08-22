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

from research_team.application.course_authoring import (
    AREAS_DIR,
    PROMPT_ANCHORS,
    CourseAuthor,
    desired_results_prompt,
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
