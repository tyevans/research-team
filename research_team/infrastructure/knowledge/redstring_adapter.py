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
    AUTO,
    Adjudicator,
    Chunker,
    Consolidator,
    EmbeddingProvider,
    FeatureWeights,
    GraphStore,
    LlmProvider,
    RedstringError,
    SourceDocument,
    VectorStore,
    build_graph,
    document_stream,
)

from research_team.application.knowledge import (
    ExtractionNote,
    ExtractionReporter,
    IngestReport,
    KnowledgeError,
    Match,
    MergeRecord,
    SourceRef,
)
from research_team.application.retry import with_retry
from research_team.domain import Corpus, StoreSourceDocument

logger = logging.getLogger(__name__)

#: Longest document accepted in one `remember`. Roughly a long article.
MAX_DOCUMENT_CHARS = 200_000


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


#: Why the name feature is worth less than the embedding one.
#:
#: redstring 0.9.0 added token containment to `string_similarity`, so a
#: title-qualified name scores `CONTAINMENT_CEILING` (0.85) rather than the
#: 0.437 an edit distance gives it -- `Dr. Grant`/`Grant` and
#: `Alan Grant`/`Grant` are the shape. **That fix does not fire under
#: redstring's default weights**, and the arithmetic is the whole reason this
#: constant exists. A cross-document pair carries `graph = 0.0` as a *present*
#: feature, `combined_score` renormalizes over present features, so the zero
#: stays in the divisor:
#:
#:     0.5(0.85) + 0.3(1.00) + 0.2(0.00)  =  0.7250   <  LOW_SIMILARITY 0.75
#:
#: Rejected before the adjudicator is offered it, at *any* embedding value --
#: clearing 0.75 would need an embedding of 1.083. Moving 0.2 from name to
#: embedding lands the same pair at 0.7550 and buys nothing else:
#:
#:     0.3(0.85) + 0.5(1.00) + 0.2(0.00)  =  0.7550   >= 0.75, adjudicated
#:
#: **The graph weight is deliberately left at redstring's default**, and the
#: obvious-looking alternatives are both worse:
#:
#: `weights=FeatureWeights(graph=0.0)` and `use_graph_signal=False` are the
#: same thing -- a zero weight is exactly equivalent to an absent feature, by
#: `combined_score`'s own docstring -- and neither is scoped to the
#: cross-document case, because weights are fixed at construction and `resolve`
#: takes no override. Dropping graph from the divisor makes the score a
#: weighted mean of two features that are both near 1.0 for a duplicate, so it
#: clears `HIGH_SIMILARITY` (0.92) for *any* name/embedding split: the `#84`
#: exact duplicate would auto-merge at 1.0000 with **no model call at all**,
#: and `University of York`/`University of Cork` at 0.9823 with it. That is not
#: a tuning slip to be fixed by a different ratio; it is what removing the
#: third feature does. Keeping graph at 0.2 caps every cross-document pair at
#: 0.8000 -- perfect name, perfect embedding -- which is below 0.92, and is
#: what keeps the adjudicator in the loop.
#: `test_auto_merge_stays_out_of_reach_so_every_duplicate_costs_a_call` is the
#: test that goes red if anyone zeroes it.
#:
#: What this does *not* fix, and is the item to prefer over retuning these
#: numbers again: `graph = 0.0` across a document boundary is doing two jobs.
#: Two documents describing different facets of one entity share no neighbours
#: *because they are different documents*, not because the entities differ.
#: redstring draws exactly that distinction elsewhere -- `candidates.py` returns
#: the feature **absent** for a dangling entity, on the reasoning that "an id
#: nothing can be learned about is not evidence of disagreement" -- and a
#: cross-document neighbourhood arguably deserves the same reading. If it got
#: one upstream, the feature would go absent, the divisor would renormalize
#: honestly, and this constant could go back to the defaults. See BACKLOG B58.
#:
#: The `Dr. Grant` and `York`/`Cork` figures above are `string_similarity`
#: measured on 0.9.1 against an **assumed** embedding, not an observed one:
#: `FakeEmbeddingProvider` hashes text and cannot produce them, and no real
#: model has been run over this pair. The exact-duplicate 0.8000 is measured.
#: Treat the two near-miss numbers as arithmetic on an estimate.
_WEIGHTS = FeatureWeights(name=0.3, embedding=0.5, graph=0.2)


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
        domain: str = "auto",
        adjudicate: bool = True,
        embeddings: EmbeddingProvider | None = None,
        vector_store: VectorStore | None = None,
        concurrency: int = 1,
        chunker: Chunker | None = None,
    ) -> None:
        self._project_id = project_id
        self._store = store
        self._event_store = event_store
        self._provider = provider
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
        self._domain = AUTO if domain == "auto" else domain
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
            weights=_WEIGHTS,
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
            counting = _CountingProvider(
                self._provider, lambda calls: announce("extracting", model_calls=calls)
            )
            async with tenant_scope(self._project_id):
                embeddings, vectors = await self._embedding_pair()
                built = await build_graph(
                    document,
                    provider=counting,
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
        for position, entity in enumerate(entities, start=1):
            announce("consolidating", index=position, total=total, detail=entity.name)
            try:
                report = await self._consolidator.resolve(
                    entity, adjudicator=self._adjudicator
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
        """Entities whose name contains `query`, case-insensitively.

        Filtered here rather than by the store because `find_entities(name=...)`
        matches `normalized_name` exactly -- no substring, no fuzziness -- and a
        tool the agent drives with free text needs more give than that. The cost
        is a page of the tenant's entities per call, which is acceptable against
        an in-memory store and is the first thing to revisit behind Neo4j.
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
                matches = []
                for entity in entities:
                    # `==`, not `is`: an adapter may rebuild the UUID for an id
                    # that is not an alias, and `is` would filter out
                    # everything and answer that the project is empty.
                    if canonical[entity.id] != entity.id:
                        continue
                    if needle not in entity.name.lower():
                        continue
                    edges = await self._store.get_relationships_for(
                        [entity.id], self._project_id
                    )
                    matches.append(
                        Match(
                            entity_id=entity.id,
                            name=entity.name,
                            entity_type=entity.entity_type,
                            relationship_count=len(edges),
                        )
                    )
                    if len(matches) == limit:
                        break
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
