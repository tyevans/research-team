"""StateBackends for agent file tools.

Includes both the mutable event-sourced backend used by interactive session
agents, and the read-only projection backend used by Ask and Socratic agents.

`StateBackend` implements every file tool in terms of two private seams,
`_read_files` and `_send_files_update`. Overriding just those two gives us
deepagents' exact semantics -- line numbering, read windowing, edit ambiguity
checks, glob/grep, truncation, error strings -- with the aggregate or snapshot as
the store. Do not reimplement any inherited method.
"""

from typing import Any, NoReturn

from deepagents.backends.protocol import EditResult
from deepagents.backends.state import StateBackend

from research_team.session.domain import (
    DeleteFile,
    EditFile,
    Session,
    WriteFile,
)

__all__ = [
    "EventSourcedBackend",
    "ReadOnlyFilesystem",
    "ReadOnlyProjectBackend",
]


class EventSourcedBackend(StateBackend):
    def __init__(self, aggregate: Session) -> None:
        self._aggregate = aggregate
        self._edit_intent: tuple[str, str, bool] | None = None

    # ---- the two seams ----

    def _read_files(self) -> dict[str, Any]:
        return dict(self._aggregate.state.files)

    def _send_files_update(self, update: dict[str, Any]) -> None:
        for path, file_data in update.items():
            if file_data is None:
                self._aggregate.execute(DeleteFile(path=path))
            elif self._edit_intent is not None:
                old_string, new_string, replace_all = self._edit_intent
                self._aggregate.execute(
                    EditFile(
                        path=path,
                        file_data=file_data,
                        old_string=old_string,
                        new_string=new_string,
                        replace_all=replace_all,
                    )
                )
            else:
                self._aggregate.execute(WriteFile(path=path, file_data=file_data))

    # ---- intent capture ----

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Record *why* the file changed, then defer entirely to the superclass.

        The superclass performs all validation and the replacement itself; we
        only observe, so `FileEdited` can carry the edit intent alongside the
        resulting content.
        """
        self._edit_intent = (old_string, new_string, replace_all)
        try:
            return super().edit(file_path, old_string, new_string, replace_all=replace_all)
        finally:
            self._edit_intent = None


class ReadOnlyFilesystem(RuntimeError):
    """Raised when the ask agent tries to write.

    A distinct type so a test can name it, and so a caller can tell this
    apart from a genuine backend fault.
    """


class ReadOnlyProjectBackend(StateBackend):
    """A `StateBackend` over a snapshot of a project's files, with writes refused.

    `EventSourcedBackend` turns the deep agent's file tools into domain events.
    This one turns the reads into dictionary lookups and the writes into an
    exception, because the ask page has no session to append to and no business
    appending to one.
    """

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
