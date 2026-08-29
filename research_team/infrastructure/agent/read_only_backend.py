"""A `StateBackend` over a snapshot of a project's files, with writes refused.

`EventSourcedBackend` turns the deep agent's file tools into domain events.
This one turns the reads into dictionary lookups and the writes into an
exception, because the ask page has no session to append to and no business
appending to one.

As in `backend.py`: `StateBackend` implements every file tool in terms of the
two methods below. Do not reimplement any inherited method.
"""

from typing import Any, NoReturn

from deepagents.backends.state import StateBackend


class ReadOnlyFilesystem(RuntimeError):
    """Raised when the ask agent tries to write.

    A distinct type so a test can name it, and so a caller can tell this
    apart from a genuine backend fault.
    """


class ReadOnlyProjectBackend(StateBackend):
    def __init__(self, files: dict[str, Any]) -> None:
        # Copied, not aliased: the caller's dict is a live project snapshot
        # elsewhere, and sharing it would make this backend writable by
        # accident.
        self._files = dict(files)

    def _read_files(self) -> dict[str, Any]:
        return dict(self._files)

    def _send_files_update(self, update: dict[str, Any]) -> NoReturn:
        raise ReadOnlyFilesystem(
            f"the ask agent cannot write files (attempted: {sorted(update)})"
        )
