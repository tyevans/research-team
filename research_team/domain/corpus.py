"""A corpus: the source text a project was built from, kept rather than discarded.

Extraction reads a document, writes a graph, and throws the document away.
That makes every provenance claim downstream unfalsifiable -- a citation can
name a source, but nothing can go back and check that the source says it. This
aggregate is the other half: the log keeps the bytes, so a quote can be
verified against them years later.

**The state holds no text.** `DocumentRecord` carries metadata and a digest;
the text lives only in the `SourceDocumentStored` payload, and retrieval is a
read model's job. Snapshots are taken every 50 events, and a text field here
would fold whole corpora into each one. The cost is that answering "what does
s1 say" needs a projection rather than a state read, which is the trade we
want: the fold stays cheap and constant-sized, and retrieval is a query.

**No creation event.** A corpus has no attributes of its own -- no name, no
settings -- so `CorpusCreated` would be an empty payload whose only effect is
to make the first store fail if a caller forgot it. It shares its UUID with
its project and is a distinct stream by `StreamId(aggregate_id, "Corpus")`,
so there is nothing for creation to establish that the project's own creation
has not already established. The first `SourceDocumentStored` creates it. The
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
"""

import hashlib
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from eventsource import CommandRejectedError, DeciderAggregate, DomainEvent, register_event
from pydantic import BaseModel, Field

from research_team.domain.targeting import ChecksCommandTarget


@register_event
class SourceDocumentStored(DomainEvent):
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
class SourceDocumentDropped(DomainEvent):
    """A source was excluded, and why.

    The reason is required and non-empty. A document that disappears without
    one is indistinguishable from one that was never fetched, which is the
    silent-drop failure the intake research independently called the worst
    one -- the corpus looks complete and nobody can tell that it is not.
    """

    aggregate_type: str = "Corpus"
    source_id: str
    reason: str


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


CorpusCommand = StoreSourceDocument | DropSourceDocument


class DocumentRecord(BaseModel):
    """What the fold keeps about one source. Deliberately not its text."""

    source_id: str
    sha256: str
    char_count: int
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    dropped_reason: str | None = None
    """Set means excluded. The record stays, so the exclusion stays auditable."""


class CorpusState(BaseModel):
    """Everything derivable from the corpus's event stream."""

    corpus_id: UUID | None = None
    """None before the corpus exists. Set by the fold of its first event.

    Optional because `initial_state()` takes no arguments (eventsource 0.12):
    the value before any event is one value for the aggregate *type*, and an
    id is not part of it.
    """

    status: Literal["new", "created"] = "new"
    documents: dict[str, DocumentRecord] = Field(default_factory=dict)
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

    The digest is computed here rather than accepted from the caller. A
    supplied sha256 makes `by_digest` a claim instead of a fact, and a wrong
    one stays invisible until two unrelated documents collide in it.
    """
    corpus_id = state.corpus_id
    match command, state:
        case StoreSourceDocument(), _:
            return [
                SourceDocumentStored(
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
                SourceDocumentDropped(
                    aggregate_id=corpus_id, source_id=source_id, reason=reason
                )
            ]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


def evolve(state: CorpusState, event: DomainEvent) -> CorpusState:
    """What each fact does to the state.

    Total on purpose: an unknown event leaves the state alone rather than
    raising, so a stream carrying an event this build does not know about still
    replays instead of failing halfway through.
    """
    match event:
        case SourceDocumentStored():
            previous = state.documents.get(event.source_id)
            by_digest = dict(state.by_digest)
            if previous is not None and by_digest.get(previous.sha256) == event.source_id:
                # Supersession: the old bytes are no longer what this id holds.
                del by_digest[previous.sha256]
            # First claimant of a digest keeps it, so the map answers "which
            # document already carries these bytes" with a stable id.
            by_digest.setdefault(event.sha256, event.source_id)
            record = DocumentRecord(
                source_id=event.source_id,
                sha256=event.sha256,
                char_count=len(event.text),
                uri=event.uri,
                title=event.title,
                published_at=event.published_at,
                note=event.note,
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

        case SourceDocumentDropped():
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


class Corpus(ChecksCommandTarget, DeciderAggregate[CorpusState, CorpusCommand]):
    """The imperative shell. Holds no rules -- it delegates all three.

    Mirrors `Project`'s shape exactly: the class attributes bind directly to
    the module-level functions rather than wrapping them in new method bodies,
    so there is exactly one implementation of each rule to keep in sync.
    """

    aggregate_type = "Corpus"
    target_field = "corpus_id"

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)
