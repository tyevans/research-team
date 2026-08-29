"""The persisted `/sessions` list, over a real SQLite file.

The projection's own tests use an in-memory repository, because what they are
about is the fold. These are about the parts only a real database has: that
the table gets created, that rows survive a reopen, and that the projection
picks up where it left off instead of starting over or double-counting.
"""

from uuid import uuid4

import aiosqlite
import pytest
from eventsource import ReadModel
from eventsource.ports.readmodels import ReadModelSchemaMismatchError

from research_team.domain import (
    SendUserMessage,
    SessionPurpose,
    StartSession,
)
from research_team.infrastructure.persistence import SessionSummaryStore
from research_team.infrastructure.persistence.read_models import (
    SocraticDialogueRow,
    SocraticTurnRow,
    apply_schema,
    model_schema,
)
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


async def test_an_empty_table_takes_the_recreate_rather_than_the_refusal(db_path):
    """`BACKLOG.md` B47: the one branch here that destroys a table.

    `apply_schema` has three outcomes and until now two of them were pinned.
    The widen is `test_a_populated_table_gains_an_addable_column`; the refusal
    is `test_a_refused_reconcile_leaves_the_table_untouched`. The third -- a
    `DROP TABLE` and a recreate -- was reached only incidentally, by
    `test_a_database_written_before_a_field_existed_gains_its_column`, which
    passes because `project_id` arrives rather than because the table was
    dropped.

    That asymmetry is what B47 is about: the branch is chosen by a single
    `SELECT 1 ... LIMIT 1`, and inverting that condition would drop a populated
    table with nothing in the tree turning red. This test and the refusal test
    are the pair -- same model, same DDL, one row of difference.

    **`owner` is the assertion that separates the two paths.** It is `NOT NULL`
    with no default, so `generate_additive_migration` refuses it categorically
    and no `ALTER` can ever produce it. A table that has it was recreated; a
    table that widened cannot have it.

    The argument for destroying the table, which lived only in a docstring
    until now: a read model holds nothing that is not re-derivable from the
    log, and an *empty* one holds nothing at all. The cost is that the
    condition is about rows rather than about meaning -- a table that is empty
    because a projection has not replayed yet is dropped just as readily, which
    is harmless for the same reason and worth knowing before widening this
    branch to anything that is not a read model.

    **Proved red on 2026-08-29** by inverting the guard to `if rows is None:
    raise` -- this test fails with `ReadModelSchemaMismatchError` and
    `test_a_refused_reconcile_leaves_the_table_untouched` fails on the
    `nickname` assertion. Neither fails alone, which is why both are needed.
    """
    async with aiosqlite.connect(db_path) as connection:
        await connection.executescript(model_schema(_NarrowRow))
        # No row, deliberately, and no INSERT anywhere above: that is the
        # entire difference from the refusal test, and stating it here saves
        # the next reader diffing two near-identical bodies.
        await connection.commit()

        await apply_schema(connection, _WidenedRow)

        columns = await connection.execute("PRAGMA table_info(widening_rows)")
        present = {row[1] for row in await columns.fetchall()}
        remaining = await (
            await connection.execute("SELECT COUNT(*) FROM widening_rows")
        ).fetchone()

    assert "owner" in present, (
        "the unaddable column is only reachable by recreating the table; its "
        "absence means the widen path ran and silently skipped it"
    )
    assert "nickname" in present
    assert remaining == (0,)


