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

The cost of taking the direct path is that indexing does not come with it --
`index` hangs off `_store_document`, which is bypassed -- so both methods call
it themselves. An edit that skipped it would leave the chunk corpus quoting
text the document no longer contains, which is the one failure
`corpus_spans.py` exists to make impossible.

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
from research_team.application.knowledge import SourceRef
from research_team.domain.corpus import Corpus, DropSourceDocument


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
        existing = await reader.list_documents(include_dropped=True)
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
        if not await reader.list_documents(include_dropped=True):
            raise UnknownDocument(f"no document {source_id!r} in this corpus")
        corpus = await self._corpus.load_or_create(project_id)
        corpus.execute(DropSourceDocument(source_id=source_id, reason=reason))
        await self._corpus.save(corpus)
