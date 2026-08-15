"""A corpus: the source text a project was built from, kept rather than discarded.

Extraction reads a document, writes a graph, and throws the document away.
That makes every provenance claim downstream unfalsifiable -- a citation can
name a source, but nothing can go back and check that the source says it. This
aggregate is the other half: the log keeps the bytes, so a quote can be
verified against them years later.

**The state holds no text.** `DocumentRecord` carries metadata and a digest;
the text lives only in the `CorpusDocumentStored` payload, and retrieval is a
read model's job. Snapshots are taken every 50 events, and a text field here
would fold whole corpora into each one. The cost is that answering "what does
s1 say" needs a projection rather than a state read, which is the trade we
want: the fold stays cheap and constant-sized, and retrieval is a query.

**No creation event.** A corpus has no attributes of its own -- no name, no
settings -- so `CorpusCreated` would be an empty payload whose only effect is
to make the first store fail if a caller forgot it. It shares its UUID with
its project and is a distinct stream by `StreamId(aggregate_id, "Corpus")`,
so there is nothing for creation to establish that the project's own creation
has not already established. The first `CorpusDocumentStored` creates it. The
house `status: "new" | "created"` vocabulary is kept anyway, because it is
what a reader of `project.py` expects and because "empty" still has to answer
for itself: a drop against a corpus that never held anything is a caller bug
worth naming, not a silent no-op.

**Supersession is by `source_id`.** Storing a `source_id` that already exists
replaces its record -- a re-fetch of the same URI is a revision of one
document, not a second document. The earlier text is still in the log and
still folds into any read model that wants versions; only the index moves to
the new bytes, since "current" is the only question state can usefully answer.
The alternative, rejecting a re-store and forcing a drop first, would make the
ordinary case (refetching a page that changed) a two-command dance whose
intermediate state is a corpus with a hole in it.

Identical bytes under a *different* `source_id` are detectable via `by_digest`
but not refused. The same document legitimately arrives at two URIs, and the
domain has no basis for choosing which one the caller meant; detection is what
the ingest path needs to skip re-extraction, and prevention is not its call.

**One `source_id` namespace holds both text and media.** A source is a source
whichever kind its bytes are, `by_digest` and supersession-by-`source_id` mean
the same thing for either, and a second namespace would need its own answer to
every question this module already answers for text -- for no reader-visible
gain, since nothing downstream cares which namespace an id came from. A
`source_id` cannot change kind once claimed: `decide` refuses a store that
would flip it, in both directions, because supersession is a revision of one
source and a kind change is a different source wearing the old id.

**For media the digest is supplied, and that is a deliberate weakening.** The
bytes never reach the domain -- holding a video in memory to hand it to a pure
function is not a thing to do -- so `CorpusMediaStored.sha256` is what the blob
store computed while streaming, and `by_digest` is a claim for those entries
rather than a fact. `application/blobs.py` carries the mitigation: `put`
returns the digest and there is no parameter by which a caller could offer a
different one, so a wrong digest requires a bug in the store rather than a
mistake at a call site.
"""

import hashlib
from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from eventsource import CommandRejectedError, DeciderAggregate, DomainEvent, register_event
from pydantic import BaseModel, Field


@register_event
class CorpusDocumentStored(DomainEvent):
    """The text of a source, kept verbatim. Also the corpus's creation event.

    `published_at` is text, not a date: sources report dates in whatever shape
    they please, and parsing at the boundary would either lose the ones that
    do not fit or invent precision the source never claimed.
    """

    aggregate_type: str = "Corpus"
    source_id: str
    text: str
    sha256: str
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    fetched_at: str | None = None


@register_event
class CorpusDocumentDropped(DomainEvent):
    """A source was excluded, and why.

    The reason is required and non-empty. A document that disappears without
    one is indistinguishable from one that was never fetched, which is the
    silent-drop failure the intake research independently called the worst
    one -- the corpus looks complete and nobody can tell that it is not.
    """

    aggregate_type: str = "Corpus"
    source_id: str
    reason: str


@register_event
class CorpusMediaStored(DomainEvent):
    """A media source was stored: the claim about it, never its bytes.

    `sha256` is where the bytes are and what proves they are the ones this
    event meant. Unlike `CorpusDocumentStored.sha256` it is *supplied* rather
    than computed -- see this module's docstring, and `application/blobs.py`
    for why that is a hazard rather than a trap.

    `published_at` is text for the same reason it is on the document event:
    sources report dates in whatever shape they please.
    """

    aggregate_type: str = "Corpus"
    source_id: str
    sha256: str
    media_type: str
    byte_count: int
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    fetched_at: str | None = None


@dataclass(frozen=True)
class StoreSourceDocument:
    #: Which corpus to store into. Storing is what brings a corpus into
    #: existence, so this is the one command whose target cannot be read back
    #: off the state -- there is no state yet. Every later command takes its
    #: id from the fold of this one's event.
    corpus_id: UUID
    source_id: str
    text: str
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    fetched_at: str | None = None


