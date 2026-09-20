"""Course catalog, blurb, outline, and featured read models, stores, and projections.

Houses read-side state and projections for courses, blurbs, outlines, and catalog features.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID, uuid5

import aiosqlite
from eventsource import (
    DeclarativeProjection,
    ReadModel,
    handles,
)
from eventsource.adapters.sqlite.readmodels import SQLiteReadModelRepository
from eventsource.ports.readmodels import (
    Filter,
    Query,
    ReadModelRepository,
)
from pydantic import Field, field_validator

from research_team.domain.catalog_curation import CourseFeatured, CourseUnfeatured
from research_team.domain.course import CourseAbandoned, CourseRealized
from research_team.infrastructure.persistence.store_base import (
    CATALOG_NAMESPACE,
    LOCAL_RETRY_POLICY,
    BaseReadModelStore,
    open_readmodel_connection,
)

__all__ = [
    "CatalogFeatureProjection",
    "CatalogFeatureRow",
    "CatalogFeatureStore",
    "CourseBlurbRow",
    "CourseBlurbStore",
    "CourseOutlineRow",
    "CourseOutlineStore",
    "CourseProjection",
    "CourseRow",
    "CourseStore",
]


class CatalogFeatureRow(ReadModel):
    """One candidate somebody put on the front page.

    Keyed by `(project_id, slug)` through `row_id`, so featuring the same slug
    twice moves its rank rather than adding a second row. That idempotence is
    what lets the route be a plain POST with no read-modify-write.
    """

    __table_name__ = "catalog_features"

    project_id: UUID
    slug: str
    rank: int = 0

    @staticmethod
    def row_id(project_id: UUID, slug: str) -> UUID:
        return uuid5(CATALOG_NAMESPACE, f"{project_id}:{slug}")


class CourseBlurbRow(ReadModel):
    """One generated blurb, cached against the cluster it describes.

    A cache and not a projection's own state, exactly like
    `EntityDefinitionRow`: the catalog service's `put` is the only writer.

    Unlike that row there is no `stale` flag, and the difference is
    deliberate. A definition is invalidated by graph events this table never
    reads, so it needs a flag something else can set. A blurb carries
    `membership_hash`, which answers the same question *by comparison* -- the
    caller already holds the current hash and can see the disagreement
    itself. A flag would be a second answer to one question, and the two
    would drift.
    """

    __table_name__ = "course_blurbs"

    project_id: UUID
    slug: str
    text: str
    membership_hash: str
    model: str
    generated_at: str
    title: str = ""
    """A generated course title, not the anchor entity's name -- Task 15.

    Defaulted, not required: `apply_schema` reconciles an added column onto a
    table that already has rows, but it leaves the column empty in every row
    that predates it. A required column with no default is refused outright
    on a populated table -- see CLAUDE.md's "Read models" section, which
    records this project shipping exactly that bug once. `""` is the honest
    value for "generated before this field existed", and
    `CatalogService.build`'s `cached.title or area.display_name()` is the
    fallback that covers it."""

    @staticmethod
    def row_id(project_id: UUID, slug: str) -> UUID:
        # The `blurb:` prefix keeps this id from colliding with
        # `CatalogFeatureRow.row_id`, which shares `CATALOG_NAMESPACE` and
        # hashes the same `{project_id}:{slug}` pair with no prefix of its
        # own.
        return uuid5(CATALOG_NAMESPACE, f"blurb:{project_id}:{slug}")


class CourseBlurbStore(BaseReadModelStore):
    """The blurb cache table and the connection it owns.

    No projection here, matching `EntityDefinitionStore`: nothing on the
    event log describes a blurb, so there is nothing for a projection to
    replay. The catalog service calls `put` directly after generating one.
    """

    def __init__(self, connection: aiosqlite.Connection, rows: ReadModelRepository) -> None:
        super().__init__(connection)
        self._rows = rows

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> CourseBlurbStore:
        connection = await open_readmodel_connection(db_path, CourseBlurbRow)
        # `apply_schema` reconciles columns, not indexes -- the same note
        # `EntityDefinitionStore.open` carries, for the same reason: every
        # read here is project-scoped.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_course_blurbs_project "
            f"ON {CourseBlurbRow.table_name()}(project_id)"
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, CourseBlurbRow, tracer)
        return cls(connection, rows)

    async def get(self, project_id: UUID, slug: str) -> CourseBlurbRow | None:
        """The cached blurb, or None if none has been generated yet.

        `row.project_id != project_id` cannot happen through this class's
        own `row_id` -- the pair is baked into the id -- but is checked
        anyway for the same reason `EntityDefinitionStore.get` checks it: a
        row reached by id alone makes no claim about which project asked.
        """
        row = await self._rows.get(CourseBlurbRow.row_id(project_id, slug))
        if row is None or row.project_id != project_id:
            return None
        return row

    async def all_for_project(self, project_id: UUID) -> dict[str, CourseBlurbRow]:
        """Every cached blurb for this project, keyed by slug, in one query.

        `CatalogService.build` used to call `get` once per area -- an N+1
        over the areas in a curriculum. `idx_course_blurbs_project` already
        exists for exactly this read and nothing used it. A slug absent from
        the returned dict means "not cached", the same thing `get` returning
        `None` means, so a caller can switch from `await get(project_id,
        slug)` to `cache.get(slug)` on this dict without changing what
        "missing" means.
        """
        rows = await self._rows.find(Query(filters=[Filter.eq("project_id", str(project_id))]))
        return {row.slug: row for row in rows}

    async def put(
        self,
        project_id: UUID,
        slug: str,
        title: str,
        text: str,
        membership_hash: str,
        model: str,
        generated_at: datetime,
    ) -> None:
        """Cache a blurb, superseding whatever was cached before for this
        slug -- `save` writes by id, and `row_id` is stable per
        `(project_id, slug)`, so a rewrite replaces rather than duplicates.
        """
        await self._rows.save(
            CourseBlurbRow(
                id=CourseBlurbRow.row_id(project_id, slug),
                project_id=project_id,
                slug=slug,
                text=text,
                membership_hash=membership_hash,
                model=model,
                generated_at=generated_at.isoformat(),
                title=title,
            )
        )


class CourseOutlineRow(ReadModel):
    """One generated outline, cached against the cluster it describes.

    Its own table rather than a `kind` column beside `CourseBlurbRow`. A blurb's
    payload is one `text` column and this one's is a structured list, so a
    shared table needs a JSON column that only half its rows ever fill -- and
    then the two row types share nothing but a primary key and a namespace. Two
    stores of the same shape are duplication a reader can see; one store with a
    column meaningful for half its rows is a schema that has to be explained.

    No `stale` flag, for `CourseBlurbRow`'s reason: `membership_hash` answers
    the same question by comparison, and a flag would be a second answer that
    can disagree with the first.
    """

    __table_name__ = "course_outlines"

    project_id: UUID
    slug: str
    promise: str
    sections: list[dict] = Field(default_factory=list)
    """`[{"heading": ..., "summary": ...}]`, in reading order."""
    membership_hash: str
    model: str
    generated_at: str

    @field_validator("sections", mode="before")
    @classmethod
    def _decode_json_list(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def row_id(project_id: UUID, slug: str) -> UUID:
        # The `outline:` prefix keeps this id from colliding with
        # `CourseBlurbRow.row_id` and `CatalogFeatureRow.row_id`, which share
        # `CATALOG_NAMESPACE` and hash the same `{project_id}:{slug}` pair
        # with their own (or no) prefix.
        return uuid5(CATALOG_NAMESPACE, f"outline:{project_id}:{slug}")


class CourseOutlineStore(BaseReadModelStore):
    """The outline cache table and the connection it owns.

    No projection here, matching `CourseBlurbStore`: nothing on the event log
    describes an outline, so there is nothing for a projection to replay. The
    catalog service calls `put` directly after generating one.
    """

    def __init__(self, connection: aiosqlite.Connection, rows: ReadModelRepository) -> None:
        super().__init__(connection)
        self._rows = rows

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> CourseOutlineStore:
        connection = await open_readmodel_connection(db_path, CourseOutlineRow)
        # `apply_schema` reconciles columns, not indexes -- the same note
        # `CourseBlurbStore.open` carries, for the same reason: every read
        # here is project-scoped.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_course_outlines_project "
            f"ON {CourseOutlineRow.table_name()}(project_id)"
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, CourseOutlineRow, tracer)
        return cls(connection, rows)

    async def get(self, project_id: UUID, slug: str) -> CourseOutlineRow | None:
        """The cached outline, or None if none has been generated yet.

        `row.project_id != project_id` cannot happen through this class's
        own `row_id` -- the pair is baked into the id -- but is checked
        anyway for the same reason `CourseBlurbStore.get` checks it: a row
        reached by id alone makes no claim about which project asked.
        """
        row = await self._rows.get(CourseOutlineRow.row_id(project_id, slug))
        if row is None or row.project_id != project_id:
            return None
        return row

    async def put(
        self,
        project_id: UUID,
        slug: str,
        promise: str,
        sections: list[dict],
        membership_hash: str,
        model: str,
        generated_at: datetime,
    ) -> None:
        """Cache an outline, superseding whatever was cached before for this
        slug -- `save` writes by id, and `row_id` is stable per
        `(project_id, slug)`, so a rewrite replaces rather than duplicates.
        """
        await self._rows.save(
            CourseOutlineRow(
                id=CourseOutlineRow.row_id(project_id, slug),
                project_id=project_id,
                slug=slug,
                promise=promise,
                sections=sections,
                membership_hash=membership_hash,
                model=model,
                generated_at=generated_at.isoformat(),
            )
        )


class CatalogFeatureStore(BaseReadModelStore):
    """The featured table and the connection it owns."""

    def __init__(self, connection: aiosqlite.Connection, rows: ReadModelRepository) -> None:
        super().__init__(connection)
        self._rows = rows

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> CatalogFeatureStore:
        connection = await open_readmodel_connection(db_path, CatalogFeatureRow)
        # `apply_schema` reconciles columns, not indexes -- the same note
        # `EntityDefinitionStore.open` carries, for the same reason: every
        # read here is project-scoped.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_catalog_features_project "
            f"ON {CatalogFeatureRow.table_name()}(project_id)"
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, CatalogFeatureRow, tracer)
        return cls(connection, rows)

    async def feature(self, project_id: UUID, slug: str, rank: int) -> None:
        await self._rows.save(
            CatalogFeatureRow(
                id=CatalogFeatureRow.row_id(project_id, slug),
                project_id=project_id,
                slug=slug,
                rank=rank,
            )
        )

    async def unfeature(self, project_id: UUID, slug: str) -> None:
        """Deleting something absent is a no-op, not an error.

        This is driven by a projection over a log that may hold an unfeature
        for a slug whose feature was never projected -- a rebuild from an
        arbitrary checkpoint does exactly that -- and raising here would put a
        routine replay in the dead-letter queue.
        """
        await self._rows.delete(CatalogFeatureRow.row_id(project_id, slug))

    async def featured_for(self, project_id: UUID) -> dict[str, int]:
        cursor = await self._connection.execute(
            f"SELECT slug, rank FROM {CatalogFeatureRow.table_name()} "
            "WHERE project_id = ? AND deleted_at IS NULL",
            (str(project_id),),
        )
        try:
            return {row[0]: row[1] for row in await cursor.fetchall()}
        finally:
            await cursor.close()


class CatalogFeatureProjection(DeclarativeProjection):
    """Keeps `catalog_features` level with the curation events."""

    def __init__(
        self,
        store: CatalogFeatureStore,
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._store = store
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(CourseFeatured)
    async def _featured(self, event: CourseFeatured) -> None:
        await self._store.feature(event.project_id, event.slug, event.rank)

    @handles(CourseUnfeatured)
    async def _unfeatured(self, event: CourseUnfeatured) -> None:
        await self._store.unfeature(event.project_id, event.slug)


class CourseRow(ReadModel):
    """A realized course: the frozen membership `CourseRealized` carried,
    kept so it survives a restart without folding the log.

    Keyed by `(project_id, slug)` through `row_id`, exactly like
    `CourseBlurbRow` and `CatalogFeatureRow` -- all three share
    `CATALOG_NAMESPACE` and hash the same pair, so the `course:` prefix below
    is what keeps this row's id from colliding with theirs.
    """

    __table_name__ = "courses"

    project_id: UUID
    slug: str
    title: str
    member_entity_ids: list[str] = Field(default_factory=list)
    membership_hash: str
    realized_at: datetime
    abandoned: bool = False
    """Marked rather than deleted, so a rebuild replaying `CourseRealized`
    then `CourseAbandoned` lands where a rebuild replaying only the first
    does not. A delete would make abandonment invisible to the replay that
    follows it: a rebuild that stops (or starts) between the two events
    would resurrect a course whose row was removed rather than flagged."""

    @field_validator("member_entity_ids", mode="before")
    @classmethod
    def _decode_json_list(cls, value: object) -> object:
        # `AuthoringRunRow._decode_json_list`'s pattern: SQLite has no list
        # column, so `member_entity_ids` round-trips through this table as a
        # JSON string and needs decoding back on the way out.
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def row_id(project_id: UUID, slug: str) -> UUID:
        # `course:` for the reason `CourseBlurbRow` gives for `blurb:` --
        # three row types now share CATALOG_NAMESPACE over the same
        # {project}:{slug} pair.
        return uuid5(CATALOG_NAMESPACE, f"course:{project_id}:{slug}")


class CourseStore(BaseReadModelStore):
    """The courses table and the connection it owns."""

    def __init__(self, connection: aiosqlite.Connection, rows: ReadModelRepository) -> None:
        super().__init__(connection)
        self._rows = rows

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> CourseStore:
        connection = await open_readmodel_connection(db_path, CourseRow)
        # `apply_schema` reconciles columns, not indexes -- the same note
        # `CourseBlurbStore.open` carries, for the same reason: every read
        # here is project-scoped.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_courses_project "
            f"ON {CourseRow.table_name()}(project_id)"
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, CourseRow, tracer)
        return cls(connection, rows)

    async def get(self, project_id: UUID, slug: str) -> CourseRow | None:
        """The row for this slug, regardless of `abandoned`, or None if it
        has never been realized.

        `row.project_id != project_id` cannot happen through this class's
        own `row_id` -- the pair is baked into the id -- but is checked
        anyway for the reason `CourseBlurbStore.get` checks it: a row reached
        by id alone makes no claim about which project asked.
        """
        row = await self._rows.get(CourseRow.row_id(project_id, slug))
        if row is None or row.project_id != project_id:
            return None
        return row

    async def for_project(self, project_id: UUID) -> list[CourseRow]:
        """Every non-abandoned course in this project. `abandoned` rows are
        omitted here rather than absent from the table -- see `CourseRow`."""
        return await self._rows.find(
            Query(
                filters=[
                    Filter.eq("project_id", str(project_id)),
                    Filter.eq("abandoned", False),
                ]
            )
        )

    async def realize(
        self,
        project_id: UUID,
        slug: str,
        title: str,
        member_entity_ids: list[str],
        membership_hash: str,
        realized_at: datetime,
    ) -> None:
        """Write (or rewrite) the row -- `save` writes by id, and `row_id`
        is stable per `(project_id, slug)`, so a second `CourseRealized` for
        an already-abandoned slug reinstates it rather than duplicating."""
        await self._rows.save(
            CourseRow(
                id=CourseRow.row_id(project_id, slug),
                project_id=project_id,
                slug=slug,
                title=title,
                member_entity_ids=member_entity_ids,
                membership_hash=membership_hash,
                realized_at=realized_at,
                abandoned=False,
            )
        )

    async def abandon(self, project_id: UUID, slug: str) -> None:
        """Mark the row abandoned rather than deleting it -- see `CourseRow`
        for why. A no-op if the slug was never realized: a rebuild from an
        arbitrary checkpoint may replay an abandon whose realize predates the
        checkpoint, and raising here would put a routine replay in the
        dead-letter queue (the same reasoning `CatalogFeatureStore.unfeature`
        gives for tolerating a delete of something absent)."""
        row = await self.get(project_id, slug)
        if row is None:
            return
        await self._rows.save(row.model_copy(update={"abandoned": True}))


class CourseProjection(DeclarativeProjection):
    """Keeps `courses` level with the realization events."""

    def __init__(
        self,
        store: CourseStore,
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._store = store
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(CourseRealized)
    async def _realized(self, event: CourseRealized) -> None:
        await self._store.realize(
            event.project_id,
            event.slug,
            event.title,
            event.member_entity_ids,
            event.membership_hash,
            event.realized_at,
        )

    @handles(CourseAbandoned)
    async def _abandoned(self, event: CourseAbandoned) -> None:
        await self._store.abandon(event.project_id, event.slug)
