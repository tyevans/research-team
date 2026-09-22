"""Corpus read models, projections, stores, and runners.

Houses read-side state and projections for corpus documents and media.
"""

from __future__ import annotations

from uuid import UUID

import aiosqlite
from eventsource.adapters.sqlite.readmodels import SQLiteReadModelRepository
from eventsource.ports.readmodels import (
    Filter,
    Query,
    ReadModelRepository,
)

from research_team.infrastructure.persistence.corpus_projection import CorpusProjection
from research_team.infrastructure.persistence.corpus_rows import (
    CORPUS_NAMESPACE,
    CorpusDocumentRow,
    CorpusMediaRow,
    _decode_degradations,
    _degradations_of,
    to_record,
)
from research_team.infrastructure.persistence.store_base import (
    BaseProjectionRunner,
    BaseReadModelStore,
    open_readmodel_connection,
)

__all__ = [
    "CORPUS_NAMESPACE",
    "CorpusDocumentRow",
    "CorpusMediaRow",
    "CorpusProjection",
    "CorpusRunner",
    "CorpusStore",
    "_decode_degradations",
    "_degradations_of",
    "to_record",
]


class CorpusStore(BaseReadModelStore):
    """The corpus table, its projection, and the connection they share.

    Mirrors `SessionSummaryStore`: opening it applies the model's own DDL, so
    there is no migration step to run and forget.
    """

    def __init__(
        self,
        connection: aiosqlite.Connection,
        rows: ReadModelRepository[CorpusDocumentRow],
        media_rows: ReadModelRepository[CorpusMediaRow],
        projection: CorpusProjection,
    ) -> None:
        super().__init__(connection)
        self._rows = rows
        self._media_rows = media_rows
        self.projection = projection

    @classmethod
    async def open(
        cls, db_path: str, checkpoint_repo=None, dlq_repo=None, tracer=None
    ) -> CorpusStore:
        connection = await open_readmodel_connection(
            db_path, CorpusDocumentRow, CorpusMediaRow
        )
        # `apply_schema` reconciles columns and not indexes, so this stays: it
        # is not made redundant by the line above and deleting it would put
        # every project's reads back on a full scan.
        #
        # The generated schema indexes `deleted_at` and nothing else. Every
        # read here is by project, and a corpus is the one table expected to
        # grow into the millions of characters, so the scan is worth avoiding.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_corpus_documents_project "
            f"ON {CorpusDocumentRow.table_name()}(project_id)"
        )
        # Mirrors the index above, and for the same reason: every read of
        # this table is scoped to one project.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_corpus_media_project "
            f"ON {CorpusMediaRow.table_name()}(project_id)"
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, CorpusDocumentRow, tracer)
        media_rows = SQLiteReadModelRepository(connection, CorpusMediaRow, tracer)
        return cls(
            connection,
            rows,
            media_rows,
            CorpusProjection(rows, media_rows, checkpoint_repo, dlq_repo, tracer),
        )

    async def get(
        self, project_id: UUID, source_id: str, *, include_dropped: bool = False
    ) -> CorpusDocumentRow | None:
        """One document with its text, or None if it is unknown -- or dropped,
        unless `include_dropped` says otherwise.

        Returns the row rather than a separate shape. `/sessions` converts
        because `SessionSummary` already existed as the application's own
        vocabulary; nothing here predates the row, and inventing a twin of it
        would be a second thing to keep in sync for no gain.

        A dropped source answers None by default: it is a document somebody
        excluded, and the caller asking for it wants to hear that it is not
        available, not to handle an exception for an ordinary state. That is
        wrong for exactly one caller -- `CorpusEditor.restore`, which exists
        to put a dropped document back and needs its text to do so, and which
        is the only caller whose job is to un-exclude what this method would
        otherwise hide. `include_dropped` is keyword-only and defaults False
        so every other caller keeps seeing what it always has.
        """
        row = await self._rows.get(CorpusDocumentRow.row_id(project_id, source_id))
        if row is None or row.project_id != project_id:
            return None
        if row.dropped_reason is not None and not include_dropped:
            return None
        return row

    async def get_media(
        self, project_id: UUID, source_id: str, *, include_dropped: bool = False
    ) -> CorpusMediaRow | None:
        """One media source, or None if it is unknown -- or dropped, unless
        `include_dropped` says otherwise. Mirrors `get` exactly, over the
        other table.
        """
        row = await self._media_rows.get(CorpusMediaRow.row_id(project_id, source_id))
        if row is None or row.project_id != project_id:
            return None
        if row.dropped_reason is not None and not include_dropped:
            return None
        return row

    async def list_all(
        self, project_id: UUID, *, include_dropped: bool = False
    ) -> list[CorpusDocumentRow | CorpusMediaRow]:
        """Every source in a project, text and media together, whole rows.

        The only listing method. There used to be a second one, `list`, which
        selected columns explicitly and queried the documents table alone; it
        was deleted with `CorpusReadPort.list_documents` and for the same
        reason. A caller holding a `CorpusRunner` could reach it, its return
        type said `SourceListing`, and what it returned was half a corpus --
        which renders exactly like a whole one.

        The cost of that deletion is real and is not paid back here: `list`
        projected nine columns and this loads whole rows, `text` included, so
        listing a corpus of a hundred papers now pulls every one of them
        through memory to render a table of titles. Measured on
        2026-08-16 rather than reasoned about: 34.4 ms and 22.0 MB peak for a
        corpus of 500 documents of 40,000 characters, 140.7 ms and 102 MB at
        500 documents near `MAX_DOCUMENT_CHARS`. Still accepted, because every
        caller left on this path is a person pressing something once -- the one
        caller that ran it in a loop, `fetch.stored_page`, was moved to
        `list_text_uris` below. Nothing above this sees the text:
        `SourceListing.record` is a `TextRecord`/`MediaRecord` and has no field
        for it.

        The fix, when a listing is felt (about 1,500 documents of 40,000
        characters), is two column-projected queries that both have to feed
        `to_record` -- which reads `char_count` on one kind and
        `media_type`/`byte_count` on the other, so unlike `list_text_uris` they
        cannot share a column tuple. `BACKLOG.md` B84 carries the full numbers,
        including why the narrower row model it once suspected would have saved
        nothing: peak memory is entirely the bytes, and the per-row pydantic
        cost scales with the size of `text` rather than with the row count.

        Two tables, one query each, held to the same
        `dropped_reason`/`deleted_at` filter as `get` and `get_media`.
        """
        project_filter = [Filter.eq("project_id", str(project_id))]
        by_project = Query(filters=project_filter, order_by="source_id")
        documents = await self._rows.find(by_project)
        media = await self._media_rows.find(by_project)
        return sorted(
            (
                row
                for row in (*documents, *media)
                if row.deleted_at is None and (include_dropped or row.dropped_reason is None)
            ),
            key=lambda row: row.source_id,
        )

    async def list_text_uris(self, project_id: UUID) -> list[tuple[str, str]]:
        """`(source_id, uri)` for every live text source that has a URI.

        Raw SQL and two columns, deliberately, where every other read here
        goes through the repository and gets whole pydantic rows. That is the
        entire point of this method: `fetch.stored_page` needs exactly these
        two strings on every `fetch` tool call, and answering it through
        `list_all` loads every document's text. Measured on 2026-08-16 on a
        fixture corpus of 500 documents x 40,000 characters -- 48.1 ms and
        22.5 MB peak per call through `list_sources`, 5.7 ms and 0.16 MB
        through this. `CorpusReadPort.list_text_uris` carries the attribution
        and `BACKLOG.md` B84 the rest.

        Documents only, and this is *not* the half-corpus hazard `list` was
        deleted over: nothing renders this, and its caller wants text sources
        specifically. It is also why it is a separate method rather than a
        flag on `list_all` -- a listing that answered for one table would read
        downstream as a whole corpus, and this cannot, because it answers with
        strings.

        The filter matches `list_all`'s exactly, minus the `include_dropped`
        opt-in nobody on this path wants. Kept as literal SQL against the
        generated column names, which is the cost: a rename of `dropped_reason`
        or `uri` on `CorpusDocumentRow` breaks this at runtime rather than at
        type-check time. `test_the_uri_listing_matches_what_a_full_listing_says`
        is what fails if it drifts.
        """
        async with self._connection.execute(
            f"SELECT source_id, uri FROM {CorpusDocumentRow.table_name()} "
            "WHERE project_id = ? AND uri IS NOT NULL "
            "AND deleted_at IS NULL AND dropped_reason IS NULL "
            "ORDER BY source_id",
            (str(project_id),),
        ) as cursor:
            return [(row[0], row[1]) for row in await cursor.fetchall()]

    async def truncate(self) -> None:
        """Empty both tables, for a rebuild to fill again.

        Deletes rather than soft-deletes, for the reason `SessionSummaryStore`
        gives: a soft-deleted row would linger invisibly and collide with the
        row the replay is about to write for the same source. Both tables,
        because one rebuild replays both `CorpusDocumentStored` and
        `CorpusMediaStored` -- truncating only the document table would leave
        stale media rows the replay never revisits.
        """
        await self._truncate_tables(CorpusDocumentRow, CorpusMediaRow)


