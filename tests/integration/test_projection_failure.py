"""What happens when the `/sessions` projection cannot process an event.

This is the failure mode the read model introduced. A fold that runs per
request cannot drift -- it is recomputed from the log every time, so a bug is
visible and a fix is retroactive. A projection is written down once, and a
handler that throws leaves the row wrong *permanently*: the subscription
continues (which is what keeps one bad event from stopping the rest), the
checkpoint advances past it, and catch-up on the next start therefore begins
after the event that was never applied.

So the read model needs what the fold got for free: a record that it happened,
and a way to rebuild. These tests pin both.
"""

import logging

import pytest

from research_team.infrastructure.persistence import read_models


def _breaking(method):
    """A replacement handler that raises but is still a registered handler.

    `@handles` marks the function with `_handles_event_type`, and
    `DeclarativeProjection` builds its routing table from those marks at
    `__init__`. A naive monkeypatch drops the mark, so the event stops being
    subscribed to at all -- which looks identical from the outside (the field
    is never written) but exercises the "no handler for this type" path, where
    nothing raises and nothing is meant to. Carrying the mark across is what
    makes this a test about a handler that *fails*.
    """

    async def broken(self, event):
        raise RuntimeError("projection handler is broken")

    broken._handles_event_type = method._handles_event_type
    return broken


@pytest.fixture
def broken_handler(monkeypatch):
    """Break one projection handler for the duration of a test.

    Patched on the class before the projection is constructed, because
    `DeclarativeProjection` binds its handlers into a registry at `__init__`
    -- a patch applied afterwards is never consulted.
    """
    monkeypatch.setattr(
        read_models.SessionSummaryProjection,
        "_on_user_message",
        _breaking(read_models.SessionSummaryProjection._on_user_message),
    )


@pytest.fixture
def quiet_projection_errors():
    """The library logs a permanent failure at CRITICAL. That is correct, and
    it is noise in a test that is deliberately causing one."""
    logger = logging.getLogger("eventsource.application.projections.base")
    previous = logger.level
    logger.setLevel(logging.CRITICAL + 1)
    yield
    logger.setLevel(previous)


async def test_a_failed_event_is_recorded_in_the_dead_letter_queue(
    build_application, fake_model, db_path, broken_handler, quiet_projection_errors
):
    """Without this, the only trace of a corrupted row is a log line.

    The row is wrong either way -- that is what `continue_on_error` buys, and
    it is the right trade. What is not acceptable is the wrongness being
    unrecorded, because then nothing can tell you a rebuild is needed.
    """
    application = await build_application(model=fake_model, db_path=db_path)
    session_id = await application.service.create_session()
    await application.service.run_turn(session_id, "this message will be dropped")
    await application.summaries_caught_up()

    failures = await application.summaries.failures()

    assert len(failures) == 1
    assert failures[0].event_type == "UserMessageSent"
    assert "projection handler is broken" in failures[0].error_message
    # The entry carries the event itself, so a rebuild is not the only remedy:
    # the payload that failed is recoverable from here.
    assert str(session_id) in str(failures[0].event_data)


async def test_the_row_is_wrong_but_the_rest_of_the_turn_still_lands(
    build_application, fake_model, db_path, broken_handler, quiet_projection_errors
):
    """One bad handler must not stop the subscription.

    Stopping would trade one wrong field for a read model frozen at the moment
    of the failure, which is worse and harder to notice.
    """
    application = await build_application(model=fake_model, db_path=db_path)
    session_id = await application.service.create_session()
    await application.service.run_turn(session_id, "dropped")
    await application.summaries_caught_up()

    [summary] = await application.service.list_sessions()
    assert summary.first_message == ""  # the dropped event
    assert summary.turns == 1  # everything after it still applied


async def test_a_rebuild_repairs_a_drifted_row(
    build_application, fake_model, db_path, quiet_projection_errors, monkeypatch
):
    """The repair, and the proof that the table is derived rather than owned.

    A restart alone cannot fix this -- the checkpoint is already past the
    failed event. Rebuilding drops the rows and the checkpoint together, so
    catch-up replays the whole log into an empty table.
    """

    original = read_models.SessionSummaryProjection._on_user_message
    monkeypatch.setattr(
        read_models.SessionSummaryProjection, "_on_user_message", _breaking(original)
    )
    application = await build_application(model=fake_model, db_path=db_path)
    session_id = await application.service.create_session()
    await application.service.run_turn(session_id, "the real first message")
    await application.summaries_caught_up()
    assert (await application.service.list_sessions())[0].first_message == ""

    # The handler is fixed; the stored row is still wrong.
    monkeypatch.setattr(read_models.SessionSummaryProjection, "_on_user_message", original)
    await application.summaries.rebuild()

    [summary] = await application.service.list_sessions()
    assert summary.first_message == "the real first message"
    assert summary.turns == 1
    assert summary.session_id == session_id


async def test_a_rebuild_on_a_healthy_table_changes_nothing(
    build_application, fake_model, db_path
):
    """Rebuilding is the repair, so it has to be safe to reach for.

    If it were only *usually* idempotent nobody would run it on a hunch, which
    is exactly when it is most useful.
    """
    application = await build_application(model=fake_model, db_path=db_path)
    session_id = await application.service.create_session()
    await application.service.run_turn(session_id, "hello")
    await application.summaries_caught_up()
    before = await application.service.list_sessions()

    await application.summaries.rebuild()

    assert await application.service.list_sessions() == before


async def test_a_healthy_projection_reports_itself_healthy(
    build_application, fake_model, db_path
):
    application = await build_application(model=fake_model, db_path=db_path)
    await application.service.create_session()
    await application.summaries_caught_up()

    health = await application.service.summaries_health()

    assert health.healthy is True
    assert health.failed_events == 0
    assert health.following is True


async def test_a_drifted_projection_reports_itself_unhealthy(
    build_application, fake_model, db_path, broken_handler, quiet_projection_errors
):
    """The point of the whole exercise.

    Drift is survivable and repairable, but only if somebody finds out. A
    wrong row looks exactly like a right one, so the signal has to come from
    the DLQ rather than from reading the list and squinting.
    """
    application = await build_application(model=fake_model, db_path=db_path)
    session_id = await application.service.create_session()
    await application.service.run_turn(session_id, "dropped")
    await application.summaries_caught_up()

    health = await application.service.summaries_health()

    assert health.healthy is False
    assert health.failed_events == 1


async def test_a_rebuild_clears_the_unhealthy_report(
    build_application, fake_model, db_path, quiet_projection_errors, monkeypatch
):
    """Repairing the table must also clear the alarm.

    A health check that stays red after the fix trains everyone to ignore it.
    """
    original = read_models.SessionSummaryProjection._on_user_message
    monkeypatch.setattr(
        read_models.SessionSummaryProjection, "_on_user_message", _breaking(original)
    )
    application = await build_application(model=fake_model, db_path=db_path)
    session_id = await application.service.create_session()
    await application.service.run_turn(session_id, "the real first message")
    await application.summaries_caught_up()
    assert (await application.service.summaries_health()).healthy is False

    monkeypatch.setattr(read_models.SessionSummaryProjection, "_on_user_message", original)
    await application.summaries.rebuild()

    health = await application.service.summaries_health()
    assert health.healthy is True
    assert health.failed_events == 0
