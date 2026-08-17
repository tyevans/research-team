"""Find -- and, only when told to, delete -- blobs no `corpus_media` row names.

`CorpusEditor.store_media` writes bytes before it saves the record, on purpose:
a rejected store then leaves an unreferenced blob, which content addressing
makes harmless, where the other order would commit a record pointing at bytes
that are not there. Supersession and drops leave orphans the same way. Nothing
reclaimed them until this module; `BACKLOG.md` B85 is the entry that accepted
the cost and named the sweep.

**The two writes are not in one transaction, and that is what makes this more
than a `for` loop.** A sweep running between `put` and the save would delete
the bytes of a store still in flight -- turning a design that only wastes disk
into one that destroys data. The ruling: a blob is a candidate only if its
filesystem mtime is older than `config.blob_sweep_grace_seconds()`, whatever
the table says. That sidesteps the window without inventing a transaction
across the blob store and the event store, and it is honest about being a
probability rather than a proof -- see that setting's docstring for the
residual risk and what would trigger it.

Three further deliberate choices:

*Dropped sources keep their blob.* `CorpusMediaProjection` marks a dropped row
rather than deleting it, so its digest is still named here and the sweep will
never touch it. B85 counts a drop as an orphan source because `by_digest`
releases the digest inside the aggregate; the read model disagrees, and the
read model is the conservative one. Reclaiming a dropped source's bytes is
deliberately left undone -- it needs a decision about whether a drop is
reversible, which nothing has made.

*The table is read straight out of SQLite* rather than through `CorpusRunner`.
The sweep must see every project's rows, and `CorpusRunner` only answers per
project; starting the whole projection stack to enumerate one column would
also mean this tool could not run against a copy of a database (see
`local_copy.py` for why a copy does not open where you put it).

*Only files under a two-hex fan-out directory are considered.* A
`.incoming-...` temporary sits at the root, not in a fan-out directory, and is
skipped by construction -- it may belong to an upload happening right now, and
the store's own `except BaseException` is what cleans those up.
"""

import argparse
import sqlite3
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from research_team.infrastructure.config import (
    blob_root,
    blob_sweep_grace_seconds,
    default_db_path,
)
from research_team.infrastructure.persistence.blob_store import FilesystemBlobStore

FANOUT_WIDTH = 2
"""Matches `FilesystemBlobStore._path`'s `sha256[:2]`. If that changes, this
walk finds nothing and every blob looks referenced -- which is the safe
direction, but the sweep would silently stop working."""


@dataclass(frozen=True)
class Orphan:
    """A blob the sweep would remove, with what removing it recovers."""

    sha256: str
    path: Path
    byte_count: int
    age_seconds: float


@dataclass
class SweepReport:
    """What the sweep saw, and what it did about it.

    Counted separately rather than derived from the orphan list, because the
    interesting number when nothing is removed is `within_grace`: a large one
    means the grace period is doing its job or that the operator is sweeping
    too soon after ingest, and both are things to see before deleting.
    """

    scanned: int = 0
    referenced: int = 0
    within_grace: int = 0
    orphans: list[Orphan] = field(default_factory=list)
    removed: list[Orphan] = field(default_factory=list)
    failed: list[tuple[Orphan, str]] = field(default_factory=list)

    @property
    def reclaimable_bytes(self) -> int:
        return sum(orphan.byte_count for orphan in self.orphans)

    @property
    def removed_bytes(self) -> int:
        return sum(orphan.byte_count for orphan in self.removed)


class ReferencesUnavailableError(RuntimeError):
    """The database holds no `corpus_media` table, so nothing is known.

    Raised rather than treated as "no rows", which would make every blob under
    the root an orphan. The failure this guards is an operator pointing
    `--db` at the wrong file: a database that has never seen a media store has
    the table (`apply_schema` creates it) and zero rows, so a *missing* table
    means this is not the database that owns these blobs.
    """


def referenced_digests(db_path: str) -> set[str]:
    """Every `sha256` in `corpus_media`, dropped rows included.

    Read-only (`mode=ro`) so this cannot write to a database the application
    is using, and so a path that does not exist fails here rather than being
    created empty and read as zero rows -- the same wrong-path hazard
    `ReferencesUnavailableError` guards.
    """
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        present = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='corpus_media'"
        ).fetchone()
        if present is None:
            raise ReferencesUnavailableError(
                f"{db_path} has no corpus_media table; refusing to treat every blob "
                "as unreferenced"
            )
        rows = connection.execute("SELECT sha256 FROM corpus_media").fetchall()
    finally:
        connection.close()
    return {sha256 for (sha256,) in rows if sha256}


