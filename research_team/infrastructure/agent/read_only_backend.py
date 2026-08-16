"""A `StateBackend` over a snapshot of a project's files, with writes refused.

`EventSourcedBackend` turns the deep agent's file tools into domain events.
This one turns the reads into dictionary lookups and the writes into an
exception, because the ask page has no session to append to and no business
appending to one.

As in `backend.py`: `StateBackend` implements every file tool in terms of the
two methods below. Do not reimplement any inherited method.
"""

from typing import Any, NoReturn

from deepagents.backends.protocol import ReadResult
from deepagents.backends.state import StateBackend

from research_team.infrastructure.agent.source_mount import MountsSources, refusal


class ReadOnlyFilesystem(RuntimeError):
    """Raised when the ask agent tries to write.

    A distinct type so a test can name it, and so a caller can tell this
    apart from a genuine backend fault.
    """


class ReadOnlyProjectBackend(MountsSources, StateBackend):
    def __init__(self, files: dict[str, Any], sources: dict[str, Any] | None = None) -> None:
        # Copied, not aliased: the caller's dict is a live project snapshot
        # elsewhere, and sharing it would make this backend writable by
        # accident.
        self._files = dict(files)
        self._sources = dict(sources or {})

    def _read_files(self) -> dict[str, Any]:
        return self._merge_sources(dict(self._files))

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        """Refuse a mounted corpus document, as `EventSourcedBackend` does.

        The citation reason for that refusal bites hardest here: this is the
        page that renders `Citation`s, and `CITED_BY_TOOL` credits
        `read_source` alone. A readable mount would let an answer quote a
        source with nothing attached.
        """
        if self._mounted(file_path):
            return ReadResult(error=refusal(file_path))
        return super().read(file_path, offset, limit)

    def _send_files_update(self, update: dict[str, Any]) -> NoReturn:
        raise ReadOnlyFilesystem(
            f"the ask agent cannot write files (attempted: {sorted(update)})"
        )
