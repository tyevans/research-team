"""Art and candidate art read models and stores.

Houses the global art library and per-candidate art assignment read models.
"""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID, uuid5

import aiosqlite
from eventsource import ReadModel
from eventsource.adapters.sqlite.readmodels import SQLiteReadModelRepository
from eventsource.ports.readmodels import ReadModelRepository
from pydantic import Field, field_validator

from research_team.infrastructure.persistence.store_base import (
    CATALOG_NAMESPACE,
    BaseReadModelStore,
    open_readmodel_connection,
)

__all__ = [
    "ArtRow",
    "ArtStore",
    "CandidateArtRow",
    "CandidateArtStore",
]


class ArtRow(ReadModel):
    """One piece of art in the global library.

    `art_id` is `uuid4`, minted once by the writer and never derived from a
    slug or any other input -- unlike every id in this module built through
    `uuid5(CATALOG_NAMESPACE, ...)`. Those are deliberately *derivable*, so
    that looking a row up again needs no index: give the same
    `(project_id, slug)` and you get the same id back. Art is the opposite
    case on purpose. The whole point of a library (increment 3's "Why") is
    that one picture is reusable across many candidates and many projects --
    a derived id would tie a picture to whichever slug happened to generate
    it first, and every other card that could reuse it would need its own
    copy of the same bytes with a different id instead of one row with
    `uses` counted up. `CandidateArtRow` below is the derivable mapping;
    this is the thing it points at.
    """

    __table_name__ = "art_library"

    svg: str
    """Sanitised before this is ever constructed -- see `ArtStore.put`'s
    docstring for why storage does not re-check it and the serving route
    does."""
    description: str
    """What the picture depicts, in words. This is the search key the
    sibling task's lexical search reads -- token overlap against a
    candidate's title and anchor names -- not a caption shown to a person."""
    tags: list[str] = Field(default_factory=list)
    palette: str = ""
    """The category key this was drawn for (`"work"`, `"person"`, ...), or
    `""` for a piece with no category affinity. Matches `SeededArtProvider`'s
    `CategoryKey` vocabulary but is stored as a plain string rather than that
    type -- this table outlives any one category scheme, and a string needs
    no migration if the scheme's vocabulary grows."""
    # `created_at` is not redeclared here -- `ReadModel` already carries it
    # as a `datetime` with a UTC default, and every other row in this module
    # that wants a distinctly-named generation timestamp (`generated_at` on
    # `CourseBlurbRow`/`CourseOutlineRow`) declares a second field rather
    # than fighting the base one. The spec's `created_at: datetime` is that
    # base field, not a second one.
    source: str
    """`"generated"` or `"seeded"` -- literal strings rather than an enum for
    the same reason similarly-shaped fields elsewhere in this module are
    plain strings: a read model's job is to be read by a query, and a query
    does not care whether Python enforces the vocabulary, only that the
    value on disk is one of the two."""
    uses: int = 0
    """How many `CandidateArtRow`s currently point at this. Bumped by
    `increment_uses`, not recomputed by counting -- see that method's
    docstring for why."""

    @field_validator("tags", mode="before")
    @classmethod
    def _decode_json_list(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value


class ArtStore(BaseReadModelStore):
    """The art library table and the connection it owns.

    A cache, not a projection, for `CourseBlurbStore`'s exact reason: nothing
    on the event log describes a piece of art -- there is no `ArtGenerated`
    event this table replays -- so there is nothing for a projection to
    fold. The generator (a sibling task) calls `put` directly after a
    sanitised SVG comes back from the model; `SeededArtProvider`'s
    placeholder never reaches this table at all, because it is computed
    per-request from the slug rather than stored.
    """

    def __init__(self, connection: aiosqlite.Connection, rows: ReadModelRepository) -> None:
        super().__init__(connection)
        self._rows = rows

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> ArtStore:
        connection = await open_readmodel_connection(db_path, ArtRow)
        # `apply_schema` reconciles columns, not indexes -- the same note
        # every other store in this module carries. No index beyond the
        # primary key: `all()` is a full-table scan by design (the sibling
        # task's search scores every row; the library is small enough for
        # that to be fine, and the increment-3 spec's search section says why
        # an index meant to speed that up is premature before the corpus is
        # large enough to measure).
        rows = SQLiteReadModelRepository(connection, ArtRow, tracer)
        return cls(connection, rows)

    async def get(self, art_id: UUID) -> ArtRow | None:
        return await self._rows.get(art_id)

    async def put(
        self,
        art_id: UUID,
        svg: str,
        description: str,
        tags: list[str],
        palette: str,
        created_at: datetime,
        source: str,
        uses: int = 0,
    ) -> None:
        """Store a piece of art under an id the caller already minted --
        unlike every other `put` in this module, this does not compute the
        row's `id` itself, because it is `uuid4` and has no derivation to
        repeat (see `ArtRow`'s own docstring).

        Takes already-sanitised `svg`. Sanitising here as well would mean
        every caller pays the parse cost a second time for a value the
        generator already validated once before asking to store it; the
        route that serves this back out re-sanitises instead (see
        `app.py`), which is where the cost of *not* re-checking here would
        actually surface to a browser.
        """
        await self._rows.save(
            ArtRow(
                id=art_id,
                svg=svg,
                description=description,
                tags=tags,
                palette=palette,
                created_at=created_at,
                source=source,
                uses=uses,
            )
        )

    async def all(self) -> list[ArtRow]:
        """Every row, for the sibling task's search to score. `find()` with
        no query is the repository's own "everything" case. See `open`'s
        docstring for why this is a full scan rather than an indexed query."""
        return await self._rows.find()

    async def increment_uses(self, art_id: UUID) -> None:
        """Bumps `uses` by reading the current row and writing it back,
        rather than an atomic `UPDATE ... SET uses = uses + 1` the
        repository layer does not expose. `ReadModelRepository` here is a
        read/save abstraction over arbitrary rows, not a query builder, so
        this is the same read-modify-write shape `apply_schema`'s own
        column reconciliation uses. Fine for this table's write pattern:
        one assignment per candidate, never concurrent increments racing on
        the same row within a single sweep (increment 3's sweep is one
        candidate at a time, per the spec)."""
        row = await self._rows.get(art_id)
        if row is None:
            return
        row.uses += 1
        await self._rows.save(row)

    async def decrement_uses(self, art_id: UUID) -> None:
        """`increment_uses`'s mirror, for the art-refresh work: a reroll or a
        drift-triggered reassignment moves a candidate off a piece without
        deleting it -- the piece may still suit another candidate, per the
        owner's brief -- so the count of who still points at it has to come
        back down. Floored at 0 rather than allowed to go negative: a stale
        assignment double-cleared (a crash between clearing and reassigning,
        retried) must not leave `uses` reading as if fewer candidates than
        zero point at a picture nothing else miscounts.
        """
        row = await self._rows.get(art_id)
        if row is None:
            return
        row.uses = max(0, row.uses - 1)
        await self._rows.save(row)


class CandidateArtRow(ReadModel):
    """Which piece of art a candidate is assigned, keyed by `(project_id,
    slug)` exactly like `CourseBlurbRow`/`CourseOutlineRow` -- so that the
    decision (increment 3's "Assignment is a decision") is made once and
    read back the same way every subsequent request, rather than
    recomputed.
    """

    __table_name__ = "candidate_art"

    project_id: UUID
    slug: str
    art_id: UUID
    membership_hash: str = ""
    """The candidate's `membership_hash` at the moment this assignment was
    made -- the art-refresh feature's whole hook for "does this candidate's
    art match a cluster that no longer exists in this shape". Compared
    against `CourseCandidate.membership_hash` the same way `CourseBlurbRow`
    is compared against a candidate's current hash; see that field's
    docstring.

    Defaulted to `""` rather than required, for `CourseBlurbRow.title`'s
    exact reason: `apply_schema` reconciles this column onto a database that
    already has assignment rows, and leaves it empty in every one of them.
    A real `membership_hash` is a sha256 hex digest and is never `""`, so an
    old row's empty default can never equal a live candidate's hash -- it
    reads as **stale**, not fresh, the moment this ships. Getting this
    backwards (defaulting to a value that happened to match, or skipping the
    comparison for an empty hash) is CLAUDE.md's read-models failure mode
    exactly: every pre-existing assignment would silently never refresh
    again, while every code path claims the feature works.
    """

    @staticmethod
    def row_id(project_id: UUID, slug: str) -> UUID:
        # The `art:` prefix keeps this id from colliding with
        # `CourseOutlineRow.row_id`, `CourseBlurbRow.row_id` and
        # `CatalogFeatureRow.row_id`, which share `CATALOG_NAMESPACE` and
        # hash the same `{project_id}:{slug}` pair with their own (or no)
        # prefix -- `outline:`, `blurb:`, `course:` and none, respectively.
        return uuid5(CATALOG_NAMESPACE, f"art:{project_id}:{slug}")


class CandidateArtStore(BaseReadModelStore):
    """The candidate-to-art assignment table and the connection it owns.

    No projection, for `CourseBlurbStore`'s reason: nothing on the event log
    describes an assignment. The sibling task's `LibraryArtProvider` calls
    `put` directly the first time it assigns a candidate a picture, whether
    by search match or by generation.
    """

    def __init__(self, connection: aiosqlite.Connection, rows: ReadModelRepository) -> None:
        super().__init__(connection)
        self._rows = rows

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> CandidateArtStore:
        connection = await open_readmodel_connection(db_path, CandidateArtRow)
        # `apply_schema` reconciles columns, not indexes -- the same note
        # `CourseBlurbStore.open` carries, for the same reason: every read
        # here is project-scoped.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_candidate_art_project "
            f"ON {CandidateArtRow.table_name()}(project_id)"
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, CandidateArtRow, tracer)
        return cls(connection, rows)

    async def get(self, project_id: UUID, slug: str) -> CandidateArtRow | None:
        """The assigned art, or None if this candidate has never been
        assigned one. `row.project_id != project_id` is checked for
        `CourseBlurbStore.get`'s exact reason -- unreachable through this
        class's own `row_id`, but a row reached by id alone makes no claim
        about which project asked."""
        row = await self._rows.get(CandidateArtRow.row_id(project_id, slug))
        if row is None or row.project_id != project_id:
            return None
        return row

    async def put(
        self, project_id: UUID, slug: str, art_id: UUID, membership_hash: str
    ) -> None:
        """Assign art to a candidate, superseding whatever was assigned
        before for this slug -- `save` writes by id, and `row_id` is stable
        per `(project_id, slug)`, so a rewrite replaces rather than
        duplicates.

        `membership_hash` is required, not defaulted, on this write path --
        the column default of `""` (see `CandidateArtRow`) exists only to
        let a pre-existing row load; every caller minting or refreshing an
        assignment knows the candidate's current hash and must stamp it, or
        the row it just wrote would read as stale again on the very next
        check.
        """
        await self._rows.save(
            CandidateArtRow(
                id=CandidateArtRow.row_id(project_id, slug),
                project_id=project_id,
                slug=slug,
                art_id=art_id,
                membership_hash=membership_hash,
            )
        )
