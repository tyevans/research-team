"""`summarize_sessions` is a pure fold over events -- test it as one."""

from uuid import uuid4

import pytest

from research_team.application import summarize_sessions
from research_team.domain import CodingSession

SYSTEM_PROMPT = "You are a coding agent."
MODEL_NAME = "test-model"


def user_message(text: str) -> dict:
    return {"type": "human", "data": {"content": text}}


@pytest.fixture
def make_session(aggregates):
    def make(first_message: str | None = None) -> CodingSession:
        aggregate = aggregates.create_new(uuid4())
        aggregate.start(SYSTEM_PROMPT, MODEL_NAME)
        if first_message is not None:
            aggregate.send_user_message(user_message(first_message))
        return aggregate

    return make


async def summaries_for(repository, *aggregates_to_save):
    for aggregate in aggregates_to_save:
        await repository.save(aggregate)
    return summarize_sessions(await repository.all_events())


async def test_sessions_are_newest_first(repository, make_session):
    older = make_session("older")
    newer = make_session("newer")

    rows = await summaries_for(repository, older, newer)

    assert [row.session_id for row in rows] == [newer.aggregate_id, older.aggregate_id]
    assert [row.first_message for row in rows] == ["newer", "older"]


async def test_counts_turns_and_surviving_files(repository, make_session):
    session = make_session("do things")
    session.complete_turn()
    session.write_file("/a.py", {"content": "a"})
    session.write_file("/b.py", {"content": "b"})
    session.delete_file("/b.py")
    session.send_user_message(user_message("again"))
    session.complete_turn()

    (row,) = await summaries_for(repository, session)

    assert row.turns == 2
    assert row.files == 1
    assert row.first_message == "do things"
    assert row.forked_from is None
    assert row.failed_turns == 0


async def test_failed_turns_are_counted_and_do_not_count_as_turns(
    repository, make_session
):
    session = make_session()
    session.fail_turn(RuntimeError("boom"))
    session.fail_turn(RuntimeError("boom again"))

    (row,) = await summaries_for(repository, session)

    assert row.failed_turns == 2
    assert row.turns == 0
    assert row.first_message == ""


async def test_fork_lineage_is_reported(repository, make_session):
    source = make_session("original")
    forked = make_session("copy")
    forked.record_fork_source(source.aggregate_id, 1)

    summaries = await summaries_for(repository, source, forked)
    rows = {row.session_id: row for row in summaries}

    assert rows[forked.aggregate_id].forked_from == source.aggregate_id
    assert rows[source.aggregate_id].forked_from is None
