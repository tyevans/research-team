"""Direct aggregate writes and index synchronization for the corpus.

Handles the direct execution paths to the `Corpus` aggregate for documents,
media, and derived text (transcripts), bypassing `store_source`'s hash check
so that revisions and metadata edits succeed without silent discards.
"""

import json
from collections.abc import AsyncIterator
from uuid import UUID

from eventsource.application.aggregates.repository import AggregateRepository

from research_team.knowledge.application.knowledge import (
    MAX_DOCUMENT_CHARS,
    KnowledgeError,
    SourceRef,
)
from research_team.platform.shared.blobs import BlobStorePort
from research_team.research.application.corpus_read import StoredDocument
from research_team.research.application.document_extraction import (
    OpenKnowledge,
)
from research_team.research.domain.corpus import (
    Corpus,
    MediaRecord,
    StoreDerivedText,
    StoreSourceDocument,
    StoreSourceMedia,
)

__all__ = ["CorpusStorageWriter"]


class CorpusStorageWriter:
    """Direct aggregate writer for text documents, media records, and transcripts."""

    def __init__(
        self,
        open_knowledge: OpenKnowledge,
        corpus: AggregateRepository[Corpus],
        blobs: BlobStorePort,
    ) -> None:
        self._open_knowledge = open_knowledge
        self._corpus = corpus
        self._blobs = blobs

    async def store_media(
        self,
        project_id: UUID,
        source_id: str,
        stream: AsyncIterator[bytes],
        media_type: str,
        *,
        uri: str | None = None,
        title: str | None = None,
        note: str | None = None,
        published_at: str | None = None,
        fetched_at: str | None = None,
    ) -> MediaRecord:
        """Stream the bytes to the blob store, then record the claim.

        Bytes first, deliberately: a rejected command then leaves an
        unreferenced blob, which content addressing makes harmless -- the next
        store of the same bytes adopts it. The other order would commit a
        record whose bytes are not there, and a dangling reference is the one
        failure this design promised to make loud rather than merely rare.
        Cheap failure (an orphan blob) over expensive one (a record pointing
        at nothing). `test_a_rejected_store_leaves_the_blob_and_no_record` is
        what holds the order -- measured, not assumed: reordering the two
        writes fails that test and only that test, because the blob exists at
        the end of a *successful* store either way.

        The orphan that leaves behind is now reclaimable, and only by hand:
        `infrastructure/persistence/blob_sweep.py` is an operator-run
        mark-and-sweep, reporting by default and deleting only under
        `--remove`. It is deliberately on no timer, because the two writes
        below are not one transaction -- see B85 and that module's docstring
        for the grace period that stands in for the transaction there is not.

        Takes no `sha256`. That absence is the whole mitigation for the domain
        accepting a digest it did not compute; see `application/blobs.py`.
        `test_store_media_takes_no_digest_from_its_caller` asserts the
        signature directly, because it is the signature -- not this
        docstring -- that keeps the claim true.

        No existence check against text the way `store` has one: `decide`
        already refuses `StoreSourceMedia` for a `source_id` a text record
        holds (`corpus.py`'s `_kind_of` guard), and that refusal is the
        aggregate's exactly as `drop`'s refusals are -- duplicating it here
        would risk drifting from it, the same reasoning `store`'s own
        docstring gives for leaving the blank-id and double-drop checks to
        `decide`. A media `source_id` repeat is not creation the way a text
        upload is, so there is no "upload means creation" rule to re-pay here.
        """
        stat = await self._blobs.put(stream)
        corpus = await self._corpus.load_or_create(project_id)
        corpus.execute(
            StoreSourceMedia(
                corpus_id=project_id,
                source_id=source_id,
                sha256=stat.sha256,
                media_type=media_type,
                byte_count=stat.byte_count,
                uri=uri,
                title=title,
                published_at=published_at,
                note=note,
                fetched_at=fetched_at,
            )
        )
        await self._corpus.save(corpus)
        record = corpus.state.documents[source_id]
        # Narrowing, not a check: `decide` refuses this command outright when
        # the id holds text, so the only record it can have written here is a
        # MediaRecord. The assert is what tells the type checker that.
        assert isinstance(record, MediaRecord)
        return record

    async def store_media_record(
        self,
        project_id: UUID,
        record: MediaRecord,
        *,
        uri: str | None = None,
        title: str | None = None,
        note: str | None = None,
        published_at: str | None = None,
    ) -> None:
        """Re-store a media claim over itself, with `None` meaning "keep".

        The whole of restore and the metadata half of revise, because for
        media they are the same write: a second `StoreSourceMedia` under one
        `source_id` supersedes the record, and `evolve` builds a fresh one
        that does not carry `dropped_reason` across. Restore is that with
        nothing changed; revise is that with a field or two replaced.

        No blob work, deliberately. `sha256`, `media_type` and `byte_count`
        come off the stored record, so this re-points at the bytes that are
        already there -- an edit that re-derived any of them would need the
        bytes in hand, and a metadata fix has no business reading a
        two-gigabyte file.

        Nothing here re-pays what `_store` re-pays: `MAX_DOCUMENT_CHARS` is a
        cap on prose and there is none, and `index` hangs off the text the
        chunk store quotes, which media has none of. When something does
        extract media, this is where that call would have to be added.
        """
        corpus = await self._corpus.load_or_create(project_id)
        corpus.execute(
            StoreSourceMedia(
                corpus_id=project_id,
                source_id=record.source_id,
                sha256=record.sha256,
                media_type=record.media_type,
                byte_count=record.byte_count,
                uri=record.uri if uri is None else uri,
                title=record.title if title is None else title,
                note=record.note if note is None else note,
                published_at=(record.published_at if published_at is None else published_at),
                fetched_at=record.fetched_at,
            )
        )
        await self._corpus.save(corpus)

    async def store_derived_text(
        self,
        project_id: UUID,
        stored: StoredDocument,
        *,
        title: str | None = None,
        note: str | None = None,
    ) -> None:
        """Re-store a transcript over itself, with `None` meaning "keep".

        `_store_media`'s shape for the same two callers, and `_store`'s
        obligations minus one. Restore is this with nothing changed; the
        metadata half of revise is this with a field replaced.

        **The perception fields are carried, not defaulted.** `derived_from`,
        `locator_map`, `perceived_with` and `degradations` all come off the
        stored record, exactly as `fetched_at` is carried on the fetched-
        document path and for the identical reason: `StoreDerivedText` has no
        way to say "leave this alone", so a re-store that omitted one would
        zero a transcript's provenance as the side effect of correcting its
        title. `derived_from` in particular cannot be re-derived from anything
        here, and `decide` refuses a re-store that changes it -- so getting it
        wrong is a 409 rather than silent damage, which is the good case.

        **`text` is never a parameter.** A derived source's text is what a
        model perceived; the only thing entitled to replace it is another
        perception. `revise` refuses a caller's `text` before reaching here,
        and this signature is what keeps that refusal from being one `if` away
        from being bypassed.

        **No `MAX_DOCUMENT_CHARS` check, unlike `_store`, and this is the one
        place the two paths deliberately differ.** `MediaPerceiver` does not
        enforce the cap on the way in (B93), so a transcript longer than it can
        already be stored -- and a restore that checked the cap would refuse to
        put back a transcript this system itself wrote, which is a worse dead
        end than the one this branch exists to fix. The cap belongs where the
        text is *produced*; adding it here would only make an existing row
        unrestorable.

        `index` *is* re-paid, exactly as `_store` re-pays it: the chunk store
        quotes this text like any other document's, and a restore that skipped
        it would leave `corpus_spans.quote` unable to find a transcript that is
        back in the corpus.
        """
        record = stored.record
        corpus = await self._corpus.load_or_create(project_id)
        corpus.execute(
            StoreDerivedText(
                corpus_id=project_id,
                source_id=record.source_id,
                # Narrowing for the type checker, not a check: this method's
                # two callers both test `derived_from is not None` first, and
                # `decide` would refuse a `StoreDerivedText` that tried to make
                # a non-derived row derived anyway.
                derived_from=record.derived_from or "",
                text=stored.text,
                # `or` and not `is None`, and the fallbacks are load-bearing
                # rather than defensive. Both fields are non-null on every row
                # this build writes; a row from an earlier build -- one stored
                # before `locator_map` had a column, or repaired by hand -- can
                # still be missing them, and `StoreDerivedText` types both as
                # required `str`. Refusing the restore in that case would make
                # exactly the permanent dead end this method exists to remove,
                # for a transcript whose text is intact. So the fallbacks are
                # the empty map and the empty fingerprint: a locator that
                # resolves to nothing and a reading that names no model, both
                # of which are *true* of a row that never recorded either.
                locator_map=stored.locator_map or "[]",
                perceived_with=record.perceived_with or "",
                degradations=json.dumps(list(record.degradations)),
                title=record.title if title is None else title,
                note=record.note if note is None else note,
            )
        )
        await self._corpus.save(corpus)
        knowledge = await self._open_knowledge(project_id)
        await knowledge.index(
            SourceRef(
                source_id=record.source_id,
                text=stored.text,
                title=record.title if title is None else title,
                note=record.note if note is None else note,
            )
        )

    async def store_source_document(self, project_id: UUID, source: SourceRef) -> None:
        """The direct path: the length cap, then command, then index.

        All three are required and none is optional for a caller. The cap
        check has no local evidence if it is skipped -- see the module
        docstring's accounting of what this path re-pays. The index call is
        the same: the corpus is correct without it and the chunk store is
        not, so it lives here rather than at the two call sites, where one of
        them would eventually be written without it.

        **No `with_retry` here, where `_store_document` has one.** That retry
        exists for two `remember` calls racing in the same assistant turn --
        concurrent by construction, and common enough to need a retry rather
        than a raised `OptimisticLockError`. `revise` and `restore` are
        browser-driven edits to one document; two of them landing on the same
        `source_id` in the same instant is not a case this feature has to
        absorb, and `drop` above takes the same single-attempt shape for the
        same reason.
        """
        if len(source.text) > MAX_DOCUMENT_CHARS:
            # Mirrors `store_source`'s own check (`redstring_adapter.py`):
            # `decide` has no opinion on document size, so nothing upstream of
            # this call refuses an oversized `revise`, and a document over the
            # cap can never be extracted later -- see `MAX_DOCUMENT_CHARS`'s
            # docstring in `knowledge.py` for why the constant lives there.
            raise KnowledgeError(
                f"that is {len(source.text)} characters; the limit is "
                f"{MAX_DOCUMENT_CHARS}. Record it in parts, each with its own "
                f"source_id."
            )
        corpus = await self._corpus.load_or_create(project_id)
        corpus.execute(
            StoreSourceDocument(
                corpus_id=project_id,
                source_id=source.source_id,
                text=source.text,
                uri=source.uri,
                title=source.title,
                published_at=source.published_at,
                note=source.note,
                fetched_at=source.fetched_at,
            )
        )
        await self._corpus.save(corpus)
        knowledge = await self._open_knowledge(project_id)
        await knowledge.index(source)
