"""`BlobStorePort` over an ordinary directory.

Two hex characters of fan-out (`blobs/ab/abcdef...`) because a flat directory
of a hundred thousand files is slow to list on every filesystem that matters,
and listing is what a future garbage sweep would do.

The root is a constructor argument and never an environment variable, so two
differently-rooted stores can run side by side in one test process.
"""

import hashlib
import os
from collections.abc import AsyncIterator
from pathlib import Path

import aiofiles

from research_team.application.blobs import BlobStat

CHUNK_SIZE = 1024 * 1024
"""How much is read per `open` iteration. A megabyte is large enough that a
gigabyte file is a thousand awaits rather than a million, and small enough
that a handful of concurrent streams cannot exhaust memory."""


class FilesystemBlobStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def _path(self, sha256: str) -> Path:
        return self._root / sha256[:2] / sha256

    async def put(self, stream: AsyncIterator[bytes]) -> BlobStat:
        """Stream to a temporary file, then `os.replace` it into place.

        The rename is the atomicity: the digest is not known until the last
        byte, so a direct write would be readable under a name claiming content
        it does not yet hold. `os.replace` within one filesystem is atomic,
        which is why the temporary lives in the destination directory rather
        than in `/tmp`.

        The cleanup on failure catches `BaseException`, not `Exception`: an
        upload ceiling (a later task) cancels the stream by raising
        `asyncio.CancelledError` partway through, which is a `BaseException`.
        `except Exception` would let it past the `unlink` and leave the
        temporary file sitting under the root forever.
        """
        self._root.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        byte_count = 0
        # `os.getpid` so two processes sharing a root cannot collide on the
        # temporary name; `id(self)` so two stores in one process cannot either.
        temporary = self._root / f".incoming-{os.getpid()}-{id(self)}-{id(stream)}"
        try:
            async with aiofiles.open(temporary, "wb") as handle:
                async for part in stream:
                    digest.update(part)
                    byte_count += len(part)
                    await handle.write(part)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

        sha256 = digest.hexdigest()
        destination = self._path(sha256)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            # Write-once: identical bytes are already here, and rewriting them
            # would briefly replace a file other readers may be streaming.
            temporary.unlink(missing_ok=True)
            return BlobStat(sha256=sha256, byte_count=destination.stat().st_size)
        os.replace(temporary, destination)
        return BlobStat(sha256=sha256, byte_count=byte_count)

    async def open(self, sha256: str) -> AsyncIterator[bytes]:
        path = self._path(sha256)
        # Raises FileNotFoundError, which is the loud answer this wants: a
        # silent empty stream would render as a zero-byte video, turning a
        # dangling reference into what looks like a corrupt file.
        async with aiofiles.open(path, "rb") as handle:
            while True:
                part = await handle.read(CHUNK_SIZE)
                if not part:
                    return
                yield part

    async def stat(self, sha256: str) -> BlobStat | None:
        path = self._path(sha256)
        if not path.is_file():
            return None
        return BlobStat(sha256=sha256, byte_count=path.stat().st_size)
