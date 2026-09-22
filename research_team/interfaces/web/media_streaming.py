"""Media upload limits, type sniffing, and RFC 9110 byte-range streaming helpers."""

import sys
from collections.abc import AsyncIterator

from research_team.research.application.media_acquisition import MAX_UPLOAD_BYTES

__all__ = [
    "UPLOAD_CHUNK_BYTES",
    "_MAGIC_NUMBERS",
    "_RangeNotSatisfiable",
    "_UploadTooLarge",
    "_first_bytes",
    "_max_upload_bytes",
    "_parse_byte_range",
    "_sniff_media_type",
]

UPLOAD_CHUNK_BYTES = 1024 * 1024
"""How much is read from the request per iteration, matching
`FilesystemBlobStore.CHUNK_SIZE` for its reasons."""


def _max_upload_bytes() -> int:
    app_mod = sys.modules.get("research_team.interfaces.web.app")
    if app_mod is not None and hasattr(app_mod, "MAX_UPLOAD_BYTES"):
        return app_mod.MAX_UPLOAD_BYTES
    return MAX_UPLOAD_BYTES


class _UploadTooLarge(Exception):
    """The ceiling was crossed mid-stream. Raised from inside `put`'s loop."""


#: Leading bytes that identify a format, for the cases a browser gets wrong.
#: Deliberately short: this is not a content-type database, it is a correction
#: for `application/octet-stream`, which is what a browser sends for anything
#: the operating system has no association for -- `.mkv` and `.webm` on a bare
#: machine, most often. A format missing from here is stored under whatever the
#: browser said, which is the same behaviour as before sniffing existed.
_MAGIC_NUMBERS: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
    (b"OggS", "audio/ogg"),
    (b"ID3", "audio/mpeg"),
    (b"fLaC", "audio/flac"),
    # EBML, which is Matroska *and* WebM -- the magic number cannot tell them
    # apart, and reading far enough to find the DocType is more parsing than a
    # correction for a wrong header is worth. `video/webm` is the deliberate
    # choice of the two: it is the same container family, it is what a browser
    # will attempt, and being wrong costs a `<video>` that fails on codec
    # rather than one that never tries. `video/x-matroska` would be the
    # honest label for a `.mkv` and Chromium refuses to play it outright, so
    # the accurate answer is the less useful one here.
    (b"\x1a\x45\xdf\xa3", "video/webm"),
)


def _sniff_media_type(head: bytes) -> str | None:
    """What the leading bytes say this is, or `None` if they say nothing.

    The two container formats that cannot be a prefix table are handled first:
    ISO base media (`.mp4`, `.m4a`, `.mov`) puts `ftyp` at offset 4 behind a
    length, and RIFF puts its real form at offset 8.
    """
    if head[4:8] == b"ftyp":
        return "video/mp4"
    if head[:4] == b"RIFF":
        if head[8:12] == b"WAVE":
            return "audio/wav"
        if head[8:12] == b"AVI ":
            return "video/x-msvideo"
        return None
    for prefix, media_type in _MAGIC_NUMBERS:
        if head.startswith(prefix):
            return media_type
    return None


class _RangeNotSatisfiable(Exception):
    """A range starting past the end. 416, with the real length attached."""

    def __init__(self, total: int) -> None:
        super().__init__(f"range starts past the end of {total} bytes")
        self.total = total


def _parse_byte_range(header: str, total: int) -> tuple[int, int] | None:
    """`Range: bytes=…` as an inclusive `(start, end)`, or `None` to ignore it.

    `None` for anything this does not understand -- multiple ranges, a unit
    that is not `bytes`, a malformed header -- because RFC 9110 says a
    recipient that cannot satisfy a Range must ignore it and answer 200 with
    the whole representation. Answering 400 instead would break a client that
    was entitled to ask.

    An end below the start (`bytes=2-1`) is ignored too, and that is a
    distinction worth keeping straight: RFC 9110 §14.1.1 makes a
    `last-byte-pos` below `first-byte-pos` an *invalid* byte-range-spec, and
    an invalid ranges-specifier must be ignored rather than refused. Only a
    range starting at or past the end is genuinely *unsatisfiable*, and that
    is what raises `_RangeNotSatisfiable` -- there the client asked for bytes
    that do not exist and a 200 would silently give it different ones.

    The three forms, all of which a browser sends: `bytes=2-5` (both ends),
    `bytes=2-` (open-ended, what a `<video>` sends first), and `bytes=-500`
    (the last 500 bytes, which is how a player finds an MP4's trailing
    `moov` atom).

    **Every form is decided against `total` in one place, at the bottom.** The
    suffix branch used to return before reaching it, and against a zero-byte
    blob that produced `(0, -1)` and a response header of
    `content-range: bytes 0--1/0` -- not a valid `Content-Range`, and a strict
    client is entitled to call the response broken.
    `test_a_suffix_range_against_an_empty_blob_answers_416` is what fails if
    any branch takes a short cut past the guard again.
    """
    unit, _, spec = header.partition("=")
    if unit.strip().lower() != "bytes" or "," in spec:
        return None
    first, sep, last = spec.strip().partition("-")
    if not sep:
        return None
    try:
        if not first:
            if not last:
                return None
            length = int(last)
            if length <= 0:
                return None
            # Suffix form: the last N bytes, which for a blob shorter than N
            # begins at byte zero. Its end is `None` -- "to the last byte" --
            # rather than `total - 1`, so that an empty blob reaches the
            # unsatisfiable check below instead of arriving there as an end of
            # -1 that looks like the invalid spec it is not.
            start, requested_end = max(0, total - length), None
        else:
            start = int(first)
            requested_end = None if not last else int(last)
    except ValueError:
        return None
    if requested_end is not None and requested_end < start:
        return None
    if start >= total:
        raise _RangeNotSatisfiable(total)
    # An absent end means "to the last byte", and an end past the last byte is
    # clamped rather than refused -- a client that asks for more than there is
    # gets what there is, which is what a player expects.
    return start, total - 1 if requested_end is None else min(requested_end, total - 1)


async def _first_bytes(stream: AsyncIterator[bytes], length: int) -> AsyncIterator[bytes]:
    """The first `length` bytes of a stream, then stop.

    Only the *tail* is trimmed here. The head is `BlobStorePort.open`'s
    `start`, which is a real `seek` -- this used to discard the prefix chunk
    by chunk instead, which made a seek into a 400MB film a ~300MB read, per
    seek, per viewer, while every byte-for-byte test stayed green. The
    trimming that remains cannot be pushed down the same way: the store reads
    in megabyte chunks and a range rarely ends on one.

    What a test would fail on: the arithmetic is off-by-one-prone in both
    directions -- an inclusive end read as exclusive truncates every seek by
    one byte -- and `test_the_range_forms_a_browser_actually_sends` holds it
    at both edges, open-ended, suffix and clamped.
    """
    sent = 0
    async for part in stream:
        remaining = length - sent
        if len(part) >= remaining:
            yield part[:remaining]
            return
        sent += len(part)
        yield part
