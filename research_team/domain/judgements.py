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

import re
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from eventsource import CommandRejectedError, DeciderAggregate, DomainEvent, register_event
from pydantic import BaseModel, ConfigDict, Field

_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Casefold, strip, and collapse internal whitespace runs to one space.

    **A deliberate copy of redstring's own `normalize_name`, and the copy is
    forced.** The key this module builds has to match what
    `find_entities(name=...)` compares against, which is redstring's
    `normalized_name` -- so the two functions agreeing is a correctness
    requirement, not a convenience. But redstring does not export it: it lives
    at `redstring.domain.normalization` and is absent from `redstring.__all__`,
    and `tests/test_architecture.py` forbids `research_team/` from reaching
    into `redstring.domain.` at all, because anything behind a dotted path
    there is private and may change in a *patch* release. The domain layer is
    additionally forbidden from naming redstring at any path.

    So there is no import that is both available and allowed, and three lines
    are copied instead. `test_normalisation_matches_redstrings` pins the
    agreement by importing the private function -- `tests/` is exempt from that
    rule precisely so a parity check like this one can exist -- and fails the
    moment redstring's definition moves. That test is the whole safety of this
    copy; deleting it turns a pinned duplication into an unpinned one.

    Hyphens and underscores are left untouched. `casefold`, not `lower`: they
    differ on non-ASCII (German ß casefolds to ss) and redstring uses casefold.
    Never raises.
    """
    return _WHITESPACE_RUN.sub(" ", name.casefold().strip())


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


class JudgementRecord(BaseModel):
    """One judgement as the fold keeps it, live or withdrawn."""

    kind: Literal["same", "distinct"]
    keys: list[EntityKey]
    reason: str
    withdrawn_reason: str | None = None
    """Set means the fold no longer applies it. The record stays, so the
    decision and its retraction both remain auditable."""


class JudgementsState(BaseModel):
    """Everything derivable from this project's judgement stream.

    Holds the judgements and derives groups on demand rather than caching
    them. Withdrawal makes a cache the harder half: removing one judgement can
    split a group, leave it whole, or do nothing, depending on what else joined
    those keys, so the honest incremental update is a recompute anyway. The set
    is human-authored and small.
    """

    judgements_id: UUID | None = None
    judgements: dict[UUID, JudgementRecord] = Field(default_factory=dict)

    def _live(self, kind: str) -> list[JudgementRecord]:
        return [
            record
            for record in self.judgements.values()
            if record.kind == kind and record.withdrawn_reason is None
        ]

    def group_for(self, key: EntityKey) -> frozenset[EntityKey]:
        """Every key held to denote the same thing as `key`, including itself.

        A key nobody has judged comes back alone rather than empty, so callers
        need no None branch and "no judgement" reads as "a group of one".
        """
        group = {key}
        # Fixed point rather than one pass: A=B recorded after B=C still has to
        # pull A into C's group, and the records are in event order, not
        # dependency order.
        changed = True
        while changed:
            changed = False
            for record in self._live("same"):
                members = set(record.keys)
                if members & group and not members <= group:
                    group |= members
                    changed = True
        return frozenset(group)

    def are_held_distinct(self, left: EntityKey, right: EntityKey) -> bool:
        """Whether a human has said these two are never the same thing.

        Pairwise and symmetric, and deliberately **not** transitive: "A is not
        B" and "B is not C" says nothing whatever about A and C.
        """
        pair = {left, right}
        return any(set(record.keys) == pair for record in self._live("distinct"))


def initial_state() -> JudgementsState:
    return JudgementsState()


def evolve(state: JudgementsState, event: DomainEvent) -> JudgementsState:
    """What each fact does to the state.

    Total on purpose: an unknown event leaves the state alone rather than
    raising, so a stream carrying an event this build does not know about still
    replays instead of failing halfway through.
    """
    match event:
        case EntitiesHeldSame():
            record = JudgementRecord(kind="same", keys=list(event.keys), reason=event.reason)
            return state.model_copy(
                update={
                    "judgements_id": state.judgements_id or event.aggregate_id,
                    "judgements": {**state.judgements, event.event_id: record},
                }
            )

        case EntitiesHeldDistinct():
            record = JudgementRecord(
                kind="distinct", keys=[event.left, event.right], reason=event.reason
            )
            return state.model_copy(
                update={
                    "judgements_id": state.judgements_id or event.aggregate_id,
                    "judgements": {**state.judgements, event.event_id: record},
                }
            )

        case JudgementWithdrawn():
            existing = state.judgements.get(event.judgement_id)
            if existing is None:
                return state
            return state.model_copy(
                update={
                    "judgements": {
                        **state.judgements,
                        event.judgement_id: existing.model_copy(
                            update={"withdrawn_reason": event.reason}
                        ),
                    }
                }
            )

        case _:
            return state


@dataclass(frozen=True)
class HoldSame:
    #: Which project's judgements. Carried on the command rather than read off
    #: the state because this may be the creation command, exactly as
    #: `StoreSourceDocument.corpus_id` is.
    judgements_id: UUID
    keys: list[EntityKey]
    reason: str


@dataclass(frozen=True)
class HoldDistinct:
    judgements_id: UUID
    left: EntityKey
    right: EntityKey
    reason: str


@dataclass(frozen=True)
class WithdrawJudgement:
    #: No `judgements_id`: a withdrawal can only follow a judgement, so the
    #: stream already exists and the state carries its id.
    judgement_id: UUID
    reason: str


JudgementCommand = HoldSame | HoldDistinct | WithdrawJudgement


def _prospective_group(state: JudgementsState, keys: list[EntityKey]) -> set[EntityKey]:
    """Every key that would end up in one group if `keys` were held same."""
    group: set[EntityKey] = set()
    for key in keys:
        group |= state.group_for(key)
    return group


def decide(command: JudgementCommand, state: JudgementsState) -> list[DomainEvent]:
    """Which judgements are legal, and what facts they produce.

    Contradictions are refused **here** rather than resolved later by
    `JudgedCandidates`. A finder that had to reconcile "same" against "not the
    same" would be choosing on a human's behalf, silently, at scoring time --
    and whichever way it chose would be invisible.
    """
    match command:
        case HoldSame(judgements_id=judgements_id, keys=keys, reason=reason):
            if not reason.strip():
                raise CommandRejectedError("a judgement requires a reason")
            unique = set(keys)
            if len(unique) < 2:
                raise CommandRejectedError(
                    "holding names the same needs at least two distinct keys"
                )
            group = _prospective_group(state, keys)
            # Checked over the prospective group, not the command's own keys:
            # holding A=B is a contradiction when B already shares a group with
            # C and A is held distinct from C, and that only appears after the
            # union.
            for judgement_id, record in state.judgements.items():
                if record.kind != "distinct" or record.withdrawn_reason is not None:
                    continue
                if set(record.keys) <= group:
                    raise CommandRejectedError(
                        f"those names are held distinct by judgement {judgement_id}; "
                        f"withdraw it first"
                    )
            return [
                EntitiesHeldSame(aggregate_id=judgements_id, keys=list(keys), reason=reason)
            ]

        case HoldDistinct(judgements_id=judgements_id, left=left, right=right, reason=reason):
            if not reason.strip():
                raise CommandRejectedError("a judgement requires a reason")
            if left == right:
                raise CommandRejectedError("a name cannot be held distinct from itself")
            group = state.group_for(left)
            if right in group:
                # Name the same-record responsible, the way the HoldSame branch
                # names the distinct-record it conflicts with -- otherwise the
                # caller is told to withdraw a judgement without saying which
                # one, and a group can be the union of arbitrarily many
                # same-records so it cannot be inferred.
                #
                # A group can have more than one live same-record contributing
                # to it (A=B, then B=C -- both are "responsible" for A and C
                # sharing a group). Naming any one live record whose keys
                # intersect the group is enough for a UI to offer "withdraw
                # this one first"; which one is an arbitrary choice, not a
                # meaningful one.
                for judgement_id, record in state.judgements.items():
                    if record.kind != "same" or record.withdrawn_reason is not None:
                        continue
                    if set(record.keys) & group:
                        raise CommandRejectedError(
                            f"those names are held same by judgement {judgement_id}; "
                            f"withdraw it first"
                        )
            return [
                EntitiesHeldDistinct(
                    aggregate_id=judgements_id, left=left, right=right, reason=reason
                )
            ]

        case WithdrawJudgement(judgement_id=judgement_id, reason=reason):
            if not reason.strip():
                raise CommandRejectedError("a withdrawal requires a reason")
            record = state.judgements.get(judgement_id)
            if record is None:
                raise CommandRejectedError(f"unknown judgement {judgement_id}")
            if record.withdrawn_reason is not None:
                raise CommandRejectedError(
                    f"judgement {judgement_id} was already withdrawn: "
                    f"{record.withdrawn_reason}"
                )
            return [
                JudgementWithdrawn(
                    aggregate_id=state.judgements_id,
                    judgement_id=judgement_id,
                    reason=reason,
                )
            ]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


class EntityJudgements(DeciderAggregate[JudgementsState, JudgementCommand]):
    """The imperative shell. Holds no rules -- it delegates all three.

    Mirrors `Corpus`'s shape exactly: the class attributes bind directly to the
    module-level functions rather than wrapping them in new method bodies, so
    there is exactly one implementation of each rule to keep in sync.
    """

    aggregate_type = "EntityJudgements"

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)
