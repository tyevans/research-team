"""Ontology and entity definition read models, projections, stores, and runners.

Houses read-side state and projections for entity definitions and discovered ontology classes.
"""

from __future__ import annotations

import json
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
from redstring import DocumentExtracted
from redstring.events.streams import DOCUMENT_CATEGORY

from research_team.infrastructure.persistence.definition_read_models import (
    DEFINITION_NAMESPACE as DEFINITION_NAMESPACE,
)
from research_team.infrastructure.persistence.definition_read_models import (
    EntityDefinitionProjection as EntityDefinitionProjection,
)
from research_team.infrastructure.persistence.definition_read_models import (
    EntityDefinitionRow as EntityDefinitionRow,
)
from research_team.infrastructure.persistence.definition_read_models import (
    EntityDefinitionRunner as EntityDefinitionRunner,
)
from research_team.infrastructure.persistence.definition_read_models import (
    EntityDefinitionStore as EntityDefinitionStore,
)
from research_team.infrastructure.persistence.store_base import (
    LOCAL_RETRY_POLICY,
    BaseProjectionRunner,
    BaseReadModelStore,
    open_readmodel_connection,
)
from research_team.knowledge.domain.ontology import (
    ONTOLOGY_AGGREGATE_TYPE,
    DiscoveredClass,
    OntologyDiscovered,
)

ONTOLOGY_NAMESPACE = UUID("3f7b21c9-6d84-5e02-a1b7-9c4e0f83d216")
"""Distinct from `DEFINITION_NAMESPACE` and `CORPUS_NAMESPACE` for the reason
stated on those: three tables keyed on unrelated things that are all just
strings by the time `uuid5` sees them must not be able to collide on `id`."""

__all__ = [
    "DEFINITION_NAMESPACE",
    "ONTOLOGY_NAMESPACE",
    "EntityDefinitionProjection",
    "EntityDefinitionRow",
    "EntityDefinitionRunner",
    "EntityDefinitionStore",
    "OntologyClassRow",
    "OntologyExaminedRow",
    "OntologyMembershipRow",
    "OntologyProjection",
    "OntologyRunner",
    "OntologyStore",
]


class OntologyClassRow(ReadModel):
    """One class discovered in one document, with what it was derived from.

    Entirely derived, unlike `EntityDefinitionRow`: every column here is
    rewritten by replaying the log, where a definition's `text` comes from a
    service's `put` and a replay could not restore it. That is why this
    table's rebuild may truncate and the definition runner's may not.

    Keyed on `(project_id, source_id, name)`. Two documents each stating "six
    difficulties" therefore produce two rows, deliberately -- merging them is
    the entity-identity problem redstring's `Consolidator` exists for and
    should reuse it, not grow a private version here.
    """

    __table_name__ = "ontology_classes"

    project_id: UUID
    source_id: str
    name: str
    kind: str
    """`ordered_scale` | `unordered_set` | `taxonomy`, as a plain string.

    Not the event's `Literal`: a column that refused an unknown value would
    put a replay in the DLQ over a payload the log has already accepted, and
    the log is not rewritable. Validation belongs at the point the value is
    believed -- `verify_classes` -- not at the point it is re-read.
    """
    declared_count: int | None = None
    member_count: int = 0
    """What was actually stored, recorded rather than counted from the
    membership table on read. A number derived by a join would always agree
    with itself, including after a half-finished write; two independently
    recorded numbers can disagree, which is the entire point of a checksum."""
    parent_class_id: UUID | None = None
    evidence_start: int = 0
    evidence_end: int = 0
    rejected_members: str = "[]"
    """JSON array of `{name, reason}`. A string column for the same reason
    `EntityDefinitionRow.citations` is one: it is handed whole to a browser
    that renders it, and decoding here would be work with no reader."""
    evidence_quoted: bool = True
    """Whether `evidence_start`/`evidence_end` are the model's located quote or
    a lenient pass's fallback to a member occurrence. See
    `DiscoveredClass.evidence_quoted`.

    Defaulted True, which is what makes it an additive column `apply_schema`
    can `ALTER` onto a database that predates it. The rows already there were
    all written by a strict pass -- there was no other kind -- so the default
    is the true value for them rather than a convenient one, and no backfill is
    owed."""
    model: str = ""
    generated_at: str = ""
    stale: bool = False

    @staticmethod
    def row_id(project_id: UUID, source_id: str, name: str) -> UUID:
        return uuid5(ONTOLOGY_NAMESPACE, f"{project_id}:{source_id}:{name}")


