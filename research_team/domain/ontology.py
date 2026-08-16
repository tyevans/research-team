"""The event a discovery pass appends, and the shapes inside it.

Its own module rather than `events.py`, whose docstring scopes that file to
"domain events for a coding session" -- this is a fact about a project's
corpus, not about a conversation. `corpus.py` already establishes that a
second event module is the shape here.

**Names, not entity ids.** A member is carried as the surface string the
document used, and resolution to an entity happens in the projection and again
on read. Storing ids would make the log record a fact about a graph state that
re-extraction can invalidate, which is the durable-log-of-derived-facts mistake
redstring's ADR 0005 is about -- and re-extraction remints ids routinely.

Changing a shape here obeys `events.py`'s strategy: a new field gets a default
meaning what its absence meant, a restructure gets a
`model_validator(mode="before")` and an `event_version` bump, and either way
`tests/infrastructure/test_schema_evolution.py` grows a case. The field most
likely to need it is `kind`, whose vocabulary is expected to grow.
"""

from typing import Literal
from uuid import UUID

from eventsource import DomainEvent, register_event
from pydantic import BaseModel, Field


class EvidenceSpan(BaseModel):
    """Where in a document the class was stated, as half-open offsets.

    Deliberately the same `source_id` plus two integers that
    `application/corpus_spans.Span` and `entity_definitions.Citation` already
    use, and deliberately not a chunk id: chunks are an index detail that gets
    rebuilt, and a citation that survives re-chunking is one a reader can still
    follow a month later.

    Offsets are into the document's own text as the corpus stored it, never
    into a chunk's text. A chunker that repeats a table header into every
    chunk of it -- which this repository now has -- makes a chunk's text stop
    being a contiguous slice of the original, so a span resolved through one
    would point at the wrong words while still rendering correctly. Nothing
    here resolves a span through a chunk, and nothing later should.
    """

    source_id: str
    start: int
    end: int


class DiscoveredMember(BaseModel):
    """One member of a class, as the document spelled it.

    `ordinal` is `None` for an unordered set and the position counting from 0
    for an ordered one. It is not derived from list order: a reader sorting an
    `unordered_set` by arrival would be reading a sequence into a bag, so the
    absence of an ordinal has to be expressible.
    """

    name: str
    ordinal: int | None = None


class RejectedMember(BaseModel):
    """A member the model proposed and verification refused, and why.

    Recorded rather than dropped because a class that found five of a declared
    six with no explanation is unjudgeable -- the reader cannot tell an
    invented member from a document that is genuinely short one, and those are
    opposite conclusions about whether to trust the pass at all.
    """

    name: str
    reason: str


class DiscoveredClass(BaseModel):
    """One class, its members, and the sentence that stated it."""

    name: str
    kind: Literal["ordered_scale", "unordered_set", "taxonomy"]
    evidence: EvidenceSpan
    members: list[DiscoveredMember]
    declared_count: int | None = None
    """The count the text stated, when it stated one -- "There are **six**
    difficulties". A checksum, not a length: it is compared against the members
    actually found, and a disagreement is shown rather than resolved. Most
    classes state no count, so `None` is ordinary rather than an error.

    It also catches a case the design did not originally anticipate. Measured
    2026-08-15 in `wiki-roman-economy`: "Inscriptions record 268 different
    occupations ... including fishermen, salt merchants, olive oil dealers"
    names nine members against a declared 268. "Including" marks a list the
    document is sampling rather than stating, and `9 of 268` renders as a
    sample on sight with no further machinery.
    """
    parent_name: str | None = None
    rejected_members: list[RejectedMember] = Field(default_factory=list)


@register_event
class OntologyDiscovered(DomainEvent):
    """The classes one discovery pass found in one document.

    Appended directly rather than through a `DeciderAggregate`, unlike
    `Corpus`: this enforces no invariant, because a pass replaces a source's
    classes wholesale and re-running it is idempotent by construction. There is
    nothing for a decider to decide, and routing through `Corpus` would fold
    derived data into the aggregate that owns the verbatim source text.

    One stream per project (`aggregate_id` is the project id). `project_id` is
    also a field, because a projection reads the payload and should not have to
    know that the two happen to be equal -- `SessionStarted.project_id` carries
    a project the same way for the same reason.

    An empty `classes` is a real and expected outcome: it records that this
    document was examined and states no classes. That is the difference between
    "grouped, nothing found" and "never grouped", and `ungrouped` depends on
    being able to tell them apart.
    """

    aggregate_type: str = "Ontology"
    project_id: UUID
    source_id: str
    model_version: str
    classes: list[DiscoveredClass] = Field(default_factory=list)
