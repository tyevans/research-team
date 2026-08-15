"""What a human has decided about which names are the same thing.

Consolidation reaches the adjudicator for 2 of 10 genuine duplicates --
measured on 2026-08-14 against a real `nomic-embed-text`, and recorded in
BACKLOG B58 with the table. Four attempts to close that by scoring failed for
one reason: every signal derived from document context (graph neighbours,
descriptions, source snippets) pulls true cross-document pairs apart, because
two documents about one entity describe *different facets* of it. The name is
the only document-invariant signal there is.

So this aggregate is the manual override, and its key is the only key that can
carry across documents. Entity ids cannot: they are
`uuid5(uuid5(uuid5(tenant_id, source_id), entity_type), normalize_name(name))`,
so `source_id` is in the hash and "Grant" in two documents is two ids by
construction -- which is why cross-document duplicates exist as separate nodes
at all. An id-keyed judgement would survive `/rebuild` and still say nothing
about the next document, leaving a human to re-answer the same question per
document. That treadmill is what this exists to end.

**The cost, stated because it is real.** A name-keyed judgement cannot express
"distinct here, same there". A project holding both `Mercury` the planet and
`Mercury` the element cannot keep them apart in one place and together in
another. Accepted deliberately; per-id judgements remain addable later as a
second kind without disturbing this one.
"""

from uuid import UUID

from eventsource import DomainEvent, register_event
from pydantic import BaseModel, ConfigDict
from redstring.domain.similarity import normalize_name


class EntityKey(BaseModel):
    """One name-and-type a judgement can be about.

    Frozen and hashable because the fold indexes dicts and sets by it.
    """

    model_config = ConfigDict(frozen=True)

    normalized_name: str
    entity_type: str

    @classmethod
    def of(cls, name: str, entity_type: str) -> "EntityKey":
        """Build a key, normalising the name exactly as redstring does.

        The only constructor call sites should use. Constructing the model
        directly with an unnormalised name yields a key that matches nothing,
        and the symptom is a judgement that appears to do nothing rather than
        an error.
        """
        return cls(normalized_name=normalize_name(name), entity_type=entity_type)


@register_event
class EntitiesHeldSame(DomainEvent):
    """A human said these names denote one thing."""

    aggregate_type: str = "EntityJudgements"
    keys: list[EntityKey]
    reason: str


@register_event
class EntitiesHeldDistinct(DomainEvent):
    """A human said these two names never denote one thing."""

    aggregate_type: str = "EntityJudgements"
    left: EntityKey
    right: EntityKey
    reason: str


@register_event
class JudgementWithdrawn(DomainEvent):
    """A human took back an earlier judgement.

    Compensating rather than a delete: the judgement stays in the log and the
    fold stops applying it, so "what did I once believe" is still answerable.
    """

    aggregate_type: str = "EntityJudgements"
    judgement_id: UUID
    reason: str