class OntologyMembershipRow(ReadModel):
    """One member of one class, as the document spelled it.

    **No entity id, deliberately.** The first design stored one and it was
    wrong in the way redstring's ADR 0005 warns about: re-extraction remints
    entity ids with no invalidation event, so a stored id would name an entity
    that no longer exists, and nothing here would know. `ProjectGraphReader`
    resolves the name against the entities it is already holding, on every
    read -- which costs no extra query and cannot go stale.

    So the name is the whole record. A member that matches no entity today is
    still a member: its row keeps `member_count` honest against the class's
    `declared_count`, and the next read resolves it if extraction later
    produces the entity. Deleting it instead would make an unrelated
    re-extraction look like a discovery failure.
    """

    __table_name__ = "ontology_memberships"

    project_id: UUID
    class_id: UUID
    member_name: str
    ordinal: int | None = None

    @staticmethod
    def row_id(class_id: UUID, member_name: str) -> UUID:
        return uuid5(ONTOLOGY_NAMESPACE, f"{class_id}:{member_name}")


class OntologyExaminedRow(ReadModel):
    """That a discovery pass looked at this source, whatever it found.

    A separate row rather than a flag on a class, because the case it exists
    for is the one with *no* class: a document the pass read and found nothing
    in has nowhere else to record that it was read. Without this, "states no
    classes" and "never examined" are the same observation, and the `ungrouped`
    sweep re-runs every barren document on every pass, at model cost.
    """

    __table_name__ = "ontology_examined"

    project_id: UUID
    source_id: str

    @staticmethod
    def row_id(project_id: UUID, source_id: str) -> UUID:
        return uuid5(ONTOLOGY_NAMESPACE, f"examined:{project_id}:{source_id}")


