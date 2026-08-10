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
    Consolidator,
    FeatureWeights,
    GraphStore,
    LlmProvider,
    RedstringError,
    SourceDocument,
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


def _exact_name_with_no_shared_structure() -> float:
    """The score two *identically named* entities get when they share no neighbour.

    Not a tuning constant -- a number forced on us by redstring's defaults, and
    derived from them rather than written down, so it moves if they move.

    We run with no `VectorStore`, so scoring has two features: `name` and
    `graph`. A cross-document duplicate scores `name = 1.0` and `graph = 0.0`,
    and `combined_score` renormalizes over the present weights, giving
    `name / (name + graph)` -- 0.5 / 0.7 = **0.7143** on redstring's defaults.
    redstring's `LOW_SIMILARITY` is 0.75, so *an exact name match is rejected
    before anything is asked about it*.

    **The artefact this was written for is gone; the floor is not.** When PR
    #84 added this, `graph = 0.0` was an artefact of the id scheme: neighbours
    were compared by id, `entity_id_for` namespaces ids per document, so two
    entities extracted from two documents *could not* share a neighbour however
    obviously identical they were. redstring 0.5.0 compares neighbours by
    normalized name instead, and a cross-document duplicate whose documents
    describe the same neighbourhood now scores `graph = 1.0` and merges on its
    own -- `test_two_documents_describing_the_same_pair_merge_without_a_floor`
    pins that, and passes with this floor removed.

    What is left is a real finding, and still not one worth rejecting on: two
    documents can name the same thing while saying different things *about* it.
    "Nova Scotia Duck Tolling Retriever" beside "Canada" in one document and
    beside "Duck hunting" in another has genuinely disjoint neighbours, scores
    `graph = 0.0` honestly, and lands on the same 0.7143 -- below
    `LOW_SIMILARITY`, so it is dropped before anything is asked about it.
    Removing this floor was tried against
    `test_one_entity_named_the_same_in_two_documents_becomes_one_node` and that
    test goes red: two nodes, one breed. A single graph signal disagreeing must
    not outrank an exact name match to the point of refusing to *ask*, which is
    what 0.75 does to a deployment with no embeddings.

    Using this as `low` admits precisely the pairs an exact name match reaches
    and nothing weaker, because `decide` bands inclusive-from-below. Measured
    against the near-misses that make loosening dangerous, all of which stay
    rejected: "Nova Scotia Duck Tolling Retriever(s)" 0.7102, "Robert Smith" /
    "Roberta Smith" 0.7033, "World War I" / "World War II" 0.7024, "University
    of York" / "University of Cork" 0.6984.

    Those four were measured on 0.4.0, where every cross-document pair scored
    `graph = 0.0`, so they are now the *floor* of what those pairs score rather
    than the whole story: "Robert Smith" and "Roberta Smith" described in two
    documents with the same neighbours score 0.9890 and merge unasked. The
    numbers above are still what this constant admits, because they are what
    the pairs score with no shared structure; what has changed is that shared
    structure can now lift a near-miss past `high` without this constant being
    involved. Embeddings are the signal that would separate them (upstream R1).

    **Nothing merges unasked because of this.** This lowers `low`; it does not
    touch `high`, so the merge-without-asking band is redstring's 0.92 as it
    always was, and every pair *this* admits lands in the adjudicated band --
    a model call, and a `no` by default. With `adjudicate=False` the band is
    rejected and this is a no-op, which is why the fixture that disables
    adjudication sees no change.

    Unasked merges do now happen, and not because of this: since 0.5.0 a
    cross-document pair with an identical name and a shared neighbour name
    scores a flat 1.0 and merges without adjudication. That is redstring's
    decision, reached by the same `high` a single-document pair has always
    faced. It is worth knowing about, because before 0.5.0 no cross-document
    pair could reach 0.92 at all.
    """
    weights = FeatureWeights()
    return weights.name / (weights.name + weights.graph)


#: Cached at import: `FeatureWeights()` is frozen and the value cannot vary
#: between calls, so recomputing it per entity would be a division per
#: candidate for no reason.
EXACT_NAME_SCORE = _exact_name_with_no_shared_structure()


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
    ) -> None:
        self._project_id = project_id
        self._store = store
        self._event_store = event_store
        self._provider = provider
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
        self._consolidator = Consolidator(
            store,
            event_store=event_store,
            snapshot_store=snapshot_store,
        )
        # Without an adjudicator the middle similarity band is rejected rather
        # than merged, so consolidation would be name-and-structure-only. There
        # are no embeddings to contribute a third signal (upstream R1), which
        # makes the model's judgement worth more here, not less.
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
                built = await build_graph(
                    document,
                    provider=counting,
                    store=self._store,
                    tenant_id=self._project_id,
                    domain=self._domain,
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

        `low=EXACT_NAME_SCORE` overrides redstring's `LOW_SIMILARITY`, which is
        too high for a deployment with no embeddings to consolidate anything
        across documents. See `_exact_name_with_no_shared_structure` for the
        arithmetic, what it admits, and why nothing merges unasked as a result.
        """
        entities = list(entities)
        merges: list[MergeRecord] = []
        failures = 0
        total = len(entities)
        for position, entity in enumerate(entities, start=1):
            announce("consolidating", index=position, total=total, detail=entity.name)
            try:
                report = await self._consolidator.resolve(
                    entity, adjudicator=self._adjudicator, low=EXACT_NAME_SCORE
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
