"""Entity definition read models, projections, stores, and runners.

Houses read-side state and projections for entity definitions.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid5

import aiosqlite
from eventsource import (
    DeclarativeProjection,
    ReadModel,
    handles,
)
from eventsource.adapters.sqlite.readmodels import SQLiteReadModelRepository
from eventsource.ports.readmodels import ReadModelRepository
from redstring import DocumentExtracted, EntitiesMerged

from research_team.infrastructure.persistence.store_base import (
    LOCAL_RETRY_POLICY,
    BaseProjectionRunner,
    BaseReadModelStore,
    open_readmodel_connection,
)
from research_team.research.domain.corpus import CorpusDocumentDropped

DEFINITION_NAMESPACE = UUID("8a2c1e6d-4b9f-5a71-9e3c-2d6f8b1a0c45")
"""Distinct from `CORPUS_NAMESPACE` so a definition and a document that
happened to share a `(project_id, entity_id)`-shaped key could never collide
on `id` -- the two tables are keyed on unrelated things (an entity, a source)
that are both just strings by the time `uuid5` sees them."""

__all__ = [
    "DEFINITION_NAMESPACE",
    "EntityDefinitionProjection",
    "EntityDefinitionRow",
    "EntityDefinitionRunner",
    "EntityDefinitionStore",
]


class EntityDefinitionRow(ReadModel):
    """One generated definition, cached against the entity it describes.

    A cache and not a projection's own state: the definition service's `put`
    is the only writer of `text`/`citations`/`model`/`generated_at`, but the
    row also has to be *invalidated* by graph events this table never reads
    the payload of -- a merge or an edit changes what an entity is without
    itself carrying new definition text. Splitting "what the definition says"
    from "whether it's still trustworthy" into `mark_stale`/`delete` on the
    store, rather than folding invalidation events here too, keeps the one
    thing this table promises -- `stale=True` means *some* graph change
    invalidated this text -- true regardless of which event caused it,
    without this row's shape needing to grow a case per invalidating event.
    """

    __table_name__ = "entity_definitions"

    project_id: UUID
    entity_id: UUID
    text: str
    citations: str
    """JSON array of `{source_id, start, end}`. A string column and not a
    list, deliberately unlike `SessionSummaryRow.file_paths`: that field is
    read back into application code that iterates it, where a citation is
    only ever handed whole to the browser that renders spans against source
    text it also holds. Decoding here would be work with no reader."""
    model: str
    generated_at: str
    stale: bool = False

    @staticmethod
    def row_id(project_id: UUID, entity_id: UUID) -> UUID:
        """The row id for a definition, matching `CorpusDocumentRow.row_id`'s
        shape: keying on the pair means one project's entity ids -- which are
        graph-local, not global -- cannot collide with another project's."""
        return uuid5(DEFINITION_NAMESPACE, f"{project_id}:{entity_id}")