class CorpusRunner(BaseProjectionRunner[CorpusStore]):
    """Keeps the corpus table following the log, and answers from it.

    A second runner rather than a second projection on `SessionSummaryRunner`,
    which was the first thing tried. That class can technically carry another
    subscription -- `SubscriptionManager` holds many, and `InMemoryEventBus`
    broadcasts to every subscriber, so there is no competing-consumer hazard --
    but two things make it the wrong home.

    The first is the port. `SessionSummaryRunner` satisfies `SessionSummaries`,
    whose documented subject is the `/sessions` list, and whose `health()`,
    `rebuild()` and `projection_name` are all singular. Making any of them
    answer for two projections is how a port stops meaning anything, and the
    web layer already calls all three.

    The second is `rebuild()`, and it is the one that decides it. Rebuilding is
    a manual repair that stops the manager, truncates a table, resets a
    checkpoint and starts again. Sharing a manager would mean repairing
    `/sessions` also stopped corpus reads, and would put the corpus table one
    editing mistake away from being truncated by a repair that had nothing to
    do with it. Two tables that can fail independently have to be repairable
    independently.

    What sharing would actually have bought is smaller than it looks: the two
    projections write to different tables through different connections either
    way, and SQLite serialises writers at the file level regardless, so the
    duplication avoided is an engine and two repositories that are keyed by
    projection name anyway.
    """

    _label = "corpus"
    _store_class = CorpusStore
    _projection_class = CorpusProjection

    @property
    def _corpus(self) -> CorpusStore | None:
        return self._store_instance

    async def get(
        self, project_id: UUID, source_id: str, *, include_dropped: bool = False
    ) -> CorpusDocumentRow | None:
        return await self._started().get(
            project_id, source_id, include_dropped=include_dropped
        )

    async def get_media(
        self, project_id: UUID, source_id: str, *, include_dropped: bool = False
    ) -> CorpusMediaRow | None:
        return await self._started().get_media(
            project_id, source_id, include_dropped=include_dropped
        )

    async def list_all(
        self, project_id: UUID, *, include_dropped: bool = False
    ) -> list[CorpusDocumentRow | CorpusMediaRow]:
        return await self._started().list_all(project_id, include_dropped=include_dropped)

    async def list_text_uris(self, project_id: UUID) -> list[tuple[str, str]]:
        return await self._started().list_text_uris(project_id)
