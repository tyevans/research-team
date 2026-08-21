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
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from eventsource import collect
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.domain.tenant_context import tenant_scope
from eventsource.ports.positions import ExpectedVersion
from eventsource.ports.snapshots import SnapshotStore
from eventsource.ports.store import AggregateStore
from redstring import (
    Adjudicator,
    BoundaryPreferenceChunker,
    CandidateFinder,
    Chunker,
    ChunkStore,
    Consolidator,
    EmbeddingProvider,
    GraphStore,
    LlmProvider,
    RedstringError,
    RetrievalMode,
    Retriever,
    SourceDocument,
    VectorStore,
    build_graph,
    document_stream,
    index_documents,
)

from research_team.application.knowledge import (
    MAX_DOCUMENT_CHARS,
    ExtractionNote,
    ExtractionReporter,
    IngestReport,
    KnowledgeError,
    Match,
    MergeRecord,
    SourceRef,
)
from research_team.application.retry import with_retry
from research_team.domain import Corpus, EntityJudgements, StoreSourceDocument
from research_team.infrastructure.knowledge.domain_schemas import (
    RESEARCH_CORPUS,
    resolve_domain,
)
from research_team.infrastructure.knowledge.judged_candidates import JudgedCandidates
from research_team.infrastructure.knowledge.markdown_table_chunker import MarkdownTableChunker
from research_team.infrastructure.knowledge.temporal_expressions import (
    RAW_TEMPORAL_PROPERTY,
    normalize_for_parsing,
)

#: Re-exported: written here, defined next to the normalisation it compensates
#: for, and read by `temporal_rendering.py`. Named in `__all__`-less code, so
#: this assignment is what stops a linter calling the import unused.
_ = RAW_TEMPORAL_PROPERTY

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


class _CountingProvider:
    """An `LlmProvider` that says how many calls have been made through it.

    `build_graph` takes no callbacks and is one opaque await containing domain
    classification, chunking and a call per chunk -- the longest part of an
    ingest, and the part a watcher most needs to see moving. `LlmProvider` is
    a single-method protocol, so wrapping it is the whole cost of getting
    inside.

    It counts **calls, not chunks.** The chunk count is not knowable before
    extraction runs, and "chunk 4 of 9" would be a denominator invented here
    that nobody could check.
    """

    def __init__(self, inner: LlmProvider, announce) -> None:
        self._inner = inner
        self._announce = announce
        self._calls = 0

    @property
    def model(self) -> str:
        return self._inner.model

    @property
    def calls(self) -> int:
        return self._calls

    async def extract(self, text, schema, *, system_prompt=None):
        self._calls += 1
        self._announce(self._calls)
        return await self._inner.extract(text, schema, system_prompt=system_prompt)


class _DatingProvider:
    """An `LlmProvider` that respells dates on the way back from the model.

    **The only seam available.** The correction has to land between the model
    answering and redstring parsing, and `map_extraction` runs inside
    `build_graph`, which writes the graph store and builds the
    `DocumentExtracted` event together. Correcting the entities afterwards
    would fix the event and leave the store disagreeing with it, so the
    correction goes in the input where there is exactly one copy of it.

    Wraps `_CountingProvider` rather than replacing it: counting calls and
    respelling dates are unrelated jobs, and one class doing both would be
    harder to read than two doing one each. See
    `temporal_expressions.py` for what is respelled and the measurements
    behind each rule.
    """

    def __init__(self, inner: LlmProvider) -> None:
        self._inner = inner

    @property
    def model(self) -> str:
        return self._inner.model

    async def extract(self, text, schema, *, system_prompt=None):
        answer = await self._inner.extract(text, schema, system_prompt=system_prompt)
        return _with_respelled_dates(answer)


