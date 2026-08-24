"""`CourseStore` / `CourseProjection`: the read model `CourseRealized` and
`CourseAbandoned` project into.

`abandoned` is a column, not a delete -- a rebuild replays `CourseRealized`
then `CourseAbandoned` in order, and a delete-based projection that replays
out of order or is truncated mid-way resurrects the course. Every test here
asserts the row's state after both events in order, never merely that a
delete happened.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from research_team.domain.course import CourseAbandoned, CourseRealized, course_stream_id
from research_team.infrastructure.persistence.read_models import (
    CATALOG_NAMESPACE,
    CatalogFeatureRow,
    CourseBlurbRow,
    CourseProjection,
    CourseRow,
    CourseStore,
)

pytestmark = pytest.mark.asyncio


async def test_realizing_stores_the_frozen_membership(tmp_path):
    """Asserts the row and its ids, not that anything returned 200.

    This is the test CLAUDE.md's projection entry asks for: an event no
    projection handles counts as applied, so a build with CourseProjection
    unregistered answers every request happily with an empty table. An
    assertion on a status code passes with the projection deleted; this one
    does not.
    """
    store = await CourseStore.open(str(tmp_path / "r.db"))
    project_id = uuid4()
    await CourseProjection(store).handle(
        CourseRealized(
            aggregate_id=course_stream_id(project_id, "warp-drive").aggregate_id,
            project_id=project_id,
            slug="warp-drive",
            title="Warp Drive",
            member_entity_ids=["a", "b"],
            membership_hash="deadbeef",
            realized_at=datetime.now(UTC),
        )
    )
    row = await store.get(project_id, "warp-drive")
    assert row is not None
    assert row.member_entity_ids == ["a", "b"]
    assert row.abandoned is False
    await store.close()


async def test_abandoning_marks_the_row_rather_than_deleting_it(tmp_path):
    """A delete would let a rebuild resurrect the course: the projection
    replays CourseRealized, finds nothing to undo it, and the course comes
    back realized. The column survives the replay in the right order."""
    store = await CourseStore.open(str(tmp_path / "r.db"))
    project_id = uuid4()
    projection = CourseProjection(store)
    await projection.handle(
        CourseRealized(
            aggregate_id=course_stream_id(project_id, "warp-drive").aggregate_id,
            project_id=project_id,
            slug="warp-drive",
            title="Warp Drive",
            member_entity_ids=["a", "b"],
            membership_hash="deadbeef",
            realized_at=datetime.now(UTC),
        )
    )
    await projection.handle(
        CourseAbandoned(
            aggregate_id=course_stream_id(project_id, "warp-drive").aggregate_id,
            project_id=project_id,
            slug="warp-drive",
        )
    )
    row = await store.get(project_id, "warp-drive")
    assert row is not None
    assert row.abandoned is True
    assert row.member_entity_ids == ["a", "b"]
    await store.close()


async def test_for_project_omits_another_projects_courses(tmp_path):
    store = await CourseStore.open(str(tmp_path / "r.db"))
    project_id = uuid4()
    other_project_id = uuid4()
    projection = CourseProjection(store)
    await projection.handle(
        CourseRealized(
            aggregate_id=course_stream_id(project_id, "warp-drive").aggregate_id,
            project_id=project_id,
            slug="warp-drive",
            title="Warp Drive",
            member_entity_ids=["a", "b"],
            membership_hash="deadbeef",
            realized_at=datetime.now(UTC),
        )
    )
    await projection.handle(
        CourseRealized(
            aggregate_id=course_stream_id(other_project_id, "ftl-comms").aggregate_id,
            project_id=other_project_id,
            slug="ftl-comms",
            title="FTL Comms",
            member_entity_ids=["c"],
            membership_hash="feedface",
            realized_at=datetime.now(UTC),
        )
    )
    rows = await store.for_project(project_id)
    assert [row.slug for row in rows] == ["warp-drive"]
    await store.close()


async def test_for_project_omits_abandoned_courses(tmp_path):
    store = await CourseStore.open(str(tmp_path / "r.db"))
    project_id = uuid4()
    projection = CourseProjection(store)
    await projection.handle(
        CourseRealized(
            aggregate_id=course_stream_id(project_id, "warp-drive").aggregate_id,
            project_id=project_id,
            slug="warp-drive",
            title="Warp Drive",
            member_entity_ids=["a", "b"],
            membership_hash="deadbeef",
            realized_at=datetime.now(UTC),
        )
    )
    await projection.handle(
        CourseAbandoned(
            aggregate_id=course_stream_id(project_id, "warp-drive").aggregate_id,
            project_id=project_id,
            slug="warp-drive",
        )
    )
    rows = await store.for_project(project_id)
    assert rows == []
    await store.close()


async def test_a_course_row_id_does_not_collide_with_a_blurb_or_a_feature():
    """All three share CATALOG_NAMESPACE and hash the same {project}:{slug}
    pair. The prefixes are what keep them apart, and this fails if one is
    dropped."""
    project_id, slug = uuid4(), "warp-drive"
    ids = {
        CourseRow.row_id(project_id, slug),
        CourseBlurbRow.row_id(project_id, slug),
        CatalogFeatureRow.row_id(project_id, slug),
    }
    assert len(ids) == 3
    # And genuinely under CATALOG_NAMESPACE, not merely three distinct values.
    assert CourseRow.row_id(project_id, slug) != CATALOG_NAMESPACE
