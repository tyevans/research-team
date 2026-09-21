"""Batched entity consolidation, retries, and merge recording."""

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any
from uuid import UUID

from eventsource import collect
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.domain.tenant_context import tenant_scope
from eventsource.ports.store import AggregateStore
from redstring import (
    Adjudicator,
    CandidateFinder,
    Consolidator,
    GraphStore,
    RedstringError,
    VectorStore,
)
from redstring.events.streams import document_stream

from research_team.infrastructure.config import DEFAULT_CONSOLIDATION_BATCH
from research_team.infrastructure.knowledge.judged_candidates import JudgedCandidates
from research_team.infrastructure.knowledge.redstring_providers import (
    _batches,
    _no_announcement,
)
from research_team.knowledge.application import KnowledgeError, MergeRecord
from research_team.knowledge.domain import EntityJudgements

logger = logging.getLogger(__name__)


def build_merge_record(
    report: Any,
    names: Mapping[Any, str],
    announce: Callable,
    index: int,
    total: int,
) -> MergeRecord:
    """One report, announced and recorded. Shared by both paths.

    `absorbed_names` holds ids rather than names, as it always has -- the
    field's name predates the report carrying ids and is not worth a
    rename that would touch the agent-facing surface.
    """
    canonical = names.get(report.canonical_entity_id, str(report.canonical_entity_id))
    absorbed = tuple(str(i) for i in report.affected_entity_ids)
    announce(
        "consolidating",
        index=index,
        total=total,
        detail=f"{canonical} absorbed {', '.join(absorbed)} -- {report.reason}",
    )
    return MergeRecord(
        merge_id=report.event.event_id,
        canonical_name=canonical,
        absorbed_names=absorbed,
        reason=report.reason,
    )


