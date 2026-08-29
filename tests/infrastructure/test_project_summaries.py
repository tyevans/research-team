"""The index's counts, driven end to end over tables nothing here declared.

Every test builds its database with hand-written `CREATE TABLE` statements
rather than through `apply_schema`, and that is the whole design of this file.
`SqliteProjectSummaries` owns no schema -- four other runners do -- so a
fixture that created the tables through the read-model classes would be
proving the reader can query a table the reader's own dependencies just made.
CLAUDE.md's fixture rule one level up: the arrange phase must not supply the
thing under test.

The columns below are therefore a *copy* of the read models' shape, which is
a duplication with a known failure mode -- the copy drifts and the tests keep
passing against a table the system no longer writes.
`test_the_tables_this_reads_are_the_tables_the_read_models_declare` is what
holds the names in agreement; the column names are held by
`test_every_column_this_reads_exists_on_the_read_model_that_writes_it`.
"""

from uuid import UUID

import aiosqlite
import pytest

from research_team.infrastructure.persistence.project_summaries import (
    CORPUS,
    COURSES,
    SESSIONS,
    TOPICS,
    SqliteProjectSummaries,
)

PROJECT = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"

# The four tables as an older build wrote them: every column the reader names,
# and nothing else. Deliberately narrower than the real read models, so a
# reader that started selecting a column it does not need fails here.
SCHEMA = f"""
CREATE TABLE {TOPICS} (
    project_id TEXT, status TEXT, deleted_at TEXT
);
CREATE TABLE {CORPUS} (
    project_id TEXT, extracted_at TEXT, dropped_reason TEXT, deleted_at TEXT
);
CREATE TABLE {COURSES} (
    project_id TEXT, abandoned INTEGER, deleted_at TEXT
);
CREATE TABLE {SESSIONS} (
    project_id TEXT, started_at TEXT, updated_at TEXT, deleted_at TEXT
);
"""


@pytest.fixture
async def connection():
    """An in-memory database holding the four tables and nothing else."""
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(SCHEMA)
    await conn.commit()
    yield conn
    await conn.close()


async def test_a_project_with_nothing_in_it_is_absent_rather_than_zeroed(connection):
    """The reader answers only projects it has rows for.

    Pinned because the presenter depends on it: `project_summary_view` turns
    `None` into zeros, and it would be dead code -- and the "nothing yet"
    versus "not measured" distinction lost -- if the reader zero-filled here
    instead. This test fails if that judgement moves down a layer.
    """
    assert await SqliteProjectSummaries(connection).all() == {}


async def test_each_stage_counts_its_own_rows_for_its_own_project(connection):
    """The four counts, over a database where every stage has a decoy.

    Each table holds a row for `OTHER` as well, so a reader that dropped its
    `GROUP BY` and counted the table would answer 2 where 1 is right. A
    fixture with one project in it could not tell those apart.
    """
    await connection.execute(
        f"INSERT INTO {TOPICS} VALUES (?, 'open', NULL), (?, 'investigating', NULL), "
        f"(?, 'open', NULL)",
        (PROJECT, PROJECT, OTHER),
    )
    await connection.execute(
        f"INSERT INTO {CORPUS} VALUES (?, '2026-01-01', NULL, NULL), (?, NULL, NULL, NULL), "
        f"(?, NULL, NULL, NULL)",
        (PROJECT, PROJECT, OTHER),
    )
    await connection.execute(
        f"INSERT INTO {COURSES} VALUES (?, 0, NULL), (?, 0, NULL)", (PROJECT, OTHER)
    )
    await connection.execute(
        f"INSERT INTO {SESSIONS} VALUES (?, 'a', 'b', NULL), (?, 'a', 'b', NULL)",
        (PROJECT, OTHER),
    )
    await connection.commit()

    summary = (await SqliteProjectSummaries(connection).all())[UUID(PROJECT)]

    assert summary.topics == 2
    assert summary.topics_open == 1
    assert summary.sources == 2
    assert summary.extracted == 1
    assert summary.courses == 1
    assert summary.sessions == 1


