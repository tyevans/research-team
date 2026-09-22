"""Corpus document and media read model rows and record conversions.

Extracted from corpus_read_models.py to isolate SQLite table schemas and
record transformations from projections and runner orchestration.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid5

from eventsource import ReadModel

from research_team.research.domain import (
    UNREADABLE_DEGRADATIONS,
    MediaRecord,
    SourceRecord,
    TextRecord,
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
    "_decode_degradations",
    "_degradations_of",
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
