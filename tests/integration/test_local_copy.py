"""Copying a live database somewhere else, so a projection will still open it.

`CLAUDE.md` asks for read-model changes to be run against a copy of a real
database. These are about the thing that stops that from working: a checkpoint
carries the store id of the database it was written against, and that id is
derived from the database path.

No real database is needed or read here -- each test builds its own, runs it
until the library writes a checkpoint of its own, and copies that. Hand-writing
a position token instead would pin the format this code happens to expect
rather than the one eventsource actually writes, which is the one free to
change under a minor.
"""

import json
import sqlite3

import pytest

from research_team.infrastructure.persistence.local_copy import (
    copy_database,
    rebind_checkpoints,
)
from tests.conftest import start_session


async def _written(build_application, fake_model, path: str):
    """A closed database with one session in it and a checkpoint past it."""
    application = await build_application(model=fake_model, db_path=path)
    session_id = await start_session(application.service)
    await application.service.run_turn(session_id, "copied")
    await application.summaries_caught_up()
    await application.close()
    assert _tokens(path), "the library wrote no position token; these tests are moot"
    return session_id


def _tokens(path: str) -> list[str]:
    connection = sqlite3.connect(path)
    try:
        return [
            token
            for (token,) in connection.execute(
                "SELECT position_token FROM projection_checkpoints"
            )
            if token is not None
        ]
    finally:
        connection.close()


async def test_a_copy_at_a_new_path_is_readable(build_application, fake_model, tmp_path):
    """The whole point: start against the copy and see what was in it.

    Reverting the rebinding in `copy_database` turns this red with
    `PositionForeignError: cannot order positions from ... and ...`, raised
    before any event is replayed.
    """
    original = str(tmp_path / "original.db")
    session_id = await _written(build_application, fake_model, original)
    destination = str(tmp_path / "copy.db")

    assert copy_database(original, destination) >= 1

    reopened = await build_application(model=fake_model, db_path=destination)
    listed = await reopened.service.list_sessions()
    assert [summary.session_id for summary in listed] == [session_id]


async def test_an_unrebound_copy_refuses_to_start(build_application, fake_model, tmp_path):
    """The failure this module exists to prevent, pinned so it stays prevented.

    Without it, the test above would still pass if the library stopped deriving
    store ids from the path -- it would be asserting that a copy works, not that
    rebinding is what makes it work.
    """
    original = str(tmp_path / "original.db")
    await _written(build_application, fake_model, original)
    destination = str(tmp_path / "raw.db")
    connection = sqlite3.connect(f"file:{original}?mode=ro", uri=True)
    connection.execute("VACUUM INTO ?", (destination,))
    connection.close()

    with pytest.raises(RuntimeError, match="failed to start"):
        await build_application(model=fake_model, db_path=destination)


async def test_rebinding_moves_the_store_id_and_nothing_else(
    build_application, fake_model, tmp_path
):
    """Every token names this file, and the positions themselves are untouched.

    The second assertion is the one with teeth: a rebind that also reset the
    key would leave a database that starts and silently replays from zero,
    which is the state `CLAUDE.md` says not to test against.
    """
    original = str(tmp_path / "original.db")
    await _written(build_application, fake_model, original)
    before = [json.loads(token) for token in _tokens(original)]

    moved = rebind_checkpoints(original)

    after = [json.loads(token) for token in _tokens(original)]
    assert moved == len(before)
    assert {position["s"] for position in after} == {f"sqlite:{original}"}
    assert [position["k"] for position in after] == [position["k"] for position in before]


async def test_rebinding_twice_changes_nothing(build_application, fake_model, tmp_path):
    """Idempotent, so nobody has to remember whether they ran it already."""
    original = str(tmp_path / "original.db")
    await _written(build_application, fake_model, original)
    rebind_checkpoints(original)
    once = _tokens(original)

    rebind_checkpoints(original)

    assert _tokens(original) == once


async def test_it_refuses_to_overwrite_an_existing_copy(
    build_application, fake_model, tmp_path
):
    """A copy is somebody's evidence; replacing it silently loses the bug."""
    original = str(tmp_path / "original.db")
    await _written(build_application, fake_model, original)
    destination = str(tmp_path / "copy.db")
    copy_database(original, destination)

    with pytest.raises(FileExistsError):
        copy_database(original, destination)