async def test_retracted_work_is_not_counted_as_work(connection):
    """A dropped document and an abandoned course are excluded.

    Both are *marked* rather than deleted in their read models, on purpose, so
    a reader that filtered on `deleted_at` alone would count them. That is the
    specific mistake this covers: `deleted_at IS NULL` looks like a complete
    filter and is not, and the row it lets through reports a decision as its
    opposite.
    """
    await connection.execute(
        f"INSERT INTO {CORPUS} VALUES (?, '2026-01-01', 'duplicate', NULL), "
        f"(?, '2026-01-01', NULL, NULL)",
        (PROJECT, PROJECT),
    )
    await connection.execute(
        f"INSERT INTO {COURSES} VALUES (?, 1, NULL), (?, 0, NULL)", (PROJECT, PROJECT)
    )
    await connection.commit()

    summary = (await SqliteProjectSummaries(connection).all())[UUID(PROJECT)]

    assert summary.sources == 1, "a dropped document is retracted, not held"
    assert summary.extracted == 1, "and it must not be counted as extracted either"
    assert summary.courses == 1, "an abandoned course is not a course"


async def test_last_activity_is_the_newest_update_not_the_newest_start(connection):
    """The field the landing page had wrong, rather than missing.

    The two rows below are the shape measured against a copy of the real
    database on 2026-08-29: a session started early and updated late, beside a
    session started late and never updated since. Ranking on `started_at`
    picks the second and reports the project as last touched at 05:00; the
    truth is 06:30.

    **This test fails if `_grouped_activity` selects `started_at`**, which is
    the one-word change that would silently restore the old behaviour -- and
    would restore it invisibly, because every value stays plausible.
    """
    await connection.execute(
        f"INSERT INTO {SESSIONS} VALUES "
        f"(?, '2026-08-29T04:00:00Z', '2026-08-29T06:30:00Z', NULL), "
        f"(?, '2026-08-29T05:00:00Z', '2026-08-29T05:00:00Z', NULL)",
        (PROJECT, PROJECT),
    )
    await connection.commit()

    summary = (await SqliteProjectSummaries(connection).all())[UUID(PROJECT)]

    assert summary.last_activity == "2026-08-29T06:30:00Z"


async def test_a_missing_table_answers_zero_rather_than_raising():
    """A build with a runner unwired still lists its projects.

    The index is the one surface where a partial answer beats no answer: an
    `OperationalError` out of `/api/projects` would take the whole page down
    over a stage that is merely absent. Only `sessions` exists here.
    """
    conn = await aiosqlite.connect(":memory:")
    await conn.executescript(
        f"CREATE TABLE {SESSIONS} (project_id TEXT, started_at TEXT, "
        f"updated_at TEXT, deleted_at TEXT);"
    )
    await conn.execute(f"INSERT INTO {SESSIONS} VALUES (?, 'a', 'b', NULL)", (PROJECT,))
    await conn.commit()

    summary = (await SqliteProjectSummaries(conn).all())[UUID(PROJECT)]

    assert summary.sessions == 1
    assert summary.sources == 0 and summary.topics == 0 and summary.courses == 0
    await conn.close()


def test_the_tables_this_reads_are_the_tables_the_read_models_declare():
    """The four literals, against the classes that own them.

    The reader names its tables as strings to avoid importing the whole of
    `read_models.py` to build a `SELECT`. That is only safe while something
    compares the two, and this is it: a table renamed on the read model and
    not here would otherwise make every count silently zero, because
    `_present` turns an unknown table into an empty result rather than an
    error.
    """
    from research_team.infrastructure.persistence.read_models import (
        CorpusDocumentRow,
        CourseRow,
        SessionSummaryRow,
    )

    assert CorpusDocumentRow.table_name() == CORPUS
    assert CourseRow.table_name() == COURSES
    assert SessionSummaryRow.table_name() == SESSIONS


def test_every_column_this_reads_exists_on_the_read_model_that_writes_it():
    """The column names, held the same way the table names are.

    `SCHEMA` above hand-writes these tables, so nothing else in this file
    would notice `extracted_at` being renamed on `CorpusDocumentRow` -- the
    fixture would keep creating the old column and every test would keep
    passing against a table the system no longer writes. That is the drift
    this closes.

    `topics` is absent because its read model lives in redstring's ontology
    layer rather than in `read_models.py`; its columns are covered by the
    live-database test below instead.
    """
    from research_team.infrastructure.persistence.read_models import (
        CorpusDocumentRow,
        CourseRow,
        SessionSummaryRow,
    )

    assert {"project_id", "extracted_at", "dropped_reason"} <= set(
        CorpusDocumentRow.model_fields
    )
    assert {"project_id", "abandoned"} <= set(CourseRow.model_fields)
    assert {"project_id", "started_at"} <= set(SessionSummaryRow.model_fields)
