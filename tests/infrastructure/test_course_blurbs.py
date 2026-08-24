"""The blurb cache. A cache, not a projection -- nothing writes it from the log."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from research_team.infrastructure.persistence.read_models import CourseBlurbStore


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


async def test_a_blurb_row_written_before_titles_existed_reads_back_with_an_empty_title(
    store, db_path
):
    """`apply_schema` reconciles added columns, but it leaves them empty in
    rows that predate the change. A `title` with no default would make the
    column required on a populated table, which the read-models section of
    CLAUDE.md records as the case SQLite refuses and this project already
    shipped once. Empty is the honest value and the fallback covers it.

    A pre-migration row is simulated with a real `ALTER TABLE ... DROP
    COLUMN` against a *populated* table, not by inserting a row that merely
    omits `title` against the current schema -- that lighter version only
    pins `DEFAULT ''` firing on insert, and says nothing about whether
    `apply_schema` can widen a table that already has rows in it without
    raising. CLAUDE.md's "Read models" section is explicit that a read-model
    change verified only against a fresh database is unverified; reopening
    through `CourseBlurbStore.open` after the column is gone is what actually
    exercises the reconciliation path, and this is the case CLAUDE.md
    describes as already having shipped broken once (a required column with
    no default refused outright on a table with rows in it).
    """
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
    await store._connection.execute("ALTER TABLE course_blurbs DROP COLUMN title")
    await store._connection.commit()
    await store.close()

    reopened = await CourseBlurbStore.open(db_path)
    try:
        row = await reopened.get(project, "warp")
    finally:
        await reopened.close()

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


async def test_all_for_project_reads_every_cached_slug_in_one_call(store):
    """`CatalogService.build` used to call `get` once per area; this is the
    replacement -- one query for the whole project. Keyed by slug, matching
    what a caller would already build from N `get` calls, so switching
    callers over changes nothing about what "cached" means."""
    project = uuid4()
    await store.put(project, "warp", "Warp", "Warp copy.", "h1", "m", datetime.now(UTC))
    await store.put(
        project, "shields", "Shields", "Shield copy.", "h2", "m", datetime.now(UTC)
    )

    rows = await store.all_for_project(project)

    assert set(rows) == {"warp", "shields"}
    assert rows["warp"].text == "Warp copy."
    assert rows["shields"].membership_hash == "h2"


async def test_all_for_project_excludes_another_projects_rows(store):
    """The same isolation `get` enforces via `row.project_id != project_id`,
    proven here for the bulk read instead -- a query over the wrong id would
    leak another project's cached copy into this one's catalog."""
    mine, theirs = uuid4(), uuid4()
    await store.put(mine, "warp", "Mine", "Mine.", "abc", "m", datetime.now(UTC))
    await store.put(theirs, "warp", "Theirs", "Theirs.", "def", "m", datetime.now(UTC))

    rows = await store.all_for_project(mine)

    assert set(rows) == {"warp"}
    assert rows["warp"].text == "Mine."


async def test_all_for_project_is_empty_for_a_project_with_no_cached_blurbs(store):
    assert await store.all_for_project(uuid4()) == {}
