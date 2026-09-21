"""Media proposal read models, stores, projections, and runners.

Houses read-side state and projections for media proposals, needs, and ignored assets/hosts.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid5

import aiosqlite
from eventsource import (
    DeclarativeProjection,
    ReadModel,
    handles,
)
from eventsource.adapters.sqlite.readmodels import SQLiteReadModelRepository
from eventsource.ports.readmodels import ReadModelRepository

from research_team.application.research.media_acquisition import AcceptedProposal
from research_team.domain.research.media_proposals import (
    MediaAssetIgnored,
    MediaAssetUnignored,
    MediaHostIgnored,
    MediaHostUnignored,
    MediaNeedsIdentified,
    MediaProposalAccepted,
    MediaProposalFailed,
    MediaProposalRejected,
    MediaProposalStored,
    MediaProposed,
)
from research_team.infrastructure.persistence.store_base import (
    LOCAL_RETRY_POLICY,
    BaseProjectionRunner,
    BaseReadModelStore,
    open_readmodel_connection,
)

MEDIA_PROPOSAL_NAMESPACE = UUID("d4a1c6e2-8f3b-5a90-9e7c-1b4d3f6a8c2e")
"""Distinct from every other namespace in this module, for the reason each of
theirs gives: two tables sharing one derivation could let an id chosen in one
collide with an id chosen in the other."""

__all__ = [
    "MEDIA_PROPOSAL_NAMESPACE",
    "MediaIgnoredAssetRow",
    "MediaIgnoredHostRow",
    "MediaNeedRow",
    "MediaProposalProjection",
    "MediaProposalRow",
    "MediaProposalRunner",
    "MediaProposalStore",
]


class MediaNeedRow(ReadModel):
    """One need from a `MediaNeedsIdentified` payload, kept only so
    `MediaProposalProjection` can look a description up by `need_id` when a
    later `MediaProposed` names it.

    Not exposed through `MediaProposalStore` -- nothing reads this table
    directly. It exists purely to survive past the event that filled it, so
    the denormalization onto `MediaProposalRow` works whether a proposal
    arrives in the same process run that saw the needs event or a later one
    resuming from a checkpoint.
    """

    __table_name__ = "media_needs"

    project_id: UUID
    need_id: str
    description: str

    @staticmethod
    def row_id(project_id: UUID, need_id: str) -> UUID:
        """Keyed on the pair: `need_id` is chosen per stage-1 run and a
        second project's need with the same id must not overwrite this one.
        """
        return uuid5(MEDIA_PROPOSAL_NAMESPACE, f"need:{project_id}:{need_id}")


class MediaIgnoredAssetRow(ReadModel):
    """One asset a person has told the chain never to propose again.

    A row's existence is the fact; nothing on it varies. `MediaAssetUnignored`
    deletes the row outright rather than flagging it, because "currently
    ignored" is exactly what `for_project`-style listing over this table
    would otherwise have to filter for, and there is no reader that wants a
    history of past ignores.
    """

    __table_name__ = "media_ignored_assets"

    project_id: UUID
    asset_key: str

    @staticmethod
    def row_id(project_id: UUID, asset_key: str) -> UUID:
        return uuid5(MEDIA_PROPOSAL_NAMESPACE, f"ignored-asset:{project_id}:{asset_key}")


class MediaIgnoredHostRow(ReadModel):
    """Mirrors `MediaIgnoredAssetRow` exactly, at the host grain."""

    __table_name__ = "media_ignored_hosts"

    project_id: UUID
    host: str

    @staticmethod
    def row_id(project_id: UUID, host: str) -> UUID:
        return uuid5(MEDIA_PROPOSAL_NAMESPACE, f"ignored-host:{project_id}:{host}")


class MediaProposalRow(ReadModel):
    """One proposal, project/proposal/topic/need/reason/asset/thumbnail and
    the state it has reached.

    `need_description` is denormalized from `MediaNeedsIdentified` rather
    than joined at read time: the projection already sees both events on the
    same stream, in order, and a join across `MediaNeedRow` (or worse, a
    JSON `needs` column) is the more expensive way to answer a question this
    handler can answer once and write down. See the controller ruling in the
    task-7 brief -- without it the pane can group proposals by need but
    cannot label the groups.

    `source_id` and `error` are mutually exclusive outcomes of the same
    lifecycle step (`stored` vs `failed`) and both nullable, mirroring how
    `CorpusDocumentRow.dropped_reason` stays None until the fact it records
    happens -- the two are never both set on this build's own writes, but
    nothing enforces that here; the domain aggregate is where that guard
    lives, on `decide`'s lifecycle cases.
    """

    __table_name__ = "media_proposals"

    project_id: UUID
    proposal_id: str
    need_id: str
    need_description: str = ""
    topic_id: str
    page_url: str
    asset_url: str
    thumbnail_url: str = ""
    kind: str
    title: str
    reason: str
    query: str
    status: str = "proposed"
    note: str = ""
    source_id: str | None = None
    error: str | None = None

    @staticmethod
    def row_id(proposal_id: str) -> UUID:
        """Keyed on `proposal_id` alone, not the `(project_id, id)` pair
        `CorpusDocumentRow` uses. Every event after `MediaProposed` --
        `MediaProposalAccepted`, `Rejected`, `Stored`, `Failed` -- carries
        only `proposal_id`, not `project_id`; a key that needed both could
        not be derived from those events without a lookup this method exists
        to avoid. `decide`'s own guard makes `proposal_id` a domain-wide
        unique choice already: `AcceptMediaProposal` and friends are rejected
        with "unknown proposal" unless a record for that id already exists in
        *this project's* fold, so a `MediaProposalStore`'s own aggregate never
        mistakes another project's id for its own.
        """
        return uuid5(MEDIA_PROPOSAL_NAMESPACE, f"proposal:{proposal_id}")


class MediaProposalProjection(DeclarativeProjection):
    """Writes proposals, and the needs they are denormalized against.

    Every handler loads, changes and saves back, the same idempotent-on-
    replay shape `SessionSummaryProjection` uses -- so resuming from a
    slightly-behind checkpoint re-derives the same row rather than
    accumulating state twice.
    """

    def __init__(
        self,
        rows: ReadModelRepository[MediaProposalRow],
        needs: ReadModelRepository[MediaNeedRow],
        ignored_assets: ReadModelRepository[MediaIgnoredAssetRow],
        ignored_hosts: ReadModelRepository[MediaIgnoredHostRow],
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._rows = rows
        self._needs = needs
        self._ignored_assets = ignored_assets
        self._ignored_hosts = ignored_hosts
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(MediaNeedsIdentified)
    async def _on_needs_identified(self, event: MediaNeedsIdentified) -> None:
        """Record every need's description, keyed for `_on_proposed` to find.

        `needs` is JSON by design -- see the field's own docstring in
        `domain/media_proposals.py` -- so this is the one place that parses
        it. A need missing `description` or `need_id` is skipped rather than
        raising: stage 1's prompt is what shapes this payload and a malformed
        entry here must not put an otherwise-good discovery pass in the DLQ.
        """
        for need in json.loads(event.needs):
            need_id = need.get("need_id")
            if not need_id:
                continue
            await self._needs.save(
                MediaNeedRow(
                    id=MediaNeedRow.row_id(event.aggregate_id, need_id),
                    project_id=event.aggregate_id,
                    need_id=need_id,
                    description=need.get("description", ""),
                )
            )

    @handles(MediaProposed)
    async def _on_proposed(self, event: MediaProposed) -> None:
        """Create the row, denormalizing the need's description if one has
        been recorded. `event.project_id` is text on the event -- see its
        docstring -- and `aggregate_id` is the same value already parsed, so
        this reads from `aggregate_id` rather than re-parsing it.
        """
        need_row = await self._needs.get(
            MediaNeedRow.row_id(event.aggregate_id, event.need_id)
        )
        await self._rows.save(
            MediaProposalRow(
                id=MediaProposalRow.row_id(event.proposal_id),
                project_id=event.aggregate_id,
                proposal_id=event.proposal_id,
                need_id=event.need_id,
                need_description=need_row.description if need_row is not None else "",
                topic_id=event.topic_id,
                page_url=event.page_url,
                asset_url=event.asset_url,
                thumbnail_url=event.thumbnail_url,
                kind=event.kind,
                title=event.title,
                reason=event.reason,
                query=event.query,
            )
        )

    @handles(MediaProposalAccepted)
    async def _on_accepted(self, event: MediaProposalAccepted) -> None:
        row = await self._require(event.proposal_id)
        row.status = "accepted"
        await self._rows.save(row)

    @handles(MediaProposalRejected)
    async def _on_rejected(self, event: MediaProposalRejected) -> None:
        row = await self._require(event.proposal_id)
        row.status = "rejected"
        row.note = event.note
        await self._rows.save(row)

    @handles(MediaProposalStored)
    async def _on_stored(self, event: MediaProposalStored) -> None:
        row = await self._require(event.proposal_id)
        row.status = "stored"
        row.source_id = event.source_id
        await self._rows.save(row)

    @handles(MediaProposalFailed)
    async def _on_failed(self, event: MediaProposalFailed) -> None:
        """A failure stays visible rather than disappearing -- the design
        doc's own point: a judged candidate that turned out to serve an HTML
        interstitial is a failure, not a source, and the pane has to be able
        to say why a proposal never became one.
        """
        row = await self._require(event.proposal_id)
        row.status = "failed"
        row.error = event.error
        await self._rows.save(row)

    @handles(MediaAssetIgnored)
    async def _on_asset_ignored(self, event: MediaAssetIgnored) -> None:
        await self._ignored_assets.save(
            MediaIgnoredAssetRow(
                id=MediaIgnoredAssetRow.row_id(event.aggregate_id, event.asset_key),
                project_id=event.aggregate_id,
                asset_key=event.asset_key,
            )
        )

    @handles(MediaAssetUnignored)
    async def _on_asset_unignored(self, event: MediaAssetUnignored) -> None:
        """Reversible, per the module's own docstring -- a blacklist with no
        way back is a trap a single misclick sets permanently. `delete`
        answering False (nothing to remove) is not an error here: the same
        state an already-unignored asset would leave behind.
        """
        await self._ignored_assets.delete(
            MediaIgnoredAssetRow.row_id(event.aggregate_id, event.asset_key)
        )

    @handles(MediaHostIgnored)
    async def _on_host_ignored(self, event: MediaHostIgnored) -> None:
        await self._ignored_hosts.save(
            MediaIgnoredHostRow(
                id=MediaIgnoredHostRow.row_id(event.aggregate_id, event.host),
                project_id=event.aggregate_id,
                host=event.host,
            )
        )

    @handles(MediaHostUnignored)
    async def _on_host_unignored(self, event: MediaHostUnignored) -> None:
        await self._ignored_hosts.delete(
            MediaIgnoredHostRow.row_id(event.aggregate_id, event.host)
        )

    async def _require(self, proposal_id: str) -> MediaProposalRow:
        """The row for a proposal, which must already exist.

        `MediaProposed` is the creation event and cannot be preceded by
        `MediaProposalAccepted`/`Rejected`/`Stored`/`Failed` on a well-formed
        stream -- `decide`'s own unknown-id guard refuses those commands
        before this projection ever sees the events they would produce. A
        missing row here means events arrived out of order or the table was
        truncated under a checkpoint that survived, both worth an error
        rather than a silently invented row -- mirrors
        `SessionSummaryProjection._require`.
        """
        row = await self._rows.get(MediaProposalRow.row_id(proposal_id))
        if row is None:
            raise LookupError(f"no proposal row for {proposal_id}")
        return row


class MediaProposalStore(BaseReadModelStore):
    """The proposal table, its supporting tables, and the connection they
    share. Mirrors `OntologyStore`: one store over several tables that are
    written together, opened with `apply_schema` so there is no migration
    step to run and forget.
    """

    def __init__(
        self,
        connection: aiosqlite.Connection,
        rows: ReadModelRepository[MediaProposalRow],
        needs: ReadModelRepository[MediaNeedRow],
        ignored_assets: ReadModelRepository[MediaIgnoredAssetRow],
        ignored_hosts: ReadModelRepository[MediaIgnoredHostRow],
        projection: MediaProposalProjection,
    ) -> None:
        super().__init__(connection)
        self._rows = rows
        self._needs = needs
        self._ignored_assets = ignored_assets
        self._ignored_hosts = ignored_hosts
        self.projection = projection

    @classmethod
    async def open(
        cls, db_path: str, checkpoint_repo=None, dlq_repo=None, tracer=None
    ) -> MediaProposalStore:
        connection = await open_readmodel_connection(
            db_path,
            MediaProposalRow,
            MediaNeedRow,
            MediaIgnoredAssetRow,
            MediaIgnoredHostRow,
        )
        # `apply_schema` reconciles columns and not indexes, so this stays --
        # the same note as `CorpusStore.open`. Every read here is by project.
        for statement in (
            f"CREATE INDEX IF NOT EXISTS idx_media_proposals_project "
            f"ON {MediaProposalRow.table_name()}(project_id)",
            f"CREATE INDEX IF NOT EXISTS idx_media_needs_project "
            f"ON {MediaNeedRow.table_name()}(project_id)",
            f"CREATE INDEX IF NOT EXISTS idx_media_ignored_assets_project "
            f"ON {MediaIgnoredAssetRow.table_name()}(project_id)",
            f"CREATE INDEX IF NOT EXISTS idx_media_ignored_hosts_project "
            f"ON {MediaIgnoredHostRow.table_name()}(project_id)",
        ):
            await connection.execute(statement)
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, MediaProposalRow, tracer)
        needs = SQLiteReadModelRepository(connection, MediaNeedRow, tracer)
        ignored_assets = SQLiteReadModelRepository(connection, MediaIgnoredAssetRow, tracer)
        ignored_hosts = SQLiteReadModelRepository(connection, MediaIgnoredHostRow, tracer)
        return cls(
            connection,
            rows,
            needs,
            ignored_assets,
            ignored_hosts,
            MediaProposalProjection(
                rows, needs, ignored_assets, ignored_hosts, checkpoint_repo, dlq_repo, tracer
            ),
        )

    async def for_project(self, project_id: UUID) -> list[MediaProposalRow]:
        """Every proposal in a project, newest table order -- mirrors
        `OntologyStore.classes_for`'s shape: a repository `get` per id rather
        than a projected SELECT, because a proposal row is a handful of short
        strings, nothing worth a column list to avoid loading.
        """
        cursor = await self._connection.execute(
            f"SELECT id FROM {MediaProposalRow.table_name()} "
            "WHERE project_id = ? AND deleted_at IS NULL",
            (str(project_id),),
        )
        try:
            ids = [UUID(row[0]) for row in await cursor.fetchall()]
        finally:
            await cursor.close()
        rows = [await self._rows.get(row_id) for row_id in ids]
        return [row for row in rows if row is not None]

    async def get_by_proposal_id(self, proposal_id: str) -> MediaProposalRow | None:
        """One proposal, keyed the way `AcceptMediaProposal`/`StoreMediaProposal`
        name it -- by `proposal_id` alone, not `(project_id, id)`.
        `MediaProposalRow.row_id` already derives the storage key from just
        `proposal_id` for this reason (see its docstring); this is the direct
        `self._rows.get` that reasoning exists to enable, with no scan.
        """
        return await self._rows.get(MediaProposalRow.row_id(proposal_id))

    async def accepted(self) -> list[MediaProposalRow]:
        """Every `accepted` proposal, across every project -- ordered by
        `proposal_id`, not scoped by `WHERE project_id = ?` the way every
        other read on this store is. Deliberately: reconciliation runs once
        per process, before anything has asked about a particular project,
        and an accepted proposal in a project nobody opens this session is
        exactly the one most likely to have been abandoned.
        """
        cursor = await self._connection.execute(
            f"SELECT id FROM {MediaProposalRow.table_name()} "
            "WHERE status = 'accepted' AND deleted_at IS NULL "
            "ORDER BY proposal_id",
            (),
        )
        try:
            ids = [UUID(row[0]) for row in await cursor.fetchall()]
        finally:
            await cursor.close()
        rows = [await self._rows.get(row_id) for row_id in ids]
        return [row for row in rows if row is not None]

    async def ignored_assets(self, project_id: UUID) -> set[str]:
        cursor = await self._connection.execute(
            f"SELECT asset_key FROM {MediaIgnoredAssetRow.table_name()} "
            "WHERE project_id = ? AND deleted_at IS NULL",
            (str(project_id),),
        )
        try:
            return {row[0] for row in await cursor.fetchall()}
        finally:
            await cursor.close()

    async def ignored_hosts(self, project_id: UUID) -> set[str]:
        cursor = await self._connection.execute(
            f"SELECT host FROM {MediaIgnoredHostRow.table_name()} "
            "WHERE project_id = ? AND deleted_at IS NULL",
            (str(project_id),),
        )
        try:
            return {row[0] for row in await cursor.fetchall()}
        finally:
            await cursor.close()


class MediaProposalRunner(BaseProjectionRunner[MediaProposalStore]):
    """Keeps the proposal tables following the log, and answers from them.

    A distinct runner rather than another projection sharing an existing
    manager, for `CorpusRunner`'s own reason: `rebuild()` truncates tables
    and resets a checkpoint, and sharing a manager would mean repairing one
    projection's drift also interrupted an unrelated one's reads.
    """

    _label = "media-proposal"
    _store_class = MediaProposalStore
    _projection_class = MediaProposalProjection
    _caught_up_aggregate_types = ("MediaProposals",)

    @property
    def _proposals(self) -> MediaProposalStore | None:
        return self._store_instance

    async def _truncate_store(self) -> None:
        """Truncate all proposal tables on rebuild."""
        async with aiosqlite.connect(self._db_path) as connection:
            for table in (
                MediaProposalRow.table_name(),
                MediaNeedRow.table_name(),
                MediaIgnoredAssetRow.table_name(),
                MediaIgnoredHostRow.table_name(),
            ):
                await connection.execute(f"DELETE FROM {table}")
            await connection.commit()

    async def for_project(self, project_id: UUID) -> list[MediaProposalRow]:
        return await self._started().for_project(project_id)

    async def get(self, proposal_id: str) -> AcceptedProposal | None:
        """Satisfies `MediaAcceptWorker`'s `MediaProposalReadPort` directly off
        this projection, rather than through a separate adapter -- this runner
        is already handed to routes as the read side of proposals
        (`list_media_proposals` reads `for_project` off it the same way), so
        composition hands the accept worker this same instance for `reads`.

        Returns whatever the row currently says regardless of `status`: the
        worker is only ever invoked after `AcceptMediaProposal` has already
        landed, and re-deriving that check here would be a second place for
        the two to disagree about what "accepted" means.
        """
        row = await self._started().get_by_proposal_id(proposal_id)
        if row is None:
            return None
        return AcceptedProposal(
            project_id=str(row.project_id),
            page_url=row.page_url,
            asset_url=row.asset_url,
            title=row.title,
        )

    async def accepted_proposal_ids(self) -> list[str]:
        """The accepted-but-unfinished set, across every project -- what
        `MediaAcceptReconciler` loops over. See `MediaProposalStore.accepted`
        for why this is not scoped to one project.
        """
        rows = await self._started().accepted()
        return [row.proposal_id for row in rows]

    async def ignored_assets(self, project_id: UUID) -> set[str]:
        return await self._started().ignored_assets(project_id)

    async def ignored_hosts(self, project_id: UUID) -> set[str]:
        return await self._started().ignored_hosts(project_id)
