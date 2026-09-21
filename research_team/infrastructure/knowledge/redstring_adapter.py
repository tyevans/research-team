"""The one module that imports redstring.

Everything above this speaks `KnowledgePort`'s vocabulary, which is why the
redstring names stop here.

Two things about redstring's shape drive the code below, and both are easy to
get wrong:

1. **`build_graph` folds into the store and returns the event unappended.**
   That is exactly what a caller with an event log wants -- append it and the
   store and the log agree. Driving `ExtractionPipeline` by hand would work but
   loses `domain` and `domain_confidence`, recovering which means a dotted
   import of an internal classifier.

2. **`Consolidator.resolve` appends *and* folds its own merge event.** It is
   handed the shared event store at construction. Appending `EntitiesMerged`
   here as well would apply the merge twice.
"""

import hashlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from eventsource import collect
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.domain.tenant_context import tenant_scope
from eventsource.ports.snapshots import SnapshotStore
from eventsource.ports.store import AggregateStore
from redstring import (
    Adjudicator,
    Chunker,
    ChunkStore,
    Consolidator,
    EmbeddingProvider,
    GraphStore,
    LlmProvider,
    RedstringError,
    SlidingWindowChunker,
    SourceDocument,
    VectorStore,
    build_graph,
    document_stream,
    index_documents,
)
from redstring.events.document import DocumentChunked

from research_team.application.knowledge import (
    MAX_DOCUMENT_CHARS,
    ExtractionReporter,
    IngestReport,
    KnowledgeError,
    MergeRecord,
    SearchOutcome,
    SourceRef,
)
from research_team.application.retry import with_retry
from research_team.domain import Corpus, EntityJudgements, StoreSourceDocument
from research_team.infrastructure.config import DEFAULT_CONSOLIDATION_BATCH
from research_team.infrastructure.knowledge.co_mentions import CoMentionIndex
from research_team.infrastructure.knowledge.domain_schemas import (
    RESEARCH_CORPUS,
    resolve_domain,
)
from research_team.infrastructure.knowledge.entity_cards import index_cards
from research_team.infrastructure.knowledge.markdown_table_chunker import MarkdownTableChunker
from research_team.infrastructure.knowledge.rebuild import (
    CoMentionProjection,
    carries_entity_links,
)
from research_team.infrastructure.knowledge.redstring_consolidation import (
    ConsolidationPipeline,
)
from research_team.infrastructure.knowledge.redstring_embeddings import (
    EmbeddingCoordinator,
)
from research_team.infrastructure.knowledge.redstring_providers import (
    _CountingProvider,
    _DatingProvider,
    _no_announcement,
    _parse_published_at,
    _reporting,
    _with_respelled_dates,
)
from research_team.infrastructure.knowledge.redstring_query import (
    describe_entities,
    search_entities,
)
from research_team.infrastructure.knowledge.temporal_expressions import (
    RAW_TEMPORAL_PROPERTY,
)

#: Re-exported: written here, defined next to the normalisation it compensates
#: for, and read by `temporal_rendering.py`. Named in `__all__`-less code, so
#: this assignment is what stops a linter calling the import unused.
_ = (RAW_TEMPORAL_PROPERTY, _with_respelled_dates)

logger = logging.getLogger(__name__)


#: Why there is no `low=` override here any more.
#:
#: PR #84 added `low=EXACT_NAME_SCORE` (0.7143) because a cross-document
#: duplicate scored `name = 1.0`, `graph = 0.0` and nothing else, landing below
#: redstring's `LOW_SIMILARITY` of 0.75 -- dropped before the adjudicator was
#: ever offered it. PR #87 kept the override on redstring 0.5.0, correctly: the
#: id-namespacing artefact 0.5.0 fixed was only one of the two ways that pair
#: reaches `graph = 0.0`, and the other is honest. Two documents can name the
#: same thing while describing different neighbourhoods, and then 0.0 is a true
#: statement rather than an artefact.
#:
#: The embedding channel is what makes the override unnecessary rather than
#: merely narrower. That same pair now scores **0.8000** and clears 0.75 on its
#: own evidence, so the threshold is redstring's again and this module no
#: longer has an opinion about it.
#:
#: Two things that did *not* improve, recorded here because a reader will
#: assume both did. Discrimination is unchanged: redstring embeds `entity.name`
#: and nothing else, so under a real model an exact duplicate and
#: `University of York` / `University of Cork` land about 0.011 apart, and both
#: are adjudicated. And auto-merge is still unreachable across documents -- a
#: perfect name and a perfect embedding cap at 0.8 against `graph = 0.0`,
#: below `HIGH_SIMILARITY` 0.92 -- so **every cross-document duplicate costs one
#: adjudicator call**. `test_embedded_consolidation.py` pins all three facts.


