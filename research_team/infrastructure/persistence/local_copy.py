"""Make a working copy of a live database that projections will actually open.

`CLAUDE.md` asks for a read-model change to be run against a database that
predates it, and a copy of a real one is the best such database. Copying it is
not enough: `eventsource`'s SQLite store derives its store id from the database
string it was handed (`f"sqlite:{database}"`, `adapters/sqlite/store.py`), every
checkpoint in `projection_checkpoints` stores that id inside its position token,
and `Position.__ge__` refuses to order two positions from different stores. So a
copy at a new path fails on the way up with

    PositionForeignError: cannot order positions from
    'sqlite:/home/you/.research-team/sessions.db' and 'sqlite:/tmp/copy.db'

before a single event is replayed -- measured against the real database on
2026-08-13, eventsource-py 0.14.0.

This rewrites the store id in each checkpoint's position token to the copy's own
path, which is the only part of the token that is path-dependent; the position
key is a global position in the log, and the log came along with the copy.

The alternative -- deleting every row from `projection_checkpoints` -- also gets
the process up, and it is the wrong tool for this particular job. A projection
with no checkpoint replays the whole log and rewrites every row, which is
`/rebuild`. That is exactly the state the rule exists to *avoid* testing:
against a real database the projection resumes near the end of the log, so rows
written before a field existed keep the empty column the reconcile added and are
never backfilled. Emptying `session_summary_rows` in two copies and starting
each showed the difference plainly -- the cleared copy came back with all four
rows, the rebound copy with none.

    uv run python -m research_team.infrastructure.persistence.local_copy /tmp/probe.db

Only checkpoints are touched. Read-model rows, snapshots and the DLQ are left as
they were copied, because they are the stale state worth testing against.
"""

import argparse
import json
import sqlite3
from pathlib import Path

from research_team.infrastructure.config import default_db_path

STORE_ID_PREFIX = "sqlite:"


def rebind_checkpoints(db_path: str) -> int:
    """Point every checkpoint in `db_path` at `db_path`. Returns how many moved.

    Idempotent: a token that already names this path is rewritten to itself.
    A checkpoint with no token yet (the store writes one only after it has
    processed an event) is left alone rather than invented.

    The store id is built from the database *string*, not from a canonical
    path, so the value passed here has to be the one the application will pass
    to `SQLiteEventStore` -- `AGENT_DB=./copy.db` and `AGENT_DB=/abs/copy.db`
    are two different stores as far as the library is concerned. The CLI below
    resolves the destination and prints the `AGENT_DB` line to match, which is
    the only reason this is not a trap of its own.
    """
    store_id = f"{STORE_ID_PREFIX}{db_path}"
    connection = sqlite3.connect(db_path)
    try:
        rows = connection.execute(
            "SELECT projection_name, position_token FROM projection_checkpoints"
        ).fetchall()
        moved = 0
        for name, token in rows:
            if token is None:
                continue
            position = json.loads(token)
            position["s"] = store_id
            connection.execute(
                "UPDATE projection_checkpoints SET position_token = ? "
                "WHERE projection_name = ?",
                (json.dumps(position, separators=(",", ":")), name),
            )
            moved += 1
        connection.commit()
        return moved
    finally:
        connection.close()


def copy_database(source: str, destination: str) -> int:
    """Copy `source` to `destination` and rebind the copy's checkpoints.

    `VACUUM INTO` rather than `shutil.copy`, because the live database runs in
    WAL mode: copying the file alone leaves behind whatever is still in the
    `-wal`, which for a database in use is usually the most recent events --
    the ones a stale read model is most likely to be wrong about. It also opens
    the source read-only, so nothing here can write to a database somebody is
    using.
    """
    if Path(destination).exists():
        raise FileExistsError(
            f"{destination} exists; pick a new path rather than overwriting a copy "
            "whose state you may still need"
        )
    connection = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        connection.execute("VACUUM INTO ?", (destination,))
    finally:
        connection.close()
    return rebind_checkpoints(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("destination", help="path to write the copy to")
    parser.add_argument(
        "--source",
        default=None,
        help="database to copy (default: the one the application would open)",
    )
    arguments = parser.parse_args()
    source = arguments.source or default_db_path()
    destination = str(Path(arguments.destination).resolve())
    moved = copy_database(source, destination)
    print(f"{source} -> {destination} ({moved} checkpoints rebound)")
    print(f"run against it with: AGENT_DB={destination}")


if __name__ == "__main__":
    main()
