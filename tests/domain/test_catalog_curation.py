"""The two curation events, and the one property they have to keep."""

from uuid import uuid4

from research_team.domain.catalog_curation import (
    CATALOG_AGGREGATE_TYPE,
    CourseFeatured,
    CourseUnfeatured,
)


def test_featuring_carries_the_slug_rather_than_a_course_id():
    """A person features a candidate, and most candidates are not realized.

    Keying on a minted course id would make the hero row unusable on a fresh
    project, which is every project before anyone has built a course.
    """
    project = uuid4()
    event = CourseFeatured(aggregate_id=project, project_id=project, slug="warp-drive", rank=0)

    assert event.slug == "warp-drive"
    assert event.rank == 0


def test_both_events_land_on_the_catalog_stream():
    project = uuid4()

    assert (
        CourseFeatured(
            aggregate_id=project, project_id=project, slug="s", rank=1
        ).aggregate_type
        == CATALOG_AGGREGATE_TYPE
    )
    assert (
        CourseUnfeatured(aggregate_id=project, project_id=project, slug="s").aggregate_type
        == CATALOG_AGGREGATE_TYPE
    )
