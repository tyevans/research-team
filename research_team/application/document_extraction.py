"""Extracting a document the corpus already holds.

`remember` fetches text and extracts it in one call, which is right for an
agent: it has just read something and wants it in the graph. It is wrong for a
person looking at the Documents page, where the text is already stored and the
only thing missing is the graph -- re-fetching to re-extract would go back to
the network for bytes the corpus can already produce, and would fail outright
for a URL that has since gone.

So this reads the stored text and ingests it. `KnowledgePort.ingest` stores
before it extracts, and the corpus swallows a re-store of identical bytes, so
handing back text the corpus already has is a no-op on the corpus and an
extraction on the graph -- which is exactly the operation wanted, without a
second ingest path that could store differently from the first.

A service rather than a route body because it needs two things the web layer
has no business assembling: a project's `KnowledgePort` (which only
`open_graph`'s closure can build) and its `CorpusReadPort`. `AskService` is
the precedent -- a read path that needs the same closure, constructed inside
`build_application` for the same reason.
"""

from collections.abc import Awaitable, Callable
from uuid import UUID

from research_team.application.corpus_read import CorpusReadPort
from research_team.application.knowledge import (
    ExtractionReporter,
    IngestReport,
    KnowledgePort,
    SourceRef,
)

#: Opens one project's `KnowledgePort`. A callable rather than a port because a
#: port belongs to one project and this service serves any of them.
OpenKnowledge = Callable[[UUID], Awaitable[KnowledgePort]]

#: One project's `CorpusReadPort`, built per call. Matches how `app.py` and
#: `composition.py` already hand out corpus readers.
CorpusReaders = Callable[[UUID], CorpusReadPort]

#: One project's `ExtractionReporter`, or None with no web layer listening.
Reporters = Callable[[UUID], ExtractionReporter]


class UnknownDocument(Exception):
    """This project's corpus holds no such `source_id`.

    Its own type rather than `CorpusReadError`, which means storage failed:
    only one of the two is a bug, and a caller that wants to answer 404 needs
    to tell them apart. `read_document` draws the same distinction by
    answering None rather than raising, and this is that None given a name at
    the one call site that cannot proceed without the document.
    """


class DocumentExtractor:
    """Puts a stored document through extraction, into its project's graph."""

    def __init__(
        self,
        *,
        open_knowledge: OpenKnowledge,
        corpus_readers: CorpusReaders,
        reporters: Reporters | None = None,
    ) -> None:
        self._open_knowledge = open_knowledge
        self._corpus_readers = corpus_readers
        self._reporters = reporters

    async def extract(self, project_id: UUID, source_id: str) -> IngestReport:
        """Extract one stored document. Raises `UnknownDocument` if it is not there.

        The document is read *here* rather than inside whatever defers this
        call, so a bad `source_id` surfaces to the caller that can still answer
        for it. Deferred, it would fail asynchronously and show up as a failure
        against a document that does not exist -- which is to say, nowhere.

        Every field the record carries is passed back through, so the re-stored
        document keeps the title, URI and dates the original fetch established.
        Rebuilding a `SourceRef` from the text alone would silently strip the
        provenance that makes a citation checkable.

        `fetched_at` is deliberately not set: it means "when this text was read
        off the network", and that was some earlier fetch, not this call.
        Stamping it now would date the bytes to the moment somebody pressed a
        button.
        """
        stored = await self._corpus_readers(project_id).read_document(source_id)
        if stored is None:
            raise UnknownDocument(f"no document {source_id!r} in project {project_id}")

        knowledge = await self._open_knowledge(project_id)
        record = stored.record
        return await knowledge.ingest(
            SourceRef(
                source_id=record.source_id,
                text=stored.text,
                note=record.note,
                uri=record.uri,
                title=record.title,
                published_at=record.published_at,
            ),
            report=self._reporters(project_id) if self._reporters is not None else None,
        )

    async def unextracted(self, project_id: UUID) -> tuple[str, ...]:
        """Every live document with no graph, in listing order.

        Dropped documents are excluded because `list_documents` excludes them
        by default, and that default is the right one here: a drop is a
        judgement that the document should not inform the project, and
        extracting it would put it into the graph the drop was meant to keep
        it out of.

        Order is the listing's, so "extract all" runs the queue in the order
        the page shows -- a progress pane that jumped around a list the reader
        is looking at would be harder to follow than one that walks it.
        """
        listings = await self._corpus_readers(project_id).list_documents()
        return tuple(listing.record.source_id for listing in listings if not listing.extracted)

    async def reindex(self, project_id: UUID) -> int:
        """Put every stored document back through chunk indexing. No model call.

        **Why this exists at all:** `index` is called from exactly one place,
        the store-a-document path, and nothing backfills. A corpus written
        before chunk indexing shipped has no `DocumentChunked` for the replay
        to fold, so its chunk store comes up empty -- and an empty chunk store
        is not an error anywhere: retrieval simply returns nothing and the
        entity panel says "No mentions of this entity were found", which reads
        exactly like the truthful answer for an entity nobody wrote about.
        That is the wrong-answer-indistinguishable-from-a-right-one failure
        this feature's design names by name, so it needs a remedy an operator
        can reach rather than a note telling them to re-store every document.

        **Why a plain loop and not a queue.** `index` makes no model call
        (`RedstringKnowledge.index` passes no embeddings, and says so), so
        there is no per-token cost to defer and nothing worth making durable;
        the queue and progress channel that extraction needs would be
        machinery bought for a pass whose only cost is chunking bytes already
        in memory. The cost that is real: this is synchronous, so a very large
        corpus holds its request open. Accepted -- it is a repair an operator
        runs deliberately, not a control on a page.

        Returns how many documents were indexed rather than how many chunks
        were written: `index` is idempotent through the adapter's event store
        (an unchanged document is skipped there), so a chunk count would read
        as 0 on a healthy second run and look like a failure.

        Dropped documents are excluded, for `unextracted`'s reason: a drop is
        a judgement that the document should not inform the project, and its
        passages would be quoted back to a reader if they were indexed.
        """
        knowledge = await self._open_knowledge(project_id)
        reader = self._corpus_readers(project_id)
        indexed = 0
        for listing in await reader.list_documents():
            stored = await reader.read_document(listing.record.source_id)
            if stored is None:
                # Dropped or removed between the listing and this read. Not an
                # error: the listing is a read model and this is a repair.
                continue
            record = stored.record
            await knowledge.index(
                SourceRef(
                    source_id=record.source_id,
                    text=stored.text,
                    note=record.note,
                    uri=record.uri,
                    title=record.title,
                    published_at=record.published_at,
                )
            )
            indexed += 1
        return indexed
