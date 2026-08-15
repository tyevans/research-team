"""Bytes too large for an event payload, addressed by their own digest.

The corpus keeps document text inside the event that stored it, and says why:
the log holding the bytes is what makes a quote checkable years later. Media
cannot go there -- snapshots every 50 events would fold whole films into the
store and into every replay -- so the log keeps the claim and this keeps the
bytes, joined by a digest.

**`put` returns the digest rather than accepting one, and that is the whole
mitigation for the guarantee this weakens.** For text, `Corpus.decide` computes
the digest from bytes it holds, so `by_digest` is a fact about the event. Media
bytes never pass through the domain -- holding a video in memory to hand it to
a pure function is not a thing to do -- so the command carries a digest computed
out here. Giving the caller no parameter by which to offer a different one makes
a wrong digest require a bug in the store rather than a mistake at a call site:
a hazard rather than a trap.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BlobStat:
    """What a stored blob is: its digest, and how many bytes it holds."""

    sha256: str
    byte_count: int


class BlobStorePort(Protocol):
    """Write-once, content-addressed byte storage."""

    async def put(self, stream: AsyncIterator[bytes]) -> BlobStat:
        """Store a stream, returning the digest computed while reading it.

        Idempotent by content: storing bytes already held returns the stat of
        what is there without writing again, so the same video ingested into
        two projects costs one blob.
        """
        ...

    def open(self, sha256: str, start: int = 0) -> AsyncIterator[bytes]:
        """Stream a blob back from `start`. Raises `FileNotFoundError` if gone.

        **`start` is a seek, not a filter.** The bytes before it are never read
        -- that is the entire point, and it is why this is on the port rather
        than done by the caller discarding chunks. The web layer's range
        handling read and threw away everything before the offset until this
        parameter existed, which made a seek into a 400MB film a ~300MB read,
        per seek, per viewer. Files were chosen over SQLite BLOBs for exactly
        this (see `config.blob_root`), and the reason went unused for a slice.

        Out of range is not an error here: a `start` at or past the end yields
        nothing, matching what `seek` past EOF then `read` does, and the range
        route answers 416 from the record's own `byte_count` before it ever
        opens anything. What a test would fail on:
        `test_open_from_an_offset_does_not_read_the_prefix` in
        `test_blob_store.py` reads the file through a handle that records its
        seeks, so an implementation that filtered instead of seeking goes red
        while every byte-for-byte assertion stays green.

        Declared `def`, not `async def`, to match the implementation: an
        `async def` containing `yield` is an async-generator *function*, and
        calling one returns the async iterator directly rather than a
        coroutine that must be awaited to get one. A Protocol member has no
        body to make it an async generator by the same route, so the honest
        signature for "returns an async iterator, non-async to call" is a
        plain `def` with this return type -- matching what
        `FilesystemBlobStore.open` actually is, rather than what an `async
        def` stub would misdescribe it as.
        """
        ...

    async def stat(self, sha256: str) -> BlobStat | None:
        """What is stored under this digest, or `None`.

        `None` is how a caller asks whether a record's bytes still exist, which
        is an ordinary question rather than an error -- the read path answers it
        on every media request.
        """
        ...