def _with_respelled_dates(extraction):
    """`extraction` with every entity's temporal expression normalised.

    Rebuilt by `model_copy` rather than mutated: the pipeline holds the same
    answer object for gleaning and carryover, and editing it in place would
    make what a later stage reads depend on whether this ran first.
    """
    entities = []
    changed = False
    for candidate in extraction.entities:
        # `properties` first, and that is not a fallback -- it is where the
        # date usually is. Traced against qwen3.8-27b-mtp on the real 'Edict
        # of Milan' article: across three chunks every `temporal_expression`
        # field came back None while `properties` held
        # {"temporal_expression": "AD 380", "outcome": ...}. The model files
        # the date beside `outcome`, `role` and `creator`, which is where the
        # domain schema's own per-type properties go, and the prompt's phrase
        # "that entity's `temporal_expression` field" does nothing to single
        # it out. The schema field is read second because the model does
        # sometimes use it, and when it does it is the more direct answer.
        raw = candidate.properties.get(RAW_TEMPORAL_PROPERTY) or candidate.temporal_expression
        if not isinstance(raw, str) or not raw.strip():
            entities.append(candidate)
            continue
        changed = True
        entities.append(
            candidate.model_copy(
                update={
                    "temporal_expression": normalize_for_parsing(raw),
                    "properties": {**candidate.properties, RAW_TEMPORAL_PROPERTY: raw},
                }
            )
        )
    if not changed:
        return extraction
    return extraction.model_copy(update={"entities": entities})


def _reporting(report: ExtractionReporter | None, source_id: str):
    """A guarded `report`, or a no-op.

    Guarded rather than trusted: a listener that raises must not cost a
    document that has already been fetched and paid for. The work is what
    matters; the telling about it is not. A no-op when `report` is None so
    every call site can announce unconditionally rather than guard twice.
    """

    def announce(stage: str, **fields: Any) -> None:
        if report is None:
            return
        try:
            report(ExtractionNote(source_id=source_id, stage=stage, **fields))
        except Exception:
            # Broad on purpose -- see the docstring: a listener is arbitrary
            # caller code and any failure in it must cost nothing. No `noqa`,
            # because `exc_info=True` is ruff's own signal that this handles
            # the exception rather than swallowing it.
            logger.warning("an extraction reporter raised; carrying on", exc_info=True)

    return announce


def _no_announcement(stage: str, **fields: Any) -> None:
    """The default announcer: says nothing.

    `_consolidate` has two callers and only one of them is watching. A default
    here beats a required parameter that `reconsolidate` would have to satisfy
    with a throwaway lambda at every call site -- and beats an
    `announce=None` sentinel that every announcement inside the loop would
    have to test for.
    """


