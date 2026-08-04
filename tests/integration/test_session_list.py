"""`/sessions` end to end: the projection, its checkpoint, and a restart.

The old implementation read every event in the database to answer this, which
was correct and got slower forever. What replaces it has to stay correct
across the two things a fold never had to worry about -- a process restart,
and a log that already had events in it before the projection existed.
"""

from contextlib import suppress


async def _settle(application) -> None:
    """Let the subscription catch up with what was just appended."""
    await application.summaries_caught_up()


async def test_a_new_session_appears_in_the_list(build_application, fake_model, db_path):
    application = await build_application(model=fake_model, db_path=db_path)
    session_id = await application.service.create_session()
    await _settle(application)

    listed = await application.service.list_sessions()

    assert [summary.session_id for summary in listed] == [session_id]


async def test_a_turn_updates_the_row(build_application, fake_model, db_path):
    application = await build_application(model=fake_model, db_path=db_path)
    session_id = await application.service.create_session()
    await application.service.run_turn(session_id, "hello")
    await _settle(application)

    [summary] = await application.service.list_sessions()

    assert summary.turns == 1
    assert summary.first_message == "hello"


async def test_a_log_written_before_the_projection_existed_is_caught_up(
    build_application, fake_model, db_path
):
    """The table starts empty against a log that does not.

    This is the upgrade path -- and the rebuild path, if the table is ever
    dropped. Catch-up is what makes the read model derived rather than
    authoritative, so it has to actually run.
    """
    first = await build_application(model=fake_model, db_path=db_path)
    session_id = await first.service.create_session()
    await first.close()

    reopened = await build_application(model=fake_model, db_path=db_path)
    await _settle(reopened)

    listed = await reopened.service.list_sessions()
    assert [summary.session_id for summary in listed] == [session_id]


async def test_a_restart_does_not_double_count(build_application, fake_model, db_path):
    """The checkpoint's whole job.

    `failed_turns` is a running total, so replaying events the projection has
    already seen would inflate it -- which is exactly what a checkpoint that is
    not being written, or not being read, looks like.
    """
    first = await build_application(model=fake_model, db_path=db_path)
    session_id = await first.service.create_session()
    fake_model.responses = []  # nothing to reply with: the turn fails
    with suppress(Exception):
        await first.service.run_turn(session_id, "this will not work")
    await _settle(first)
    [before] = await first.service.list_sessions()
    await first.close()

    reopened = await build_application(model=fake_model, db_path=db_path)
    await _settle(reopened)

    [after] = await reopened.service.list_sessions()
    assert after.failed_turns == before.failed_turns


async def test_nothing_can_ask_the_store_for_every_event(repository):
    """The full scan is gone, not merely unused.

    `all_events` existed only to feed the per-request fold. Leaving it on the
    port would leave the slow path one call away from coming back, so the
    guarantee here is structural rather than a matter of discipline.
    """
    assert not hasattr(repository, "all_events")


async def test_a_new_session_is_listed_without_waiting(
    build_application, fake_model, db_path
):
    """Create-then-list is consistent in practice, and should stay that way.

    The read model is eventually consistent in principle, but the bus it
    follows is in-process and publishes inline: `save()` awaits the publish,
    the dispatch runs the subscription's handler, and only then does the turn
    return. So a person who creates a session and lands on the list sees it,
    with no settle and no refresh.

    That is a property of the wiring, not of the design -- publishing in the
    background, or moving to an out-of-process bus, would break it. This test
    is deliberately free of `_settle()` so that such a change shows up here as
    a failure rather than in the UI as an intermittently missing row.
    """
    application = await build_application(model=fake_model, db_path=db_path)

    session_id = await application.service.create_session()

    listed = await application.service.list_sessions()
    assert session_id in {summary.session_id for summary in listed}
