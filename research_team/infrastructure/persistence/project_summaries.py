"""The one adapter behind `ProjectSummaries`, reading four tables in one pass.

Every table this touches -- `topics`, `corpus_documents`, `courses`,
`session_summary_rows` -- lives in the same SQLite file, which is what makes
this a single connection and four `GROUP BY`s rather than a fan-out across
four stores. That is a fact about how this project is deployed rather than a
guarantee of the read models, and it is the assumption to check first if this
ever answers zeros: a store moved to its own file would still open, still
answer, and silently group over an empty table.

**It owns no schema.** Every table it reads is created and kept level with the
log by the runner that owns it (`CorpusRunner`, `OntologyRunner`,
`_CourseRunner`, `SessionSummaryRunner`), and this class deliberately does not
call `apply_schema` on any of them: a reader that also declared the schema
would be a second writer of the same DDL, and the two would drift the first
time a column was added to one and not the other. The cost is that this has to
tolerate a table that does not exist yet -- see `_present`.
"""

from uuid import UUID

import aiosqlite

from research_team.application.project_summaries import ProjectSummary

# The four tables, named once. They are string literals rather than
# `CorpusDocumentRow.table_name()` calls on purpose: importing four read-model
# classes to reach four constant strings would make this module depend on the
# whole of `read_models.py` -- roughly 3,000 lines and every store in the
# system -- to build a `SELECT`. The names are pinned instead by
# `test_the_tables_this_reads_are_the_tables_the_read_models_declare`, which
# imports those classes in the test process and fails if a name here stops
# matching. A constant that is checked is cheaper than an import that is not.
TOPICS = "topics"
CORPUS = "corpus_documents"
COURSES = "courses"
SESSIONS = "session_summary_rows"


class SqliteProjectSummaries:
    """`ProjectSummaries` over the console's own database."""

    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._connection = connection

    async def all(self) -> dict[UUID, ProjectSummary]:
        """Every project's counts, in four grouped queries and no per-project work.

        The queries are issued separately rather than joined into one
        statement, and the reason is that they cannot be joined correctly: a
        project with 11 sources and 14 topics has no relation between the two
        sets, so a join would produce 154 rows and a `COUNT` over it would be
        the product rather than either count. Four scans and a merge in Python
        is both right and, on tables this size, faster than the `DISTINCT`
        that would be needed to repair the join.
        """
        topics = await self._grouped(
            TOPICS,
            "COUNT(*), SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END)",
            "deleted_at IS NULL",
        )
        # `dropped_reason IS NULL` mirrors `CorpusStore.list`'s own filter
        # rather than being invented here: a dropped document is a judgement
        # somebody made, kept on the row so it stays legible, and an index
        # that counted it would report work the project has explicitly
        # retracted.
        sources = await self._grouped(
            CORPUS,
            "COUNT(*), SUM(CASE WHEN extracted_at IS NOT NULL THEN 1 ELSE 0 END)",
            "deleted_at IS NULL AND dropped_reason IS NULL",
        )
        # `abandoned = 0` for `dropped_reason`'s reason. `CourseRow` marks
        # rather than deletes so that a replay landing between `CourseRealized`
        # and `CourseAbandoned` differs from one landing after both; that
        # distinction is the archive's, and an index showing an abandoned
        # course as a course would be reporting a decision as its opposite.
        courses = await self._grouped(
            COURSES, "COUNT(*), 0", "deleted_at IS NULL AND abandoned = 0"
        )
        sessions = await self._grouped_activity()

        ids = set(topics) | set(sources) | set(courses) | set(sessions)
        summaries: dict[UUID, ProjectSummary] = {}
        for project_id in ids:
            topic_count, topic_open = topics.get(project_id, (0, 0))
            source_count, extracted = sources.get(project_id, (0, 0))
            course_count, _ = courses.get(project_id, (0, 0))
            session_count, last_activity = sessions.get(project_id, (0, None))
            summaries[project_id] = ProjectSummary(
                topics=topic_count,
                topics_open=topic_open,
                sources=source_count,
                extracted=extracted,
                courses=course_count,
                sessions=session_count,
                last_activity=last_activity,
            )
        return summaries

    async def _grouped(
        self, table: str, columns: str, where: str
    ) -> dict[UUID, tuple[int, int]]:
        """One stage's two counts per project, or nothing if the table is absent."""
        if not await self._present(table):
            return {}
        cursor = await self._connection.execute(
            f"SELECT project_id, {columns} FROM {table} WHERE {where} GROUP BY project_id"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return {
            UUID(str(row[0])): (int(row[1] or 0), int(row[2] or 0))
            for row in rows
            if row[0] is not None
        }

    async def _grouped_activity(self) -> dict[UUID, tuple[int, str | None]]:
        """Session count and the newest `updated_at`, per project.

        `MAX(updated_at)` rather than `MAX(started_at)`, which is the whole
        point of this method existing separately from `_grouped`: the start is
        when a session was minted and the update is when the projection last
        folded a turn into it. The landing page showed the first and called it
        the second.

        Lexicographic `MAX` over an ISO-8601 string is a real ordering here
        because every writer of this column emits UTC with the same offset
        form; a naive local timestamp in the same column would sort wrong and
        would do so silently. Nothing in this repository writes one, and
        `test_last_activity_is_the_newest_update_not_the_newest_start` is what
        would fail if that changed.
        """
        if not await self._present(SESSIONS):
            return {}
        cursor = await self._connection.execute(
            f"SELECT project_id, COUNT(*), MAX(updated_at) FROM {SESSIONS} "
            "WHERE deleted_at IS NULL GROUP BY project_id"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return {
            UUID(str(row[0])): (int(row[1] or 0), row[2]) for row in rows if row[0] is not None
        }

    async def _present(self, table: str) -> bool:
        """Whether a table exists at all.

        Checked rather than assumed because this reader owns none of these
        tables and is constructed beside the runners that do, not after them.
        A build that wires the summaries and leaves one runner out is a
        configuration this has to survive: the alternative is an
        `OperationalError` out of `GET /api/projects`, which would take the
        whole index down over a stage that is merely empty.

        The honest cost, stated because it is the failure this cannot
        distinguish: a table that is missing and a table that is empty both
        answer zero, so a stage silently absent from every row looks like a
        stage nobody has used. That is the right trade for an index -- it is
        the surface where a partial answer beats no answer -- and it is the
        wrong trade anywhere a caller acts on the number.
        """
        cursor = await self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        )
        found = await cursor.fetchone()
        await cursor.close()
        return found is not None