class EntityDefinitionStore(BaseReadModelStore):
    """The definition cache table and the connection it owns.

    No projection here, unlike `CorpusStore` and `SessionSummaryStore` --
    this store is written to directly by whatever generates a definition and
    by Task 8's invalidation projection, both through `put`/`mark_stale`/
    `delete`, rather than by this store reading events itself. A store with
    no projection is still a store: `open()` still owns reconciling the
    table's schema, which is the part every caller needs and none should
    duplicate.
    """

    def __init__(self, connection: aiosqlite.Connection, rows: ReadModelRepository) -> None:
        super().__init__(connection)
        self._rows = rows

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> EntityDefinitionStore:
        connection = await open_readmodel_connection(db_path, EntityDefinitionRow)
        # `apply_schema` reconciles columns, not indexes -- see the identical
        # note on `CorpusStore.open`. Every read here is project-scoped
        # (`get`, and `mark_stale`/`delete` before it), so an unindexed table
        # would put every project's reads behind a scan of every other
        # project's cached definitions.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_entity_definitions_project "
            f"ON {EntityDefinitionRow.table_name()}(project_id)"
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, EntityDefinitionRow, tracer)
        return cls(connection, rows)

    async def get(self, project_id: UUID, entity_id: UUID) -> EntityDefinitionRow | None:
        """The cached definition, or None if there is none yet.

        `row.project_id != project_id` cannot happen through this class's own
        `row_id` -- the pair is baked into the id -- but is checked anyway for
        the same reason `CorpusStore.get` checks it: a row reached by id alone
        makes no claim about which project asked, and a bug elsewhere that
        looked one entity up under the wrong project should not read back
        another project's definition as if it were an answer.
        """
        row = await self._rows.get(EntityDefinitionRow.row_id(project_id, entity_id))
        if row is None or row.project_id != project_id:
            return None
        return row

    async def put(self, row: EntityDefinitionRow) -> None:
        """Store a definition, superseding whatever was cached before."""
        await self._rows.save(row)

    async def mark_stale(self, project_id: UUID, entity_id: UUID) -> None:
        """Flag a cached definition as no longer trustworthy, without
        discarding it -- Task 8 sets this from a graph event that changed the
        entity, and the stale text stays visible (labelled) until something
        regenerates it, rather than disappearing out from under a reader.

        A missing row is a no-op, not an error: this is called from an
        invalidation projection reacting to graph events, and "this entity
        has never had a definition generated" is the ordinary case for most
        entities, not drift the way a missing row is for `CorpusProjection`'s
        drop handler. Raising here would put routine graph activity in the
        DLQ for a store that was never asked to remember anything.

        **One `UPDATE`, not a read-modify-write** (B74). The previous shape
        read the row through `get`, set `stale` on the loaded object and saved
        the whole thing back, which is a lost update between two writers: a
        generator finishing a definition and calling `put` in the window
        between this read and this write has its fresh text overwritten by the
        stale copy this method is holding, and the row ends up carrying old
        text marked stale rather than new text. That race is not theoretical
        for this table -- B79 records the browser-edit-versus-agent-write
        version of it on the same read model.

        Written against the connection rather than through the repository
        because the repository has no partial update: `save` is an upsert of
        every column, which is the read-modify-write. The three things `save`
        would have done are done here by hand -- `updated_at`, `version + 1`,
        and skipping soft-deleted rows -- so a row that goes through this path
        is indistinguishable from one that went through `save`. If that
        bookkeeping drifts, the tell is a `version` that stops incrementing.

        `project_id` is in the `WHERE` as well as in the id, for `get`'s
        reason: the id already encodes the pair, so the extra clause can only
        ever match, and it means a bug that computed the id under the wrong
        project stales nothing instead of staling a stranger's row.
        """
        await self._connection.execute(
            f"UPDATE {EntityDefinitionRow.table_name()} "  # nosec B608 - name from the model
            "SET stale = 1, updated_at = ?, version = version + 1 "
            "WHERE id = ? AND project_id = ? AND deleted_at IS NULL",
            (
                datetime.now(UTC).isoformat(),
                str(EntityDefinitionRow.row_id(project_id, entity_id)),
                str(project_id),
            ),
        )
        await self._connection.commit()

    async def mark_stale_many(self, project_id: UUID, entity_ids: Sequence[UUID]) -> int:
        """Flag multiple cached definitions as stale in one atomic operation."""
        if not entity_ids:
            return 0
        row_ids = [str(EntityDefinitionRow.row_id(project_id, eid)) for eid in entity_ids]
        placeholders = ",".join("?" for _ in row_ids)
        cursor = await self._connection.execute(
            f"UPDATE {EntityDefinitionRow.table_name()} "  # nosec B608
            "SET stale = 1, updated_at = ?, version = version + 1 "
            f"WHERE id IN ({placeholders}) AND project_id = ? "
            "AND stale = 0 AND deleted_at IS NULL",
            (
                datetime.now(UTC).isoformat(),
                *row_ids,
                str(project_id),
            ),
        )
        await self._connection.commit()
        return cursor.rowcount

    async def delete(self, project_id: UUID, entity_id: UUID) -> None:
        """Discard a cached definition outright -- for an entity that no
        longer exists, where marking it stale would leave a permanent orphan
        nothing will ever regenerate. A missing row is a no-op for the same
        reason `mark_stale`'s is."""
        await self._rows.delete(EntityDefinitionRow.row_id(project_id, entity_id))

    async def delete_many(self, project_id: UUID, entity_ids: Sequence[UUID]) -> int:
        """Discard multiple cached definitions in one atomic operation."""
        if not entity_ids:
            return 0
        row_ids = [str(EntityDefinitionRow.row_id(project_id, eid)) for eid in entity_ids]
        placeholders = ",".join("?" for _ in row_ids)
        cursor = await self._connection.execute(
            f"DELETE FROM {EntityDefinitionRow.table_name()} "  # nosec B608
            f"WHERE id IN ({placeholders}) AND project_id = ?",
            (
                *row_ids,
                str(project_id),
            ),
        )
        await self._connection.commit()
        return cursor.rowcount

    async def mark_stale_for_source(self, project_id: UUID, source_id: str) -> int:
        """Flag any cached definition that cites `source_id` as stale."""
        cursor = await self._connection.execute(
            f"UPDATE {EntityDefinitionRow.table_name()} "  # nosec B608
            "SET stale = 1, updated_at = ?, version = version + 1 "
            "WHERE project_id = ? AND citations LIKE ? AND stale = 0 AND deleted_at IS NULL",
            (
                datetime.now(UTC).isoformat(),
                str(project_id),
                f'%"{source_id}"%',
            ),
        )
        await self._connection.commit()
        return cursor.rowcount

    async def mark_all_stale(self, project_id: UUID) -> int:
        """Flag all cached definitions for a project as stale."""
        cursor = await self._connection.execute(
            f"UPDATE {EntityDefinitionRow.table_name()} "  # nosec B608
            "SET stale = 1, updated_at = ?, version = version + 1 "
            "WHERE project_id = ? AND stale = 0 AND deleted_at IS NULL",
            (
                datetime.now(UTC).isoformat(),
                str(project_id),
            ),
        )
        await self._connection.commit()
        return cursor.rowcount