# ---------------------------------------------------------------------------
# The two dialogue tables -- `BACKLOG.md` B112.
#
# Both were proved *inert* against a real checkpointed database on 2026-08-17,
# and B112 records why that proof is weaker than it sounds: they are created
# whole on a database that has never seen them, so `apply_schema`'s reconcile
# branch was never entered. Creation was measured; widening was not.
#
# What widening actually does to them, measured field by field on 2026-08-29
# by dropping each column from the real schema, seeding one row, and calling
# `apply_schema`:
#
#   socratic_dialogues   widens on  opening_prompt, pending_prompt, status,
#                                   concluded_reason, turn_count
#                        refuses    project_id, topic, goal, stopping_condition,
#                                   opened_at, observations
#   socratic_turns       widens on  -- nothing --
#                        refuses    every one of its seven fields
#
# Two things in that table are worth carrying forward. **`socratic_turns` has
# no addable column at all**, so any future addition to it against a database
# with turns in it is a `/rebuild`, not a deploy -- which is a fact about the
# table's shape rather than a defect, and is the sort of thing nobody discovers
# until the deploy -- and it is no longer hypothetical. Measured on 2026-08-29
# against a rebound copy of the real database
# (`python -m research_team.infrastructure.persistence.local_copy`, checkpoints
# rebound rather than cleared): **`socratic_dialogues` holds 7 rows and
# `socratic_turns` holds 5**. B112's own 2026-08-17 measurement found both
# tables created whole and empty, which is what let it conclude only that
# creation works. They are populated now, so the drop-and-recreate branch is no
# longer available to either of them, and the next column added to
# `socratic_turns` is a `/rebuild` rather than a deploy. `apply_schema` against
# that copy answers OK for both tables today, which is the un-alarming half:
# nothing is broken, and the next addition is where it would be.
#
# And **`observations` refuses despite having a default**:
# `Field(default_factory=list)` is required-with-no-default as far as
# `generate_additive_migration` is concerned, so the JSON-list columns behave
# like the required scalars and not like `pending_prompt`. Nothing about
# `= Field(default_factory=list)` suggests that from the declaration site.

#: Which declared fields of each dialogue row can be added to a table that
#: already has rows in it. Split rather than a single "addable" list so the
#: registry test below can prove the pair *covers* the model, which is what
#: makes a newly added field fail loudly instead of going unmeasured.
DIALOGUE_WIDENS = {
    SocraticDialogueRow: frozenset(
        {"opening_prompt", "pending_prompt", "status", "concluded_reason", "turn_count"}
    ),
    SocraticTurnRow: frozenset(),
}

DIALOGUE_REFUSES = {
    SocraticDialogueRow: frozenset(
        {"project_id", "topic", "goal", "stopping_condition", "opened_at", "observations"}
    ),
    SocraticTurnRow: frozenset(
        {
            "dialogue_id",
            "project_id",
            "position",
            "prompt",
            "reply",
            "citations",
            "recorded_at",
        }
    ),
}

#: One legal value per column, so a row can be inserted into the narrowed table.
#: Written as SQLite literals rather than through the repository on purpose:
#: the repository would write today's schema, and the table under test is
#: deliberately yesterday's.
DIALOGUE_SEEDS = {
    SocraticDialogueRow: {
        "project_id": "00000000-0000-0000-0000-000000000001",
        "topic": "aerodynamics",
        "goal": "understand lift",
        "stopping_condition": "the reader explains circulation",
        "opening_prompt": "what holds a wing up?",
        "pending_prompt": "what holds a wing up?",
        "opened_at": "2026-08-29T00:00:00+00:00",
        "status": "started",
        "concluded_reason": "",
        "turn_count": 0,
        "observations": "[]",
    },
    SocraticTurnRow: {
        "dialogue_id": "00000000-0000-0000-0000-000000000001",
        "project_id": "00000000-0000-0000-0000-000000000002",
        "position": 0,
        "prompt": "what holds a wing up?",
        "reply": "a pressure difference",
        "citations": "[]",
        "recorded_at": "2026-08-29T00:00:00+00:00",
    },
}


def _declared(model: type[ReadModel]) -> set[str]:
    """The fields this model adds to `ReadModel`, which is what a schema
    reconcile has an opinion about. `id`, `version` and the timestamps come
    from the base and exist in every table already."""
    return set(model.model_fields) - set(ReadModel.model_fields)


