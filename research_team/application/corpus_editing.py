"""Changing the corpus, in this application's own terms.

`corpus_read.py` is the corpus's read side; this is its write side, and the
same argument shapes both -- a narrow port above, no storage vocabulary, the
project supplied by the instance rather than by the caller.

A service rather than four route bodies for `DocumentExtractor`'s reason: the
web layer has no business assembling a project's `KnowledgePort` (only
`open_graph`'s closure builds one) alongside its corpus repository. It is also
where the awkward part of this feature is paid, in one place with a comment on
it rather than spread across the routes:

**Two paths reach one aggregate, deliberately.** `store` goes through
`KnowledgePort.store_source`, which gives it the length cap, the blank-id
refusal and indexing for free. `revise` and `restore` (task 2) execute
`StoreSourceDocument` on the repository directly. They have to:
`RedstringKnowledge._store_document` skips a store whose text hashes to what
that `source_id` already holds, which is right for its callers -- a second
`remember` of an unchanged page should not append a revision that revised
nothing -- and silently wrong for an edit. Correcting a title without touching
the text is exactly the case that check discards, and it discards it with no
error: `store_source` returns None and the caller would answer 200 over a
document that did not change. `decide` has no such check.

The direct path re-pays two of the three things `store_source` gave `store`
for free, and is honest about the third it does not:

- **The length cap** is not free and is re-paid: `_store` checks
  `MAX_DOCUMENT_CHARS` itself, because `decide` has no opinion on document
  size and `revise(text=<huge>)` would otherwise write exactly the entry
  `store_source`'s own docstring says must never exist.
- **Indexing** is not free and is re-paid: `index` hangs off
  `_store_document`, which is bypassed, so both methods call it themselves.
  An edit that skipped it would leave the chunk corpus quoting text the
  document no longer contains, which is the one failure `corpus_spans.py`
  exists to make impossible.
- **The blank-id refusal** is not free and is *not* re-paid, and does not need
  to be: both methods only ever reach `_store` with a `source_id` read back
  from an existing record, never one supplied fresh by a caller, so there is
  no request shape that could exercise it here. `store`'s own existence check
  is the only place a caller's `source_id` is untrusted.

The alternative was a `force: bool` on `store_source`. It is fewer lines, and
it turns the adapter's most carefully-reasoned guard into a request parameter
every future caller opts out of at will.

**A derived source reaches it on a fourth**, `_store_derived`, and it is
there for the same reason `_store_media` is: `read_document` *does* answer for
a transcript -- a derived source is a text row -- so both methods resolved it
happily and then executed `StoreSourceDocument`, which `decide` refuses
outright for a derived id. The console offers Restore on every dropped text
row, so pressing it on a dropped transcript answered 409 saying the operator
had tried to overwrite a transcript with prose nobody perceived, which is not
what they did. A transcript's title was equally uneditable.

The fix keeps the guard and re-issues the right command: a re-store of a
derived record is `StoreDerivedText` carrying `derived_from`, `locator_map`,
`perceived_with` and `degradations` through unchanged, exactly as "unchanged"
already promises for `fetched_at`. Reading `locator_map` back is what needed
adding -- the column was write-only until this caller existed; see
`StoredDocument.locator_map`.

The one thing `revise` refuses on that path is `text`. Hand-editing a
transcript would make it prose nobody perceived and nobody wrote, which is the
provenance hole the derivedness guard exists to close -- and unlike media it
cannot be left to `decide`, because `StoreDerivedText` with an edited `text`
is a shape the aggregate accepts (it is what a re-perception looks like). So
the refusal is this layer's, and it names re-perceiving as the way to change
a transcript. `DocumentEditForm` withholds the Text field for a derived source
the same way it already does for a media one.

**A media source reaches the aggregate on a third path**, `_store_media`,
which `revise` and `restore` fall to when `read_document` answers `None`.
None of the three things above apply to it -- there is no `store_source` to
bypass, no prose to cap and no text to index -- so it is a bare re-execution
of `StoreSourceMedia` off the stored record. It exists because both methods
resolved only through `read_document`, which promises text, and so answered
404 for every media source while the console offered Restore and Edit.
"""