class EntityDefinitionProjection(DeclarativeProjection):
    """Marks cached definitions untrustworthy in reaction to graph events.

    Deliberately writes no definition text -- `put` is for whatever generates
    one, elsewhere. This projection only calls `mark_stale`/`delete`, both of
    which already tolerate a missing row, so the two handlers below never
    need their own existence check the way `CorpusProjection._on_dropped`
    does through `_require`: there is no aggregate invariant here that would
    make a missing row drift rather than the ordinary case of an entity
    nobody has read yet.

    **Marks, never regenerates.** A bulk re-extraction touching two hundred
    entities would otherwise fire two hundred LLM calls for definitions
    nobody asked to read -- `stale=True` is a label the next click resolves,
    not a queue this projection drains itself.

    **Does not subscribe to `MergeUndone`, on purpose.** Undoing a merge
    deletes-then-restores the absorbed entities' rows via redstring's own
    projection, so on the next click they regenerate from scratch -- correct,
    with no help needed here. The canonical entity is left stale from the
    original `EntitiesMerged`, which is also correct: it is still the entity
    whose properties the merge touched, undo or not. No case a `MergeUndone`
    handler could catch actually yields a wrong answer today, so there is
    nothing here for one to do. If undo becomes routine enough that leaving
    the canonical stale (rather than restoring its pre-merge staleness) reads
    as surprising, that is the point to revisit this, not before.
    """

    def __init__(
        self,
        definitions: EntityDefinitionStore,
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._definitions = definitions
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(DocumentExtracted)
    async def _on_extracted(self, event: DocumentExtracted) -> None:
        """Stale every cached definition an extraction run touched.

        Entities never gain properties incrementally -- a property change
        arrives as a whole-entity payload inside `DocumentExtracted`, the way
        a new mention or a corrected name would -- so this one subscription
        is the entire "more properties were added" case; there is no second
        event to also watch for that.
        """
        entity_ids = [entity.id for entity in event.entities]
        await self._definitions.mark_stale_many(event.tenant_id, entity_ids)

    @handles(EntitiesMerged)
    async def _on_merged(self, event: EntitiesMerged) -> None:
        """Stale the survivor, delete the absorbed.

        The canonical entity's definition may no longer describe it fully --
        a merge can bring in properties the cached text never saw -- so it is
        marked stale rather than left alone. An absorbed id, by contrast, is
        no longer clickable anywhere in the UI once merged away, so its
        cached definition is unreachable text; deleting it (not staling it)
        also keeps `/rebuild` producing the same row count as steady-state
        operation, where nothing ever generates a definition for an id that
        cannot be clicked. Leaving it would be a silent divergence nobody
        could later explain.
        """
        await self._definitions.mark_stale(event.tenant_id, event.canonical_entity_id)
        if event.merged_entity_ids:
            await self._definitions.delete_many(event.tenant_id, event.merged_entity_ids)

    @handles(CorpusDocumentDropped)
    async def _on_source_dropped(self, event: CorpusDocumentDropped) -> None:
        """Stale any cached definitions that cited this dropped document."""
        await self._definitions.mark_stale_for_source(event.aggregate_id, str(event.source_id))


class EntityDefinitionRunner(BaseProjectionRunner[EntityDefinitionStore]):
    """Keeps the definition cache's staleness following the log.

    A third runner beside `CorpusRunner` and `SessionSummaryRunner`, for the
    same reasons `CorpusRunner`'s docstring gives for being a second one
    rather than sharing: a distinct port (`rebuild()` and `health()`-shaped
    surface for this table alone), and a `rebuild()` that must not be able to
    truncate a table it does not own.

    Unlike those two, this runner's `rebuild()` recomputes staleness rather
    than the rows themselves -- see `rebuild` below for why truncating here
    would be destructive rather than merely wasteful.
    """

    _label = "entity definition"
    _store_class = EntityDefinitionStore
    _projection_class = EntityDefinitionProjection

    @property
    def _definitions(self) -> EntityDefinitionStore | None:
        return self._store_instance

    async def _truncate_store(self) -> None:
        """Reset the checkpoint and replay, without truncating the table.

        `CorpusRunner.rebuild` and its `/sessions` counterpart both truncate
        first because their tables hold nothing that is not entirely derived
        from the log. This table is different: `text`/`citations`/`model`/
        `generated_at` come from the definition service's `put`, not from the
        event log this projection replays at all -- see the class
        docstring on why invalidation is split from generation. Truncating
        here would discard every generated definition and replace it with
        nothing, where a resubscribed replay would only re-derive
        `stale`. Resetting the checkpoint and replaying re-applies every
        `DocumentExtracted`/`EntitiesMerged` in the log, which correctly
        re-stales (and re-deletes) whatever the current rows say -- the same
        repair `CorpusRunner.rebuild` performs, minus the truncate that would
        make it destructive for this table.
        """
        pass

    async def get(self, project_id: UUID, entity_id: UUID) -> EntityDefinitionRow | None:
        """This project's cached definition of `entity_id`, if there is one.

        Delegated the way `CorpusRunner.get` is, rather than handing the
        `EntityDefinitionStore` out through a property, and the reason is
        `rebuild()`: it closes the store and opens another one. A caller
        holding the store would go on calling a closed connection, silently,
        after a repair -- where a caller holding the runner reaches whichever
        store is current on every call. That is also what keeps the route's
        cache and this projection's invalidation the *same* table: there is
        one owner of the connection, and it is this object.
        """
        return await self._started().get(project_id, entity_id)

    async def put(self, row: EntityDefinitionRow) -> None:
        """Store a generated definition, superseding whatever was cached.

        The write half of `get`, for the same one-owner reason. This
        projection never calls it -- see the class docstring on why
        generation and invalidation are split -- but the generating service
        reaches the table through here so that both halves go through one
        connection rather than two that would each cache the other's stale
        reads.
        """
        await self._started().put(row)

    async def mark_stale(self, project_id: UUID, entity_id: UUID) -> None:
        await self._started().mark_stale(project_id, entity_id)

    async def delete(self, project_id: UUID, entity_id: UUID) -> None:
        await self._started().delete(project_id, entity_id)

    async def mark_stale_many(self, project_id: UUID, entity_ids: Sequence[UUID]) -> int:
        return await self._started().mark_stale_many(project_id, entity_ids)

    async def delete_many(self, project_id: UUID, entity_ids: Sequence[UUID]) -> int:
        return await self._started().delete_many(project_id, entity_ids)

    async def mark_stale_for_source(self, project_id: UUID, source_id: str) -> int:
        return await self._started().mark_stale_for_source(project_id, source_id)

    async def mark_all_stale(self, project_id: UUID) -> int:
        return await self._started().mark_all_stale(project_id)
