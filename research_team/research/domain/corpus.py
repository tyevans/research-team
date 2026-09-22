"""A corpus: the source text a project was built from, kept rather than discarded.

Extraction reads a document, writes a graph, and throws the document away.
That makes every provenance claim downstream unfalsifiable -- a citation can
name a source, but nothing can go back and check that the source says it. This
aggregate is the other half: the log keeps the bytes, so a quote can be
verified against them years later.

Decision logic (command validation and invariant enforcement) and event
evolution (state fold rules) are factored into `corpus_decider.py`.
"""

from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from eventsource import CommandRejectedError, DeciderAggregate, DomainEvent, register_event
from pydantic import BaseModel, Field

UNREADABLE_DEGRADATIONS = ("<degradations could not be read from the event>",)
"""What `evolve` records when an event's `degradations` payload will not parse.

Angle-bracketed so it cannot be mistaken for a degradation a perception model
actually reported -- this is the state saying it failed to read a field, not a
transcriber saying it failed to see something. Exported rather than inlined
because a reader of a `TextRecord` may want to test for it, and a string
literal repeated at both ends is a string literal that drifts at one end.
"""


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


@register_event
class CorpusDerivedTextStored(DomainEvent):
    """What a perception model made of a stored medium.

    A separate event from `CorpusDocumentStored` because a derived source has
    to stay permanently distinguishable from a fetched one: a quote from a
    transcript is a quote from a model's reading of an audio track, and
    provenance that cannot tell those apart is the unfalsifiable-provenance
    failure this module exists to prevent, one level up.
    """

    aggregate_type: str = "Corpus"
    source_id: str
    derived_from: str
    text: str
    sha256: str
    locator_map: str
    perceived_with: str
    degradations: str
    title: str | None = None
    note: str | None = None


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


@dataclass(frozen=True)
class StoreDerivedText:
    """Store what perception made of a medium."""

    corpus_id: UUID
    source_id: str
    derived_from: str
    text: str
    locator_map: str
    perceived_with: str
    degradations: str
    title: str | None = None
    note: str | None = None


CorpusCommand = StoreSourceDocument | StoreSourceMedia | StoreDerivedText | DropSourceDocument


class SourceRecordBase(BaseModel):
    """What every source has, whatever its bytes are."""

    source_id: str
    sha256: str
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    fetched_at: str | None = None
    dropped_reason: str | None = None


class TextRecord(SourceRecordBase):
    """A source the corpus holds as prose. Deliberately not its text."""

    kind: Literal["text"] = "text"
    char_count: int
    derived_from: str | None = None
    perceived_with: str | None = None
    degradations: tuple[str, ...] = ()


class MediaRecord(SourceRecordBase):
    """A source whose bytes live in the blob store under `sha256`."""

    kind: Literal["media"] = "media"
    media_type: str
    byte_count: int


SourceRecord = Annotated[TextRecord | MediaRecord, Field(discriminator="kind")]


class CorpusState(BaseModel):
    """Everything derivable from the corpus's event stream."""

    corpus_id: UUID | None = None
    status: Literal["new", "created"] = "new"
    documents: dict[str, SourceRecord] = Field(default_factory=dict)
    by_digest: dict[str, str] = Field(default_factory=dict)


def initial_state() -> CorpusState:
    return CorpusState()


from research_team.research.domain.corpus_decider import decide, evolve  # noqa: E402


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


__all__ = [
    "UNREADABLE_DEGRADATIONS",
    "CommandRejectedError",
    "Corpus",
    "CorpusCommand",
    "CorpusDerivedTextStored",
    "CorpusDocumentDropped",
    "CorpusDocumentStored",
    "CorpusMediaStored",
    "CorpusState",
    "DropSourceDocument",
    "MediaRecord",
    "SourceRecord",
    "SourceRecordBase",
    "StoreDerivedText",
    "StoreSourceDocument",
    "StoreSourceMedia",
    "TextRecord",
    "decide",
    "evolve",
    "initial_state",
]
