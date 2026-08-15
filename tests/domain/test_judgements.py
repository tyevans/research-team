"""The value types a judgement is expressed in."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from research_team.domain.corpus import CorpusDocumentStored
from research_team.domain.judgements import (
    EntitiesHeldDistinct,
    EntitiesHeldSame,
    EntityKey,
    JudgementWithdrawn,
    evolve,
    initial_state,
)

PROJECT = uuid4()

JFK = EntityKey.of("JFK", "person")
JOHN = EntityKey.of("John F. Kennedy", "person")
KENNEDY = EntityKey.of("Kennedy", "person")
IRAN = EntityKey.of("Iran", "place")
IRAQ = EntityKey.of("Iraq", "place")


def _fold(*events):
    state = initial_state()
    for event in events:
        state = evolve(state, event)
    return state


def test_a_key_normalises_the_name_when_it_is_built():
    """Normalised at construction, so equality is plain field equality.

    A key that skipped normalisation would silently never match anything --
    `find_entities(name=...)` compares `normalized_name` exactly -- and the
    failure would look like "the judgement did nothing" rather than like a
    bug. `of` is the only constructor call sites use, for that reason.
    """
    assert EntityKey.of("Dr. Grant", "person") == EntityKey.of("  dr. grant ", "person")
    assert EntityKey.of("Grant", "person") != EntityKey.of("Grant", "organisation")


def test_a_key_is_hashable_so_the_state_can_index_by_it():
    """The fold keys dicts and sets by this, so frozen-and-hashable is load-bearing."""
    assert len({EntityKey.of("Grant", "person"), EntityKey.of("grant", "person")}) == 1


def test_a_key_is_frozen():
    key = EntityKey.of("Grant", "person")
    with pytest.raises(ValidationError):
        key.normalized_name = "other"


def test_the_events_carry_their_aggregate_type():
    """Bound here rather than at every construction site; the repository reads it."""
    same = EntitiesHeldSame(
        aggregate_id=PROJECT,
        keys=[EntityKey.of("JFK", "person"), EntityKey.of("John F. Kennedy", "person")],
        reason="same president",
    )
    assert same.aggregate_type == "EntityJudgements"
    distinct = EntitiesHeldDistinct(
        aggregate_id=PROJECT,
        left=EntityKey.of("Iran", "place"),
        right=EntityKey.of("Iraq", "place"),
        reason="different countries",
    )
    assert distinct.aggregate_type == "EntityJudgements"
    withdrawn = JudgementWithdrawn(
        aggregate_id=PROJECT, judgement_id=same.event_id, reason="mistake"
    )
    assert withdrawn.aggregate_type == "EntityJudgements"


def test_a_same_judgement_puts_both_keys_in_one_group():
    state = _fold(EntitiesHeldSame(aggregate_id=PROJECT, keys=[JFK, JOHN], reason="r"))

    assert state.group_for(JFK) == frozenset({JFK, JOHN})
    assert state.group_for(JOHN) == frozenset({JFK, JOHN})


def test_a_key_nobody_judged_is_alone_in_its_group():
    """Alone rather than absent, so callers need no None branch."""
    assert initial_state().group_for(JFK) == frozenset({JFK})


def test_same_judgements_are_transitive():
    """A=B and B=C makes one group of three, which is why groups beat pairs.

    Modelling pairs would put this closure in every reader instead.
    """
    state = _fold(
        EntitiesHeldSame(aggregate_id=PROJECT, keys=[JFK, JOHN], reason="r"),
        EntitiesHeldSame(aggregate_id=PROJECT, keys=[JOHN, KENNEDY], reason="r"),
    )

    assert state.group_for(JFK) == frozenset({JFK, JOHN, KENNEDY})


def test_distinct_judgements_are_not_transitive():
    """A!=B and B!=C says nothing about A and C, so distinctness is pairwise."""
    a, b, c = JFK, JOHN, KENNEDY
    state = _fold(
        EntitiesHeldDistinct(aggregate_id=PROJECT, left=a, right=b, reason="r"),
        EntitiesHeldDistinct(aggregate_id=PROJECT, left=b, right=c, reason="r"),
    )

    assert state.are_held_distinct(a, b)
    assert not state.are_held_distinct(a, c)


def test_distinctness_is_symmetric():
    state = _fold(
        EntitiesHeldDistinct(aggregate_id=PROJECT, left=IRAN, right=IRAQ, reason="r")
    )

    assert state.are_held_distinct(IRAN, IRAQ)
    assert state.are_held_distinct(IRAQ, IRAN)


def test_withdrawing_a_same_judgement_splits_only_what_it_joined():
    """Recomputed from the survivors, not subtracted -- the subtractive version
    is wrong whenever two judgements overlap, and looks obviously right.

    Here A=B and B=C both hold; withdrawing A=B must leave B and C together
    and drop A, rather than dissolving the whole group.
    """
    first = EntitiesHeldSame(aggregate_id=PROJECT, keys=[JFK, JOHN], reason="r")
    second = EntitiesHeldSame(aggregate_id=PROJECT, keys=[JOHN, KENNEDY], reason="r")
    state = _fold(
        first,
        second,
        JudgementWithdrawn(aggregate_id=PROJECT, judgement_id=first.event_id, reason="w"),
    )

    assert state.group_for(JFK) == frozenset({JFK})
    assert state.group_for(JOHN) == frozenset({JOHN, KENNEDY})


def test_withdrawing_a_distinct_judgement_releases_the_pair():
    held = EntitiesHeldDistinct(aggregate_id=PROJECT, left=IRAN, right=IRAQ, reason="r")
    state = _fold(
        held, JudgementWithdrawn(aggregate_id=PROJECT, judgement_id=held.event_id, reason="w")
    )

    assert not state.are_held_distinct(IRAN, IRAQ)


def test_a_withdrawn_judgement_is_kept_with_its_reason():
    """A compensating event, not a delete: the audit trail survives."""
    held = EntitiesHeldSame(aggregate_id=PROJECT, keys=[JFK, JOHN], reason="same man")
    state = _fold(
        held,
        JudgementWithdrawn(aggregate_id=PROJECT, judgement_id=held.event_id, reason="wrong"),
    )

    record = state.judgements[held.event_id]
    assert record.reason == "same man"
    assert record.withdrawn_reason == "wrong"


def test_an_unknown_event_leaves_the_state_alone():
    """Total on purpose, so a stream carrying an event this build does not know
    still replays instead of failing halfway through."""
    state = _fold(EntitiesHeldSame(aggregate_id=PROJECT, keys=[JFK, JOHN], reason="r"))

    assert (
        evolve(
            state,
            CorpusDocumentStored(aggregate_id=uuid4(), source_id="s", text="t", sha256="d"),
        )
        == state
    )
