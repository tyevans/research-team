"""Source and document presenters for the web interface."""

from typing import Any

from research_team.research.application.corpus_read import SourceListing, StoredDocument
from research_team.research.application.corpus_spans import Span
from research_team.research.domain import SourceRecord


def _record_view(summary: SourceRecord) -> dict[str, Any]:
    """The fields every source view shares: everything the record itself knows.

    Split from `source_view` when `extracted` arrived, rather than letting
    `source_text_view` inherit it. Reading one document answers from the row
    and does not carry extraction state, so building on the full view would
    have meant `source_text_view` inventing a value for a field it cannot
    know -- and `False` there would read as "this has no graph" on a document
    that has one.

    `char_count` on a text record and `media_type`/`byte_count` on a media one
    -- discriminated on `kind` rather than `getattr(summary, "char_count",
    None)`. There is no type checker in CI or `pyproject.toml`, so nothing
    checks the cases are exhaustive at build time; what this form buys is the
    *runtime* failure being loud. A third `kind` added without a case here
    falls into the `else` and raises `AttributeError` on the first request
    that touches one -- where `getattr` with a default would have rendered
    `char_count: null` for it and shipped. A media row has no character count
    to report and a text row has no mimetype; putting one number under a name
    the other kind cannot give would read as data rather than as the absence
    it is. Covered by the pair of tests in `test_presenters.py`, each of which
    asserts the other kind's fields are *absent* rather than null.
    """
    fields: dict[str, Any] = {
        "source_id": summary.source_id,
        "kind": summary.kind,
        # The digest is what lets a caller prove a quote (or a download) came
        # from the bytes on record rather than from a source since revised.
        "sha256": summary.sha256,
        "uri": summary.uri,
        "title": summary.title,
        "published_at": summary.published_at,
        "note": summary.note,
        # Provenance for by-reference content the corpus did not create, not
        # a corpus fact -- see `TextRecord.fetched_at`. Exposed because
        # `revise` and `restore` both carry it through unconditionally, and a
        # console that could not read it back would have no way to show that
        # an edit had (or had not) disturbed it.
        "fetched_at": summary.fetched_at,
        # Null for a live document; set means excluded. Always present so a
        # caller can tell "not dropped" from "the field went missing".
        "dropped_reason": summary.dropped_reason,
    }
    if summary.kind == "media":
        fields["media_type"] = summary.media_type
        fields["byte_count"] = summary.byte_count
    else:
        fields["char_count"] = summary.char_count
        # Always present on a text row, `None`/`[]` for one nobody perceived.
        # Unconditional rather than emitted only for a transcript, because the
        # page's question is "was this derived, and what was missed" -- and a
        # key that appears only on derived rows would make "not derived" and
        # "an older server that did not send this" the same absence.
        fields["derived_from"] = summary.derived_from
        # A list, not the JSON string the event carries: the read model has
        # already decoded it (`_decode_degradations`), and re-encoding it here
        # would hand the browser a second thing to parse.
        fields["degradations"] = list(summary.degradations)
    return fields


def source_view(listing: SourceListing) -> dict[str, Any]:
    """One row of `/api/projects/{id}/sources`: what a source is, not what it says.

    No `text` key, and that absence is the contract rather than an oversight.
    A corpus can hold hundreds of papers; a listing that inlined even a
    snippet of each would cost more to render than reading the one document
    the caller actually wanted.

    Takes the listing rather than the record because `extracted` is not on the
    record and deliberately cannot be: extraction lives on another aggregate's
    stream. See `SourceListing`.
    """
    return {
        **_record_view(listing.record),
        # Whether this document's text has been folded into the graph. False
        # on every row of a database that predates the column until the corpus
        # projection is rebuilt -- see `CorpusDocumentRow.extracted_at` -- and
        # unconditionally False for media, which nothing extracts yet.
        "extracted": listing.extracted,
    }


def source_text_view(document: StoredDocument, span: Span) -> dict[str, Any]:
    """One source's text, with the offsets that make a quote from it checkable.

    `start` and `end` are read off `span` -- what was actually returned --
    rather than off the request, which is only a guess and may have asked for
    more than the document has. A citation built on requested offsets looks
    verifiable and is not, which is the failure this whole layer exists to
    prevent. `char_count` stays the whole document's, so a caller can tell a
    partial read from a complete one without a second request.
    """
    return {
        **_record_view(document.record),
        "text": span.text,
        "start": span.start,
        "end": span.end,
    }
