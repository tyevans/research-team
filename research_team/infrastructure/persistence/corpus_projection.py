"""Corpus read model event projection.

Extracted from corpus_read_models.py to isolate event handling logic
from table schemas and store/runner lifecycle orchestration.
"""

from __future__ import annotations

import json
from uuid import UUID

from eventsource import DeclarativeProjection, handles
from eventsource.ports.readmodels import ReadModelRepository
from redstring import DocumentExtracted

from research_team.infrastructure.persistence.corpus_rows import (
    CorpusDocumentRow,
    CorpusMediaRow,
    _decode_degradations,
)
from research_team.infrastructure.persistence.store_base import LOCAL_RETRY_POLICY
from research_team.research.domain import (
    UNREADABLE_DEGRADATIONS,
    CorpusDerivedTextStored,
    CorpusDocumentDropped,
    CorpusDocumentStored,
    CorpusMediaStored,
)

__all__ = ["CorpusProjection"]


class CorpusProjection(DeclarativeProjection):
    """Applies corpus events to their row, one event at a time.

    Both handlers are idempotent by overwrite rather than by increment: there
    is no counter here, so replaying from a checkpoint that is behind
    re-derives exactly the same row instead of accumulating. That is why a
    rebuild is safe to reach for.
    """

    def __init__(
        self,
        rows: ReadModelRepository[CorpusDocumentRow],
        media_rows: ReadModelRepository[CorpusMediaRow],
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._rows = rows
        self._media_rows = media_rows
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(CorpusDocumentStored)
    async def _on_stored(self, event: CorpusDocumentStored) -> None:
        """Write the document, superseding whatever the source held before.

        The existing row is loaded and mutated rather than replaced wholesale,
        so the repository's version counter keeps climbing instead of resetting
        -- and `dropped_reason` is cleared explicitly, because storing asserts
        presence and a live document explaining why it is absent is nonsense.
        """
        row_id = CorpusDocumentRow.row_id(event.aggregate_id, event.source_id)
        fields = {
            "project_id": event.aggregate_id,
            "source_id": event.source_id,
            "text": event.text,
            "sha256": event.sha256,
            "char_count": len(event.text),
            "uri": event.uri,
            "title": event.title,
            "published_at": event.published_at,
            "note": event.note,
            "fetched_at": event.fetched_at,
            "dropped_reason": None,
            "extracted_at": None,
        }
        existing = await self._rows.get(row_id)
        if existing is None:
            await self._rows.save(CorpusDocumentRow(id=row_id, **fields))
            return
        for name, value in fields.items():
            setattr(existing, name, value)
        await self._rows.save(existing)

    @handles(CorpusDerivedTextStored)
    async def _on_derived_text(self, event: CorpusDerivedTextStored) -> None:
        """Write a transcript into `corpus_documents`, not a new table.

        A derived source *is* a text source -- it chunks, it quotes, it
        extracts -- so every existing text reader has to find it here, not in
        a parallel place that would need its own `get`/`list_all`/extraction
        wiring to match. Load-and-mutate, matching `_on_stored` and
        `_on_media_stored`: the version counter climbs on a re-perception
        rather than resetting.

        **`degradations` is stored as the marker, not as null, when the
        event's own field will not parse.** The two candidates were: null
        the column, or store `UNREADABLE_DEGRADATIONS` (JSON-encoded, since
        the column is JSON text). Null loses the distinction `TextRecord`
        depends on -- its docstring says an *empty* `degradations` means "a
        complete perception", so a NULL that `to_record` decoded as `()`
        would read back as a clean transcript when the truth is that this
        column could not be read at all. Storing the marker instead means
        `to_record` decodes it to the same tuple the aggregate's own
        `_degradations_from` returns for the identical failure in `evolve` --
        one string, one meaning, whichever side reads it, and `to_record`
        reads through the identical `_decode_degradations` check this handler
        writes through, so that parity is enforced by sharing the check
        rather than by two call sites agreeing to write the same logic twice.
        This branch is not reachable through `decide`, which refuses a
        malformed payload before an event is ever written; it exists for the
        same reason `_degradations_from` does, for an event this build did
        not write -- an earlier build, a repair script, or a direct append.
        """
        row_id = CorpusDocumentRow.row_id(event.aggregate_id, event.source_id)
        degradations = (
            event.degradations
            if _decode_degradations(event.degradations) is not None
            else json.dumps(list(UNREADABLE_DEGRADATIONS))
        )
        fields = {
            "project_id": event.aggregate_id,
            "source_id": event.source_id,
            "text": event.text,
            "sha256": event.sha256,
            "char_count": len(event.text),
            "title": event.title,
            "note": event.note,
            "dropped_reason": None,
            "derived_from": event.derived_from,
            "locator_map": event.locator_map,
            "perceived_with": event.perceived_with,
            "degradations": degradations,
            "extracted_at": None,
        }
        existing = await self._rows.get(row_id)
        if existing is None:
            await self._rows.save(CorpusDocumentRow(id=row_id, **fields))
            return
        for name, value in fields.items():
            setattr(existing, name, value)
        await self._rows.save(existing)

    @handles(DocumentExtracted)
    async def _on_extracted(self, event: DocumentExtracted) -> None:
        """Note that this source now has a graph.

        The one handler here fed by a stream the corpus does not own.
        `CorpusRunner` subscribes to the whole store rather than one category,
        and dispatch is by event type, so redstring's own event arrives here
        without any new wiring -- `tenant_id` is the project, which is what
        makes the row addressable.

        **A missing row is skipped rather than raised**, which is the opposite
        of `_on_dropped`'s rule and deliberately so. `_require` treats a
        missing row as drift because the corpus aggregate refuses to drop what
        it does not hold, so the event could not legitimately exist. Nothing
        makes that true here: extraction is a different aggregate, redstring
        will happily extract a document this corpus never stored, and every
        `DocumentExtracted` written before the corpus table existed is exactly
        that. Raising would put ordinary history in the DLQ and report drift
        that is not there.
        """
        row = await self._rows.get(CorpusDocumentRow.row_id(event.tenant_id, event.source_id))
        if row is None:
            return
        row.extracted_at = event.occurred_at.isoformat()
        await self._rows.save(row)

    @handles(CorpusMediaStored)
    async def _on_media_stored(self, event: CorpusMediaStored) -> None:
        """Write the media source, superseding whatever it held before.

        Load-and-mutate, matching `_on_stored`: the version counter keeps
        climbing on a re-store rather than resetting, and `dropped_reason` is
        cleared explicitly for the same reason it is there -- storing asserts
        presence.
        """
        row_id = CorpusMediaRow.row_id(event.aggregate_id, event.source_id)
        fields = {
            "project_id": event.aggregate_id,
            "source_id": event.source_id,
            "sha256": event.sha256,
            "media_type": event.media_type,
            "byte_count": event.byte_count,
            "uri": event.uri,
            "title": event.title,
            "published_at": event.published_at,
            "note": event.note,
            "fetched_at": event.fetched_at,
            "dropped_reason": None,
        }
        existing = await self._media_rows.get(row_id)
        if existing is None:
            await self._media_rows.save(CorpusMediaRow(id=row_id, **fields))
            return
        for name, value in fields.items():
            setattr(existing, name, value)
        await self._media_rows.save(existing)

    @handles(CorpusDocumentDropped)
    async def _on_dropped(self, event: CorpusDocumentDropped) -> None:
        """Mark whichever table holds the id, never both.

        Task 2's kind-collision guard makes an id held in both tables
        impossible -- `decide` refuses a store that would change what an
        existing source id means. A handler that updated both tables
        unconditionally would not merely tolerate that guard being violated,
        it would hide the violation: the drop would "succeed" against a row
        that should not exist, instead of surfacing the id collision as
        drift. Trying the document row first and falling back to the media
        row is the same distinction `_kind_of` makes in the domain, made
        again here because the read side cannot ask the aggregate.
        """
        row_id = CorpusDocumentRow.row_id(event.aggregate_id, event.source_id)
        row = await self._rows.get(row_id)
        if row is not None:
            row.dropped_reason = event.reason
            await self._rows.save(row)
            return
        media_row = await self._require_media(event.aggregate_id, event.source_id)
        media_row.dropped_reason = event.reason
        await self._media_rows.save(media_row)

    async def _require_media(self, project_id: UUID, source_id: str) -> CorpusMediaRow:
        """The media row for a source, which must already exist.

        Reached only once `_on_dropped` has ruled out a document row, so a
        miss here means the id is in neither table: the aggregate rejects
        dropping a source it does not hold, so that cannot come from a
        legitimate stream. Inventing a row would hide exactly the drift worth
        knowing about, matching `_require`'s reasoning for the document side.
        """
        row = await self._media_rows.get(CorpusMediaRow.row_id(project_id, source_id))
        if row is None:
            raise LookupError(f"no corpus row for {source_id!r} in project {project_id}")
        return row
