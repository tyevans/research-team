"""The persisted `/sessions` list, over a real SQLite file.

The projection's own tests use an in-memory repository, because what they are
about is the fold. These are about the parts only a real database has: that
the table gets created, that rows survive a reopen, and that the projection
picks up where it left off instead of starting over or double-counting.
"""

from uuid import uuid4

import aiosqlite
from eventsource import ReadModel
from eventsource.ports.readmodels import ReadModelSchemaMismatchError

from research_team.domain import (
    SendUserMessage,
    SessionPurpose,
    StartSession,
)
from research_team.infrastructure.persistence import SessionSummaryStore
from research_team.infrastructure.persistence.read_models import apply_schema, model_schema
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
            purpose=SessionPurpose.CHAT,
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
                    purpose=SessionPurpose.CHAT,
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
            purpose=SessionPurpose.CHAT,
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


class _NarrowRow(ReadModel):
    """A read model as an older build declared it."""

    __table_name__ = "widening_rows"

    settled: str = ""


class _WidenedRow(_NarrowRow):
    """The same table after two fields were added, one of them unaddable.

    Declaration order is load-bearing: `generate_additive_migration` walks the
    model's fields in order, so `nickname` is the column the old loop had
    already applied by the time SQLite refused `owner`.
    """

    nickname: str | None = None
    owner: str


class _AddableRow(_NarrowRow):
    """The same table grown by a column that any table can take."""

    nickname: str | None = None


async def test_a_populated_table_gains_an_addable_column(db_path):
    """Rows present is the normal case, and must still reconcile.

    Passes against the previous implementation too -- it is here because the
    refusal path now recreates an empty table wholesale, and a mistake in the
    branch that chooses between the two would take this case with it and lose
    the rows. Nothing else asserts the data survives, because every other
    old-database test starts from a table with no rows in it.
    """
    async with aiosqlite.connect(db_path) as connection:
        await connection.executescript(model_schema(_NarrowRow))
        await connection.execute(
            "INSERT INTO widening_rows (id, created_at, updated_at, version, settled) "
            "VALUES ('a', '2026-08-13', '2026-08-13', 1, 'kept')"
        )
        await connection.commit()

        await apply_schema(connection, _AddableRow)

        columns = await connection.execute("PRAGMA table_info(widening_rows)")
        assert "nickname" in {row[1] for row in await columns.fetchall()}
        surviving = await (
            await connection.execute("SELECT settled FROM widening_rows")
        ).fetchall()

    assert surviving == [("kept",)]


async def test_a_refused_reconcile_leaves_the_table_untouched(db_path):
    """A model that cannot be reconciled must add none of its columns, not some.

    The old loop issued one ALTER per missing column and let SQLite refuse the
    impossible one mid-way, so a model that grew two fields -- one addable, one
    NOT NULL with no default -- left the table half-widened, with the error
    naming only the second. `generate_additive_migration` raises before
    returning any statement, so the refusal is atomic and the next developer
    sees the table exactly as it was.

    Fails against the previous implementation on the `nickname` assertion,
    which is checked before the exception type deliberately: the old code did
    refuse, so a test that only asserted the raise would fail on the type and
    say nothing about what the refusal left behind.
    """
    async with aiosqlite.connect(db_path) as connection:
        await connection.executescript(model_schema(_NarrowRow))
        # A row, because that is what makes the column impossible. SQLite
        # accepts `NOT NULL` with no default on an *empty* table, so a test
        # against a fresh one would watch the old loop widen the table
        # completely and prove nothing about the refusal at all.
        await connection.execute(
            "INSERT INTO widening_rows (id, created_at, updated_at, version, settled) "
            "VALUES ('a', '2026-08-13', '2026-08-13', 1, 'kept')"
        )
        await connection.commit()

        raised: Exception | None = None
        try:
            await apply_schema(connection, _WidenedRow)
        except Exception as error:  # noqa: BLE001 -- the type is asserted below
            raised = error

        columns = await connection.execute("PRAGMA table_info(widening_rows)")
        present = {row[1] for row in await columns.fetchall()}

    assert "nickname" not in present, "the addable column landed before the refusal"
    assert "owner" not in present
    assert isinstance(raised, ReadModelSchemaMismatchError)
    assert "owner" in str(raised)
