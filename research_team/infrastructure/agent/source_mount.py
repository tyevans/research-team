"""The corpus, as files the built-in search tools can already see.

`grep` searched `session.state.files` and nothing else, so a phrase appearing
in every gathered document returned no matches -- and an empty grep result is
indistinguishable from a search that ran against the right store and found
nothing. The corpus has no search of its own either: `corpus_tools.py` offers
`list_sources` and `read_source`, so finding a phrase meant opening documents
one at a time.

`StateBackend` implements *every* file tool in terms of `_read_files()`, so
merging documents into that one dictionary gives `ls`, `glob` and `grep`
deepagents' own matching, filtering and truncation over the corpus without
reimplementing any of it. That is the same reasoning `backend.py` already
gives for overriding only the two seams.

**Search here, read through the corpus tool.** `read_file` on a mounted path is
refused, and the refusal names `read_source`. The corpus contract is
`source_id@start-end` computed by `corpus_spans.quote` and reported back from
the result rather than from the request; a mounted read would return a
line-numbered window and earn no citation, which on the ask page is an answer
quoting gathered material with nothing attached. Grep *snippets* still reach
the model uncited -- that is how it decides what to open, and the alternative
is a search that will not say what it found.

The snapshot is per turn, because `_read_files()` is synchronous and the corpus
port is not. A document stored mid-turn is therefore not greppable until the
next one; the tool that stored it returned its `source_id`, so it can be read
immediately without being searched for.
"""

from typing import Any

from deepagents.backends.utils import create_file_data

from research_team.application.corpus_read import CorpusReadPort
from research_team.domain import TextRecord

MOUNT_PREFIX = "/sources/"
"""One path segment per source, which is safe only because `decide` refuses a
`source_id` holding `/` (06ad597). Before that, a url-keyed id would have
mounted as a directory tree and `ls /sources/` would have answered `https:/`.

No file extension: `glob("/sources/*")` needs none, and a suffix would sit
between the path the model reads out of a grep hit and the `source_id` it has
to hand to `read_source`."""


def mount_path(source_id: str) -> str:
    return f"{MOUNT_PREFIX}{source_id}"


def mounted_source_id(path: str) -> str | None:
    """The `source_id` a mounted path names, or None if it is not one."""
    if not path.startswith(MOUNT_PREFIX):
        return None
    return path[len(MOUNT_PREFIX) :]


def refusal(path: str) -> str:
    """Why a mounted path cannot be read or written, and what to call instead."""
    source_id = mounted_source_id(path)
    return (
        f"'{path}' is a mounted corpus document, which the file tools can search "
        f"but not open or change. Read it with "
        f'read_source(source_id="{source_id}") -- that is the only path that '
        f"returns a citable source_id@start-end span."
    )


async def mounted_sources(corpus: CorpusReadPort) -> dict[str, Any]:
    """This project's text sources, keyed by mount path.

    Media is excluded because it has no text: mounting a filename with no
    content puts an empty file in front of every `grep`, which reads as
    "searched it, found nothing" for a source that was never searchable.

    Dropped documents are excluded twice over -- the port's own default already
    omits them, and a record arriving with `dropped_reason` set is skipped here
    as well. Not redundant: `CorpusReadPort` is a Protocol, and a second
    implementation defaulting the other way would silently resurrect every
    exclusion the project made.

    Reads every document in full, and every `grep` rescans all of it. Measured
    on 2026-08-16 against a copy of the real database: three projects, 69 text
    sources, 21/17/31 documents mounting to 1.5M/331K/181K characters. The
    largest is 1.5MB resident per turn and walked per call -- affordable now,
    and the number to watch. A cap was rejected rather than sized: a mount that
    silently drops its tail produces exactly the miss-in-silence this module
    exists to remove.
    """
    mount: dict[str, Any] = {}
    for listing in await corpus.list_sources():
        record = listing.record
        if not isinstance(record, TextRecord) or record.dropped_reason is not None:
            continue
        document = await corpus.read_document(record.source_id)
        if document is None:
            # Listed but unreadable: the row exists and its text does not. Skip
            # rather than mount an empty file, for the same reason media is
            # skipped -- an empty mount answers a search with a lie.
            continue
        file_data = create_file_data(document.text)
        # `create_file_data` stamps *now*, and `ls` renders `modified_at`. A
        # document fetched last week reported as modified this second is a
        # wrong answer wearing a right one's shape.
        stamp = record.fetched_at or ""
        file_data["created_at"] = stamp
        file_data["modified_at"] = stamp
        mount[mount_path(record.source_id)] = file_data
    return mount


class MountsSources:
    """Merges a source mount into a `StateBackend`'s file view.

    A mixin rather than a shared base class because the two backends it serves
    have genuinely different stores underneath -- one appends events, one holds
    a snapshot -- and the only thing they share is this.

    Mounted entries win over whatever the underlying store holds at the same
    path. An older build, before the write guard below existed, could have
    appended a `FileWritten` under `/sources/`; those events still replay, so
    without precedence a stale scratch copy would answer every search for that
    source forever.
    """

    _sources: dict[str, Any]

    def _merge_sources(self, files: dict[str, Any]) -> dict[str, Any]:
        return {**files, **self._sources}

    def _mounted(self, path: str) -> bool:
        return path in self._sources

    def _refuse_mounted_writes(self, update: dict[str, Any]) -> None:
        """Raise before anything is executed if any path in `update` is mounted.

        Checked over the whole update first, not per key as it is applied: a
        guard that refuses partway through has already appended events for the
        paths it got to, and those are not rewritten.
        """
        refused = sorted(path for path in update if self._mounted(path))
        if refused:
            raise MountedSourceIsReadOnly(refusal(refused[0]))


class MountedSourceIsReadOnly(RuntimeError):
    """A write reached a mounted corpus document.

    A distinct type so a test can name it, and so a caller can tell it from a
    genuine backend fault. It carries `refusal`'s text because the deepagents
    tool layer turns a raised message into what the model reads.
    """
