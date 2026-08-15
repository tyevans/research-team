"""The value types a judgement is expressed in."""

from uuid import uuid4

import pytest
from eventsource import CommandRejectedError
from pydantic import ValidationError

from research_team.domain import EntityJudgements
from research_team.domain.corpus import CorpusDocumentStored
from research_team.domain.judgements import (
    EntitiesHeldDistinct,
    EntitiesHeldSame,
    EntityKey,
    HoldDistinct,
    HoldSame,
    JudgementWithdrawn,
    WithdrawJudgement,
    decide,
    evolve,
    initial_state,
    normalize_name,
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


def test_holding_two_names_same_produces_one_event():
    events = decide(
        HoldSame(judgements_id=PROJECT, keys=[JFK, JOHN], reason="same president"),
        initial_state(),
    )

    assert len(events) == 1
    assert events[0].keys == [JFK, JOHN]
    assert events[0].aggregate_id == PROJECT


def test_every_judgement_requires_a_reason():
    """The reason is what the aliases panel shows and the only record of why a
    human decided something. Blank is refused rather than stored empty."""
    for command in (
        HoldSame(judgements_id=PROJECT, keys=[JFK, JOHN], reason="  "),
        HoldDistinct(judgements_id=PROJECT, left=IRAN, right=IRAQ, reason=""),
    ):
        with pytest.raises(CommandRejectedError, match="reason"):
            decide(command, initial_state())


def test_holding_fewer_than_two_distinct_keys_same_is_refused():
    with pytest.raises(CommandRejectedError, match="two"):
        decide(HoldSame(judgements_id=PROJECT, keys=[JFK], reason="r"), initial_state())
    with pytest.raises(CommandRejectedError, match="two"):
        decide(HoldSame(judgements_id=PROJECT, keys=[JFK, JFK], reason="r"), initial_state())


def test_holding_a_key_distinct_from_itself_is_refused():
    with pytest.raises(CommandRejectedError, match="itself"):
        decide(
            HoldDistinct(judgements_id=PROJECT, left=JFK, right=JFK, reason="r"),
            initial_state(),
        )


def test_holding_same_what_is_already_held_distinct_is_refused():
    state = _fold(
        EntitiesHeldDistinct(aggregate_id=PROJECT, left=IRAN, right=IRAQ, reason="r")
    )

    with pytest.raises(CommandRejectedError, match="held distinct"):
        decide(HoldSame(judgements_id=PROJECT, keys=[IRAN, IRAQ], reason="r"), state)


def test_holding_distinct_what_is_already_one_group_is_refused():
    state = _fold(EntitiesHeldSame(aggregate_id=PROJECT, keys=[JFK, JOHN], reason="r"))

    with pytest.raises(CommandRejectedError, match="held same"):
        decide(HoldDistinct(judgements_id=PROJECT, left=JFK, right=JOHN, reason="r"), state)


def test_a_same_judgement_that_would_transitively_unite_a_distinct_pair_is_refused():
    """The refusal that is easy to miss, and the reason it is checked on the
    prospective *group* rather than on the command's own keys.

    A and C are held distinct. Holding A=B is legal on its face, but B is
    already grouped with C, so the union would put A and C together -- and the
    contradiction only appears after the merge. Would pass with the naive
    check that only compares the command's own key pairs.
    """
    a, b, c = JFK, JOHN, KENNEDY
    state = _fold(
        EntitiesHeldDistinct(aggregate_id=PROJECT, left=a, right=c, reason="r"),
        EntitiesHeldSame(aggregate_id=PROJECT, keys=[b, c], reason="r"),
    )

    with pytest.raises(CommandRejectedError, match="held distinct"):
        decide(HoldSame(judgements_id=PROJECT, keys=[a, b], reason="r"), state)


def test_withdrawing_an_unknown_judgement_is_refused():
    with pytest.raises(CommandRejectedError, match="unknown"):
        decide(WithdrawJudgement(judgement_id=uuid4(), reason="r"), initial_state())


def test_withdrawing_twice_is_refused():
    held = EntitiesHeldSame(aggregate_id=PROJECT, keys=[JFK, JOHN], reason="r")
    state = _fold(
        held, JudgementWithdrawn(aggregate_id=PROJECT, judgement_id=held.event_id, reason="w")
    )

    with pytest.raises(CommandRejectedError, match="already withdrawn"):
        decide(WithdrawJudgement(judgement_id=held.event_id, reason="again"), state)


def test_a_refusal_names_the_conflicting_judgement_so_a_ui_can_offer_to_undo_it():
    """A dead end is a worse error than one that says what to withdraw first."""
    conflict = EntitiesHeldDistinct(aggregate_id=PROJECT, left=IRAN, right=IRAQ, reason="r")
    state = _fold(conflict)

    with pytest.raises(CommandRejectedError, match=str(conflict.event_id)):
        decide(HoldSame(judgements_id=PROJECT, keys=[IRAN, IRAQ], reason="r"), state)


def test_a_hold_distinct_refusal_also_names_the_conflicting_judgement():
    """The mirror of the HoldSame case above: HoldDistinct against a group that
    already holds both names same must name the same-judgement responsible, not
    just say "withdraw that judgement" -- a caller cannot infer which one a
    group is the union of arbitrarily many same-records.
    """
    conflict = EntitiesHeldSame(aggregate_id=PROJECT, keys=[JFK, JOHN], reason="r")
    state = _fold(conflict)

    with pytest.raises(CommandRejectedError, match=str(conflict.event_id)):
        decide(HoldDistinct(judgements_id=PROJECT, left=JFK, right=JOHN, reason="r"), state)


def test_a_hold_distinct_refusal_over_a_transitive_group_is_still_refused():
    """A=B and B=C put A and C in one group via group_for's transitive closure;
    HoldDistinct(A, C) must still be refused even though no single same-record
    names both A and C directly. Pins the transitive direction that the
    HoldSame side already has a test for (see
    test_a_same_judgement_that_would_transitively_unite_a_distinct_pair_is_refused).
    """
    a, b, c = JFK, JOHN, KENNEDY
    state = _fold(
        EntitiesHeldSame(aggregate_id=PROJECT, keys=[a, b], reason="r"),
        EntitiesHeldSame(aggregate_id=PROJECT, keys=[b, c], reason="r"),
    )

    with pytest.raises(CommandRejectedError, match="held same"):
        decide(HoldDistinct(judgements_id=PROJECT, left=a, right=c, reason="r"), state)


def test_the_aggregate_executes_a_command_and_folds_its_event():
    judgements = EntityJudgements(aggregate_id=PROJECT)
    judgements.execute(HoldSame(judgements_id=PROJECT, keys=[JFK, JOHN], reason="r"))

    assert judgements.state.group_for(JFK) == frozenset({JFK, JOHN})


def test_the_aggregate_type_keeps_the_stream_apart_from_the_corpus():
    """Project, corpus and judgements share one UUID and are three streams.

    `AggregateRepository` puts `aggregate_type` into the `StreamId`, so this
    string is the whole separation.
    """
    assert EntityJudgements.aggregate_type == "EntityJudgements"


def test_normalisation_matches_redstrings():
    """The safety of the copied `normalize_name`, and the reason it may be copied.

    `EntityKey`'s name has to match what `find_entities(name=...)` compares
    against -- redstring's `normalized_name` -- so the two normalisations
    agreeing is a correctness requirement. redstring does not export its
    version (`redstring.domain.normalization`, absent from `__all__`), and
    `test_architecture.py` forbids `research_team/` from importing anything
    under `redstring.domain.`, the domain layer from naming redstring at all.
    So it is copied, and this is what stops the copy drifting.

    Imports the private function deliberately: `tests/` is exempt from that
    architecture rule, and the docstring of the rule says so, precisely so a
    parity check can exist. If redstring changes its definition -- or moves it
    -- this fails, which is the whole point. Deleting this test turns a pinned
    duplication into an unpinned one.

    The cases are chosen where a plausible re-implementation would differ:
    `casefold` against `lower` (German ß), internal whitespace runs, tabs and
    newlines, and the leading/trailing strip.
    """
    from redstring.domain.normalization import normalize_name as theirs

    for case in (
        "JFK",
        "  Dr. Grant  ",
        "John   F.\tKennedy",
        "STRASSE",
        "Straße",
        "line\nbreak",
        "",
        "   ",
        "already normalised",
        "Nova Scotia Duck Tolling Retriever",
    ):
        assert normalize_name(case) == theirs(case), case