def _parse_published_at(raw: str | None) -> datetime | None:
    """Read a source's publication date, or give up quietly.

    redstring wants a `datetime`; sources supply prose. ISO-8601 is what
    structured metadata actually emits (`article:published_time`, JSON-LD,
    sitemaps), so it is the only format worth accepting -- a date-guessing
    library would turn ambiguity into confident wrong answers, and a wrong
    date on a citation is worse than an absent one.

    Anything else returns None and the caller keeps the raw string in the
    document's metadata: the date is still there for a human reading the
    citation, it just cannot be sorted or filtered on. Refusing the ingest
    over it would trade the whole document for one field.

    redstring rejects a naive datetime outright, so a bare `YYYY-MM-DD` --
    the most common thing a source publishes -- is read as UTC. That is a
    guess of up to a day either way, which no citation cares about, and the
    alternative is discarding every date that came without a zone.
    """
    if raw is None:
        return None
    candidate = raw.strip()
    if not candidate:
        return None
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


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
        concurrency: int = 1,
        chunker: Chunker | None = None,
        chunks: ChunkStore | None = None,
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
        # Both default to redstring's own serial behaviour rather than to the
        # configured values, so a test constructing this directly gets the
        # deterministic pipeline unless it asks otherwise. The composition
        # root is the one place that reads `config`, and it passes both.
        self._concurrency = concurrency
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
        #: None until the first ingest probes the endpoint; see
        #: `_embedding_pair`. Not probed in `__init__` because that is not
        #: async and because a project that is opened and never ingested into
        #: should not pay for a round trip.
        self._embeddings_usable: bool | None = None
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
                embeddings, vectors = await self._embedding_pair()
                built = await build_graph(
                    document,
                    provider=wrapped,
                    store=self._store,
                    tenant_id=self._project_id,
                    domain=self._domain,
                    embedding_provider=embeddings,
                    vector_store=vectors,
                    # Chunks go out in batches of `concurrency` and carryover
                    # folds back in *chunk* order rather than completion
                    # order, so this stays reproducible: the same document
                    # twice gives the same graph regardless of which call
                    # returned first. That is redstring's guarantee, not one
                    # this adapter arranges, and it is the reason the knob is
                    # passed here rather than kept behind a flag.
                    concurrency=self._concurrency,
                    chunker=self._chunker,
                )
                if built.event is None:
                    # `Document.record_extraction` found nothing new to record
                    # -- the same content and model version as a previous run.
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
                await self._event_store.append(
                    document_stream(tenant_id=self._project_id, source_id=source.source_id),
                    [built.event],
                    ExpectedVersion.any_(),
                )
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
        )

    async def _embedding_pair(self) -> tuple[EmbeddingProvider | None, VectorStore | None]:
        """The embedding provider and store to extract with, if they work.

        **Probed once, lazily, and latched.** `AGENT_VECTOR_STORE` now defaults
        to on, and its endpoint defaults to the same local server that serves
        the chat model -- which need not serve embeddings at all. llama.cpp
        serves one model per process. So the common misconfiguration is not
        exotic, and a default-on feature has to survive it.

        Surviving it means *degrading*, not failing. `build_graph` embeds after
        it has extracted, so an `EmbeddingProviderError` raised there would
        throw away a document that had already been fetched and every model
        call its extraction cost -- to lose an optional third scoring feature.
        `_store_document` makes the same trade in the other direction and for
        the same reason: the cheap failure is the one left possible.

        So the probe is one `embed` of one short string, before the first
        ingest uses it. If it raises, or the width disagrees with what the
        provider declares, this logs at **warning with the exception** and
        returns `(None, None)` for the rest of the process -- consolidation
        falls back to two features, which is exactly what shipped before #88
        and is a working configuration, not a broken one.

        **This is a degradation and it is not silent, but it is also not
        loud enough to stop anything.** That is the deliberate part: a person
        who wanted embeddings and mistyped the model name gets a warning in the
        log and worse consolidation, not a dead application. `AGENT_VECTOR_STORE
        =none` is how to say you meant it and skip the probe.

        Latched rather than retried per ingest: a wrong model name does not
        become right, and retrying would pay a round trip per document to
        re-learn it. The cost of the latch is that an endpoint which comes up
        *after* the process did stays unused until a restart, which is the
        right way round -- the alternative charges every healthy run for a
        failure mode nobody is in.
        """
        if self._embeddings is None or self._vectors is None:
            return None, None
        if self._embeddings_usable is False:
            return None, None
        if self._embeddings_usable is None:
            self._embeddings_usable = await self._probe_embeddings()
            if not self._embeddings_usable:
                return None, None
        return self._embeddings, self._vectors

    async def _probe_embeddings(self) -> bool:
        """One embed of one string, to find out whether the endpoint is there.

        Checks the width as well as the call, because the two failures need the
        same handling and only one of them raises. A provider declaring 768
        against a server returning 1024 would otherwise reach
        `VectorProjection` and raise `DimensionMismatchError` -- a *poison
        event*, which is unrecoverable rather than retryable, in the middle of
        an ingest.
        """
        assert self._embeddings is not None and self._vectors is not None
        try:
            vectors = await self._embeddings.embed(["probe"])
        except Exception:
            # Broad on purpose: the transports underneath raise their own
            # types, and every one of them means the same thing here -- no
            # embeddings this run. `exc_info` is what makes it diagnosable.
            logger.warning(
                "the embedding endpoint (%s, model %r) did not answer a probe; "
                "consolidating on name and graph only. Set AGENT_VECTOR_STORE=none "
                "to skip this probe, or fix AGENT_EMBEDDING_MODEL / "
                "AGENT_EMBEDDING_BASE_URL",
                type(self._embeddings).__name__,
                getattr(self._embeddings, "model", "?"),
                exc_info=True,
            )
            return False
        width = len(vectors[0]) if vectors else 0
        if width != self._vectors.dimension:
            logger.warning(
                "the embedding endpoint returned %d components and the vector store "
                "holds %d; consolidating on name and graph only. AGENT_EMBEDDING_MODEL "
                "and AGENT_EMBEDDING_DIMENSION are set together or not at all",
                width,
                self._vectors.dimension,
            )
            return False
        return True

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

        `BoundaryPreferenceChunker` at its own defaults, not
        `SlidingWindowChunker` (what `ingest` chunks extraction with):
        redstring documents it as the chunker for passages that will be
        quoted back to a reader, which is what this corpus is for and
        extraction's chunking is not.

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
            chunker=MarkdownTableChunker(BoundaryPreferenceChunker()),
            event_store=self._event_store,
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

    async def _judged_finder(self):
        """The candidate source for one `_consolidate` run, or None for the default.

        **Built once per run, not once per entity.** An ingest resolves every
        extracted entity in a loop, and a human cannot record a judgement
        part-way through that loop, so loading the aggregate per entity would
        be one event-store read each to re-learn something that cannot have
        changed. `reconsolidate` is the case that makes the repository rather
        than a captured state the right thing to hold: it is a separate entry
        point and must see judgements made since the last ingest.

        None when no repository was supplied. `resolve` reads that as "use my
        own default finder", so the call site needs no branch -- and an empty
        judgement set makes `JudgedCandidates` a passthrough anyway, so the two
        paths agree on behaviour rather than merely on outcome.

        `CandidateFinder` is constructed with the same arguments the
        `Consolidator` was given: the store and the vector store, with
        `weights` and `use_graph_signal` left at redstring's defaults.
        Deliberately no `weights=` here -- 6c2ae4a withdrew a reweight for lack
        of evidence, and a second one hidden inside the finder would be the
        same mistake somewhere harder to find.
        """
        if self._judgements is None:
            return None
        judgements = await self._judgements.load_or_create(self._project_id)
        return JudgedCandidates(
            CandidateFinder(self._store, vector_store=self._vectors),
            graph_store=self._store,
            tenant_id=self._project_id,
            judgements=judgements.state,
        )

    async def _consolidate(
        self, entities, *, announce=_no_announcement
    ) -> tuple[list[MergeRecord], int]:
        """Resolve each extracted entity, one at a time.

        `resolve` is per-entity by design, and it emits its own event, so this
        collects rather than appends. A failure on one entity does not abandon
        the rest: the extraction is already recorded and the merges that
        succeeded are already folded, so stopping here would leave less of the
        graph consolidated for no gain.

        `announce` defaults to silence because `reconsolidate` also calls this
        and has no watcher; it is announced *before* each `resolve` as well as
        after a merge lands, so a slow entity is visible while it is slow
        rather than only once it is done.

        `low` is redstring's own `LOW_SIMILARITY` again -- there is no override
        here any more. The module-level note above `_CountingProvider` says what
        the override was for, why PR #87 was right to keep it, and what the
        embedding channel changed that made it unnecessary.
        """
        entities = list(entities)
        merges: list[MergeRecord] = []
        failures = 0
        total = len(entities)
        finder = await self._judged_finder()
        for position, entity in enumerate(entities, start=1):
            announce("consolidating", index=position, total=total, detail=entity.name)
            try:
                report = await self._consolidator.resolve(
                    entity, adjudicator=self._adjudicator, finder=finder
                )
            except RedstringError as error:
                # The comment that used to be here said this is "typically the
                # entity was absorbed by a merge earlier in this same loop",
                # and treated every `RedstringError` as that benign case. Only
                # `ConsolidationInvariantError` is that case. `RedstringError`
                # is redstring's base class, so this arm also caught
                # `CircuitOpen`, `RateLimitExceeded`, `LlmProviderError`,
                # `MissingEntityError` and `AliasCycleError` -- a rate-limited
                # adjudicator would consolidate nothing across an entire
                # ingest, count every entity as a "failure", and say nothing.
                # Logged rather than raised: a genuine fault on one entity
                # still must not abandon the rest, for the reason in the
                # docstring. But it is no longer indistinguishable from an
                # ordinary absorbed entity.
                failures += 1
                logger.warning(
                    "consolidating %r failed; carrying on with the rest",
                    entity.name,
                    exc_info=True,
                )
                announce(
                    "consolidating",
                    index=position,
                    total=total,
                    detail=f"{entity.name} could not be consolidated: {error}",
                )
                continue
            if report is None:
                continue
            absorbed = tuple(str(i) for i in report.affected_entity_ids)
            announce(
                "consolidating",
                index=position,
                total=total,
                detail=f"{entity.name} absorbed {', '.join(absorbed)} -- {report.reason}",
            )
            merges.append(
                MergeRecord(
                    merge_id=report.event.event_id,
                    canonical_name=entity.name,
                    absorbed_names=absorbed,
                    reason=report.reason,
                )
            )
        return merges, failures

    async def reconsolidate(self, source_id: str) -> tuple[tuple[MergeRecord, ...], int]:
        """Re-resolve the entities of one recorded extraction.

        The repair path for an ingest whose consolidation was interrupted. It
        is keyed by `source_id` and bounded by that document, because redstring
        marks no entity as unconsolidated (upstream R2) -- the only alternative
        is paging every entity in the project and redoing settled work at every
        open.

        Re-resolving an already-consolidated entity is safe: `resolve` returns
        None when there is nothing to merge, and raises when the entity has
        already been absorbed, which `_consolidate` counts rather than
        propagates.
        """
        stream = document_stream(tenant_id=self._project_id, source_id=source_id)
        envelopes = await collect(self._event_store.read_stream(stream))
        if not envelopes:
            raise KnowledgeError(f"no extraction recorded for source_id {source_id!r}")

        entities = envelopes[-1].event.entities
        async with tenant_scope(self._project_id):
            merges, failures = await self._consolidate(entities)
        return tuple(merges), failures

    async def entities_for(self, source_id: str) -> tuple:
        """The entities the last recorded extraction of `source_id` found.

        Read off the event rather than the graph: the event is what the repair
        path replays, so this is the same set `reconsolidate` would act on.
        """
        stream = document_stream(tenant_id=self._project_id, source_id=source_id)
        envelopes = await collect(self._event_store.read_stream(stream))
        if not envelopes:
            raise KnowledgeError(f"no extraction recorded for source_id {source_id!r}")
        return tuple(envelopes[-1].event.entities)

    @property
    def remembers_merges_across_restarts(self) -> bool:
        """Whether `undo_merge` survives a restart. False means the log is in-memory."""
        return self._consolidator.remembers_merges_across_restarts

    async def search(self, query: str, *, limit: int = 10) -> list[Match]:
        """Entities matching `query`, best first.

        Two channels, unioned: a substring test over the tenant's names, and
        `redstring.Retriever`'s **lexical** channel -- blocking keys over the
        name, scored by Jaro-Winkler.

        **The substring channel is neither redundant nor legacy.** Measured
        2026-08-21 against this adapter: `Retriever` finds `Adah Lovelace` for
        `Ada Lovelace`, which no substring test can reach, and misses both an
        interior fragment (`ovelace`) and a short prefix (`Ada`), which the
        substring test finds -- its lexical channel blocks on a five-character
        prefix of the normalized name plus a soundex of the whole name, and a
        fragment shares neither. Neither channel dominates, so both run.
        `test_search_finds_an_entity_by_an_interior_fragment` and its
        short-prefix sibling are what fail if this one is ever dropped for the
        library's class; the original reasoning still holds too --
        `find_entities(name=...)` matches `normalized_name` exactly, and a
        tool the agent drives with free text needs more give than that.

        Reordered names (`lovelace ada`) match in neither and are not a
        regression from this change: they returned nothing before it.
        See `BACKLOG.md` B-SEARCH-REORDER-1.

        `Retriever` ranks; the substring pass does not. So fused hits come
        first in `Retriever`'s order and substring-only hits follow in store
        order, and an entity found by both appears once, at its ranked
        position.

        **`RetrievalMode.LEXICAL`, not `HYBRID`, and that is a decision.**
        Turning the semantic channel on makes this tool answer with entities
        that match the query nowhere in their text: measured here, searching
        `Nova Scotia Duck Tolling Retriever` also returned `Duck hunting` and
        `Canada`. Three reasons not to:

        * The tool this backs is documented to the model as finding entities
          **by name**, and an agent counting what it found is misled -- which
          is not hypothetical, it is how this was noticed
          (`test_embedded_consolidation.py` uses `search` to assert that a
          duplicate merged into one node).
        * stark-bench I.2 measured a model shown entities unrelated to its
          query scoring **below** one shown none. Unrelated names are not
          free context; they are attention spent.
        * Retrieving an entity by *describing* it is a real capability and it
          is deliberately the next stage's, over a corpus built for it. A weak
          version here would move the baseline that stage has to be measured
          against.

        So the entity vectors `build_graph` writes are still read by exactly
        one consumer -- consolidation scoring. This stage does not change that.

        **`Retriever` is skipped entirely when embeddings are unavailable, and
        that is a wart rather than a design.** Its lexical channel needs no
        embedding at all, but `Retriever.__init__` takes an
        `EmbeddingProvider` and dimension-checks it against the vector store,
        so there is no way to ask for the lexical half alone. Calling
        `find_by_blocking_keys` and `lexical_score` directly -- the way
        `UsageReader` calls redstring's chunk-ranking internals, for this
        exact reason -- is not available either: neither name is exported, and
        `tests/test_architecture.py` refuses `redstring.domain.*`. So a
        deployment with `AGENT_VECTOR_STORE=none`, or one whose embedding
        probe failed, gets substring matching only. See `BACKLOG.md`
        B-LEXICAL-NEEDS-EMBEDDINGS-1.

        The page of entities per call is unchanged and is still the first
        thing to revisit behind Neo4j.
        """
        if limit < 1:
            raise KnowledgeError("limit must be at least 1")
        needle = query.strip().lower()
        if not needle:
            return []

        try:
            async with tenant_scope(self._project_id):
                entities = await self._store.find_entities(self._project_id)
                # `find_entities` returns absorbed entities too -- a merge is
                # not a delete, because the row is what `undo_merge` restores.
                # Without this the agent's own search reports a consolidated
                # pair as two hits, one of which has had all its edges
                # redirected away and so answers `relationship_count=0`. The
                # same filter guards the browser's read in `graph_reader.py`;
                # both call sites exist because both read the store directly.
                canonical = await self._store.resolve_entity_ids(
                    [entity.id for entity in entities], self._project_id
                )
                # `==`, not `is`: an adapter may rebuild the UUID for an id
                # that is not an alias, and `is` would filter out everything
                # and answer that the project is empty.
                by_id = {
                    entity.id: entity
                    for entity in entities
                    if canonical[entity.id] == entity.id
                }

                embeddings, vectors = await self._embedding_pair()
                ordered: list[UUID] = []
                if embeddings is not None and vectors is not None:
                    retrieved = await Retriever(
                        embeddings=embeddings, vectors=vectors, graph=self._store
                    ).retrieve(query, self._project_id, k=limit, mode=RetrievalMode.LEXICAL)
                    # A ranked id may name an absorbed entity, which `by_id`
                    # has already dropped; skipping here rather than resolving
                    # keeps one rule about what a match is.
                    ordered = [
                        scored.entity.id
                        for scored in retrieved.matches
                        if scored.entity.id in by_id
                    ]

                seen = set(ordered)
                ordered.extend(
                    entity_id
                    for entity_id, entity in by_id.items()
                    if entity_id not in seen and needle in entity.name.lower()
                )
                ordered = ordered[:limit]

                # One read, not one per match. The previous shape issued a
                # `get_relationships_for` inside the match loop, which is N
                # round trips to answer one question and was invisible to
                # every test because the answers were identical either way.
                edges = (
                    await self._store.get_relationships_for(ordered, self._project_id)
                    if ordered
                    else []
                )
                counts: dict[UUID, int] = dict.fromkeys(ordered, 0)
                for edge in edges:
                    for endpoint in (edge.source_entity_id, edge.target_entity_id):
                        if endpoint in counts:
                            counts[endpoint] += 1

                matches = [
                    Match(
                        entity_id=entity_id,
                        name=by_id[entity_id].name,
                        entity_type=by_id[entity_id].entity_type,
                        relationship_count=counts[entity_id],
                    )
                    for entity_id in ordered
                ]
        except RedstringError as error:
            raise KnowledgeError(str(error)) from error
        return matches

    async def undo_merge(self, merge_id: UUID) -> MergeRecord:
        """Reverse a consolidation.

        `UnknownMergeError` covers "never happened", "already undone" and "made
        by a different consolidator" as one case, so this cannot report which --
        it says what it knows.
        """
        try:
            async with tenant_scope(self._project_id):
                report = await self._consolidator.undo(
                    tenant_id=self._project_id, merge_event_id=merge_id
                )
        except RedstringError as error:
            raise KnowledgeError(f"no merge in effect has id {merge_id}: {error}") from error

        return MergeRecord(
            merge_id=merge_id,
            canonical_name=str(report.canonical_entity_id),
            absorbed_names=tuple(str(i) for i in report.affected_entity_ids),
            reason=report.reason,
        )

    async def merge_entities(
        self, *, canonical: UUID, absorbed: list[UUID], reason: str
    ) -> MergeRecord:
        """Merge entities whose identity is already decided elsewhere.

        The explicit path -- no blocking, no scoring, no model call. Exposed
        because a caller that already knows two ids are one thing should not
        have to go through similarity scoring to say so.
        """
        try:
            async with tenant_scope(self._project_id):
                report = await self._consolidator.merge(
                    tenant_id=self._project_id,
                    canonical_entity_id=canonical,
                    merged_entity_ids=absorbed,
                    merge_reason=reason,
                )
        except RedstringError as error:
            raise KnowledgeError(str(error)) from error
        return MergeRecord(
            merge_id=report.event.event_id,
            canonical_name=str(report.canonical_entity_id),
            absorbed_names=tuple(str(i) for i in report.affected_entity_ids),
            reason=report.reason,
        )