import json
from collections.abc import AsyncIterator
from uuid import UUID

from eventsource.application.aggregates.repository import AggregateRepository

from research_team.application.blobs import BlobStorePort
from research_team.application.corpus_read import StoredDocument
from research_team.application.document_extraction import (
    CorpusReaders,
    OpenKnowledge,
    UnknownDocument,
)
from research_team.application.knowledge import MAX_DOCUMENT_CHARS, KnowledgeError, SourceRef
from research_team.domain.corpus import (
    Corpus,
    DropSourceDocument,
    MediaRecord,
    StoreDerivedText,
    StoreSourceDocument,
    StoreSourceMedia,
)


class DocumentExists(Exception):
    """The corpus already holds this `source_id`.

    Its own type because the route answers 409 for it and 404 for
    `UnknownDocument`, and "the id is taken" and "the id is unknown" are the
    two halves of the same question asked by different callers.
    """


class NotDropped(Exception):
    """A restore was asked for a document that is not excluded.

    Refused rather than treated as a no-op: a restore that silently does
    nothing is indistinguishable, from the far side of the network, from one
    that worked.
    """


class CorpusEditor:
    """Upload, revise, drop and restore one project's documents."""

    def __init__(
        self,
        open_knowledge: OpenKnowledge,
        readers: CorpusReaders,
        corpus: AggregateRepository[Corpus],
        blobs: BlobStorePort,
    ) -> None:
        self._open_knowledge = open_knowledge
        self._readers = readers
        self._corpus = corpus
        self._blobs = blobs

    async def store(
        self,
        project_id: UUID,
        source_id: str,
        text: str,
        *,
        uri: str | None = None,
        title: str | None = None,
        note: str | None = None,
        published_at: str | None = None,
    ) -> None:
        """Add a document nobody has stored under this id.

        The existence check is this service's and not the aggregate's, because
        the aggregate is right to allow a repeat `source_id` -- that is what a
        revision is. Only *upload* means creation, and only upload can say so.

        It checks `list_sources`, so it refuses an id already held by a *media*
        source too, not only by a document. That widening came with the move
        off `list_documents` and is deliberate: text and media share one
        `source_id` namespace by design, and a check that saw only documents
        would let an upload silently claim an id a video already answers to --
        after which two records would disagree about what that id names, and a
        citation could not say which one it meant. The cost is that "this id
        is taken" no longer implies "by a document"; the error message says
        `the corpus already holds`, which is true of both.
        """
        reader = self._readers(project_id)
        existing = await reader.list_sources(include_dropped=True)
        if any(listing.record.source_id == source_id for listing in existing):
            raise DocumentExists(f"the corpus already holds {source_id!r}")
        knowledge = await self._open_knowledge(project_id)
        await knowledge.store_source(
            SourceRef(
                source_id=source_id,
                text=text,
                uri=uri,
                title=title,
                note=note,
                published_at=published_at,
            )
        )

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

    async def drop(self, project_id: UUID, source_id: str, reason: str) -> None:
        """Exclude a document, keeping its record and its text.

        The blank reason, the unknown source *within a non-empty corpus* and
        the double drop are all the aggregate's refusals and are left to it,
        so there is one implementation of each rule. The one case translated
        here is a corpus with no documents at all, which `decide` reports as
        "corpus is empty" -- true, and not what a caller asking about one
        document needs to hear.

        The pre-check is deliberately "does this corpus hold anything", not
        "does it hold *this* `source_id`": the latter would also catch a
        wrong id against a non-empty corpus and turn it into `UnknownDocument`,
        which collapses the two refusals the aggregate keeps apart -- and a
        test that stores one document and drops a different, missing one is
        what would fail if this checked the specific id instead.
        """
        reader = self._readers(project_id)
        if not await reader.list_sources(include_dropped=True):
            raise UnknownDocument(f"no document {source_id!r} in this corpus")
        corpus = await self._corpus.load_or_create(project_id)
        corpus.execute(DropSourceDocument(source_id=source_id, reason=reason))
        await self._corpus.save(corpus)

    async def revise(
        self,
        project_id: UUID,
        source_id: str,
        *,
        text: str | None = None,
        uri: str | None = None,
        title: str | None = None,
        note: str | None = None,
        published_at: str | None = None,
    ) -> None:
        """Change a stored document's metadata, its text, or both.

        Not through `store_source` -- see the module docstring: that path
        skips a store whose text hashes to what the id already holds, which
        is most edits, and skips it silently.

        `text=None` means "keep what is stored" and is read back from the
        corpus rather than required from the caller. A browser correcting a
        title should not have to round-trip a hundred kilobytes of prose to
        do it, and a caller that had to send the text back is a caller that
        can send back a stale copy of it.

        `read_document(..., include_dropped=True)`: a revise on a dropped
        document is not refused -- the aggregate has no rule against it, and
        forbidding it here would mean choosing between "edit before restore"
        and "restore before edit" for a caller who wants both, for no benefit
        to anyone. Reading with the default `include_dropped=False` would
        report every dropped document as unknown instead of letting that
        stand.

        Carries `stored.record.fetched_at` through unconditionally, the same
        way `uri` and `published_at` are: `StoreSourceDocument.fetched_at`
        defaults to `None`, so a re-store that did not supply it would zero
        it on every field this method touches, not only the ones the caller
        asked to change. A metadata-only title fix would otherwise destroy
        the provenance of by-reference content it never meant to disturb.

        **Media falls to its own branch, and it is not a special case bolted
        on.** `read_document` promises text and answers `None` for a media
        source by design, so resolving only through it made this method 404
        for every video in the corpus while the console offered the form --
        the spec promises patch works on a `source_id` whichever kind it is.
        A media revise is a re-store of the same claim with changed metadata,
        which is exactly what `store_media` already writes and what `evolve`
        already folds; nothing new is needed in the domain.

        `text` is refused rather than ignored for a media source. `decide`'s
        `_kind_of` guard would refuse `StoreSourceDocument` over a media id
        anyway, so a recording cannot become a document either way -- but
        that refusal arrives as a 409 in the aggregate's wording, and
        silently dropping the field would answer 200 over a change that did
        not happen.

        **A derived source takes the same shape and one extra refusal.** Its
        metadata is ordinary -- a transcript's title is as correctable as any
        other source's, and refusing the whole method for a derived id (which
        is what the derivedness guard did before this branch, by accident)
        left a transcript's title permanently wrong. But `text` is refused,
        and here the refusal has to be ours: for media, `decide`'s `_kind_of`
        guard would catch it anyway and this layer only improves the message,
        whereas `StoreDerivedText` with a changed `text` is precisely the
        shape a legitimate re-perception has, so the aggregate cannot tell an
        edit from a reading. Nothing below this line would stop a hand-typed
        paragraph from being stored as something a model perceived.
        """
        reader = self._readers(project_id)
        stored = await reader.read_document(source_id, include_dropped=True)
        if stored is None:
            handle = await reader.read_media(source_id, include_dropped=True)
            if handle is None:
                raise UnknownDocument(f"no document {source_id!r} in this corpus")
            if text is not None:
                raise KnowledgeError(
                    f"{source_id!r} is a media source and has no text to revise"
                )
            await self._store_media(
                project_id,
                handle.record,
                uri=uri,
                title=title,
                note=note,
                published_at=published_at,
            )
            return
        if stored.record.derived_from is not None:
            if text is not None:
                raise KnowledgeError(
                    f"{source_id!r} is a transcript of "
                    f"{stored.record.derived_from!r} and its text cannot be "
                    f"edited; perceive the medium again to change it"
                )
            if uri is not None or published_at is not None:
                # Refused rather than dropped, for the reason the media branch
                # refuses `text`: answering 200 over a field that went nowhere
                # is the worst of the three available answers. A transcript has
                # no `uri` or `published_at` -- see
                # `CorpusDerivedTextStored.note` for why those two are absent
                # from the event while `note` is on it -- so there is nothing
                # here to write them to.
                raise KnowledgeError(
                    f"{source_id!r} is a transcript; it was not fetched from "
                    f"anywhere, so it has no uri or publication date. Those "
                    f"belong to {stored.record.derived_from!r}."
                )
            await self._store_derived(
                project_id,
                stored,
                title=title,
                note=note,
            )
            return
        await self._store(
            project_id,
            SourceRef(
                source_id=source_id,
                text=stored.text if text is None else text,
                uri=stored.record.uri if uri is None else uri,
                title=stored.record.title if title is None else title,
                note=stored.record.note if note is None else note,
                published_at=(
                    stored.record.published_at if published_at is None else published_at
                ),
                fetched_at=stored.record.fetched_at,
            ),
        )

    async def restore(self, project_id: UUID, source_id: str) -> None:
        """Put a dropped document back, unchanged.

        A re-store of the same bytes, which the fold turns into a restore for
        free: `evolve` builds a fresh record on `CorpusDocumentStored` and does
        not carry `dropped_reason` across
        (`test_storing_over_a_dropped_source_id_brings_it_back`). Restore is
        that property's only caller, so a change to `evolve` that started
        preserving the field would silently remove this feature with no test
        going red -- which is exactly why that test exists.

        Reads with `include_dropped=True`: the document being restored is, by
        definition, dropped, and the default read would report it as unknown
        rather than letting `restore` see the text it needs to re-store.

        "Unchanged" includes `fetched_at`: this is a re-store of the whole
        record, and `StoreSourceDocument.fetched_at` defaults to `None`, so
        leaving it out would restore a document with its provenance quietly
        erased -- the opposite of what "unchanged" promises above.

        **A derived source falls to its own branch**, and unlike media it does
        so from *inside* the text path rather than past it: `read_document`
        answers for a transcript, so `stored` is a real `StoredDocument` and
        everything above this point applies unchanged. Only the command
        differs -- `StoreDerivedText` rather than `StoreSourceDocument`, which
        the derivedness guard refuses. Before that branch existed, Restore on
        a dropped transcript answered 409 accusing the operator of overwriting
        a transcript with prose, and the only way back was to pay for the
        model call again.

        **Media falls to its own branch**, for the reason `revise` gives:
        `read_document` answers `None` for a media source, so resolving only
        through it left re-uploading the same bytes as the only way to
        un-drop a recording -- which requires the operator to still have the
        file, in a corpus whose purpose is to *be* the copy of record. The
        media re-store carries `sha256` and `byte_count` from the stored
        record, so it points at the blob that is already there and writes no
        bytes at all.
        """
        reader = self._readers(project_id)
        stored = await reader.read_document(source_id, include_dropped=True)
        if stored is None:
            handle = await reader.read_media(source_id, include_dropped=True)
            if handle is None:
                raise UnknownDocument(f"no document {source_id!r} in this corpus")
            if handle.record.dropped_reason is None:
                raise NotDropped(f"{source_id!r} is not dropped")
            await self._store_media(project_id, handle.record)
            return
        if stored.record.dropped_reason is None:
            raise NotDropped(f"{source_id!r} is not dropped")
        if stored.record.derived_from is not None:
            await self._store_derived(project_id, stored)
            return
        await self._store(
            project_id,
            SourceRef(
                source_id=source_id,
                text=stored.text,
                uri=stored.record.uri,
                title=stored.record.title,
                note=stored.record.note,
                published_at=stored.record.published_at,
                fetched_at=stored.record.fetched_at,
            ),
        )

    async def _store_media(
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

    async def _store_derived(
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

    async def _store(self, project_id: UUID, source: SourceRef) -> None:
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