@dataclass(frozen=True)
class DropSourceDocument:
    source_id: str
    reason: str


@dataclass(frozen=True)
class StoreSourceMedia:
    #: Carried for the same reason `StoreSourceDocument` carries it: storing is
    #: what brings a corpus into existence, so there is no state to read it off.
    corpus_id: UUID
    source_id: str
    sha256: str
    media_type: str
    byte_count: int
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    fetched_at: str | None = None


CorpusCommand = StoreSourceDocument | StoreSourceMedia | DropSourceDocument


class SourceRecordBase(BaseModel):
    """What every source has, whatever its bytes are.

    Split out rather than repeated so a field added to provenance is added
    once. The two subclasses differ by exactly the one measure the other
    cannot give: characters against bytes.
    """

    source_id: str
    sha256: str
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    fetched_at: str | None = None
    """When the source was retrieved, for by-reference content the corpus did
    not create -- provenance, not a corpus fact. Carried through so a revise
    or restore that re-stores this record's own fields cannot silently zero
    it; see `CorpusEditor._store` for why that caller has to read it back
    before writing."""
    dropped_reason: str | None = None
    """Set means excluded. The record stays, so the exclusion stays auditable."""


class TextRecord(SourceRecordBase):
    """A source the corpus holds as prose. Deliberately not its text.

    Was `DocumentRecord`, renamed when media arrived: `document` had quietly
    come to mean both "a source" and "a source made of words", and the union
    below needs those to be different words.
    """

    kind: Literal["text"] = "text"
    char_count: int


class MediaRecord(SourceRecordBase):
    """A source whose bytes live in the blob store under `sha256`.

    Carries no path or URL to those bytes. The digest *is* the address, and a
    second locator stored here would be a thing that could disagree with it --
    which is precisely the failure the digest exists to make impossible.
    """

    kind: Literal["media"] = "media"
    media_type: str
    """The mimetype, as the ingest path determined it. Not re-sniffed here:
    the domain has no bytes to sniff."""
    byte_count: int


SourceRecord = Annotated[TextRecord | MediaRecord, Field(discriminator="kind")]
"""One `source_id` namespace, two shapes.

Discriminated on a literal rather than left as a bare union so pydantic
round-trips it without guessing and so the type checker -- not a runtime
`AttributeError` in a template -- finds the readers that assumed `.text`.
"""


class CorpusState(BaseModel):
    """Everything derivable from the corpus's event stream."""

    corpus_id: UUID | None = None
    """None before the corpus exists. Set by the fold of its first event.

    Optional because `initial_state()` takes no arguments (eventsource 0.12):
    the value before any event is one value for the aggregate *type*, and an
    id is not part of it.
    """

    status: Literal["new", "created"] = "new"
    documents: dict[str, SourceRecord] = Field(default_factory=dict)
    by_digest: dict[str, str] = Field(default_factory=dict)
    """sha256 -> source_id, for live documents only.

    A dropped document releases its digest: otherwise re-ingesting the same
    bytes would look like a duplicate of something the corpus no longer holds.
    """


def initial_state() -> CorpusState:
    return CorpusState()


def decide(command: CorpusCommand, state: CorpusState) -> list[DomainEvent]:
    """Which requests are legal, and what facts they produce.

    Reads as a transition table, the way `project.decide` does.

    The digest is computed here rather than accepted from the caller -- for
    text. A supplied sha256 makes `by_digest` a claim instead of a fact, and a
    wrong one stays invisible until two unrelated documents collide in it.

    **For media the digest is supplied, and that is a deliberate weakening.**
    The bytes never reach the domain -- holding a video in memory to hand it
    to a pure function is not a thing to do -- so `CorpusMediaStored.sha256`
    is what the blob store computed while streaming, and `by_digest` is a
    claim for those entries rather than a fact. `application/blobs.py`
    carries the mitigation: `put` returns the digest and there is no
    parameter by which a caller could offer a different one, so a wrong
    digest requires a bug in the store rather than a mistake at a call site.
    """
    corpus_id = state.corpus_id
    match command, state:
        case StoreSourceDocument(source_id=source_id), _ if (
            _kind_of(state, source_id) == "media"
        ):
            raise CommandRejectedError(
                f"source {source_id!r} holds media; storing text under it would "
                "change what the id means rather than revise it"
            )

        case StoreSourceMedia(source_id=source_id), _ if _kind_of(state, source_id) == "text":
            raise CommandRejectedError(
                f"source {source_id!r} holds text; storing media under it would "
                "change what the id means rather than revise it"
            )

        case StoreSourceDocument(), _:
            return [
                CorpusDocumentStored(
                    # From the command, not the state: this is the creation
                    # command, so on a fresh corpus `state.corpus_id` is None.
                    aggregate_id=command.corpus_id,
                    source_id=command.source_id,
                    text=command.text,
                    sha256=hashlib.sha256(command.text.encode("utf-8")).hexdigest(),
                    uri=command.uri,
                    title=command.title,
                    published_at=command.published_at,
                    note=command.note,
                    fetched_at=command.fetched_at,
                )
            ]

        case StoreSourceMedia(), _:
            return [
                CorpusMediaStored(
                    # From the command, not the state: see the identical
                    # comment on the `StoreSourceDocument` case above.
                    aggregate_id=command.corpus_id,
                    source_id=command.source_id,
                    sha256=command.sha256,
                    media_type=command.media_type,
                    byte_count=command.byte_count,
                    uri=command.uri,
                    title=command.title,
                    published_at=command.published_at,
                    note=command.note,
                    fetched_at=command.fetched_at,
                )
            ]

        # Storing is the only thing an empty corpus can do, since storing is
        # what brings it into existence.
        case _, CorpusState(status="new"):
            raise CommandRejectedError("corpus is empty")

        case DropSourceDocument(source_id=source_id, reason=reason), _:
            if not reason.strip():
                raise CommandRejectedError("a drop requires a reason")
            record = state.documents.get(source_id)
            if record is None:
                # Named, not just refused: the next thing anyone asks is which
                # id the corpus actually holds.
                raise CommandRejectedError(f"unknown source {source_id!r}")
            if record.dropped_reason is not None:
                raise CommandRejectedError(
                    f"source {source_id!r} already dropped: {record.dropped_reason}"
                )
            return [
                CorpusDocumentDropped(
                    aggregate_id=corpus_id, source_id=source_id, reason=reason
                )
            ]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


