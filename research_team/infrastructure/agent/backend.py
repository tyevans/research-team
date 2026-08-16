"""Filesystem backend that records every mutation as a domain event.

`StateBackend` implements every file tool in terms of two private seams,
`_read_files` and `_send_files_update`. Overriding just those two gives us
deepagents' exact semantics -- line numbering, read windowing, edit
ambiguity checks, glob/grep, truncation, error strings -- with the
aggregate as the store. Do not reimplement any inherited method.
"""

from typing import Any

from deepagents.backends.protocol import EditResult, ReadResult
from deepagents.backends.state import StateBackend

from research_team.domain import DeleteFile, EditFile, WriteFile
from research_team.domain.session import Session
from research_team.infrastructure.agent.source_mount import MountsSources, refusal


class EventSourcedBackend(MountsSources, StateBackend):
    def __init__(self, aggregate: Session, sources: dict[str, Any] | None = None) -> None:
        self._aggregate = aggregate
        self._edit_intent: tuple[str, str, bool] | None = None
        # Defaults to empty so every existing call site keeps its exact
        # behaviour: with nothing mounted, `/sources/x` is an ordinary scratch
        # path and the guards below cannot fire.
        self._sources = dict(sources or {})

    # ---- the two seams ----

    def _read_files(self) -> dict[str, Any]:
        return self._merge_sources(dict(self._aggregate.state.files))

    def _send_files_update(self, update: dict[str, Any]) -> None:
        # Before the loop, not inside it. A write reaching a mounted path would
        # append a `FileWritten` that shadows the corpus for every later read,
        # and events are not rewritten -- so a guard that refused partway
        # through would have already made the corruption permanent for the
        # paths it got to first.
        self._refuse_mounted_writes(update)
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

    # ---- mounted sources ----

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        """Refuse a mounted corpus document, and name the tool that opens one.

        An intercept-then-defer, like `edit` below, rather than a
        reimplementation: everything not mounted goes to the superclass
        untouched. `source_mount.py` has the reason a mounted read is refused
        at all -- it would return a line-numbered window and earn no citation.
        """
        if self._mounted(file_path):
            return ReadResult(error=refusal(file_path))
        return super().read(file_path, offset, limit)

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
