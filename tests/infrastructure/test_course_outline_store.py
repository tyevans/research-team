"""The outline cache. A cache, not a projection -- nothing writes it from the
log, matching `test_course_blurbs.py` for `CourseBlurbStore`."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from research_team.infrastructure.persistence.read_models import (
    CandidateArtRow,
    CatalogFeatureRow,
    CourseBlurbRow,
    CourseOutlineRow,
    CourseOutlineStore,
    CourseRow,
)


@pytest.fixture
async def store(db_path):
    opened = await CourseOutlineStore.open(db_path)
    try:
        yield opened
    finally:
        await opened.close()


async def test_an_outline_round_trips_its_sections(store):
    project_id = uuid4()
    await store.put(
        project_id,
        "warp-drive",
        promise="What made faster-than-light travel possible.",
        sections=[{"heading": "Origins", "summary": "Cochrane's first flight."}],
        membership_hash="deadbeef",
        model="qwen",
        generated_at=datetime.now(UTC),
    )

    row = await store.get(project_id, "warp-drive")

    assert row is not None
    assert row.sections == [{"heading": "Origins", "summary": "Cochrane's first flight."}]
    assert row.membership_hash == "deadbeef"


async def test_putting_the_same_slug_twice_replaces_rather_than_duplicates(store):
    """Keyed by (project, slug) through row_id, so regenerating after drift
    overwrites. A second row would make `get` return whichever the repository
    happened to reach first, which is a cache that reports a stale hash at
    random."""
    project_id = uuid4()
    await store.put(
        project_id,
        "warp-drive",
        promise="First promise.",
        sections=[{"heading": "First", "summary": "First."}],
        membership_hash="aaa",
        model="qwen",
        generated_at=datetime.now(UTC),
    )

    await store.put(
        project_id,
        "warp-drive",
        promise="Second promise.",
        sections=[{"heading": "Second", "summary": "Second."}],
        membership_hash="bbb",
        model="qwen",
        generated_at=datetime.now(UTC),
    )

    row = await store.get(project_id, "warp-drive")
    assert row is not None
    assert row.promise == "Second promise."
    assert row.membership_hash == "bbb"


async def test_an_outline_row_id_does_not_collide_with_any_sibling(store):
    """Five row types now derive an id from `CATALOG_NAMESPACE` over the same
    `{project_id}:{slug}` pair, and a literal prefix is the only thing keeping
    any two of them apart -- none for `CatalogFeatureRow`, then `blurb:`,
    `course:`, `outline:` and `art:` (Task: art storage).

    Checked against every sibling rather than only the blurb. A version of this
    test naming one neighbour passes while `outline:` collides with any of the
    others, and the failure that would cause is a store silently reading and
    overwriting another table's row for the same course.
    """
    project_id = uuid4()
    ids = {
        CourseOutlineRow.row_id(project_id, "warp-drive"),
        CourseBlurbRow.row_id(project_id, "warp-drive"),
        CourseRow.row_id(project_id, "warp-drive"),
        CatalogFeatureRow.row_id(project_id, "warp-drive"),
        CandidateArtRow.row_id(project_id, "warp-drive"),
    }

    assert len(ids) == 5
