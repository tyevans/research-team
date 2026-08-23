"""`CatalogFeatureRecorder` over the event store.

The only place this feature appends. Featuring and unfeaturing enforce no
invariant -- `domain/catalog_curation.py` says so at length, and this mirrors
`EventStoreOntologyRecorder`'s reasoning for the same shape: no aggregate to
consult, so the event goes straight to the store rather than through a
`DeciderAggregate`.
"""

from uuid import UUID

from eventsource import ExpectedVersion, InMemoryEventBus, StreamId
from eventsource.adapters.sqlite import SQLiteEventStore

from research_team.domain.catalog_curation import (
    CATALOG_AGGREGATE_TYPE,
    CourseFeatured,
    CourseUnfeatured,
)


class EventStoreCatalogFeatureRecorder:
    """Appends one project's featuring decisions, bound to that project.

    Bound at construction rather than taking a `project_id` per call, matching
    every other per-project adapter here -- the only project a caller can
    write to is the one it was handed.
    """

    def __init__(
        self, store: SQLiteEventStore, publisher: InMemoryEventBus, project_id: UUID
    ) -> None:
        self._store = store
        self._publisher = publisher
        self._project_id = project_id

    async def feature(self, slug: str, rank: int) -> None:
        event = CourseFeatured(
            aggregate_id=self._project_id, project_id=self._project_id, slug=slug, rank=rank
        )
        await self._append(event)

    async def unfeature(self, slug: str) -> None:
        event = CourseUnfeatured(
            aggregate_id=self._project_id, project_id=self._project_id, slug=slug
        )
        await self._append(event)

    async def _append(self, event: CourseFeatured | CourseUnfeatured) -> None:
        await self._store.append(
            StreamId(self._project_id, CATALOG_AGGREGATE_TYPE),
            [event],
            # `any_()`, not an exact version, for `EventStoreOntologyRecorder`'s
            # reason: this stream protects no invariant, and a person clicking
            # feature on two candidates in the same project must not have the
            # second click fail on a version race it has no reason to care
            # about.
            ExpectedVersion.any_(),
        )
        # Appending is not delivering -- `SubscriptionManager` catches a
        # projection up from the store and then follows the bus for anything
        # after that, so an append nobody publishes reaches a running
        # projection only on the next restart or rebuild. Every writer that
        # goes through `AggregateRepository` gets this for free; this recorder
        # has no aggregate, so it publishes by hand, exactly as
        # `EventStoreOntologyRecorder` does and for the same reason its own
        # comment gives: left out, `feature` answers 200, nothing raises, and
        # the hero row never moves until something else restarts the process.
        await self._publisher.publish([event])
