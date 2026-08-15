"""The blob store: bytes under their own digest.

Every test here writes through `put` rather than placing files by hand,
because `put` computing the digest is the property the whole provenance story
rests on -- a test that wrote a file itself and asserted on its name would be
asserting about `hashlib`, not about this class.
"""

import asyncio
import hashlib
from pathlib import Path

import pytest

from research_team.infrastructure.persistence.blob_store import FilesystemBlobStore


async def chunks(*parts: bytes):
    for part in parts:
        yield part


@pytest.fixture
def store(tmp_path: Path) -> FilesystemBlobStore:
    return FilesystemBlobStore(tmp_path)


async def test_put_returns_the_digest_it_computed(store: FilesystemBlobStore) -> None:
    """The digest is a fact about the bytes, not a claim from the caller.

    `put` takes no digest argument at all, which is what makes a wrong one
    require a bug in this class rather than a mistake at a call site.
    """
    stat = await store.put(chunks(b"hello ", b"world"))
    assert stat.sha256 == hashlib.sha256(b"hello world").hexdigest()
    assert stat.byte_count == 11


async def test_bytes_come_back_whole(store: FilesystemBlobStore) -> None:
    stat = await store.put(chunks(b"one", b"two", b"three"))
    read = b"".join([part async for part in store.open(stat.sha256)])
    assert read == b"onetwothree"


async def test_storing_the_same_bytes_twice_keeps_one_blob(
    store: FilesystemBlobStore, tmp_path: Path
) -> None:
    """Deduplication is free and is the reason content addressing was chosen.

    Fails if `put` writes unconditionally: the second call would leave a second
    file, and the same video ingested into two projects would cost twice.
    """
    first = await store.put(chunks(b"same"))
    second = await store.put(chunks(b"same"))
    assert first == second
    blobs = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert len(blobs) == 1


async def test_stat_is_none_for_bytes_that_were_never_stored(
    store: FilesystemBlobStore,
) -> None:
    """The seam every missing-blob report goes through.

    `None` rather than an exception, because "are the bytes still there" is a
    question callers ask on the ordinary path.
    """
    assert await store.stat("0" * 64) is None


async def test_a_partial_write_is_never_readable_under_a_finished_name(
    store: FilesystemBlobStore, tmp_path: Path
) -> None:
    """A torn write must not be readable under a name claiming its content.

    The stream raises halfway; afterwards nothing may exist under the digest of
    the bytes that *would* have been written, and no temporary file may be left
    behind. Fails if `put` writes directly to the final path instead of
    `os.replace`-ing a temporary one into place.
    """
    payload = b"first half second half"

    async def failing():
        yield payload[:11]
        raise RuntimeError("connection dropped")

    with pytest.raises(RuntimeError):
        await store.put(failing())

    assert await store.stat(hashlib.sha256(payload).hexdigest()) is None
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []


async def test_open_raises_for_a_blob_that_is_gone(store: FilesystemBlobStore) -> None:
    """Callers are expected to `stat` first; `open` still refuses loudly.

    A silent empty stream here would render as a zero-byte video, which is the
    dangling reference presenting itself as a corrupt file.
    """
    with pytest.raises(FileNotFoundError):
        [part async for part in store.open("0" * 64)]


async def test_put_cleans_up_after_a_cancellation_mid_stream(
    store: FilesystemBlobStore, tmp_path: Path
) -> None:
    """The cleanup on a failed write must catch `BaseException`, not `Exception`.

    A later task enforces an upload ceiling by wrapping the caller's stream and
    raising partway through once too many bytes have passed -- and it does that
    with `asyncio.CancelledError`, which is a `BaseException` and is *not*
    caught by `except Exception`. Fails if `put`'s cleanup is narrowed to
    `Exception`: the temporary file would survive under the root, silently,
    because nothing about a cancelled upload looks different from a successful
    one until someone lists the directory.
    """

    async def cancelling():
        yield b"partial"
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await store.put(cancelling())

    assert [path for path in tmp_path.rglob("*") if path.is_file()] == []
