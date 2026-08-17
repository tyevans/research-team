"""That a composed application actually records interaction.

This test exists because the unit tests structurally cannot catch the two
ways this feature dies: a runner constructed but never started, and a
recorder appending to a store whose projection nobody subscribed. Both leave
every other test green and the table empty.
"""

from datetime import UTC, datetime
from uuid import uuid4

from research_team.composition import build_application
from research_team.domain.interaction import ViewEntered


async def test_a_composed_application_stores_what_the_browser_reported(db_path, tmp_path):
    interaction_db = str(tmp_path / "interactions.db")
    application = build_application(db_path=db_path, interaction_db_path=interaction_db)
    await application.start()
    try:
        browser_session = uuid4()

        await application.interaction_recorder.record(
            [
                ViewEntered(
                    aggregate_id=browser_session,
                    install_id=uuid4(),
                    seq=1,
                    view="project/timeline",
                    occurred_at=datetime.now(UTC),
                    params={},
                )
            ]
        )
        await application.interaction_log_caught_up()

        rows = await application.interaction_log.events(browser_session)
        assert len(rows) == 1
        assert rows[0].view == "project/timeline"
    finally:
        await application.close()


async def test_the_interaction_store_is_not_the_session_store(db_path, tmp_path):
    """Two stores, and the interaction one must not be writing into
    sessions.db. Fails if interaction_db_path is ignored and the runner is
    handed the session store."""
    import aiosqlite

    interaction_db = str(tmp_path / "interactions.db")
    application = build_application(db_path=db_path, interaction_db_path=interaction_db)
    await application.start()
    try:
        await application.interaction_recorder.record(
            [
                ViewEntered(
                    aggregate_id=uuid4(),
                    install_id=uuid4(),
                    seq=1,
                    view="home",
                    occurred_at=datetime.now(UTC),
                    params={},
                )
            ]
        )
        await application.interaction_log_caught_up()
    finally:
        await application.close()

    connection = await aiosqlite.connect(db_path)
    try:
        found = await (
            await connection.execute(
                "SELECT count(*) FROM events WHERE aggregate_type = 'browser_session'"
            )
        ).fetchone()
        assert found[0] == 0
    finally:
        await connection.close()
