"""The orphan sweep: what it is allowed to delete, and what it must not.

Every test asserts on the filesystem and on the returned report rather than on
the absence of an exception -- a sweep that silently did nothing would pass
"it didn't raise" in every case here, including the ones that exist to prove it
deletes.

The database is built by hand (`CREATE TABLE corpus_media`) rather than by
running the projection. The sweep reads exactly one column of one table, and
standing up `CorpusRunner` to insert a row would make these tests fail for
reasons that have nothing to do with sweeping. The risk that buys -- the real
table's name or column drifting away from this fixture's -- is covered by
`test_the_real_corpus_media_table_is_the_one_this_reads`, which builds the
schema the application actually applies.
"""

import asyncio
import os
import sqlite3
import time
from pathlib import Path

import pytest

from research_team.infrastructure.persistence.blob_store import FilesystemBlobStore
from research_team.infrastructure.persistence.blob_sweep import (
    ReferencesUnavailableError,
    plan,
    referenced_digests,
    sweep,
)

GRACE = 3600.0


async def chunks(*parts: bytes):
    for part in parts:
        yield part


@pytest.fixture
def store(tmp_path: Path) -> FilesystemBlobStore:
    return FilesystemBlobStore(tmp_path / "blobs")


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    path = tmp_path / "sessions.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE corpus_media (id TEXT PRIMARY KEY, sha256 TEXT)")
    connection.commit()
    connection.close()
    return str(path)


def reference(db_path: str, sha256: str) -> None:
    connection = sqlite3.connect(db_path)
    connection.execute("INSERT INTO corpus_media VALUES (?, ?)", (sha256, sha256))
    connection.commit()
    connection.close()


def age(store: FilesystemBlobStore, sha256: str, seconds: float) -> Path:
    """Backdate a blob's mtime, since a test cannot wait out a grace period."""
    path = store.root / sha256[:2] / sha256
    when = time.time() - seconds
    os.utime(path, (when, when))
    return path


async def store_bytes(store: FilesystemBlobStore, payload: bytes) -> str:
    return (await store.put(chunks(payload))).sha256


async def test_an_old_unreferenced_blob_is_a_candidate(
    store: FilesystemBlobStore, db_path: str
) -> None:
    """The whole point: bytes no row names, old enough to be safe to reclaim."""
    sha256 = await store_bytes(store, b"orphan")
    path = age(store, sha256, GRACE * 2)

    report = plan(store, db_path, grace_seconds=GRACE)

    assert [orphan.sha256 for orphan in report.orphans] == [sha256]
    assert report.reclaimable_bytes == len(b"orphan")

    removed = sweep(store, db_path, remove=True, grace_seconds=GRACE)
    assert [orphan.sha256 for orphan in removed.removed] == [sha256]
    assert not path.exists()


async def test_a_young_unreferenced_blob_is_never_a_candidate(
    store: FilesystemBlobStore, db_path: str
) -> None:
    """The ruling this feature exists for.

    A blob no row names may be a `store_media` between its `put` and its save
    -- the two are not in one transaction -- so youth alone protects it. Delete
    the mtime check and this goes red while every other test here stays green;
    that is the only reason it is a separate test from the one above.
    """
    sha256 = await store_bytes(store, b"still in flight")
    path = age(store, sha256, GRACE / 2)

    report = sweep(store, db_path, remove=True, grace_seconds=GRACE)

    assert report.orphans == []
    assert report.removed == []
    assert report.within_grace == 1
    assert path.read_bytes() == b"still in flight"


async def test_a_referenced_blob_is_never_a_candidate_at_any_age(
    store: FilesystemBlobStore, db_path: str
) -> None:
    """Age is a veto, not a licence: a named blob is kept however old it is."""
    sha256 = await store_bytes(store, b"referenced")
    reference(db_path, sha256)
    path = age(store, sha256, GRACE * 1000)

    report = sweep(store, db_path, remove=True, grace_seconds=GRACE)

    assert report.referenced == 1
    assert report.orphans == []
    assert path.read_bytes() == b"referenced"


async def test_a_dry_run_removes_nothing_from_disk(
    store: FilesystemBlobStore, db_path: str
) -> None:
    """`remove` defaults to false, so the accidental call is the harmless one."""
    sha256 = await store_bytes(store, b"orphan")
    path = age(store, sha256, GRACE * 2)

    report = sweep(store, db_path, grace_seconds=GRACE)

    assert [orphan.sha256 for orphan in report.orphans] == [sha256]
    assert report.removed == []
    assert path.read_bytes() == b"orphan"


async def test_an_in_flight_temporary_is_not_swept(
    store: FilesystemBlobStore, db_path: str
) -> None:
    """`.incoming-*` sits at the root, outside every fan-out directory.

    It is unreferenced by definition and can be arbitrarily old if a process
    died mid-upload, so nothing but the walk's shape keeps it: sweeping one
    would truncate an upload in progress.
    """
    # Referenced so that the only thing this test can find is the temporary --
    # otherwise it goes red whenever the grace check does, and stops isolating
    # the walk's shape from the mtime rule.
    reference(db_path, await store_bytes(store, b"anything"))
    temporary = store.root / ".incoming-1-2-3"
    temporary.write_bytes(b"half an upload")
    when = time.time() - GRACE * 2
    os.utime(temporary, (when, when))

    report = sweep(store, db_path, remove=True, grace_seconds=GRACE)

    assert report.orphans == []
    assert temporary.exists()


async def test_a_superseded_digest_becomes_a_candidate_and_the_new_one_does_not(
    store: FilesystemBlobStore, db_path: str
) -> None:
    """Supersession is one of B85's two named orphan sources."""
    old = await store_bytes(store, b"first cut")
    new = await store_bytes(store, b"second cut")
    reference(db_path, new)
    age(store, old, GRACE * 2)
    age(store, new, GRACE * 2)

    report = sweep(store, db_path, remove=True, grace_seconds=GRACE)

    assert [orphan.sha256 for orphan in report.removed] == [old]
    assert (store.root / new[:2] / new).read_bytes() == b"second cut"


def test_a_database_without_the_table_is_refused(tmp_path: Path) -> None:
    """The wrong `--db` must not make every blob an orphan.

    A database that has simply never stored media has the table and no rows;
    a missing table means this is not the database that owns these blobs.
    """
    path = tmp_path / "not-ours.db"
    sqlite3.connect(path).close()

    with pytest.raises(ReferencesUnavailableError):
        referenced_digests(str(path))


def test_the_real_corpus_media_table_is_the_one_this_reads(tmp_path: Path) -> None:
    """Guards the hand-built fixture above against the schema moving.

    Applies the application's own schema and reads it with the sweep's query.
    If `corpus_media` is renamed or loses `sha256`, this goes red -- where the
    rest of the file would keep passing against a table that no longer exists.
    """
    from research_team.infrastructure.persistence.read_models import CorpusStore

    path = tmp_path / "real.db"

    async def build() -> None:
        store = await CorpusStore.open(str(path), None, None, None)
        await store.close()

    asyncio.run(build())

    assert referenced_digests(str(path)) == set()
