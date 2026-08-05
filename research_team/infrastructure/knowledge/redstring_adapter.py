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

from uuid import UUID

from eventsource import collect
from eventsource.domain.tenant_context import tenant_scope
from eventsource.ports.positions import ExpectedVersion
from eventsource.ports.snapshots import SnapshotStore
from eventsource.ports.store import AggregateStore
from redstring import (
    AUTO,
    Adjudicator,
    Consolidator,
    GraphStore,
    LlmProvider,
    RedstringError,
    SourceDocument,
    build_graph,
)
from redstring.events.streams import document_stream

from research_team.application.knowledge import (
    IngestReport,
    KnowledgeError,
    Match,
    MergeRecord,
    SourceRef,
)

#: Longest document accepted in one `remember`. Roughly a long article.
MAX_DOCUMENT_CHARS = 200_000


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
        domain: str = "auto",
        adjudicate: bool = True,
    ) -> None:
        self._project_id = project_id
        self._store = store
        self._event_store = event_store
        self._provider = provider
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

    async def ingest(self, source: SourceRef) -> IngestReport:
        if not source.source_id.strip():
            raise KnowledgeError("source_id must not be blank; it identifies the document")
        if len(source.text) > MAX_DOCUMENT_CHARS:
            # Capped rather than chunked-without-limit. redstring chunks a long
            # document, which multiplies model calls rather than bounding them,
            # so the bound has to come from here.
            raise KnowledgeError(
                f"that is {len(source.text)} characters; the limit is "
                f"{MAX_DOCUMENT_CHARS}. Record it in parts, each with its own "
                f"source_id."
            )

        document = SourceDocument(
            id=source.source_id,
            text=source.text,
            metadata={"note": source.note} if source.note else {},
        )
        try:
            async with tenant_scope(self._project_id):
                report = await build_graph(
                    document,
                    provider=self._provider,
                    store=self._store,
                    tenant_id=self._project_id,
                    domain=self._domain,
                )
                if report.event is None:
                    # `Document.record_extraction` found nothing new to record
                    # -- the same content and model version as a previous run.
                    return IngestReport(
                        source_id=source.source_id,
                        entity_count=0,
                        relationship_count=0,
                        domain=report.domain,
                        domain_confidence=report.domain_confidence,
                    )

                await self._event_store.append(
                    document_stream(tenant_id=self._project_id, source_id=source.source_id),
                    [report.event],
                    ExpectedVersion.any_(),
                )
                merges, failures = await self._consolidate(report.event.entities)
        except KnowledgeError:
            raise
        except (RedstringError, ValueError) as error:
            raise KnowledgeError(str(error)) from error
        except Exception as error:  # provider transports raise their own types
            raise KnowledgeError(f"extraction failed: {error}") from error

        return IngestReport(
            source_id=source.source_id,
            entity_count=len(report.event.entities),
            relationship_count=len(report.event.relationships),
            domain=report.domain,
            domain_confidence=report.domain_confidence,
            merges=tuple(merges),
            consolidation_failures=failures,
        )

    async def _consolidate(self, entities) -> tuple[list[MergeRecord], int]:
        """Resolve each extracted entity, one at a time.

        `resolve` is per-entity by design, and it emits its own event, so this
        collects rather than appends. A failure on one entity does not abandon
        the rest: the extraction is already recorded and the merges that
        succeeded are already folded, so stopping here would leave less of the
        graph consolidated for no gain.
        """
        merges: list[MergeRecord] = []
        failures = 0
        for entity in entities:
            try:
                report = await self._consolidator.resolve(
                    entity, adjudicator=self._adjudicator
                )
            except RedstringError:
                # Typically the entity was absorbed by a merge earlier in this
                # same loop, which is a normal outcome rather than a fault.
                failures += 1
                continue
            if report is None:
                continue
            merges.append(
                MergeRecord(
                    merge_id=report.event.event_id,
                    canonical_name=entity.name,
                    absorbed_names=tuple(str(i) for i in report.affected_entity_ids),
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
                matches = []
                for entity in entities:
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