def iter_blobs(root: Path) -> Iterator[Path]:
    """Every file under a fan-out directory of `root`. See the module docstring."""
    if not root.is_dir():
        return
    for fanout in sorted(root.iterdir()):
        if not fanout.is_dir() or len(fanout.name) != FANOUT_WIDTH:
            continue
        for blob in sorted(fanout.iterdir()):
            if blob.is_file():
                yield blob


def plan(
    store: FilesystemBlobStore,
    db_path: str,
    *,
    grace_seconds: float | None = None,
    now: float | None = None,
) -> SweepReport:
    """What a sweep would remove. Reads only -- nothing here can delete.

    The root comes from `store.root` rather than from `config.blob_root()`:
    a deleter must be pointed at the directory a real store instance is using,
    not at one re-derived beside it.

    A blob whose mtime is in the future (a clock that went backwards, a
    restored backup) has a negative age and so is never older than the grace
    period -- it is counted `within_grace` and kept. Keeping is the direction
    to be wrong in.
    """
    grace = blob_sweep_grace_seconds() if grace_seconds is None else grace_seconds
    moment = time.time() if now is None else now
    referenced = referenced_digests(db_path)
    report = SweepReport()
    for path in iter_blobs(store.root):
        report.scanned += 1
        if path.name in referenced:
            report.referenced += 1
            continue
        stat = path.stat()
        age = moment - stat.st_mtime
        if age < grace:
            report.within_grace += 1
            continue
        report.orphans.append(
            Orphan(sha256=path.name, path=path, byte_count=stat.st_size, age_seconds=age)
        )
    return report


def sweep(
    store: FilesystemBlobStore,
    db_path: str,
    *,
    remove: bool = False,
    grace_seconds: float | None = None,
    now: float | None = None,
) -> SweepReport:
    """Plan the sweep, and delete only if `remove` is explicitly true.

    `remove=False` is the default so that every accidental call -- an import,
    a test, a half-typed command -- reports instead of destroying. A failed
    unlink is collected rather than raised: one unreadable file should not
    leave the rest of a large sweep unreclaimed, and the operator needs the
    list.
    """
    report = plan(store, db_path, grace_seconds=grace_seconds, now=now)
    if not remove:
        return report
    for orphan in report.orphans:
        try:
            orphan.path.unlink()
        except OSError as error:
            report.failed.append((orphan, str(error)))
        else:
            report.removed.append(orphan)
    return report


def _describe(report: SweepReport, *, removed: bool) -> str:
    verb = "removed" if removed else "would remove"
    counted = report.removed if removed else report.orphans
    total = report.removed_bytes if removed else report.reclaimable_bytes
    lines = [
        f"{report.scanned} blobs scanned, {report.referenced} referenced, "
        f"{report.within_grace} within the grace period",
        f"{verb} {len(counted)} blobs ({total} bytes)",
    ]
    lines += [f"  {orphan.sha256} {orphan.byte_count}B" for orphan in counted]
    if report.failed:
        lines.append(f"{len(report.failed)} could not be removed:")
        lines += [f"  {orphan.sha256}: {reason}" for orphan, reason in report.failed]
    return "\n".join(lines)


def main() -> None:
    """Operator-run, in the style of `local_copy.py`. Never on a timer.

    B99's accept sweep is safe to re-run on a schedule because it only *adds*;
    this one destroys, so it is deliberately not wired into
    `Application.start()`. Reporting is the default and `--remove` is the only
    way to delete -- and it still prints the plan first, so the run that
    deletes and the run that did not show the same list.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--remove",
        action="store_true",
        help="actually delete the orphans (default: report only)",
    )
    parser.add_argument("--db", default=None, help="database to read references from")
    parser.add_argument("--root", default=None, help="blob root to sweep")
    parser.add_argument(
        "--grace-seconds",
        type=float,
        default=None,
        help="override AGENT_BLOB_SWEEP_GRACE for this run",
    )
    arguments = parser.parse_args()
    root = Path(arguments.root) if arguments.root else blob_root()
    store = FilesystemBlobStore(root)
    db_path = arguments.db or default_db_path()

    planned = plan(store, db_path, grace_seconds=arguments.grace_seconds)
    print(_describe(planned, removed=False))
    if not arguments.remove:
        print("nothing was deleted; pass --remove to reclaim these")
        return
    # Deliberately re-planned rather than deleting the list just printed: the
    # second observation can only be safer, since a row that appeared in
    # between removes a candidate and the grace period stops anything new from
    # becoming one. The printed plan is therefore a superset of what goes.
    done = sweep(store, db_path, remove=True, grace_seconds=arguments.grace_seconds)
    print(_describe(done, removed=True))


if __name__ == "__main__":
    main()