class OntologyStore(BaseReadModelStore):
    """The three ontology tables and the connection they share.

    One store rather than one per table, unlike the rest of this module,
    because they are written and cleared together: replacing a source's classes
    must delete that source's memberships in the same breath. Two stores over
    two connections would make that two transactions with a window between them
    in which a class has no members and the canvas draws a bare hub.
    """

    def __init__(
        self,
        connection: aiosqlite.Connection,
        classes: ReadModelRepository[OntologyClassRow],
        members: ReadModelRepository[OntologyMembershipRow],
        examined: ReadModelRepository[OntologyExaminedRow],
    ) -> None:
        super().__init__(connection)
        self._classes = classes
        self._members = members
        self._examined = examined

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> OntologyStore:
        connection = await open_readmodel_connection(
            db_path,
            OntologyClassRow,
            OntologyMembershipRow,
            OntologyExaminedRow,
        )
        # `apply_schema` reconciles columns and not indexes -- the same note as
        # on `EntityDefinitionStore.open`. `members_for` runs once per class on
        # every graph read, so an unindexed membership table would put a
        # project's whole canvas behind one scan per class.
        for statement in (
            f"CREATE INDEX IF NOT EXISTS idx_ontology_classes_project "
            f"ON {OntologyClassRow.table_name()}(project_id, source_id)",
            f"CREATE INDEX IF NOT EXISTS idx_ontology_members_class "
            f"ON {OntologyMembershipRow.table_name()}(class_id)",
            f"CREATE INDEX IF NOT EXISTS idx_ontology_examined_project "
            f"ON {OntologyExaminedRow.table_name()}(project_id)",
        ):
            await connection.execute(statement)
        await connection.commit()
        return cls(
            connection,
            SQLiteReadModelRepository(connection, OntologyClassRow, tracer),
            SQLiteReadModelRepository(connection, OntologyMembershipRow, tracer),
            SQLiteReadModelRepository(connection, OntologyExaminedRow, tracer),
        )

    async def replace_for_source(
        self,
        project_id: UUID,
        source_id: str,
        classes: list[DiscoveredClass],
        *,
        model: str,
        generated_at: str,
    ) -> None:
        """Store this source's classes, discarding whatever it held before.

        Replacement rather than upsert: the pass is re-run whenever its prompt
        changes, and a re-run that no longer finds a class has to remove it. An
        upsert would leave behind every class any past prompt ever produced,
        and the canvas would accumulate one hub per attempt.

        An empty `classes` still clears and still records the source as
        examined -- see `OntologyExaminedRow`.
        """
        await self._forget_source(project_id, source_id)
        for klass in classes:
            class_id = OntologyClassRow.row_id(project_id, source_id, klass.name)
            await self._classes.save(
                OntologyClassRow(
                    id=class_id,
                    project_id=project_id,
                    source_id=source_id,
                    name=klass.name,
                    kind=klass.kind,
                    declared_count=klass.declared_count,
                    member_count=len(klass.members),
                    parent_class_id=(
                        OntologyClassRow.row_id(project_id, source_id, klass.parent_name)
                        if klass.parent_name
                        else None
                    ),
                    evidence_start=klass.evidence.start,
                    evidence_end=klass.evidence.end,
                    rejected_members=json.dumps(
                        [rejected.model_dump() for rejected in klass.rejected_members]
                    ),
                    evidence_quoted=klass.evidence_quoted,
                    model=model,
                    generated_at=generated_at,
                )
            )
            for member in klass.members:
                await self._members.save(
                    OntologyMembershipRow(
                        id=OntologyMembershipRow.row_id(class_id, member.name),
                        project_id=project_id,
                        class_id=class_id,
                        member_name=member.name,
                        ordinal=member.ordinal,
                    )
                )
        await self._examined.save(
            OntologyExaminedRow(
                id=OntologyExaminedRow.row_id(project_id, source_id),
                project_id=project_id,
                source_id=source_id,
            )
        )

    async def _forget_source(self, project_id: UUID, source_id: str) -> None:
        """Delete one source's classes and their memberships.

        Memberships are found through their classes rather than by a
        `source_id` of their own: a membership belongs to a class, and giving
        it a second copy of the class's source would be a second thing that can
        disagree. The cost is one extra query, on a table indexed for it.
        """
        for row in await self._classes_for_source(project_id, source_id):
            for member in await self.members_for(row.id):
                await self._members.delete(member.id)
            await self._classes.delete(row.id)

    async def _classes_for_source(
        self, project_id: UUID, source_id: str
    ) -> list[OntologyClassRow]:
        return [
            row for row in await self.classes_for(project_id) if row.source_id == source_id
        ]

    async def classes_for(self, project_id: UUID) -> list[OntologyClassRow]:
        """Every class in a project, newest table order.

        Goes through the repository rather than a projected SELECT, unlike
        `CorpusStore.list`: a class row is a few short strings, where a corpus
        row is an entire document, so there is nothing here worth the extra
        column list to avoid loading.
        """
        cursor = await self._connection.execute(
            f"SELECT id FROM {OntologyClassRow.table_name()} "
            "WHERE project_id = ? AND deleted_at IS NULL ORDER BY name",
            (str(project_id),),
        )
        try:
            ids = [UUID(row[0]) for row in await cursor.fetchall()]
        finally:
            await cursor.close()
        rows = [await self._classes.get(row_id) for row_id in ids]
        return [row for row in rows if row is not None]

    async def members_for(self, class_id: UUID) -> list[OntologyMembershipRow]:
        """One class's members, in the order the text gave them.

        Ordered by `ordinal` with nulls last, so an ordered scale reads as the
        document stated it and an unordered set keeps a stable arrival order
        rather than an arbitrary one. Sorting an unordered set by name here
        would read a sequence into a bag.
        """
        cursor = await self._connection.execute(
            f"SELECT id FROM {OntologyMembershipRow.table_name()} "
            "WHERE class_id = ? AND deleted_at IS NULL "
            "ORDER BY ordinal IS NULL, ordinal, member_name",
            (str(class_id),),
        )
        try:
            ids = [UUID(row[0]) for row in await cursor.fetchall()]
        finally:
            await cursor.close()
        rows = [await self._members.get(row_id) for row_id in ids]
        return [row for row in rows if row is not None]

    async def sources_with_classes(self, project_id: UUID) -> set[str]:
        """Every source a pass has examined, whatever it found.

        Named for what callers ask it -- "which sources are done" -- and
        deliberately answering from `ontology_examined` rather than from the
        class table, which would answer a different and wrong question. See
        `OntologyExaminedRow`.
        """
        cursor = await self._connection.execute(
            f"SELECT source_id FROM {OntologyExaminedRow.table_name()} "
            "WHERE project_id = ? AND deleted_at IS NULL",
            (str(project_id),),
        )
        try:
            return {row[0] for row in await cursor.fetchall()}
        finally:
            await cursor.close()

    async def mark_stale_for_source(self, project_id: UUID, source_id: str) -> None:
        """Flag a source's classes as no longer trustworthy, without discarding
        them -- the same contract `EntityDefinitionStore.mark_stale` keeps, and
        for the same reason: stale text stays visible, labelled, until
        something replaces it.

        A source with no classes is a no-op, not an error. This is called from
        a projection reacting to every extraction in the log, and most
        documents have never been examined; raising here would put routine
        extraction in the DLQ.

        One `UPDATE` over the source's classes rather than a load-mutate-save
        per row, for `EntityDefinitionStore.mark_stale`'s reasons and with the
        same hand-written `updated_at`/`version` bookkeeping -- read that
        docstring for why the repository cannot do this. The loop here was
        strictly worse than the single-row case it mirrors: it fetched *every*
        class in the project to filter by source in Python, then committed once
        per matching row, so a re-extraction of one document in a project with
        two hundred classes was two hundred rows read and one transaction per
        class staled.
        """
        await self._connection.execute(
            f"UPDATE {OntologyClassRow.table_name()} "  # nosec B608 - name from the model
            "SET stale = 1, updated_at = ?, version = version + 1 "
            "WHERE project_id = ? AND source_id = ? AND deleted_at IS NULL",
            (datetime.now(UTC).isoformat(), str(project_id), source_id),
        )
        await self._connection.commit()