@pytest.mark.parametrize(
    "model", [SocraticDialogueRow, SocraticTurnRow], ids=lambda m: m.table_name()
)
def test_the_dialogue_widening_registry_covers_every_declared_field(model):
    """A field added to either dialogue row fails here until it is measured.

    The tables above are a measurement, and a measurement written down by hand
    is documentation the moment someone adds a field -- which is CLAUDE.md's
    "a contract that has to be remembered is documentation; the test is the
    contract", one level down. Deriving the coverage from `model_fields` means
    the new field has nowhere to hide: it is in neither set, this fails at the
    name, and whoever added it has to decide which half it belongs in and run
    `test_a_dialogue_column_widens_or_refuses_as_measured` to find out.

    Asserted as a set equality rather than a subset, so a field *removed* from
    the model also fails -- a stale entry is a claim about a column that no
    longer exists, and the next reader would take it for a live measurement.
    """
    assert DIALOGUE_WIDENS[model] | DIALOGUE_REFUSES[model] == _declared(model)
    assert not DIALOGUE_WIDENS[model] & DIALOGUE_REFUSES[model]


@pytest.mark.parametrize(
    ("model", "dropped"),
    [
        (model, field)
        for model in (SocraticDialogueRow, SocraticTurnRow)
        for field in sorted(_declared(model))
    ],
    ids=lambda value: value if isinstance(value, str) else value.table_name(),
)
async def test_a_dialogue_column_widens_or_refuses_as_measured(db_path, model, dropped):
    """`apply_schema` against a *populated* dialogue table, one column at a time.

    B112 calls this the highest-consequence item it carries, and the reason is
    the failure mode CLAUDE.md opens the read-model section with: every test
    green on a fresh database, every query 500 on a real one. A test that built
    the table from today's model would be exactly that test.

    **The old build is simulated with `ALTER TABLE ... DROP COLUMN`, not with a
    narrowed copy of the row type.** A copy is a second declaration to keep in
    step with the real one, and the day it drifts this file starts asserting
    about a model nothing uses. Dropping from the real generated schema cannot
    drift.

    **A row is inserted, and that is the whole point.** SQLite refuses a
    required column with no default only on a table that has rows; on an empty
    one `apply_schema` takes the drop-and-recreate branch instead and every
    parameter here would report "widened". The row is also the second
    assertion: a widen must not lose it.

    The refusing half asserts `ReadModelSchemaMismatchError` **and** that the
    column is still absent, for `test_a_refused_reconcile_leaves_the_table_
    untouched`'s reason -- a refusal that half-widened the table would raise
    the same exception.

    **Proved red on 2026-08-29** by returning from `apply_schema` immediately
    after `executescript(model_schema(model))`, which is the pre-reconcile
    build: the five widening parameters fail on the `PRAGMA` assertion and the
    thirteen refusing ones fail on the missing raise. The seeded row survives
    under that build, so an assertion on the data alone would have proved
    nothing.
    """
    table = model.table_name()
    seed = {name: value for name, value in DIALOGUE_SEEDS[model].items() if name != dropped}
    expected_widen = dropped in DIALOGUE_WIDENS[model]

    async with aiosqlite.connect(db_path) as connection:
        await connection.executescript(model_schema(model))
        await connection.execute(f"ALTER TABLE {table} DROP COLUMN {dropped}")
        columns = ["id", "created_at", "updated_at", "version", *seed]
        await connection.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' * len(columns))})",
            ["seed-1", "2026-08-29", "2026-08-29", 1, *seed.values()],
        )
        await connection.commit()

        raised: Exception | None = None
        try:
            await apply_schema(connection, model)
        except Exception as error:  # noqa: BLE001 -- the type is asserted below
            raised = error

        present = {
            row[1]
            for row in await (
                await connection.execute(f"PRAGMA table_info({table})")
            ).fetchall()
        }
        surviving = await (await connection.execute(f"SELECT id FROM {table}")).fetchall()

    assert surviving == [("seed-1",)], "reconciling a populated table lost its row"
    if expected_widen:
        assert raised is None, f"{table}.{dropped} was measured as addable and now refuses"
        assert dropped in present, (
            f"{table} did not gain {dropped}; against a real database every "
            "read of this table would 500 while every fresh-database test passed"
        )
    else:
        assert isinstance(raised, ReadModelSchemaMismatchError), (
            f"{table}.{dropped} was measured as a rebuild rather than a widen; "
            "a build that adds it silently is one that half-widens a real table"
        )
        assert dropped not in present, "the refusal landed the column anyway"
