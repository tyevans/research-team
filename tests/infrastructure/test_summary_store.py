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
            session_id=session.aggregate_id, system_prompt=SYSTEM_PROMPT, model_name=MODEL_NAME
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
