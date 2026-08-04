"""The `/sessions` read model, and the projection that maintains it.

The old path folded every event in the database on every request. These tests
are about the replacement telling the same story incrementally -- so the
tightest one here compares the two directly, and the rest pin down the pieces
a fold gets for free but an incremental projection has to be told.
"""

from uuid import uuid4

import pytest
from eventsource.adapters.memory.readmodels import InMemoryReadModelRepository

from research_team.application import summarize_sessions
from research_team.domain import CodingSession
from research_team.infrastructure.persistence.read_models import (
    LOCAL_RETRY_POLICY,
    SessionSummaryProjection,
    SessionSummaryRow,
    to_summary,
)
from tests.conftest import MODEL_NAME, SYSTEM_PROMPT


@pytest.fixture
def rows() -> InMemoryReadModelRepository:
    return InMemoryReadModelRepository(SessionSummaryRow)


@pytest.fixture
def projection(rows) -> SessionSummaryProjection:
    return SessionSummaryProjection(rows)


async def _project(projection, session: CodingSession) -> None:
    """Feed a session's uncommitted events through the projection, in order."""
    for event in session.uncommitted_events:
        await projection.handle(event)


def _new_session(session_id=None) -> CodingSession:
    session = CodingSession(session_id or uuid4())
    session.start(SYSTEM_PROMPT, MODEL_NAME)
    return session


async def test_a_started_session_becomes_a_row(projection, rows):
    session = _new_session()
    await _project(projection, session)

    row = await rows.get(session.aggregate_id)
    assert row is not None
    assert row.turns == 0
    assert row.first_message == ""


async def test_the_first_user_message_is_the_one_that_sticks(projection, rows):
    """`first_message` labels the session in the list -- it must not drift."""
    session = _new_session()
    session.send_user_message({"type": "human", "data": {"content": "the first"}})
    session.send_user_message({"type": "human", "data": {"content": "the second"}})
    await _project(projection, session)

    row = await rows.get(session.aggregate_id)
    assert row.first_message == "the first"


async def test_a_failed_turn_counts_without_advancing_the_turn_count(projection, rows):
    session = _new_session()
    session.complete_turn()
    session.fail_turn(RuntimeError("nope"))
    await _project(projection, session)

    row = await rows.get(session.aggregate_id)
    assert (row.turns, row.failed_turns) == (1, 1)


async def test_rewriting_a_file_does_not_count_it_twice(projection, rows):
    """The count is of files, not of writes -- which a running total misses."""
    session = _new_session()
    session.write_file("/a.py", {"content": "one"})
    session.edit_file("/a.py", {"content": "two"}, "one", "two", False)
    session.write_file("/b.py", {"content": "b"})
    await _project(projection, session)

    row = await rows.get(session.aggregate_id)
    assert to_summary(row).files == 2


async def test_a_deleted_file_stops_counting(projection, rows):
    session = _new_session()
    session.write_file("/a.py", {"content": "a"})
    session.write_file("/b.py", {"content": "b"})
    session.delete_file("/a.py")
    await _project(projection, session)

    row = await rows.get(session.aggregate_id)
    assert to_summary(row).files == 1


async def test_fork_lineage_is_recorded(projection, rows):
    source = uuid4()
    session = _new_session()
    session.record_fork_source(source, 7)
    await _project(projection, session)

    summary = to_summary(await rows.get(session.aggregate_id))
    assert (summary.forked_from, summary.forked_at) == (source, 7)


async def test_the_projection_agrees_with_the_fold_it_replaces(projection, rows):
    """The real contract: same events in, same rows out.

    `summarize_sessions` is the behaviour users already have, and it stays in
    the codebase as the definition of what a summary means. If the incremental
    path ever disagrees with it, this is the test that says so.
    """
    first = _new_session()
    first.send_user_message({"type": "human", "data": {"content": "hello"}})
    first.complete_turn()
    first.write_file("/kept.py", {"content": "k"})
    first.write_file("/gone.py", {"content": "g"})
    first.delete_file("/gone.py")
    first.fail_turn(RuntimeError("boom"))

    second = _new_session()
    second.record_fork_source(first.aggregate_id, 3)
    second.send_user_message({"type": "human", "data": {"content": "forked"}})

    events = [*first.uncommitted_events, *second.uncommitted_events]
    for event in events:
        await projection.handle(event)

    projected = sorted(
        [to_summary(row) for row in await rows.find(None)],
        key=lambda summary: summary.started_at,
        reverse=True,
    )
    assert projected == summarize_sessions(events)


def test_the_projection_retries_on_local_timings_not_network_ones(rows):
    """Guards the constructor contract eventsource 0.10.0 opened up.

    `retry_policy` reaches the projection through `DeclarativeProjection`'s
    constructor. Before 0.10.0 the parent accepted it and every subclass
    silently dropped it, so the only way in was assigning the private attribute
    after construction. Nothing failed when it was dropped -- the projection
    just fell back to the library default of three attempts over about six
    seconds, which is tuned for a projection writing over a network, not to a
    local file.

    A parameter that can be ignored without anything failing is the shape that
    regresses, so this asserts the policy actually in force. It reads a private
    attribute because the library exposes no accessor; that is the right place
    for the reach, rather than widening production code to make a test possible.
    """
    projection = SessionSummaryProjection(rows)

    assert projection._retry_policy is LOCAL_RETRY_POLICY
    assert projection._retry_policy.get_backoff(0) < 1.0
