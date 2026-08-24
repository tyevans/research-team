from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eventsource import CommandRejectedError

from research_team.domain.course import (
    AbandonCourse,
    CourseAbandoned,
    CourseFit,
    CourseRealized,
    CourseState,
    RealizeCourse,
    course_stream_id,
    decide,
    evolve,
    fit_of,
)
from research_team.domain.learning_area import AreaMember, LearningArea


def _area(slug: str, ids: list[str]) -> LearningArea:
    members = tuple(
        AreaMember(entity_id=i, name=i.title(), entity_type="concept", centrality=1.0)
        for i in ids
    )
    return LearningArea(slug=slug, members=members)


def _realize(project_id, slug="warp-drive", ids=("a", "b")) -> RealizeCourse:
    return RealizeCourse(
        project_id=project_id,
        slug=slug,
        title="Warp Drive",
        member_entity_ids=tuple(ids),
        membership_hash="deadbeef",
        realized_at=datetime.now(UTC),
    )


def test_realizing_an_unrealized_course_emits_the_frozen_membership():
    project_id = uuid4()
    events = decide(_realize(project_id), CourseState())
    assert len(events) == 1
    assert isinstance(events[0], CourseRealized)
    assert events[0].member_entity_ids == ["a", "b"]


def test_realizing_twice_is_refused():
    """The invariant. A second CourseRealized would overwrite the frozen
    membership that fit is computed against, erasing the drift by observing
    it. Rejection is what keeps the comparison meaningful."""
    project_id = uuid4()
    state = evolve(CourseState(), decide(_realize(project_id), CourseState())[0])
    with pytest.raises(CommandRejectedError):
        decide(_realize(project_id, ids=("a", "b", "c")), state)


def test_abandoning_then_realizing_freezes_the_new_membership():
    """Abandon is a deliberate second decision, so re-realizing after it is
    allowed and *does* re-freeze. Distinguishes the guarded accident from the
    intended act."""
    project_id = uuid4()
    state = evolve(CourseState(), decide(_realize(project_id), CourseState())[0])
    abandoned = decide(AbandonCourse(project_id, "warp-drive"), state)[0]
    assert isinstance(abandoned, CourseAbandoned)
    state = evolve(state, abandoned)
    events = decide(_realize(project_id, ids=("a", "b", "c")), state)
    assert events[0].member_entity_ids == ["a", "b", "c"]


def test_abandoning_an_unrealized_course_is_refused():
    with pytest.raises(CommandRejectedError):
        decide(AbandonCourse(uuid4(), "warp-drive"), CourseState())


@pytest.mark.parametrize(
    "area, expected",
    [
        pytest.param(
            _area("warp-drive", ["a", "b"]),
            CourseFit(kept=("a", "b"), added=(), dropped=(), orphaned=False),
            id="unchanged",
        ),
        pytest.param(
            _area("warp-drive", ["b", "c"]),
            CourseFit(kept=("b",), added=("c",), dropped=("a",), orphaned=False),
            id="drifted",
        ),
        pytest.param(
            None,
            CourseFit(kept=(), added=(), dropped=("a", "b"), orphaned=True),
            id="orphaned",
        ),
    ],
)
def test_fit_distinguishes_drift_from_orphaning(area, expected):
    """Parametrised over the property that separates the two answers -- whether
    the slug resolves at all -- rather than over a representative example. An
    orphaned course and a course that lost every member produce identical
    `dropped` tuples and must still be told apart, which is what `orphaned`
    carries and what a single non-parametrised case would never check."""
    assert fit_of(("a", "b"), area) == expected


def test_the_same_project_and_slug_always_resolve_to_the_same_stream():
    """The property `uuid5` is being relied on for, and the one thing that
    makes realize-after-restart reach the course it already wrote.

    Nothing stores a slug-to-id mapping, so a derivation that varied by
    process -- `hash()`, which is salted per process, or a `uuid4` minted at
    call time -- would file the second realization in a stream the first never
    touched. The aggregate would then load empty, the realize-once invariant
    would never fire, and the frozen membership would be silently overwritten
    on every restart. That failure is invisible in a single process, which is
    every test in this file above this one.
    """
    project_id = uuid4()
    assert course_stream_id(project_id, "warp-drive") == course_stream_id(
        project_id, "warp-drive"
    )
    assert course_stream_id(project_id, "warp-drive") != course_stream_id(
        project_id, "transporters"
    )
    assert course_stream_id(project_id, "warp-drive") != course_stream_id(
        uuid4(), "warp-drive"
    )
