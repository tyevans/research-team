"""The value types a judgement is expressed in."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from research_team.domain.judgements import (
    EntitiesHeldDistinct,
    EntitiesHeldSame,
    EntityKey,
    JudgementWithdrawn,
)

PROJECT = uuid4()


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
