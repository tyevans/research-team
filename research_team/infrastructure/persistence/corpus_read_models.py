"""Corpus read models, projections, stores, and runners.

Houses read-side state and projections for corpus documents and media.
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
from eventsource.ports.readmodels import (
    Filter,
    Query,
    ReadModelRepository,
)
from redstring import DocumentExtracted

from research_team.domain import (
    UNREADABLE_DEGRADATIONS,
    CorpusDerivedTextStored,
    CorpusDocumentDropped,
    CorpusDocumentStored,
    CorpusMediaStored,
    MediaRecord,
    SourceRecord,
    TextRecord,
)
from research_team.infrastructure.persistence.store_base import (
    LOCAL_RETRY_POLICY,
    BaseProjectionRunner,
    BaseReadModelStore,
    open_readmodel_connection,
)

CORPUS_NAMESPACE = UUID("6f1f5f8e-0c4a-5c8f-9b3a-7d2f4c9e1a60")
"""Namespace for deriving a row id from `(project_id, source_id)`.

A read model has one `id` and a corpus document is keyed by two things, so the
id is a uuid5 of both rather than a surrogate. Derived rather than random
because the projection must be able to find the row for a source it has never
seen in this process -- after a restart, or halfway through a rebuild -- and
looking it up by a random id it would first have to store is circular.
"""

__all__ = [
    "CORPUS_NAMESPACE",
    "CorpusDocumentRow",
    "CorpusMediaRow",
    "CorpusProjection",
    "CorpusRunner",
    "CorpusStore",
    "to_record",
]


class CorpusDocumentRow(ReadModel):
    """One source document, text and all. `project_id` is the corpus's stream id.

    A `Corpus` shares its UUID with its `Project` and is a distinct stream by
    `StreamId(aggregate_id, "Corpus")`, so the event's `aggregate_id` is the
    project id and is stored under that name -- calling it `corpus_id` here
    would invent a second identifier for the thing callers already hold.

    This is the one place in the system that stores document text, which is
    the whole point: `CorpusState` gave it up so snapshots would stay small,
    and the text has to live somewhere readable or the trade bought nothing.

    `dropped_reason` is kept on the row rather than deleting it, mirroring the
    aggregate. A drop is a judgement someone made and the row is where that
    judgement stays legible; `get` and `list` filter it out, so a dropped
    document is unreadable without being unaccounted for.
    """

    __table_name__ = "corpus_documents"

    project_id: UUID
    source_id: str
    text: str
    sha256: str
    char_count: int
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    fetched_at: str | None = None
    dropped_reason: str | None = None
    derived_from: str | None = None
    """The media source this was perceived from, or None for a fetched
    document -- mirrors `TextRecord.derived_from` exactly; see its docstring
    for why this is not a third kind of row."""
    locator_map: str | None = None
    """JSON, read whole and never queried into. The locator union
    (`TimeSpan | PageRef | BBox | CharSpan | ByteRange`) belongs to
    `readeverything` and will grow arms there; a structured column here would
    make every arm it adds a schema change in this repository, for a query
    nobody makes -- resolving one offset needs every segment in the map, so
    there is no partial read that would justify decomposing it. Nullable
    because a fetched document has no map at all, not an empty one."""
    perceived_with: str | None = None
    """The capability fingerprint that produced this transcript, or None for
    a fetched document. Mirrors `TextRecord.perceived_with`."""
    degradations: str | None = None
    """JSON list of strings, or the JSON encoding of `UNREADABLE_DEGRADATIONS`
    if the event's own field could not be read -- see `_on_derived_text` for
    why null is not used for that case. None (not `"[]"`) for a fetched
    document, which is a different fact from "perception was complete"."""
    extracted_at: str | None = None
    """When this document's text was last folded into the graph, or None.

    The one field here the corpus aggregate cannot supply: extraction happens
    on redstring's `Document` stream, not the `Corpus` one, so this is written
    by `_on_extracted` from an event the fold never sees. That is also why it
    is not on `TextRecord` -- a domain record that claimed to know this
    would be claiming knowledge of another aggregate's stream.

    A timestamp rather than a flag, because "when" is free here (the event
    carries it) and answers the question a flag cannot: whether the graph
    predates a revision of the text.

    **A database written before this column reads every document as
    unextracted, and a rebuild is the only thing that fixes it.** `apply_schema`
    adds the column as NULL and the projection resumes from its checkpoint, so
    the `DocumentExtracted` events that would fill it have already gone by.
    Measured on a copy of a real database on 2026-08-14, not reasoned: three
    documents with graphs, all three reading `extracted=False` on the resume
    path and all three correct after `CorpusRunner.rebuild()`.

    Not migrated, deliberately -- this project is pre-release with no users to
    break, so the rebuild is the answer rather than a backfill nobody will need
    twice.
    """

    @staticmethod
    def row_id(project_id: UUID, source_id: str) -> UUID:
        """The row id for a source in a project.

        Source ids are chosen per project -- `"s1"`, a URL, a filename -- and
        will collide across them. Keying on the pair means one project's
        re-ingest cannot overwrite another's document.
        """
        return uuid5(CORPUS_NAMESPACE, f"{project_id}:{source_id}")


class CorpusMediaRow(ReadModel):
    """One media source: everything but its bytes.

    A separate table rather than columns on `corpus_documents`, for two
    reasons. `corpus_documents.text` is NOT NULL and every media row would have
    to lie about it -- and making it nullable would then let a text row lie
    too, which is the failure mode where a document silently loses its content
    and still lists. Second, `apply_schema` refuses a required column with no
    default outright, so widening is also the more expensive path.

    No `extracted_at`. Nothing extracts media yet, and a column whose only
    value is NULL is a promise the perception slice may not want to keep.
    """

    __table_name__ = "corpus_media"

    project_id: UUID
    source_id: str
    sha256: str
    """Where the bytes are. A row whose blob is gone is a dangling reference,
    which the read path reports as 410 rather than 404 -- see
    `CorpusReadPort.read_media`."""
    media_type: str
    byte_count: int
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    fetched_at: str | None = None
    dropped_reason: str | None = None

    @staticmethod
    def row_id(project_id: UUID, source_id: str) -> UUID:
        """Mirrors `CorpusDocumentRow.row_id` exactly.

        Deliberately the same derivation over the same inputs: the two tables
        share one `source_id` namespace, so a row id that differed between them
        would let one id name two rows. Source ids are chosen per project --
        `"s1"`, a URL, a filename -- and will collide across them. Keying on
        the pair means one project's re-ingest cannot overwrite another's.
        """
        return uuid5(CORPUS_NAMESPACE, f"{project_id}:{source_id}")


def _decode_degradations(value: str) -> tuple[str, ...] | None:
    """Parse a `degradations` JSON string, or say the shape is wrong.

    Shared by the write side (`_on_derived_text`, deciding what to store) and
    the read side (`to_record`, deciding what to hand back), so there is one
    place that knows what "a JSON list of strings" means rather than two that
    could drift. `None` means the value did not parse to that shape --
    callers decide what to do about it, since a writer wants to fall back to
    `UNREADABLE_DEGRADATIONS` and a reader wants the same, for the identical
    reason `_degradations_from` gives in `corpus.py`: an empty tuple already
    means "perception was complete", so silently producing `()` -- or, worse,
    `tuple(json.loads(...))`'s own failure modes, a `ValueError` on bad JSON
    or a tuple of dict keys on well-formed JSON of the wrong shape -- would
    misreport a value that could not be read as one that was fine.
    """
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        return None
    return tuple(parsed)


def _degradations_of(stored: str | None) -> tuple[str, ...]:
    """A row's `degradations` column as a tuple, keeping `[]` distinct from junk.

    Three cases, and the middle one is the one a `or` collapses: no column at
    all (a fetched document -- `()`), a column holding `[]` (a perception that
    missed nothing -- also `()`, and it must not be reported as unreadable),
    and a column that will not parse (`UNREADABLE_DEGRADATIONS`).
    """
    if not stored:
        return ()
    decoded = _decode_degradations(stored)
    return decoded if decoded is not None else UNREADABLE_DEGRADATIONS


def to_record(row: CorpusDocumentRow | CorpusMediaRow) -> SourceRecord:
    """Present a stored row as the aggregate's own no-bytes shape.

    Reusing `TextRecord`/`MediaRecord` rather than defining listing types here
    makes the no-content guarantee structural: there is no field for text or
    bytes to arrive in, so a listing cannot start carrying a corpus by
    accident. It also keeps the tables and the fold saying the same thing
    about a source, which is the property a rebuild depends on.
    """
    if isinstance(row, CorpusMediaRow):
        return MediaRecord(
            source_id=row.source_id,
            sha256=row.sha256,
            media_type=row.media_type,
            byte_count=row.byte_count,
            uri=row.uri,
            title=row.title,
            published_at=row.published_at,
            note=row.note,
            fetched_at=row.fetched_at,
            dropped_reason=row.dropped_reason,
        )
    return TextRecord(
        source_id=row.source_id,
        sha256=row.sha256,
        char_count=row.char_count,
        uri=row.uri,
        title=row.title,
        published_at=row.published_at,
        note=row.note,
        fetched_at=row.fetched_at,
        dropped_reason=row.dropped_reason,
        derived_from=row.derived_from,
        perceived_with=row.perceived_with,
        degradations=_degradations_of(row.degradations),
    )


class CorpusProjection(DeclarativeProjection):
    """Applies corpus events to their row, one event at a time.

    Both handlers are idempotent by overwrite rather than by increment: there
    is no counter here, so replaying from a checkpoint that is behind
    re-derives exactly the same row instead of accumulating. That is why a
    rebuild is safe to reach for.
    """

    def __init__(
        self,
        rows: ReadModelRepository[CorpusDocumentRow],
        media_rows: ReadModelRepository[CorpusMediaRow],
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._rows = rows
        self._media_rows = media_rows
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(CorpusDocumentStored)
    async def _on_stored(self, event: CorpusDocumentStored) -> None:
        """Write the document, superseding whatever the source held before.

        The existing row is loaded and mutated rather than replaced wholesale,
        so the repository's version counter keeps climbing instead of resetting
        -- and `dropped_reason` is cleared explicitly, because storing asserts
        presence and a live document explaining why it is absent is nonsense.
        """
        row_id = CorpusDocumentRow.row_id(event.aggregate_id, event.source_id)
        fields = {
            "project_id": event.aggregate_id,
            "source_id": event.source_id,
            "text": event.text,
            "sha256": event.sha256,
            "char_count": len(event.text),
            "uri": event.uri,
            "title": event.title,
            "published_at": event.published_at,
            "note": event.note,
            "fetched_at": event.fetched_at,
            "dropped_reason": None,
            "extracted_at": None,
        }
        existing = await self._rows.get(row_id)
        if existing is None:
            await self._rows.save(CorpusDocumentRow(id=row_id, **fields))
            return
        for name, value in fields.items():
            setattr(existing, name, value)
        await self._rows.save(existing)

    @handles(CorpusDerivedTextStored)
    async def _on_derived_text(self, event: CorpusDerivedTextStored) -> None:
        """Write a transcript into `corpus_documents`, not a new table.

        A derived source *is* a text source -- it chunks, it quotes, it
        extracts -- so every existing text reader has to find it here, not in
        a parallel place that would need its own `get`/`list_all`/extraction
        wiring to match. Load-and-mutate, matching `_on_stored` and
        `_on_media_stored`: the version counter climbs on a re-perception
        rather than resetting.

        **`degradations` is stored as the marker, not as null, when the
        event's own field will not parse.** The two candidates were: null
        the column, or store `UNREADABLE_DEGRADATIONS` (JSON-encoded, since
        the column is JSON text). Null loses the distinction `TextRecord`
        depends on -- its docstring says an *empty* `degradations` means "a
        complete perception", so a NULL that `to_record` decoded as `()`
        would read back as a clean transcript when the truth is that this
        column could not be read at all. Storing the marker instead means
        `to_record` decodes it to the same tuple the aggregate's own
        `_degradations_from` returns for the identical failure in `evolve` --
        one string, one meaning, whichever side reads it, and `to_record`
        reads through the identical `_decode_degradations` check this handler
        writes through, so that parity is enforced by sharing the check
        rather than by two call sites agreeing to write the same logic twice.
        This branch is not reachable through `decide`, which refuses a
        malformed payload before an event is ever written; it exists for the
        same reason `_degradations_from` does, for an event this build did
        not write -- an earlier build, a repair script, or a direct append.
        """
        row_id = CorpusDocumentRow.row_id(event.aggregate_id, event.source_id)
        degradations = (
            event.degradations
            if _decode_degradations(event.degradations) is not None
            else json.dumps(list(UNREADABLE_DEGRADATIONS))
        )
        fields = {
            "project_id": event.aggregate_id,
            "source_id": event.source_id,
            "text": event.text,
            "sha256": event.sha256,
            "char_count": len(event.text),
            "title": event.title,
            "note": event.note,
            "dropped_reason": None,
            "derived_from": event.derived_from,
            "locator_map": event.locator_map,
            "perceived_with": event.perceived_with,
            "degradations": degradations,
            "extracted_at": None,
        }
        existing = await self._rows.get(row_id)
        if existing is None:
            await self._rows.save(CorpusDocumentRow(id=row_id, **fields))
            return
        for name, value in fields.items():
            setattr(existing, name, value)
        await self._rows.save(existing)

    @handles(DocumentExtracted)
    async def _on_extracted(self, event: DocumentExtracted) -> None:
        """Note that this source now has a graph.

        The one handler here fed by a stream the corpus does not own.
        `CorpusRunner` subscribes to the whole store rather than one category,
        and dispatch is by event type, so redstring's own event arrives here
        without any new wiring -- `tenant_id` is the project, which is what
        makes the row addressable.

        **A missing row is skipped rather than raised**, which is the opposite
        of `_on_dropped`'s rule and deliberately so. `_require` treats a
        missing row as drift because the corpus aggregate refuses to drop what
        it does not hold, so the event could not legitimately exist. Nothing
        makes that true here: extraction is a different aggregate, redstring
        will happily extract a document this corpus never stored, and every
        `DocumentExtracted` written before the corpus table existed is exactly
        that. Raising would put ordinary history in the DLQ and report drift
        that is not there.
        """
        row = await self._rows.get(CorpusDocumentRow.row_id(event.tenant_id, event.source_id))
        if row is None:
            return
        row.extracted_at = event.occurred_at.isoformat()
        await self._rows.save(row)

    @handles(CorpusMediaStored)
    async def _on_media_stored(self, event: CorpusMediaStored) -> None:
        """Write the media source, superseding whatever it held before.

        Load-and-mutate, matching `_on_stored`: the version counter keeps
        climbing on a re-store rather than resetting, and `dropped_reason` is
        cleared explicitly for the same reason it is there -- storing asserts
        presence.
        """
        row_id = CorpusMediaRow.row_id(event.aggregate_id, event.source_id)
        fields = {
            "project_id": event.aggregate_id,
            "source_id": event.source_id,
            "sha256": event.sha256,
            "media_type": event.media_type,
            "byte_count": event.byte_count,
            "uri": event.uri,
            "title": event.title,
            "published_at": event.published_at,
            "note": event.note,
            "fetched_at": event.fetched_at,
            "dropped_reason": None,
        }
        existing = await self._media_rows.get(row_id)
        if existing is None:
            await self._media_rows.save(CorpusMediaRow(id=row_id, **fields))
            return
        for name, value in fields.items():
            setattr(existing, name, value)
        await self._media_rows.save(existing)

    @handles(CorpusDocumentDropped)
    async def _on_dropped(self, event: CorpusDocumentDropped) -> None:
        """Mark whichever table holds the id, never both.

        Task 2's kind-collision guard makes an id held in both tables
        impossible -- `decide` refuses a store that would change what an
        existing source id means. A handler that updated both tables
        unconditionally would not merely tolerate that guard being violated,
        it would hide the violation: the drop would "succeed" against a row
        that should not exist, instead of surfacing the id collision as
        drift. Trying the document row first and falling back to the media
        row is the same distinction `_kind_of` makes in the domain, made
        again here because the read side cannot ask the aggregate.
        """
        row_id = CorpusDocumentRow.row_id(event.aggregate_id, event.source_id)
        row = await self._rows.get(row_id)
        if row is not None:
            row.dropped_reason = event.reason
            await self._rows.save(row)
            return
        media_row = await self._require_media(event.aggregate_id, event.source_id)
        media_row.dropped_reason = event.reason
        await self._media_rows.save(media_row)

    async def _require_media(self, project_id: UUID, source_id: str) -> CorpusMediaRow:
        """The media row for a source, which must already exist.

        Reached only once `_on_dropped` has ruled out a document row, so a
        miss here means the id is in neither table: the aggregate rejects
        dropping a source it does not hold, so that cannot come from a
        legitimate stream. Inventing a row would hide exactly the drift worth
        knowing about, matching `_require`'s reasoning for the document side.
        """
        row = await self._media_rows.get(CorpusMediaRow.row_id(project_id, source_id))
        if row is None:
            raise LookupError(f"no corpus row for {source_id!r} in project {project_id}")
        return row


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
