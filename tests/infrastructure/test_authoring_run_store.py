"""`AuthoringRunStore.authored_session_for` -- the read that lets a course
page link to the session its written material lives in."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from research_team.infrastructure.persistence.read_models import AuthoringRunStore


@pytest.fixture
async def store(db_path):
    opened = await AuthoringRunStore.open(db_path)
    try:
        yield opened
    finally:
        await opened.close()


async def test_the_newest_run_wins_when_a_target_was_authored_twice(store):
    """Re-authoring an area writes a second session, and the course page must
    link the one that exists now rather than the first ever written. Ordering
    is the whole method; a version returning any match passes a single-run
    test and fails this one."""
    project_id = uuid4()
    older_run, newer_run = uuid4(), uuid4()
    older_session, newer_session = uuid4(), uuid4()

    await store.start(
        older_run,
        project_id,
        kind="course",
        targets=["warp-drive"],
        started_at=datetime.now(UTC) - timedelta(hours=1),
    )
    await store.record_authored(older_run, "warp-drive", older_session)

    await store.start(
        newer_run,
        project_id,
        kind="course",
        targets=["warp-drive"],
        started_at=datetime.now(UTC),
    )
    await store.record_authored(newer_run, "warp-drive", newer_session)

    found = await store.authored_session_for(project_id, "warp-drive")

    assert found == newer_session


async def test_a_target_no_run_authored_has_no_session(store):
    project_id = uuid4()
    run_id = uuid4()
    await store.start(
        run_id,
        project_id,
        kind="course",
        targets=["warp-drive"],
        started_at=datetime.now(UTC),
    )

    found = await store.authored_session_for(project_id, "never-authored")

    assert found is None


async def test_another_projects_run_is_not_matched(store):
    mine, theirs = uuid4(), uuid4()
    run_id = uuid4()
    session_id = uuid4()
    await store.start(
        run_id,
        theirs,
        kind="course",
        targets=["warp-drive"],
        started_at=datetime.now(UTC),
    )
    await store.record_authored(run_id, "warp-drive", session_id)

    found = await store.authored_session_for(mine, "warp-drive")

    assert found is None