async def build_judged_finder(
    *,
    store: GraphStore,
    vectors: VectorStore | None = None,
    judgements: AggregateRepository[EntityJudgements] | None = None,
    project_id: UUID,
) -> JudgedCandidates | None:
    """The candidate source for one consolidation run, or None for the default.

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
    if judgements is None:
        return None
    loaded_judgements = await judgements.load_or_create(project_id)
    return JudgedCandidates(
        CandidateFinder(store, vector_store=vectors),
        graph_store=store,
        tenant_id=project_id,
        judgements=loaded_judgements.state,
    )


async def consolidate_one_by_one(
    entities: Sequence[Any],
    *,
    consolidator: Consolidator,
    adjudicator: Adjudicator | None,
    finder: Any,
    announce: Callable,
    done: int,
    total: int,
    names: Mapping[Any, str],
) -> tuple[list[MergeRecord], int]:
    """The per-entity path, kept for the failure case only.

    A batch fails as a batch -- one rate-limited adjudicator call takes
    every subject in it down together, and the report can then say only
    "some of these did not consolidate". `format_ingest_report` prints the
    count, but the count was never the missing half: what a reader needs
    is which entity and why, which is why
    `test_a_consolidation_failure_says_which_entity_and_why` exists.

    So a failed batch is re-tried entity by entity, and each entity that
    fails is named in its own note.

    **The cost, stated plainly:** against an endpoint that is failing for
    a reason that will not clear -- a rate limit, an open circuit -- this
    spends one call per entity *after* having already spent the batch's.
    That is one call worse than the loop this branch replaced, in the case
    where every call is going to fail anyway. It is accepted because the
    happy path is where the calls actually are, and because a failure
    nobody can attribute costs more than a call.
    """
    merges: list[MergeRecord] = []
    failures = 0
    for position, entity in enumerate(entities, start=1):
        announce("consolidating", index=done + position, total=total, detail=entity.name)
        try:
            # The finder built for the whole run, passed down rather
            # than rebuilt here: `_judged_finder` is one event-store read
            # to load an aggregate no entity in this loop can have
            # changed, and its own docstring says once per run.
            report = await consolidator.resolve(entity, adjudicator=adjudicator, finder=finder)
        except RedstringError as error:
            # Only `ConsolidationInvariantError` is the benign
            # "absorbed earlier in this same pass" case; `RedstringError`
            # is redstring's base class and also covers `CircuitOpen`,
            # `RateLimitExceeded`, `LlmProviderError`, `MissingEntityError`
            # and `AliasCycleError`. Logged rather than raised so one
            # genuine fault does not abandon the rest, but no longer
            # indistinguishable from an ordinary absorbed entity.
            failures += 1
            logger.warning(
                "consolidating %r failed; carrying on with the rest",
                entity.name,
                exc_info=True,
            )
            announce(
                "consolidating",
                index=done + position,
                total=total,
                detail=f"{entity.name} could not be consolidated: {error}",
            )
            continue
        if report is None:
            continue
        merges.append(build_merge_record(report, names, announce, done + position, total))
    return merges, failures


class ConsolidationPipeline:
    """Coordinates batched entity consolidation, retries, and merge recording."""

    def __init__(
        self,
        consolidator: Consolidator,
        *,
        store: GraphStore,
        vectors: VectorStore | None = None,
        adjudicator: Adjudicator | None = None,
        judgements: AggregateRepository[EntityJudgements] | None = None,
        project_id: UUID,
        concurrency: int = 1,
        consolidation_batch: int = DEFAULT_CONSOLIDATION_BATCH,
        event_store: AggregateStore | None = None,
    ) -> None:
        self._consolidator = consolidator
        self._store = store
        self._vectors = vectors
        self._adjudicator = adjudicator
        self._judgements = judgements
        self._project_id = project_id
        self._concurrency = concurrency
        self._consolidation_batch = consolidation_batch
        self._event_store = event_store

    @property
    def remembers_merges_across_restarts(self) -> bool:
        """Whether `undo_merge` survives a restart. False means the log is in-memory."""
        return self._consolidator.remembers_merges_across_restarts

    async def build_finder(self) -> JudgedCandidates | None:
        """The candidate source for one consolidation run, or None for the default."""
        return await build_judged_finder(
            store=self._store,
            vectors=self._vectors,
            judgements=self._judgements,
            project_id=self._project_id,
        )

    async def entities_for(self, source_id: str) -> tuple:
        """The entities the last recorded extraction of `source_id` found.

        Read off the event rather than the graph: the event is what the repair
        path replays, so this is the same set `reconsolidate` would act on.
        """
        if self._event_store is None:
            raise KnowledgeError(
                f"no event store configured to read extraction for {source_id!r}"
            )
        stream = document_stream(tenant_id=self._project_id, source_id=source_id)
        envelopes = await collect(self._event_store.read_stream(stream))
        extractions = [
            envelope
            for envelope in envelopes
            if type(envelope.event).__name__ == "DocumentExtracted"
        ]
        if not extractions:
            raise KnowledgeError(f"no extraction recorded for source_id {source_id!r}")
        return tuple(extractions[-1].event.entities)

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
        entities = await self.entities_for(source_id)
        async with tenant_scope(self._project_id):
            merges, failures = await self.consolidate(entities)
        return tuple(merges), failures

    async def undo_merge(self, merge_id: UUID) -> MergeRecord:
        """Reverse a consolidation.

        `UnknownMergeError` covers "never happened", "already undone" and "made
        by a different consolidator" as one case, so this cannot report which --
        it says what it knows. Note that the returned `MergeRecord.reason` is `None`
        because redstring's `Consolidator.undo` attributes reasons only to merges,
        not their reversals (B6).
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

    def merge_record(
        self,
        report: Any,
        names: Mapping[Any, str],
        announce: Callable,
        index: int,
        total: int,
    ) -> MergeRecord:
        """One report, announced and recorded."""
        return build_merge_record(report, names, announce, index, total)

    async def consolidate_one_by_one(
        self,
        entities: Sequence[Any],
        *,
        finder: Any,
        announce: Callable,
        done: int,
        total: int,
        names: Mapping[Any, str],
    ) -> tuple[list[MergeRecord], int]:
        """The per-entity path, kept for the failure case only."""
        return await consolidate_one_by_one(
            entities,
            consolidator=self._consolidator,
            adjudicator=self._adjudicator,
            finder=finder,
            announce=announce,
            done=done,
            total=total,
            names=names,
        )

    async def consolidate(
        self,
        entities: Iterable[Any],
        *,
        announce: Callable = _no_announcement,
    ) -> tuple[list[MergeRecord], int]:
        """Resolve the extracted entities in batches, not one at a time.

        `resolve_many` is redstring's decide-then-emit pass: candidates are
        scored concurrently, the whole batch's ambiguous band goes to the
        adjudicator in **one** `adjudicate_many` call spanning subjects, and
        the merges are emitted serially. The serial emit is not a limitation
        to route around -- `ConsolidationLog` uses optimistic concurrency and
        the stream *is* the tenant, so two concurrent merges within one
        project collide by construction.

        What this buys is the number `config.extraction_chunk_size`'s
        docstring names as the one to watch: adjudicator calls per document.
        Auto-merge is unreachable across documents (see the note above
        `_CountingProvider`), so every cross-document duplicate is
        adjudicated, and `Adjudicator.adjudicate` batches only *within* one
        subject -- where the band is nearly always one pair. Per entity that
        was one round trip each.
        `test_batched_consolidation.py` counts it at the provider seam: three
        duplicates cost `[1, 1, 1]` through the old loop and `[3]` through
        this one.

        `announce` defaults to silence because `reconsolidate` also calls this
        and has no watcher. The progress it reports is now per *batch* rather
        than per entity -- the pane renders `index/total`, and the counter
        advances a batch at a time and then holds while phase 2 waits on the
        model. That is a real loss of resolution against the per-entity loop
        and it is the price of the batching: no per-subject callback can exist
        when the whole point is that the subjects are decided together.

        A batch that raises does not abandon the rest, for the reason it never
        did: the extraction is already recorded and the merges that succeeded
        are already folded. It is *retried entity by entity* first -- see
        `_consolidate_one_by_one` for what that costs and why it is worth it.
        """
        entities = list(entities)
        merges: list[MergeRecord] = []
        failures = 0
        total = len(entities)
        finder = await self.build_finder()
        # `subject.id` is what a report names, and `resolve_many` resolves each
        # subject through aliases before deciding -- so the canonical entity of
        # a merge is not always the entity that was passed in. Looked up by id
        # rather than carried alongside, with the id itself as the fallback,
        # because a `MergeRecord` naming the wrong entity is an audit trail
        # that lies while looking complete.
        names = {entity.id: entity.name for entity in entities}
        done = 0
        for batch in _batches(entities, self._consolidation_batch):
            announce(
                "consolidating",
                index=done,
                total=total,
                detail=f"considering {len(batch)} entities",
            )
            try:
                reports = await self._consolidator.resolve_many(
                    batch,
                    finder=finder,
                    adjudicator=self._adjudicator,
                    concurrency=self._concurrency,
                )
            except RedstringError:
                # Deliberately not counted as `len(batch)` failures here: the
                # retry below is what decides how many entities actually
                # failed, and it is also the only thing that can say *which*.
                logger.warning(
                    "consolidating a batch of %d failed; retrying it one at a time",
                    len(batch),
                    exc_info=True,
                )
                batch_merges, batch_failures = await self.consolidate_one_by_one(
                    batch,
                    finder=finder,
                    announce=announce,
                    done=done,
                    total=total,
                    names=names,
                )
                merges += batch_merges
                failures += batch_failures
                done += len(batch)
                continue
            done += len(batch)
            for report in reports:
                merges.append(self.merge_record(report, names, announce, done, total))
            # Announced again after the batch, not only before it. The pane
            # renders `index/total`, and with only the leading announce the
            # counter shows what was done *before* this batch and never
            # reaches `total` -- a bar that stops at 0/2 on a two-entity
            # document and then jumps straight to `consolidated`.
            announce(
                "consolidating",
                index=done,
                total=total,
                detail=f"{len(merges)} merged so far",
            )
        return merges, failures


async def consolidate_entities(
    entities: Iterable[Any],
    *,
    consolidator: Consolidator,
    store: GraphStore,
    vectors: VectorStore | None = None,
    adjudicator: Adjudicator | None = None,
    judgements: AggregateRepository[EntityJudgements] | None = None,
    project_id: UUID,
    concurrency: int = 1,
    consolidation_batch: int = DEFAULT_CONSOLIDATION_BATCH,
    announce: Callable = _no_announcement,
) -> tuple[list[MergeRecord], int]:
    """Resolve extracted entities using a ConsolidationPipeline."""
    pipeline = ConsolidationPipeline(
        consolidator,
        store=store,
        vectors=vectors,
        adjudicator=adjudicator,
        judgements=judgements,
        project_id=project_id,
        concurrency=concurrency,
        consolidation_batch=consolidation_batch,
    )
    return await pipeline.consolidate(entities, announce=announce)
