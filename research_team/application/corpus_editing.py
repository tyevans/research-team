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
"""

from uuid import UUID

from eventsource.application.aggregates.repository import AggregateRepository

from research_team.application.document_extraction import (
    CorpusReaders,
    OpenKnowledge,
    UnknownDocument,
)
from research_team.application.knowledge import MAX_DOCUMENT_CHARS, KnowledgeError, SourceRef
from research_team.domain.corpus import Corpus, DropSourceDocument, StoreSourceDocument


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
    ) -> None:
        self._open_knowledge = open_knowledge
        self._readers = readers
        self._corpus = corpus

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
        """
        reader = self._readers(project_id)
        stored = await reader.read_document(source_id, include_dropped=True)
        if stored is None:
            raise UnknownDocument(f"no document {source_id!r} in this corpus")
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
        """
        reader = self._readers(project_id)
        stored = await reader.read_document(source_id, include_dropped=True)
        if stored is None:
            raise UnknownDocument(f"no document {source_id!r} in this corpus")
        if stored.record.dropped_reason is None:
            raise NotDropped(f"{source_id!r} is not dropped")
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
