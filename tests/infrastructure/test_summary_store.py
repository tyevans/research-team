"""The persisted `/sessions` list, over a real SQLite file.

The projection's own tests use an in-memory repository, because what they are
about is the fold. These are about the parts only a real database has: that
the table gets created, that rows survive a reopen, and that the projection
picks up where it left off instead of starting over or double-counting.
"""

from uuid import uuid4

from research_team.domain import (
    SendUserMessage,
    StartSession,
)
from research_team.infrastructure.persistence import SessionSummaryStore
from tests.conftest import MODEL_NAME, SYSTEM_PROMPT


async def test_the_table_is_created_on_open(db_path):
    """No migration step to forget: opening the store is enough."""
    store = await SessionSummaryStore.open(db_path)
    try:
        assert await store.list() == []
    finally:
        await store.close()


async def test_rows_outlive_the_process(db_path, repository, session_id):
    session = repository.create(session_id)
    session.execute(
        StartSession(
            session_id=session.aggregate_id,
            system_prompt=SYSTEM_PROMPT,
            model_name=MODEL_NAME,
            project_id=uuid4(),
        )
    )
    session.execute(
        SendUserMessage(message={"type": "human", "data": {"content": "remembered"}})
    )
    events = list(session.uncommitted_events)

    store = await SessionSummaryStore.open(db_path)
    for event in events:
        await store.projection.handle(event)
    await store.close()

    reopened = await SessionSummaryStore.open(db_path)
    try:
        [summary] = await reopened.list()
        assert summary.session_id == session_id
        assert summary.first_message == "remembered"
    finally:
        await reopened.close()


async def test_sessions_are_listed_newest_first(db_path, repository):
    store = await SessionSummaryStore.open(db_path)
    try:
        for label in ("older", "newer"):
            session = repository.create(uuid4())
            session.execute(
                StartSession(
                    session_id=session.aggregate_id,
                    system_prompt=SYSTEM_PROMPT,
                    model_name=MODEL_NAME,
                    project_id=uuid4(),
                )
            )
            session.execute(
                SendUserMessage(message={"type": "human", "data": {"content": label}})
            )
            for event in session.uncommitted_events:
                await store.projection.handle(event)

        listed = await store.list()
        assert [summary.first_message for summary in listed] == ["newer", "older"]
    finally:
        await store.close()


async def test_a_sessions_project_survives_a_reopen(db_path, repository, session_id):
    """`project_id` is written by the creation handler and never touched again.

    Worth pinning over a real file rather than only in the fold: the column has
    to exist in the generated DDL, and a UUID has to survive the round trip
    through SQLite as one -- neither of which the in-memory repository proves.
    """
    project_id = uuid4()
    session = repository.create(session_id)
    session.execute(
        StartSession(
            session_id=session.aggregate_id,
            system_prompt=SYSTEM_PROMPT,
            model_name=MODEL_NAME,
            project_id=project_id,
        )
    )
    events = list(session.uncommitted_events)

    store = await SessionSummaryStore.open(db_path)
    for event in events:
        await store.projection.handle(event)
    await store.close()

    reopened = await SessionSummaryStore.open(db_path)
    try:
        [summary] = await reopened.list()
        assert summary.project_id == project_id
    finally:
        await reopened.close()


async def test_a_database_written_before_a_field_existed_gains_its_column(db_path):
    """Adding a field to the row type must not break an existing database.

    `CREATE TABLE IF NOT EXISTS` is the whole of the DDL, so a table that
    already exists never gains a column and every read fails against a row type
    declaring one. Adding `project_id` did exactly that: a fresh database was
    fine, every test passed, and `/sessions` and `/tree` answered 500 against
    the only database anybody actually had.

    Simulated by dropping the column back off, which is the shape of the
    problem: a table one field behind the model.
    """
    import aiosqlite

    store = await SessionSummaryStore.open(db_path)
    await store.close()

    async with aiosqlite.connect(db_path) as connection:
        await connection.execute("ALTER TABLE session_summary_rows DROP COLUMN project_id")
        await connection.commit()

    reopened = await SessionSummaryStore.open(db_path)
    try:
        columns = await reopened._connection.execute("PRAGMA table_info(session_summary_rows)")
        assert "project_id" in {row[1] for row in await columns.fetchall()}
        # And it still answers, which is the failure a schema check alone misses.
        assert await reopened.list() == []
    finally:
        await reopened.close()
