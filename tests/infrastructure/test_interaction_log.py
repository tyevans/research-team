"""The one table this feature writes.

Every assertion here is on a stored row rather than on a call succeeding.
`eventsource.replay` counts an event no projection handles as APPLIED -- so a
test asserting that ingest returned 202, or that nothing raised, passes with
the projection deleted entirely and proves nothing.
"""

from datetime import UTC, datetime
from uuid import uuid4

import aiosqlite
from eventsource import ExpectedVersion, InMemoryEventBus, StreamId
from eventsource.adapters.memory.readmodels import InMemoryReadModelRepository
from eventsource.adapters.sqlite import SQLiteEventStore

from research_team.domain.interaction import (
    BROWSER_SESSION_AGGREGATE_TYPE,
    INTERACTION_EVENTS,
    AskSubmitted,
    SearchPerformed,
    ViewEntered,
    ViewExited,
)
from research_team.infrastructure.persistence.interaction_log import (
    InteractionEventRow,
    InteractionLogProjection,
    InteractionLogRunner,
    InteractionLogStore,
)


def _view_entered(session_id, seq=1, **over):
    return ViewEntered(
        aggregate_id=session_id,
        install_id=uuid4(),
        seq=seq,
        view="project/entity",
        occurred_at=datetime.now(UTC),
        params={"entity_id": "ent_4a1f"},
        **over,
    )


async def test_a_stored_event_keeps_its_envelope_and_its_payload(db_path):
    store = await InteractionLogStore.open(db_path)
    try:
        browser_session = uuid4()
        event = _view_entered(browser_session, seq=7)

        await store.record(event)

        rows = await store.events(browser_session)
        assert len(rows) == 1
        assert rows[0].kind == "ViewEntered"
        assert rows[0].seq == 7
        assert rows[0].view == "project/entity"
        assert rows[0].payload["params"]["entity_id"] == "ent_4a1f"
    finally:
        await store.close()


async def test_a_stored_payload_holds_only_kind_specific_fields(db_path):
    """`ENVELOPE_FIELDS` is derived from both `DomainEvent` and
    `InteractionEvent`'s fields, not a hand-picked pair. If it missed one --
    `correlation_id`, `tenant_id`, `actor_id` are the ones the brief's
    original exclusion set missed -- it would leak into every stored payload
    alongside the fields that actually belong there.

    `ViewEntered` declares exactly one field of its own, `params`, so its
    payload should hold exactly that key and nothing else.
    """
    store = await InteractionLogStore.open(db_path)
    try:
        browser_session = uuid4()
        await store.record(_view_entered(browser_session, seq=1))

        row = (await store.events(browser_session))[0]
        assert set(row.payload.keys()) == {"params"}
    finally:
        await store.close()


async def test_the_same_sequence_number_twice_is_one_row(db_path):
    """sendBeacon can double-deliver, and a timer flush can race a page-hide
    flush. Duplicates are expected, so the row id is derived from
    (browser_session_id, seq) rather than random.

    Fails with the uuid5 derivation replaced by uuid4: two rows.
    """
    store = await InteractionLogStore.open(db_path)
    try:
        browser_session = uuid4()

        await store.record(_view_entered(browser_session, seq=3))
        await store.record(_view_entered(browser_session, seq=3))

        assert len(await store.events(browser_session)) == 1
    finally:
        await store.close()


async def test_the_same_sequence_number_in_two_sessions_is_two_rows(db_path):
    """seq is monotonic *within* a browser session, so it collides across
    them. Fails if the row id is derived from seq alone."""
    store = await InteractionLogStore.open(db_path)
    try:
        first, second = uuid4(), uuid4()

        await store.record(_view_entered(first, seq=1))
        await store.record(_view_entered(second, seq=1))

        assert len(await store.events(first)) == 1
        assert len(await store.events(second)) == 1
    finally:
        await store.close()


async def test_events_come_back_in_sequence_order(db_path):
    """Ordered by seq, not by insertion: a batch can arrive out of order and
    the whole point of seq is that this survives it."""
    store = await InteractionLogStore.open(db_path)
    try:
        browser_session = uuid4()

        await store.record(_view_entered(browser_session, seq=3))
        await store.record(_view_entered(browser_session, seq=1))
        await store.record(_view_entered(browser_session, seq=2))

        assert [row.seq for row in await store.events(browser_session)] == [1, 2, 3]
    finally:
        await store.close()


