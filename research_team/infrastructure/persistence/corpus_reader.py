"""The corpus read model, behind `CorpusReadPort`, scoped to one project.

`CorpusRunner` answers for every project -- it is one table following one log
-- and `CorpusReadPort` deliberately takes no project argument, because a
caller that could pass a different project id is a caller that could read
another project's sources. This closes that gap: the project is bound once,
here, and the tools above get a reader that can only ever see one corpus.

Nothing else lives here. The tools were written against the Protocol precisely
so the read model could be swapped without touching them, and this module is
the only place the two names appear together.
"""

from uuid import UUID

from research_team.application.corpus_read import (
    CorpusReadError,
    DocumentListing,
    StoredDocument,
)
from research_team.infrastructure.persistence.read_models import (
    CorpusDocumentRow,
    CorpusRunner,
    to_record,
)


class ProjectCorpusReader:
    """`CorpusReadPort` over `CorpusRunner`, fixed to one project."""

    def __init__(self, runner: CorpusRunner, project_id: UUID) -> None:
        self._runner = runner
        self._project_id = project_id

    async def list_documents(self, *, include_dropped: bool = False) -> list[DocumentListing]:
        try:
            return await self._runner.list(self._project_id, include_dropped=include_dropped)
        except RuntimeError as error:
            # The runner raises this when its projection was never started,
            # which is a wiring fault rather than an absent document -- and
            # `CorpusReadError` is the one the tools above know how to say.
            raise CorpusReadError(str(error)) from error

    async def read_document(self, source_id: str) -> StoredDocument | None:
        try:
            row: CorpusDocumentRow | None = await self._runner.get(self._project_id, source_id)
        except RuntimeError as error:
            raise CorpusReadError(str(error)) from error
        if row is None:
            return None
        # `to_record` is the read model's own row-to-record mapping, reused
        # rather than repeated: it is what `list` already returns, so a
        # document read one way and listed the other cannot describe itself
        # differently.
        return StoredDocument(record=to_record(row), text=row.text)
