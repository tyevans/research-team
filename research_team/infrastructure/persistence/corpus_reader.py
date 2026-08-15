"""The corpus read model, behind `CorpusReadPort`, scoped to one project.

`CorpusRunner` answers for every project -- it is two tables following one log
-- and `CorpusReadPort` deliberately takes no project argument, because a
caller that could pass a different project id is a caller that could read
another project's sources. This closes that gap: the project is bound once,
here, and the tools above get a reader that can only ever see one corpus.

Also where the blob store is bound. `read_media` needs somewhere to `stat`
and `open` bytes the corpus table only points at, and the same reasoning that
binds the project once applies: a caller handed a bare `BlobStorePort` could
point it at any digest, where a caller handed this reader can only ever reach
the bytes this project's own records name.

Nothing else lives here. The tools were written against the Protocol precisely
so the read model could be swapped without touching them, and this module is
the only place the three names appear together.
"""

from uuid import UUID

from research_team.application.blobs import BlobStorePort
from research_team.application.corpus_read import (
    CorpusReadError,
    MediaHandle,
    SourceListing,
    StoredDocument,
)
from research_team.domain import MediaRecord
from research_team.infrastructure.persistence.read_models import (
    CorpusDocumentRow,
    CorpusMediaRow,
    CorpusRunner,
    to_record,
)


class ProjectCorpusReader:
    """`CorpusReadPort` over `CorpusRunner` and a `BlobStorePort`, fixed to one project."""

    def __init__(self, runner: CorpusRunner, project_id: UUID, blobs: BlobStorePort) -> None:
        self._runner = runner
        self._project_id = project_id
        self._blobs = blobs

    async def list_sources(self, *, include_dropped: bool = False) -> list[SourceListing]:
        try:
            rows = await self._runner.list_all(
                self._project_id, include_dropped=include_dropped
            )
        except RuntimeError as error:
            # The runner raises this when its projection was never started,
            # which is a wiring fault rather than an absent document -- and
            # `CorpusReadError` is the one the tools above know how to say.
            raise CorpusReadError(str(error)) from error
        return [
            SourceListing(
                record=to_record(row),
                # Only a `CorpusDocumentRow` carries `extracted_at` -- nothing
                # extracts media yet, so every `CorpusMediaRow` is honestly
                # unextracted rather than unknown. `isinstance` rather than
                # `getattr(row, "extracted_at", None)`, because the latter
                # would silently read `False` for a *text* row that somehow
                # lost the attribute instead of raising on the typo it would
                # actually be.
                extracted=isinstance(row, CorpusDocumentRow) and row.extracted_at is not None,
            )
            for row in rows
        ]

    async def read_document(
        self, source_id: str, *, include_dropped: bool = False
    ) -> StoredDocument | None:
        try:
            row: CorpusDocumentRow | None = await self._runner.get(
                self._project_id, source_id, include_dropped=include_dropped
            )
        except RuntimeError as error:
            raise CorpusReadError(str(error)) from error
        if row is None:
            return None
        # `to_record` is the read model's own row-to-record mapping, reused
        # rather than repeated: it is what `list_sources` already returns, so
        # a document read one way and listed the other cannot describe itself
        # differently.
        return StoredDocument(record=to_record(row), text=row.text)

    async def read_media(
        self, source_id: str, *, include_dropped: bool = False
    ) -> MediaHandle | None:
        """One media source, or `None` when this project has no such id.

        Three outcomes rather than two, and the middle one is why this is not
        just `read_document` with different bytes. `None` means nothing was
        ever stored under this id. A handle whose `stat` is `None` means the
        record is here and the bytes are not -- a dangling reference, which the
        web layer reports as 410 Gone. A caller that collapsed those two would
        send an operator looking for an ingest that never happened instead of
        for bytes that went away.

        The handle carries `open` as a factory rather than an open stream, so
        a caller that only wants the metadata -- the Documents list, deciding
        whether to offer playback -- does not pay for a file descriptor it
        will not read.
        """
        try:
            row: CorpusMediaRow | None = await self._runner.get_media(
                self._project_id, source_id, include_dropped=include_dropped
            )
        except RuntimeError as error:
            raise CorpusReadError(str(error)) from error
        if row is None:
            return None
        stat = await self._blobs.stat(row.sha256)
        record = to_record(row)
        assert isinstance(record, MediaRecord)  # `to_record` on a media row always is.
        return MediaHandle(record=record, stat=stat, open=lambda: self._blobs.open(row.sha256))