class RedstringKnowledge:
    """`KnowledgePort` over redstring, scoped to one project.

    The project id is the tenant. It is supplied once here rather than per
    call, so nothing above can write into another project's graph.
    """

    def __init__(
        self,
        project_id: UUID,
        *,
        store: GraphStore,
        event_store: AggregateStore,
        snapshot_store: SnapshotStore,
        provider: LlmProvider,
        corpus: AggregateRepository[Corpus],
        # This project's own schema rather than `auto`, matching what the
        # composition root passes. A directly-constructed adapter -- which is
        # every one in the suite -- extracted with a different prompt than the
        # application until this moved, and `auto` additionally spent a
        # classifier call per document to reach a fallback we now skip.
        domain: str = RESEARCH_CORPUS,
        adjudicate: bool = True,
        embeddings: EmbeddingProvider | None = None,
        vector_store: VectorStore | None = None,
        card_vector_store: VectorStore | None = None,
        concurrency: int = 1,
        consolidation_batch: int = DEFAULT_CONSOLIDATION_BATCH,
        chunker: Chunker | None = None,
        chunks: ChunkStore | None = None,
        cards: ChunkStore | None = None,
        co_mentions: CoMentionIndex | None = None,
        judgements: AggregateRepository[EntityJudgements] | None = None,
    ) -> None:
        self._project_id = project_id
        self._store = store
        self._event_store = event_store
        self._provider = provider
        # None means chunking is off (`AGENT_CHUNK_STORE=none`), matching
        # `ProjectGraphs.chunks`'s own None-when-off shape -- `index` degrades
        # to a no-op rather than every call site having to know whether the
        # feature is configured before it can store a document at all.
        self._chunks = chunks
        #: The entity-card corpus for this project, or None when cards are off.
        #: A different store from `_chunks` on purpose -- see `ProjectGraphs`
        #: for why the separation is structural rather than a convention.
        self._cards = cards
        #: Which entities each passage named, folded from the *extraction*
        #: chunking. Not a chunk store and not a corpus: three fields per
        #: passage, because that is all `CoMentionPort`'s only reader asks for.
        #: See `infrastructure/knowledge/co_mentions.py`. `None` when the
        #: channel is off, and then this ingest still puts the links on the log
        #: -- `build_graph` records the chunking whenever it has an event store
        #: -- so turning it on is a project open away rather than a re-ingest.
        self._co_mentions = co_mentions
        # Both default to redstring's own serial behaviour rather than to the
        # configured values, so a test constructing this directly gets the
        # deterministic pipeline unless it asks otherwise. The composition
        # root is the one place that reads `config`, and it passes both.
        self._concurrency = concurrency
        # **Deliberately not defaulted to 1.** Every other knob here defaults
        # to redstring's serial behaviour so a directly-constructed adapter --
        # which is every one in the suite -- gets the deterministic pipeline
        # unless it asks otherwise. This one does not, because `resolve_many`
        # at a batch of 1 is not the old per-entity loop: it re-resolves
        # through `_still_mergeable` in a phase the loop had no equivalent of.
        # A default of 1 would leave the whole suite exercising a path
        # production never takes, which is worse than the determinism it buys.
        self._consolidation_batch = consolidation_batch
        self._chunker = chunker
        # Required rather than optional. "After `remember`, the text still
        # exists" is a guarantee, and an optional collaborator that silently
        # no-ops when a composition root forgets it is a guarantee only until
        # someone forgets. There are few construction sites and they all have
        # a repository to hand.
        self._corpus = corpus
        # Optional, and the default is what keeps every existing construction
        # site honest: with no repository there is no finder, `resolve` falls
        # back to its own, and consolidation is byte-identical to before this
        # existed. The repository rather than a snapshot of its state, because
        # `reconsolidate` is a separate entry point that must see judgements
        # made since the last ingest.
        self._judgements = judgements
        # Resolved here rather than in the composition root so that every
        # construction site gets it -- tests build this adapter directly, and a
        # translation living only in `composition.py` would mean the suite
        # extracted with a different prompt than the application does.
        #
        # Eager, in `__init__`, so a bad id raises at construction. Deferring
        # it to `ingest` would surface a typo as a failure partway through a
        # document that has already been stored.
        self._domain = resolve_domain(domain)
        # Both stores, deliberately. With either omitted the consolidator
        # substitutes an in-memory log and `undo` becomes session-only --
        # silently, which is why `remembers_merges_across_restarts` is asserted
        # in the tests rather than assumed here.
        # Both or neither. A vector store with no provider is never written
        # to and scores every pair with the embedding feature absent while
        # costing a lookup per candidate; a provider with no store has nowhere
        # to put what it computes. Either half alone is a configuration that
        # looks enabled and behaves disabled, so the pair is collapsed to one
        # fact here rather than left for `build_graph` to half-honour.
        self._embeddings = embeddings if vector_store is not None else None
        self._vectors = vector_store if embeddings is not None else None
        #: Where entity-*card* embeddings land, as opposed to redstring's
        #: name embeddings in `_vectors`. Gated on the same provider: a card
        #: store with nothing to embed with is never written to.
        self._card_vectors = card_vector_store if embeddings is not None else None
        #: Coordinates vector stores and probing. Probed lazily on first ingest.
        self._embedding_coordinator = EmbeddingCoordinator(
            embeddings=self._embeddings,
            vectors=self._vectors,
            card_vectors=self._card_vectors,
            event_store=event_store,
            store=store,
            project_id=self._project_id,
        )
        self._consolidator = Consolidator(
            store,
            event_store=event_store,
            snapshot_store=snapshot_store,
            vector_store=self._vectors,
        )
        # Without an adjudicator the middle similarity band is rejected rather
        # than merged. That band is where cross-document duplicates live and
        # where they stay: three-feature scoring caps such a pair at 0.8,
        # below `HIGH_SIMILARITY` 0.92, so the adjudicator is the only thing
        # that can merge one. Embeddings did not reduce how much the model's
        # judgement is worth here -- they increased how often it is asked.
        self._adjudicator = Adjudicator(provider) if adjudicate else None

    @property
    def graph_store(self) -> GraphStore:
        """The store this project's graph lives in, for the rebuild-at-start path."""
        return self._store

    @property
    def event_store(self) -> AggregateStore:
        """The log to rebuild the graph from, for the rebuild-at-start path."""
        return self._event_store

    @property
    def project_id(self) -> UUID:
        """The tenant this instance is scoped to."""
        return self._project_id

    async def ingest(
        self, source: SourceRef, *, report: ExtractionReporter | None = None
    ) -> IngestReport:
        """Store, extract, consolidate -- and say where it has got to.

        The announcements are the only reason this method's shape changed. An
        ingest runs for minutes and used to report nothing until it returned,
        which makes a slow model and a hung one look identical from outside.

        `announce` is built **after** the blank-id check and **before** the
        length check, which is the one ordering that works: a blank `source_id`
        has no identity to attribute a note to, so that failure is silent,
        while an oversized document does have one and its `failed` note is what
        closes a pane that has already been opened.
        """
        if not source.source_id.strip():
            raise KnowledgeError("source_id must not be blank; it identifies the document")

        announce = _reporting(report, source.source_id)
        if len(source.text) > MAX_DOCUMENT_CHARS:
            # Capped rather than chunked-without-limit. redstring chunks a long
            # document, which multiplies model calls rather than bounding them,
            # so the bound has to come from here.
            detail = (
                f"that is {len(source.text)} characters; the limit is "
                f"{MAX_DOCUMENT_CHARS}. Record it in parts, each with its own "
                f"source_id."
            )
            announce("failed", detail=detail)
            raise KnowledgeError(detail)

        metadata: dict[str, Any] = {}
        if source.note:
            metadata["note"] = source.note
        published_at = _parse_published_at(source.published_at)
        if source.published_at and published_at is None:
            metadata["published_at"] = source.published_at

        document = SourceDocument(
            id=source.source_id,
            text=source.text,
            uri=source.uri,
            title=source.title,
            published_at=published_at,
            metadata=metadata,
        )
        # Snapshotted **before** `_store_document`, which calls `index` and so
        # can itself record a chunking. What is wanted is "did anything chunk
        # this document afresh during this ingest", and both write paths count:
        # a re-`index` of changed bytes is as good a signal that the text moved
        # as a re-extraction would be.
        before = await self._chunking_signatures(source.source_id)
        await self._store_document(source)
        announce("storing")
        # `built`, not `report` -- the parameter owns that name now, and the
        # protocol fixed it, so the local is the one that moves.
        try:
            announce("extracting")
            # The adjudicator was handed the raw provider in `__init__`, so its
            # calls do not flow through this wrapper and are not counted. That
            # is acceptable: adjudication is per-merge and each merge already
            # has its own `consolidating` note, so nothing goes unreported --
            # only the model-call tally understates by those calls.
            wrapped = _DatingProvider(
                _CountingProvider(
                    self._provider, lambda calls: announce("extracting", model_calls=calls)
                )
            )
            async with tenant_scope(self._project_id):
                built = await build_graph(
                    document,
                    provider=wrapped,
                    store=self._store,
                    tenant_id=self._project_id,
                    domain=self._domain,
                    # **No `embedding_provider=`/`vector_store=`, deliberately.**
                    # redstring embeds inside `build_graph` and, with an event
                    # store, appends the `EntitiesEmbedded` itself -- which
                    # this adapter would then have to either duplicate or
                    # defer to, and both were tried. Owning the write here
                    # instead buys three things that the deferral does not:
                    # the two embedding channels become one method with one
                    # failure policy, an endpoint that dies mid-ingest costs
                    # the vectors rather than the extraction (`build_graph`
                    # raising there discards a document already folded into
                    # the graph -- see `_record_embeddings`), and the text
                    # being embedded is this repository's decision on both
                    # channels rather than redstring's on one of them.
                    #
                    # Both must be absent together or `_check_embedding_wiring`
                    # raises; both absent is redstring's own default.
                    # Chunks go out in batches of `concurrency` and carryover
                    # folds back in *chunk* order rather than completion
                    # order, so this stays reproducible: the same document
                    # twice gives the same graph regardless of which call
                    # returned first. That is redstring's guarantee, not one
                    # this adapter arranges, and it is the reason the knob is
                    # passed here rather than kept behind a flag.
                    concurrency=self._concurrency,
                    chunker=self._chunker,
                    # **Required, and no `chunks=` beside it.** Without an
                    # event store `_persist` is a no-op, so the
                    # `DocumentChunked` the aggregate builds is discarded
                    # inside the library and `GraphBuildReport` exposes only a
                    # count -- the entity links are computed on every ingest
                    # and thrown away, which is exactly the state
                    # `docs/design/co-mention-channel-findings.md` measured.
                    #
                    # With one, the event reaches the log **whether or not
                    # `chunks=` is given**: `record_chunking` runs
                    # unconditionally on the aggregate and only the write into
                    # a `ChunkStore` is gated. That is `build_graph`'s own
                    # docstring and it is why there is no second chunk store
                    # here; `infrastructure/knowledge/co_mentions.py` records
                    # what building one would have cost.
                    #
                    # It also moves the append of `built.event` in here, and
                    # makes `built.event is None` reachable: the aggregate is
                    # loaded from the log, so `record_extraction` refuses a
                    # second extraction of one document under one model
                    # version. That refusal keys on the model version **alone**
                    # -- not on the text -- which is why the branch below has
                    # to tell an unchanged document from a changed one itself.
                    event_store=self._event_store,
                )
                # Read back rather than returned: without `chunks=`,
                # `GraphBuildReport` carries no chunk event, and the live
                # co-mention index would otherwise hold nothing until the next
                # project open -- an ingest's own curriculum would not see its
                # own passages. The card-vector channel takes the same shape
                # for the same reason (`_record_embeddings` writes the store as
                # well as the log).
                chunking = await self._chunking_recorded_now(source.source_id, before)
                if built.event is None:
                    # `Document.record_extraction` refused: this document has
                    # already been extracted under this model version. Now
                    # reachable, where before this adapter passed
                    # `event_store=` the aggregate was fresh on every call and
                    # this branch was dead.
                    #
                    # **Two cases hide in here and only one of them is fine.**
                    # The refusal keys on the model version alone, not on the
                    # text, so a document whose content has changed since it
                    # was extracted also lands here. Reporting zero for that is
                    # the failure this repository is most insistent about: the
                    # corpus records the new revision (`_store_document` ran
                    # above) while the graph goes on describing the old one,
                    # and nothing says so.
                    #
                    # A new chunking signature is the tell, and it is free --
                    # `record_chunking` keys on
                    # `f"{chunker_type}:{digest}:{model_version}"`, so the
                    # aggregate refuses a repeat and emits for new bytes. If
                    # anything chunked this document afresh during *this* call
                    # while extraction refused, the text is new.
                    if chunking.signatures:
                        detail = (
                            f"{source.source_id!r} has already been extracted "
                            f"under this model and its text has changed since; "
                            f"redstring keys extraction on the model version "
                            f"alone, so re-extracting it needs a new source_id "
                            f"or a cleared project. The new text has been "
                            f"stored either way."
                        )
                        announce("failed", detail=detail)
                        raise KnowledgeError(detail)
                    # Still announced through to `consolidated`: a pane opened
                    # on a re-ingest would otherwise hang with no closing note.
                    announce(
                        "extracted",
                        entities=0,
                        relationships=0,
                        domain=built.domain,
                        domain_confidence=built.domain_confidence,
                    )
                    announce("consolidated", entities=0, relationships=0)
                    return IngestReport(
                        source_id=source.source_id,
                        entity_count=0,
                        relationship_count=0,
                        domain=built.domain,
                        domain_confidence=built.domain_confidence,
                    )

                announce(
                    "extracted",
                    entities=len(built.event.entities),
                    relationships=len(built.event.relationships),
                    domain=built.domain,
                    domain_confidence=built.domain_confidence,
                )
                # `built.event` is **not** appended here. `build_graph` was
                # given this event store, so its own repository saved the
                # aggregate -- extraction, chunking and the document-channel
                # embeddings in one `save`. Appending again would put a second
                # `DocumentExtracted` on the log, which `GraphProjection`
                # applies twice: idempotent on upserts and not on anything that
                # counts.
                #
                # Before consolidation. Before,
                # because `_consolidate` scores with the vector store and the
                # card pass reads the graph `build_graph` has just written --
                # and after, because an embedding failure must not cost the
                # extraction that is already folded into the store.
                await self._apply_co_mentions(chunking.event)
                await self._record_embeddings(built.event.entities, source_id=source.source_id)
                merges, failures = await self._consolidate(
                    built.event.entities, announce=announce
                )
        except KnowledgeError as error:
            announce("failed", detail=str(error))
            raise
        except (RedstringError, ValueError) as error:
            announce("failed", detail=str(error))
            raise KnowledgeError(str(error)) from error
        except Exception as error:  # provider transports raise their own types
            announce("failed", detail=f"extraction failed: {error}")
            raise KnowledgeError(f"extraction failed: {error}") from error

        await self._recard()

        announce(
            "consolidated",
            entities=len(built.event.entities),
            relationships=len(built.event.relationships),
        )
        return IngestReport(
            source_id=source.source_id,
            entity_count=len(built.event.entities),
            relationship_count=len(built.event.relationships),
            domain=built.domain,
            domain_confidence=built.domain_confidence,
            merges=tuple(merges),
            consolidation_failures=failures,
            # Straight off `GraphBuildReport`. redstring has computed all three
            # for longer than this project has existed and nothing here read
            # them, which is how `docs/design/co-mention-channel-findings.md`
            # describes its own defect: a number computed, returned, and
            # dropped is the same silence as a number nobody computes.
            unresolved_relationships=built.unresolved_relationships,
            lifted_dates=built.lifted_dates,
            date_nodes=built.date_nodes,
        )

    @dataclass(frozen=True, slots=True)
    class _Chunking:
        """What this ingest recorded about how the document was split."""

        #: Chunking signatures this ingest added, in log order. Empty means the
        #: aggregate refused every one -- the document has been chunked under
        #: exactly these settings before, which is what "the text is unchanged"
        #: looks like from here.
        signatures: tuple[str, ...]
        #: The newest *entity-linked* chunking, or `None`. Only extraction
        #: produces one; `index_documents` omits links entirely.
        event: object | None

    async def _chunking_signatures(self, source_id: str) -> frozenset[str]:
        """Every chunking this document's stream already records."""
        stream = document_stream(tenant_id=self._project_id, source_id=source_id)
        # `collect` rather than an async comprehension inside `frozenset(...)`:
        # that builds an async generator and hands it to a synchronous
        # constructor, which raises `TypeError: 'async_generator' object is not
        # iterable` from a line that reads as though it iterates.
        envelopes = await collect(self._event_store.read_stream(stream))
        return frozenset(
            envelope.event.chunking_signature
            for envelope in envelopes
            if isinstance(envelope.event, DocumentChunked)
        )

    async def _chunking_recorded_now(self, source_id: str, before: frozenset[str]):
        """The chunkings this ingest added, and the linked one among them.

        Two reads of one short stream per ingest, which is the price of
        `build_graph` returning a count rather than the event it built. The
        alternative -- passing `chunks=` so redstring hands the projection the
        event directly -- costs a whole second `ChunkStore` holding the corpus
        text again; see `infrastructure/knowledge/co_mentions.py`.
        """
        stream = document_stream(tenant_id=self._project_id, source_id=source_id)
        envelopes = await collect(self._event_store.read_stream(stream))
        added = [
            envelope.event
            for envelope in envelopes
            if isinstance(envelope.event, DocumentChunked)
            and envelope.event.chunking_signature not in before
        ]
        linked = [event for event in added if carries_entity_links(event)]
        return self._Chunking(
            signatures=tuple(event.chunking_signature for event in added),
            event=linked[-1] if linked else None,
        )

    async def _apply_co_mentions(self, event: object | None) -> None:
        """Fold this ingest's entity links into the live co-mention index.

        A no-op with no index (the channel off) or no linked chunking (an
        extraction that found nothing, or a re-chunk the aggregate refused).

        **Live as well as on the log**, matching the card-vector channel below.
        The index is folded from `DocumentChunked` at project open, but a
        curriculum requested later in the same session reads the instance
        `ProjectGraphs` opened -- so without this, a project's own ingest is
        invisible to it until the next restart, which is indistinguishable from
        the channel not working.
        """
        if self._co_mentions is None or event is None:
            return
        # `handle(event)`, one argument: `StoreProjection.handle` takes the
        # event alone and passes the context to the decorated method itself.
        # Calling it with `(None, event)` -- the shape the `@handles` method
        # signature suggests -- raises a TypeError naming
        # `CheckpointTrackingProjection`, which is a base class nothing here
        # mentions.
        await CoMentionProjection(self._co_mentions).handle(event)

    @property
    def _embeddings_usable(self) -> bool | None:
        return self._embedding_coordinator.usable

    @_embeddings_usable.setter
    def _embeddings_usable(self, value: bool | None) -> None:
        self._embedding_coordinator.usable = value

    async def _record_embeddings(self, entities: Sequence[Any], *, source_id: str) -> None:
        """Append this ingest's embeddings to the log, on both channels.

        Delegates to :class:`EmbeddingCoordinator`.
        """
        await self._embedding_coordinator.record(entities, source_id=source_id)

    async def _embedding_pair(self) -> tuple[EmbeddingProvider | None, VectorStore | None]:
        """The embedding provider and store to extract with, if they work.

        Delegates to :class:`EmbeddingCoordinator`.
        """
        return await self._embedding_coordinator.pair()

    async def _probe_embeddings(self) -> bool:
        """One embed of one string, to find out whether the endpoint is there.

        Delegates to :class:`EmbeddingCoordinator`.
        """
        return await self._embedding_coordinator.probe()

    async def store_source(self, source: SourceRef) -> None:
        """Keep the text, and do not extract it. Seconds, not minutes.

        `ingest` is store-extract-consolidate and runs for minutes; this is its
        first step alone. It exists because "the source is not lost" and "the
        graph knows about it" are separable goods, and an autonomous run wants
        the first for every page it reads while paying for the second only on
        the pages that turn out to matter.

        The state it leaves behind -- a corpus document with no graph -- is one
        `_store_document` already treats as ordinary and repairable rather than
        broken: see its docstring, which chooses exactly this as the failure to
        leave possible when extraction dies mid-ingest. `reconsolidate`, a
        later `remember_page`, and `/rebuild` all work against it, and
        `link_source` can cite it immediately, which is what a topic round
        actually needs from a page it read.

        It keeps `ingest`'s two refusals rather than relaxing them. Blank ids
        are refused because the id *is* the identity. The length cap is kept
        even though nothing here would chunk the text: a document over it can
        never be extracted later, so storing one would quietly create a corpus
        entry that no `remember_page` could ever complete.
        """
        if not source.source_id.strip():
            raise KnowledgeError("source_id must not be blank; it identifies the document")
        if len(source.text) > MAX_DOCUMENT_CHARS:
            raise KnowledgeError(
                f"that is {len(source.text)} characters; the limit is "
                f"{MAX_DOCUMENT_CHARS}. Record it in parts, each with its own "
                f"source_id."
            )
        await self._store_document(source)

    async def index(self, source: SourceRef) -> None:
        """Split `source`'s text into the chunk corpus. No model call.

        `index_documents` is passed no `embeddings`, which is what makes that
        promise hold -- its own docstring is explicit that supplying one is
        the single way it reaches a model. So this runs on the document-stored
        path (`_store_document` calls it directly, below) rather than behind
        `ExtractionQueue`: there is no per-token cost to defer and nothing
        worth making durable.

        `event_store` is not optional in practice. Omitted, `index_documents`
        builds an `InMemoryEventStore` per call, which suppresses a repeat
        only *within* that call -- so every re-index would rewrite every
        passage while `documents_skipped` reported 0, doing the opposite of
        what it says. This adapter's real event store is what makes the
        second `index` of an unchanged document free.

        `SlidingWindowChunker` at 1000/500, not `BoundaryPreferenceChunker`.
        Upstream documents the latter as the chunker for passages that will be
        quoted back to a reader, which is what this corpus is for -- and it
        loses on retrieval, consistently. stark-bench found it **last on dense
        retrieval across three embedding models**, with `sliding-1000-500`
        ahead of it on every channel in both corpora where both ran (Nemotron
        dense 0.2125 against 0.1845; qwen-mini hybrid 0.4079 against 0.3883).
        Three models agreeing points at the chunker rather than at an
        interaction with one embedding model.

        **The quotability argument is weaker than it reads.** Measured
        2026-08-21: `SlidingWindowChunker` defaults to
        `respect_sentence_boundaries=True` and `respect_paragraph_boundaries=
        True`, and they work -- the first chunk of a 2,700-character document
        at size 1000 ends at 990, not 1000. Both chunkers snap to sentences.
        They differ in size and overlap, which is what BM25's length
        normalisation cares about and what a reader does not notice.

        Why 1000/500 and not the extraction chunker's size: these are two
        different jobs with two different optima. `extraction_chunk_size` is
        tuned for how much a model extracts from one call; this is tuned for
        how a passage ranks. Sharing a number would tie them together for no
        reason beyond looking tidy.

        **The cost, measured rather than assumed:** a document longer than the
        window gets one redundant tail chunk, wholly inside the previous one,
        which `UsageReader`'s offset dedup cannot collapse -- so a reader sees
        one duplicate passage. `tests/infrastructure/test_chunking_defects.py`
        holds that as a strict xfail naming redstring PR #72, which fixes it
        upstream and is unreleased at the time of writing.

        Wrapped in `MarkdownTableChunker`, so a quoted passage of table rows
        carries the header naming its columns -- a row whose cells are unnamed
        is the complaint this whole path exists to answer.

        **This requires redstring >= 0.9.2 and fails silently below it.**
        Until 0.9.2, `redstring.extraction.corpus.stored_chunks` built each
        `StoredChunk` without carrying `Chunk.metadata` across, so the header
        reached the corpus inside the stored text with no
        `synthetic_prefix_chars` to subtract it back off: `original_text`
        degraded to the identity and every offset into a table chunk pointed
        at the wrong words, with nothing raising. That is why this line went
        unwrapped through two commits. The guard against a regression is
        `test_the_prefix_survives_the_round_trip_into_the_chunk_store`, which
        drives the real `index_documents` rather than trusting the chunker --
        if metadata is ever dropped again the failure names the invariant.

        Re-chunking is a re-`index`, not a `/rebuild`.
        `/rebuild` folds stored `DocumentChunked` events, which carry the old
        chunk *text* -- it reproduces the old chunking faithfully. A new
        chunker only takes effect when `index_documents` runs again and emits
        a fresh `DocumentChunked`; it will, because `chunking_signature` is
        `f"{chunker_type}:{chunking_digest(...)}"` and both halves change.
        The projection folds that with `replace_source`, which deletes the
        chunks of that source that are not in the new set -- so the old rows
        are replaced rather than orphaned, despite chunk ids being
        content-addressed over the text.

        Reads `source.text` directly rather than re-reading it back out of
        the corpus: every caller of `index` already has the text in hand (it
        is a required field of `SourceRef`), and a round trip through the
        corpus's read model would race the projection that fills it -- a
        document `index`ed immediately after being stored could read back
        nothing yet.

        A no-op when no chunk store was configured for this project: see
        `self._chunks`'s own comment.
        """
        if self._chunks is None:
            return
        await index_documents(
            [SourceDocument(id=source.source_id, text=source.text)],
            store=self._chunks,
            tenant_id=self._project_id,
            chunker=MarkdownTableChunker(
                SlidingWindowChunker(default_chunk_size=1000, default_overlap=500)
            ),
            event_store=self._event_store,
        )

    async def _recard(self) -> None:
        """Rebuild every card in this project. No model call, no-op when off.

        **The whole tenant, not the entities this ingest touched**, and that is
        correctness rather than laziness in the first version. An edge changes
        *two* neighbourhoods and only one of them is the document's subject, so
        a subject-only refresh leaves the far endpoint's card describing a graph
        it no longer matches -- invisibly, because that card is a truthful
        description of an older neighbourhood and everything it does answer is
        still right. A consolidation is worse: the absorbed entity keeps the
        card a previous pass wrote, which answers every query its name used to,
        so the merge looks undone from the retrieval side while the graph is
        correct. `index_cards` skipping absorbed entities on write does not
        remove what an earlier write left.

        The cost is real and is the obvious thing to narrow: O(entities) of
        assembly per ingest, on top of an ingest that already costs model calls
        per chunk. Narrowing it needs the two-endpoint rule above plus a way to
        delete the cards of entities that stopped being canonical, and getting
        either subtly wrong is silent. `tests/infrastructure/test_entity_cards.py`
        holds one test per failure mode so a narrowing has something to fail.
        """
        if self._cards is None:
            return
        await index_cards(
            graph=self._store,
            cards=self._cards,
            tenant_id=self._project_id,
            chunker=SlidingWindowChunker(default_chunk_size=1000, default_overlap=500),
        )

    async def _store_document(self, source: SourceRef) -> None:
        """Keep the text before extracting it, and only if it is new bytes.

        **Before, deliberately.** The two writes cannot be made one -- they are
        different aggregates over the same log -- so one of them is exposed to
        a crash in between, and the choice is which. A document stored without
        a graph is repaired by extracting it again, which costs model calls and
        nothing else. A graph without its document is not repairable at any
        price: the text is gone, and every claim the graph makes about it
        becomes uncheckable -- which is the whole reason this layer exists.
        So the cheap failure is the one left possible.

        The same reasoning decides what happens when extraction then fails: the
        stored document stays and the error propagates. Rolling it back would
        discard text the user already paid to fetch in order to restore a
        consistency nothing needs -- `reconsolidate` and a second `remember`
        both work fine against a document whose graph is missing, and the
        alternative failure mode is a user watching their source disappear
        because a model endpoint was down.

        Identical bytes under the same `source_id` are skipped rather than
        re-stored: nothing about the corpus would differ afterwards, and the
        log would carry a revision that revised nothing. Identical bytes under
        a *different* id are stored -- two URIs legitimately serve one document
        and each needs its own citable record (see `domain/corpus.py`).

        Two `remember` calls in one assistant message run concurrently, so two
        stores into one project's corpus is an ordinary event. Both would load
        at the same version and the second would lose the compare-and-swap --
        and because `remember` catches `KnowledgeError` and nothing else, that
        `OptimisticLockError` used to escape the tool and fail the entire turn,
        naming the *project* (a corpus shares its project's UUID) for a fault
        that was nothing to do with the project. The load and the digest check
        are inside the retried body precisely so the second attempt decides
        against what the winner wrote.

        **`index` runs unconditionally after, for every caller of this
        method.** `_store_document` is the one place both `ingest` and
        `store_source` funnel through, so hanging indexing here -- rather
        than on each of them separately, or on `ExtractionQueue` -- is what
        makes it impossible for a future third caller to store a document and
        forget to index it. Called even when `store()` found identical bytes
        and skipped the write: `index_documents`'s own signature check is
        what makes that call free, and this method has no cheaper way to know
        in advance whether this `source_id` was already chunked.
        """

        async def store() -> None:
            corpus = await self._corpus.load_or_create(self._project_id)
            digest = hashlib.sha256(source.text.encode("utf-8")).hexdigest()
            if corpus.state.by_digest.get(digest) == source.source_id:
                return
            corpus.execute(
                StoreSourceDocument(
                    corpus_id=self._project_id,
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

        await with_retry(store, what=f"storing {source.source_id!r}")
        await self.index(source)

    @property
    def _consolidation_pipeline(self) -> ConsolidationPipeline:
        return ConsolidationPipeline(
            self._consolidator,
            store=self._store,
            vectors=self._vectors,
            adjudicator=self._adjudicator,
            judgements=self._judgements,
            project_id=self._project_id,
            concurrency=self._concurrency,
            consolidation_batch=self._consolidation_batch,
            event_store=self._event_store,
        )

    async def _judged_finder(self):
        """The candidate source for one `_consolidate` run, or None for the default.

        Delegates to :class:`ConsolidationPipeline`.
        """
        return await self._consolidation_pipeline.build_finder()

    async def _consolidate(
        self, entities, *, announce=_no_announcement
    ) -> tuple[list[MergeRecord], int]:
        """Resolve the extracted entities in batches, not one at a time.

        Delegates to :class:`ConsolidationPipeline`.
        """
        return await self._consolidation_pipeline.consolidate(entities, announce=announce)

    async def _consolidate_one_by_one(
        self, entities, *, finder, announce, done: int, total: int, names
    ) -> tuple[list[MergeRecord], int]:
        """The per-entity path, kept for the failure case only.

        Delegates to :class:`ConsolidationPipeline`.
        """
        return await self._consolidation_pipeline.consolidate_one_by_one(
            entities,
            finder=finder,
            announce=announce,
            done=done,
            total=total,
            names=names,
        )

    def _merge_record(self, report, names, announce, index: int, total: int) -> MergeRecord:
        """One report, announced and recorded.

        Delegates to :class:`ConsolidationPipeline`.
        """
        return self._consolidation_pipeline.merge_record(report, names, announce, index, total)

    async def reconsolidate(self, source_id: str) -> tuple[tuple[MergeRecord, ...], int]:
        """Re-resolve the entities of one recorded extraction.

        The repair path for an ingest whose consolidation was interrupted.
        """
        entities = await self.entities_for(source_id)
        async with tenant_scope(self._project_id):
            merges, failures = await self._consolidate(entities)
        return tuple(merges), failures

    async def entities_for(self, source_id: str) -> tuple:
        """The entities the last recorded extraction of `source_id` found.

        Delegates to :class:`ConsolidationPipeline`.
        """
        return await self._consolidation_pipeline.entities_for(source_id)

    @property
    def remembers_merges_across_restarts(self) -> bool:
        """Whether `undo_merge` survives a restart. False means the log is in-memory."""
        return self._consolidation_pipeline.remembers_merges_across_restarts

    async def search(self, query: str, *, limit: int = 10) -> SearchOutcome:
        """Entities matching `query`, best first.

        Delegates to :func:`search_entities`.
        """
        return await search_entities(
            self._store,
            self._project_id,
            query,
            limit=limit,
        )

    async def describe(self, query: str, *, limit: int = 10) -> SearchOutcome:
        """Entities whose *card* matches `query`, best first.

        Delegates to :func:`describe_entities`.
        """
        return await describe_entities(
            cards=self._cards,
            store=self._store,
            project_id=self._project_id,
            query=query,
            limit=limit,
        )

    async def undo_merge(self, merge_id: UUID) -> MergeRecord:
        """Reverse a consolidation.

        Delegates to :class:`ConsolidationPipeline`.
        """
        return await self._consolidation_pipeline.undo_merge(merge_id)

    async def merge_entities(
        self, *, canonical: UUID, absorbed: list[UUID], reason: str
    ) -> MergeRecord:
        """Merge entities whose identity is already decided elsewhere.

        Delegates to :class:`ConsolidationPipeline`.
        """
        return await self._consolidation_pipeline.merge_entities(
            canonical=canonical, absorbed=absorbed, reason=reason
        )
