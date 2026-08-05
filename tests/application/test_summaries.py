"""`summarize_sessions` is a pure fold over events -- test it as one."""

from uuid import uuid4

import pytest

from research_team.application import summarize_sessions
from research_team.domain import (
    CodingSession,
    CompleteTurn,
    DeleteFile,
    FailTurn,
    RecordForkSource,
    SendUserMessage,
    StartSession,
    WriteFile,
)

SYSTEM_PROMPT = "You are a coding agent."
MODEL_NAME = "test-model"


def user_message(text: str) -> dict:
    return {"type": "human", "data": {"content": text}}


@pytest.fixture
def make_session(aggregates):
    def make(first_message: str | None = None) -> CodingSession:
        aggregate = aggregates.create_new(uuid4())
        aggregate.execute(StartSession(system_prompt=SYSTEM_PROMPT, model_name=MODEL_NAME))
        if first_message is not None:
            aggregate.execute(SendUserMessage(message=user_message(first_message)))
        return aggregate

    return make


def summaries_for(*sessions):
    """Fold the given sessions' events, with no store in the way.

    `summarize_sessions` takes events and returns rows -- it never needed a
    database, and routing through one only ever obscured that. Grouping is the
    fold's own job, so handing it the sessions' events back to back is enough.
    """
    return summarize_sessions([e for s in sessions for e in s.uncommitted_events])


def test_sessions_are_newest_first(make_session):
    older = make_session("older")
    newer = make_session("newer")

    rows = summaries_for(older, newer)

    assert [row.session_id for row in rows] == [newer.aggregate_id, older.aggregate_id]
    assert [row.first_message for row in rows] == ["newer", "older"]


def test_counts_turns_and_surviving_files(make_session):
    session = make_session("do things")
    session.execute(CompleteTurn())
    session.execute(WriteFile(path="/a.py", file_data={"content": "a"}))
    session.execute(WriteFile(path="/b.py", file_data={"content": "b"}))
    session.execute(DeleteFile(path="/b.py"))
    session.execute(SendUserMessage(message=user_message("again")))
    session.execute(CompleteTurn())

    (row,) = summaries_for(session)

    assert row.turns == 2
    assert row.files == 1
    assert row.first_message == "do things"
    assert row.forked_from is None
    assert row.failed_turns == 0


def test_failed_turns_are_counted_and_do_not_count_as_turns(make_session):
    session = make_session()
    session.execute(FailTurn.from_error(RuntimeError("boom")))
    session.execute(FailTurn.from_error(RuntimeError("boom again")))

    (row,) = summaries_for(session)

    assert row.failed_turns == 2
    assert row.turns == 0
    assert row.first_message == ""


def test_fork_lineage_is_reported(make_session):
    source = make_session("original")
    forked = make_session("copy")
    forked.execute(RecordForkSource(source_session_id=source.aggregate_id, at_event=1))

    summaries = summaries_for(source, forked)
    rows = {row.session_id: row for row in summaries}

    assert rows[forked.aggregate_id].forked_from == source.aggregate_id
    assert rows[source.aggregate_id].forked_from is None