class OntologyProjection(DeclarativeProjection):
    """Writes discovered classes, and stales them when extraction moves under them.

    **Marks, never regenerates**, exactly as `EntityDefinitionProjection` does
    and for the identical measured reason: a bulk re-extraction touching two
    hundred documents would otherwise fire two hundred paid model calls for
    classes nobody asked to look at. `stale=True` is a label the next discovery
    run resolves, not a queue this projection drains. It is handed no model, so
    it could not call one even by mistake.
    """

    def __init__(
        self,
        ontology: OntologyStore,
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._ontology = ontology
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(OntologyDiscovered)
    async def _on_discovered(self, event: OntologyDiscovered) -> None:
        """Replace this source's classes with what the pass found.

        `event.occurred_at` rather than a clock read here: a replay has to
        reproduce the same `generated_at` it produced the first time, or a
        rebuild would rewrite every row with today's date and lose when the
        classes were actually derived.
        """
        await self._ontology.replace_for_source(
            event.project_id,
            event.source_id,
            event.classes,
            model=event.model_version,
            generated_at=event.occurred_at.isoformat(),
        )

    @handles(DocumentExtracted)
    async def _on_extracted(self, event: DocumentExtracted) -> None:
        """Stale this source's classes: the entities its memberships name have
        just been reminted, so every resolved id is suspect.

        Keys on `event.tenant_id`, matching `EntityDefinitionProjection` --
        redstring's own event arrives here without new wiring, and `tenant_id`
        is the project.
        """
        await self._ontology.mark_stale_for_source(event.tenant_id, str(event.source_id))


class OntologyRunner(BaseProjectionRunner[OntologyStore]):
    """Keeps the ontology tables following the log.

    A sixth runner, for the reasons `CorpusRunner`'s docstring gives for being
    a second: a distinct `rebuild()`/`health()`-shaped surface for these tables
    alone, and a `rebuild()` that must not be able to truncate tables it does
    not own.
    """

    _label = "ontology"
    _store_class = OntologyStore
    _projection_class = OntologyProjection
    _caught_up_aggregate_types = (ONTOLOGY_AGGREGATE_TYPE, DOCUMENT_CATEGORY)
    _caught_up_event_types = (OntologyDiscovered.__name__, DocumentExtracted.__name__)

    @property
    def _ontology(self) -> OntologyStore | None:
        return self._store_instance

    async def _truncate_store(self) -> None:
        """Truncate all three ontology tables on rebuild."""
        async with aiosqlite.connect(self._db_path) as connection:
            for table in (
                OntologyClassRow.table_name(),
                OntologyMembershipRow.table_name(),
                OntologyExaminedRow.table_name(),
            ):
                await connection.execute(f"DELETE FROM {table}")
            await connection.commit()

    async def classes_for(self, project_id: UUID) -> list[OntologyClassRow]:
        return await self._started().classes_for(project_id)

    async def members_for(self, class_id: UUID) -> list[OntologyMembershipRow]:
        return await self._started().members_for(class_id)

    async def sources_with_classes(self, project_id: UUID) -> set[str]:
        return await self._started().sources_with_classes(project_id)
