"""Projection runners and realization wrappers for following the event log."""

from collections.abc import Sequence
from uuid import UUID

from eventsource import InMemoryEventBus
from eventsource.adapters.sqlite import SQLiteEventStore

from research_team.application.curriculum.course_realization import RealizedCourse
from research_team.infrastructure.persistence.read_models import (
    AuthoringRunRunner,
    BaseProjectionRunner,
    CatalogFeatureProjection,
    CatalogFeatureStore,
    CourseProjection,
    CourseRow,
    CourseStore,
)


class _CatalogFeatureRunner(BaseProjectionRunner[CatalogFeatureStore]):
    """Keeps `catalog_features` following the log, over the application's own
    event store and publisher rather than a second one -- catalog events
    (`CourseFeatured`/`CourseUnfeatured`) sit on their own aggregate type and
    stream, so this only ever needs to agree with `catalog_recorder`'s
    writes over the same file, matching `CatalogFeatureProjection`'s own
    reasoning.

    Mirrors `OntologyRunner` in shape, but is not one: `Application` exposes
    `catalog_features` as the `CatalogFeatureStore` itself, not a runner
    wrapping it, per the contract Task 9's reviewer wrote down -- so this
    class lives here instead, private, and `catalog_features` below is a
    property reading through its `features` attribute. `Application` is
    `frozen=True` (see `_initial_project_id`'s docstring), so `start()`
    cannot rebind a field to the store once it is open; a property reading
    through a mutable holder is what the rest of this class already does for
    exactly that reason.
    """

    _label = "catalog feature"
    _store_class = CatalogFeatureStore
    _projection_class = CatalogFeatureProjection

    def __init__(self, store: SQLiteEventStore, bus: InMemoryEventBus, db_path: str) -> None:
        super().__init__(store=store, db_path=db_path, bus=bus)

    @property
    def features(self) -> CatalogFeatureStore | None:
        return self._store_instance

    def _caught_up_timeout_message(self, target: int | None, timeout: float) -> str:
        return "the catalog feature projection did not catch up in time"


class _CourseRunner(BaseProjectionRunner[CourseStore]):
    """Keeps `courses` following the log, mirroring `_CatalogFeatureRunner`
    exactly and for the same reason: `CourseStore.open` needs a running event
    loop, so it opens in `start()`, and `Application` is `frozen=True`
    (see `_initial_project_id`'s docstring), so `courses` below has to read
    through this runner's mutable `courses` attribute rather than being a
    field `start()` could rebind once the store is open.

    Over the application's own event store and publisher, not a second one --
    `CourseRealized`/`CourseAbandoned` sit on `Course`'s own aggregate type
    and stream, so this only ever needs to agree with `course_repository`'s
    writes over the same file.
    """

    _label = "course"
    _store_class = CourseStore
    _projection_class = CourseProjection

    def __init__(self, store: SQLiteEventStore, bus: InMemoryEventBus, db_path: str) -> None:
        super().__init__(store=store, db_path=db_path, bus=bus)

    @property
    def courses(self) -> CourseStore | None:
        return self._store_instance

    def _caught_up_timeout_message(self, target: int | None, timeout: float) -> str:
        return "the course projection did not catch up in time"


class _RealizedCourses:
    """`RealizedCoursePort` joining `_CourseRunner`'s store with
    `AuthoringRunRunner.authored_session_for` -- the join `RealizedCoursePort`'s
    own docstring assigns to the adapter, not the port.

    Reads through `_CourseRunner` lazily, the same way `CatalogService`'s
    routes read through `catalog_features`: `CourseService` (this adapter's
    only caller) is built before `start()` has opened `courses`, so a request
    reaching this adapter before startup finishes raises rather than silently
    answering "nothing realized" -- the distinction `_started()` on
    `AuthoringRunRunner` already draws for the same reason.
    """

    def __init__(self, course_runner: _CourseRunner, authoring: AuthoringRunRunner) -> None:
        self._course_runner = course_runner
        self._authoring = authoring

    def _store(self) -> CourseStore:
        store = self._course_runner.courses
        if store is None:
            raise RuntimeError("the course projection has not been started")
        return store

    async def for_project(self, project_id: UUID) -> Sequence[RealizedCourse]:
        rows = await self._store().for_project(project_id)
        return tuple([await self._joined(project_id, row) for row in rows])

    async def get(self, project_id: UUID, slug: str) -> RealizedCourse | None:
        row = await self._store().get(project_id, slug)
        if row is None or row.abandoned:
            # `CourseStore.get` answers regardless of `abandoned` -- see its
            # own docstring -- but `RealizedCoursePort`'s contract
            # (`course_realization.py`) is that every implementation returns
            # only non-abandoned rows, so that filter belongs here.
            return None
        return await self._joined(project_id, row)

    async def _joined(self, project_id: UUID, row: CourseRow) -> RealizedCourse:
        authored_session_id = await self._authoring.authored_session_for(project_id, row.slug)
        return RealizedCourse(
            slug=row.slug,
            title=row.title,
            member_entity_ids=tuple(row.member_entity_ids),
            membership_hash=row.membership_hash,
            realized_at=row.realized_at,
            authored_session_id=authored_session_id,
        )
