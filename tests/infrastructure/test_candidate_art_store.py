"""The candidate-to-art assignment cache. A cache, not a projection --
nothing on the event log describes an assignment, matching
`test_course_blurbs.py` for `CourseBlurbStore`."""

from uuid import uuid4

import pytest

from research_team.infrastructure.persistence.read_models import CandidateArtStore


@pytest.fixture
async def store(db_path):
    opened = await CandidateArtStore.open(db_path)
    try:
        yield opened
    finally:
        await opened.close()


async def test_an_assignment_round_trips(store):
    project_id = uuid4()
    art_id = uuid4()

    await store.put(project_id, "warp-drive", art_id)

    row = await store.get(project_id, "warp-drive")
    assert row is not None
    assert row.art_id == art_id


async def test_an_unassigned_slug_returns_none(store):
    assert await store.get(uuid4(), "warp-drive") is None


async def test_assigning_the_same_slug_twice_replaces_rather_than_duplicates(store):
    """Keyed by (project, slug) through row_id, so reassignment overwrites --
    matching `CourseOutlineStore`'s equivalent test. A second row would make
    `get` return whichever the repository happened to reach first, which is
    an assignment that answers differently at random."""
    project_id = uuid4()
    first_art, second_art = uuid4(), uuid4()

    await store.put(project_id, "warp-drive", first_art)
    await store.put(project_id, "warp-drive", second_art)

    row = await store.get(project_id, "warp-drive")
    assert row is not None
    assert row.art_id == second_art


async def test_the_same_slug_in_two_projects_is_two_rows(store):
    slug = "warp-drive"
    project_a, project_b = uuid4(), uuid4()
    art_a, art_b = uuid4(), uuid4()

    await store.put(project_a, slug, art_a)
    await store.put(project_b, slug, art_b)

    row_a = await store.get(project_a, slug)
    row_b = await store.get(project_b, slug)
    assert row_a is not None and row_a.art_id == art_a
    assert row_b is not None and row_b.art_id == art_b