def _kind_of(state: CorpusState, source_id: str) -> str | None:
    """Which shape a source id already holds, or None if it is free.

    A dropped record still counts. Its id is taken -- restore reads it back --
    and letting a drop free the id for the other kind would make restore
    resurrect a record whose kind no longer matches its row.
    """
    record = state.documents.get(source_id)
    return None if record is None else record.kind


def evolve(state: CorpusState, event: DomainEvent) -> CorpusState:
    """What each fact does to the state.

    Total on purpose: an unknown event leaves the state alone rather than
    raising, so a stream carrying an event this build does not know about still
    replays instead of failing halfway through.
    """
    match event:
        case CorpusDocumentStored():
            previous = state.documents.get(event.source_id)
            by_digest = dict(state.by_digest)
            if previous is not None and by_digest.get(previous.sha256) == event.source_id:
                # Supersession: the old bytes are no longer what this id holds.
                del by_digest[previous.sha256]
            # First claimant of a digest keeps it, so the map answers "which
            # document already carries these bytes" with a stable id.
            by_digest.setdefault(event.sha256, event.source_id)
            record = TextRecord(
                source_id=event.source_id,
                sha256=event.sha256,
                char_count=len(event.text),
                uri=event.uri,
                title=event.title,
                published_at=event.published_at,
                note=event.note,
                fetched_at=event.fetched_at,
            )
            return state.model_copy(
                update={
                    # The event is where the id enters the state: `decide` reads
                    # it back off `state` for every command but the first.
                    "corpus_id": event.aggregate_id,
                    "status": "created",
                    "documents": {**state.documents, event.source_id: record},
                    "by_digest": by_digest,
                }
            )

        case CorpusMediaStored():
            previous = state.documents.get(event.source_id)
            by_digest = dict(state.by_digest)
            if previous is not None and by_digest.get(previous.sha256) == event.source_id:
                del by_digest[previous.sha256]
            by_digest.setdefault(event.sha256, event.source_id)
            record = MediaRecord(
                source_id=event.source_id,
                sha256=event.sha256,
                media_type=event.media_type,
                byte_count=event.byte_count,
                uri=event.uri,
                title=event.title,
                published_at=event.published_at,
                note=event.note,
                fetched_at=event.fetched_at,
            )
            return state.model_copy(
                update={
                    "corpus_id": event.aggregate_id,
                    "status": "created",
                    "documents": {**state.documents, event.source_id: record},
                    "by_digest": by_digest,
                }
            )

        case CorpusDocumentDropped():
            record = state.documents.get(event.source_id)
            if record is None:
                return state
            by_digest = {
                digest: source_id
                for digest, source_id in state.by_digest.items()
                if source_id != event.source_id
            }
            return state.model_copy(
                update={
                    "documents": {
                        **state.documents,
                        event.source_id: record.model_copy(
                            update={"dropped_reason": event.reason}
                        ),
                    },
                    "by_digest": by_digest,
                }
            )

        case _:
            return state


class Corpus(DeciderAggregate[CorpusState, CorpusCommand]):
    """The imperative shell. Holds no rules -- it delegates all three.

    Mirrors `Project`'s shape exactly: the class attributes bind directly to
    the module-level functions rather than wrapping them in new method bodies,
    so there is exactly one implementation of each rule to keep in sync.
    """

    aggregate_type = "Corpus"

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)