async def test_a_dwell_survives_the_round_trip(db_path):
    store = await InteractionLogStore.open(db_path)
    try:
        browser_session = uuid4()
        await store.record(
            ViewExited(
                aggregate_id=browser_session,
                install_id=uuid4(),
                seq=2,
                view="project/timeline",
                occurred_at=datetime.now(UTC),
                dwell_ms=240_000,
                hidden_ms=180_000,
            )
        )

        row = (await store.events(browser_session))[0]
        assert row.payload["dwell_ms"] == 240_000
        assert row.payload["hidden_ms"] == 180_000
    finally:
        await store.close()


async def test_text_survives_for_the_two_kinds_that_carry_it(db_path):
    store = await InteractionLogStore.open(db_path)
    try:
        browser_session = uuid4()
        await store.record(
            SearchPerformed(
                aggregate_id=browser_session,
                install_id=uuid4(),
                seq=1,
                view="project/entity",
                occurred_at=datetime.now(UTC),
                query_text="tetrarchy",
                result_count=0,
            )
        )
        await store.record(
            AskSubmitted(
                aggregate_id=browser_session,
                install_id=uuid4(),
                seq=2,
                view="project/ask",
                occurred_at=datetime.now(UTC),
                query_text="what changed",
            )
        )

        rows = await store.events(browser_session)
        assert rows[0].payload["query_text"] == "tetrarchy"
        assert rows[1].payload["query_text"] == "what changed"
    finally:
        await store.close()


async def test_a_database_written_before_a_field_existed_gains_its_column(db_path):
    """Adding a field to a ReadModel does not add a column to a database that
    already exists -- CREATE TABLE IF NOT EXISTS does nothing to a table that
    is there. This has shipped once in this repository, as a 500 on every
    request against a table every test built from nothing.

    Simulated the way `test_summary_store.py` does it: open the store once so
    the real schema exists, then drop one column back off, which is the
    actual shape of the problem -- a table one field behind the model. A
    table hand-built with only `(id, kind)` is not that shape: it is also
    missing `deleted_at`, and `apply_schema`'s unconditional
    `CREATE INDEX ... ON interaction_events(deleted_at)` fails against a
    table that never had the column, before the additive migration that
    would otherwise add it back ever runs. That index statement runs on
    every open regardless of what changed, so the fixture has to leave every
    base `ReadModel` column in place and remove only the field under test.
    """
    store = await InteractionLogStore.open(db_path)
    await store.close()

    connection = await aiosqlite.connect(db_path)
    try:
        await connection.execute("ALTER TABLE interaction_events DROP COLUMN view")
        await connection.commit()
    finally:
        await connection.close()

    reopened = await InteractionLogStore.open(db_path)
    try:
        browser_session = uuid4()
        await reopened.record(_view_entered(browser_session))

        assert len(await reopened.events(browser_session)) == 1
    finally:
        await reopened.close()


def test_the_projection_handles_every_kind_in_the_vocabulary():
    """A kind with no handler is silently unrecorded: replay counts an event
    no projection handles as APPLIED, so nothing raises and the read model is
    simply missing rows.

    Fails when a kind is added to INTERACTION_EVENTS and not to the
    projection -- which is the whole point.
    """
    handled = InteractionLogProjection(
        InMemoryReadModelRepository(InteractionEventRow)
    ).subscribed_to()

    assert set(INTERACTION_EVENTS) == set(handled)


async def test_the_projection_writes_a_row():
    rows = InMemoryReadModelRepository(InteractionEventRow)
    projection = InteractionLogProjection(rows)
    browser_session = uuid4()

    await projection.handle(_view_entered(browser_session, seq=4))

    stored = await rows.find(None)
    assert len(stored) == 1
    assert stored[0].seq == 4
    assert stored[0].kind == "ViewEntered"


async def test_the_runner_follows_its_own_store(db_path, tmp_path):
    """The end-to-end shape of this feature's write path: append to the
    interaction store, publish, and find a row.

    The publish is not decoration. Appending does not deliver -- the bus is a
    wake-up signal and the store owns ordering -- so an append nobody
    publishes reaches a running projection only on restart. Drop the publish
    line and this test fails with an empty list, which is exactly how it would
    fail in production.
    """
    interaction_db = str(tmp_path / "interactions.db")
    store = SQLiteEventStore(interaction_db)
    bus = InMemoryEventBus()
    runner = InteractionLogRunner(store, interaction_db, bus)
    await runner.start()
    try:
        browser_session = uuid4()
        event = _view_entered(browser_session, seq=1)

        await store.append(
            StreamId(browser_session, BROWSER_SESSION_AGGREGATE_TYPE),
            [event],
            ExpectedVersion.any_(),
        )
        await bus.publish([event])
        await runner.caught_up()

        rows = await runner.events(browser_session)
        assert len(rows) == 1
        assert rows[0].view == "project/entity"
    finally:
        await runner.stop()
