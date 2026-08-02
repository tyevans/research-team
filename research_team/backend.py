"""Filesystem backend that records every mutation as a domain event.

`StateBackend` implements every file tool in terms of two private seams,
`_read_files` and `_send_files_update`. Overriding just those two gives us
deepagents' exact semantics -- line numbering, read windowing, edit
ambiguity checks, glob/grep, truncation, error strings -- with the
aggregate as the store. Do not reimplement any inherited method.
"""

from typing import Any

from deepagents.backends.protocol import EditResult
from deepagents.backends.state import StateBackend

from research_team.session import CodingSession


class EventSourcedBackend(StateBackend):
    def __init__(self, aggregate: CodingSession) -> None:
        self._aggregate = aggregate
        self._edit_intent: tuple[str, str, bool] | None = None

    # ---- the two seams ----

    def _read_files(self) -> dict[str, Any]:
        return dict(self._aggregate.state.files)

    def _send_files_update(self, update: dict[str, Any]) -> None:
        for path, file_data in update.items():
            if file_data is None:
                self._aggregate.delete_file(path)
            elif self._edit_intent is not None:
                old_string, new_string, replace_all = self._edit_intent
                self._aggregate.edit_file(
                    path, file_data, old_string, new_string, replace_all
                )
            else:
                self._aggregate.write_file(path, file_data)

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
            return super().edit(
                file_path, old_string, new_string, replace_all=replace_all
            )
        finally:
            self._edit_intent = None
