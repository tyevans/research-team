"""The blurb cache. A cache, not a projection -- nothing writes it from the log."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from research_team.infrastructure.persistence.read_models import (
    CourseBlurbRow,
    CourseBlurbStore,
)


@pytest.fixture
async def store(db_path):
    opened = await CourseBlurbStore.open(db_path)
    try:
        yield opened
    finally:
        await opened.close()


async def test_a_stored_blurb_reads_back_with_the_hash_it_was_written_from(store):
    """The hash is the point of the row. Without it a blurb describing a
    cluster that has since doubled is indistinguishable from a current one."""
    project = uuid4()
    await store.put(
        project,
        "warp",
        "Warp Drive Basics",
        "Learn about warp drive.",
        "abc123",
        "m",
        datetime.now(UTC),
    )

    row = await store.get(project, "warp")

    assert row is not None
    assert row.title == "Warp Drive Basics"
    assert row.text == "Learn about warp drive."
    assert row.membership_hash == "abc123"


async def test_a_blurb_row_written_before_titles_existed_reads_back_with_an_empty_title(store):
    """`apply_schema` reconciles added columns, but it leaves them empty in
    rows that predate the change. A `title` with no default would make the
    column required on a populated table, which the read-models section of
    CLAUDE.md records as the case SQLite refuses and this project already
    shipped once. Empty is the honest value and the fallback covers it."""
    project = uuid4()
    connection = store._connection  # simulating a pre-migration row, before `title` existed
    now = datetime.now(UTC).isoformat()
    await connection.execute(
        "INSERT INTO course_blurbs "
        "(id, created_at, updated_at, project_id, slug, text, membership_hash, "
        "model, generated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(CourseBlurbRow.row_id(project, "warp")),
            now,
            now,
            str(project),
            "warp",
            "Learn about warp drive.",
            "abc123",
            "m",
            now,
        ),
    )
    await connection.commit()

    row = await store.get(project, "warp")

    assert row is not None
    assert row.title == ""
    assert row.text == "Learn about warp drive."


async def test_rewriting_a_slug_replaces_rather_than_duplicates(store):
    project = uuid4()
    await store.put(project, "warp", "First Title", "First.", "abc123", "m", datetime.now(UTC))

    await store.put(
        project, "warp", "Second Title", "Second.", "def456", "m", datetime.now(UTC)
    )

    row = await store.get(project, "warp")
    assert row is not None
    assert row.text == "Second."
    assert row.membership_hash == "def456"


async def test_an_unwritten_slug_is_none_rather_than_an_error(store):
    """`None` is an ordinary answer: every candidate on a cold project has no
    blurb, and the card renders without one."""
    assert await store.get(uuid4(), "never-written") is None


async def test_one_projects_blurbs_are_invisible_to_another(store):
    mine, theirs = uuid4(), uuid4()
    await store.put(mine, "warp", "Mine", "Mine.", "abc", "m", datetime.now(UTC))

    assert await store.get(theirs, "warp") is None
