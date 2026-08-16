"""`OntologyRecordPort` over the event store.

The only place this feature appends. `OntologyDiscovered` enforces no invariant
-- a pass replaces a source's classes wholesale and re-running it is idempotent
by construction -- so it goes straight to the store rather than through a
`DeciderAggregate`, exactly as redstring appends `DocumentExtracted` without
consulting one of this application's aggregates. See `domain/ontology.py` for
the full reasoning.
"""

from uuid import UUID

from eventsource import ExpectedVersion, InMemoryEventBus, StreamId
from eventsource.adapters.sqlite import SQLiteEventStore

from research_team.domain.ontology import (
    ONTOLOGY_AGGREGATE_TYPE,
    DiscoveredClass,
    OntologyDiscovered,
)


class EventStoreOntologyRecorder:
    """Appends one project's discovery events, bound to that project.

    Bound at construction rather than taking a `project_id` per call, matching
    every other per-project adapter here: the only project a caller can write
    to is the one it was handed.
    """

    def __init__(
        self, store: SQLiteEventStore, publisher: InMemoryEventBus, project_id: UUID
    ) -> None:
        self._store = store
        self._publisher = publisher
        self._project_id = project_id

    async def record(
        self, source_id: str, model_version: str, classes: list[DiscoveredClass]
    ) -> None:
        """Record what a pass found in one document, including nothing.

        An empty `classes` is appended, not skipped: it is the only record that
        this document was examined at all, and the `ungrouped` sweep is built on
        being able to tell "states no classes" from "never looked at".
        """
        event = OntologyDiscovered(
            aggregate_id=self._project_id,
            project_id=self._project_id,
            source_id=source_id,
            model_version=model_version,
            classes=classes,
        )
        await self._store.append(
            StreamId(self._project_id, ONTOLOGY_AGGREGATE_TYPE),
            [event],
            # `any_()`, not an exact version. This stream protects no invariant
            # -- there is no aggregate and no state to conflict with -- and a
            # project-wide sweep runs one pass per document against a single
            # stream, so an exact version would make the second document's
            # append fail on a race it has no reason to care about. The stream
            # is an append-only record of what each pass found, and the
            # projection replaces by `source_id`, so ordering between two
            # documents' events carries no meaning to lose.
            ExpectedVersion.any_(),
        )
        # **Appending is not delivering, and the difference is silent.**
        # `SubscriptionManager` catches a projection up from the store and then
        # transitions to live events *from the bus*, so an append nobody
        # publishes reaches a running projection only on a restart or a
        # rebuild. Every other writer in this codebase gets this for free from
        # `AggregateRepository(event_publisher=...)`; this recorder deliberately
        # has no aggregate, so it has to do the publishing half itself.
        #
        # Left out, the failure is exactly the one this feature is arranged
        # against: `discover` returns the number it found, nothing raises,
        # nothing logs, and every class request answers with an empty list.
        # It shipped that way through a green unit suite, which published by
        # hand, and was caught by `tests/integration/test_ontology_wiring.py`
        # asking a composed application for a row.
        await self._publisher.publish([event])
