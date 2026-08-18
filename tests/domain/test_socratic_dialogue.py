"""What a socratic dialogue will and will not accept, over pure functions.

Modelled on `tests/domain/test_ask_conversation.py`, which these deliberately
mirror: same `_with` fold helper, same one-assertion-per-rule shape. The
differences are the state this aggregate has that an ask cannot express -- a
goal, a stopping condition, and a terminal status -- which is the whole reason
it is a second aggregate rather than a re-prompted first one.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eventsource import CommandRejectedError, DomainEvent

from research_team.domain.socratic_dialogue import (
    ConcludeSocraticDialogue,
    ObserveSocraticProgress,
    RecordSocraticTurn,
    SocraticDialogueConcluded,
    SocraticDialogueStarted,
    SocraticDialogueState,
    SocraticProgressObserved,
    SocraticTurnRecorded,
    StartSocraticDialogue,
    decide,
    evolve,
    initial_state,
)

PROJECT_ID = uuid4()
DIALOGUE_ID = uuid4()
OPENED_AT = datetime(2026, 8, 17, tzinfo=UTC)

STARTED = SocraticDialogueStarted(
    aggregate_id=DIALOGUE_ID,
    project_id=PROJECT_ID,
    topic="the Nicene settlement",
    goal="understand what the creed actually settled",
    stopping_condition="the reader distinguishes the settlement from its politics",
    opening_prompt="What do you already believe about it?",
    opened_at=OPENED_AT,
)


def _with(*events: DomainEvent) -> SocraticDialogueState:
    state = initial_state()
    for event in events:
        state = evolve(state, event)
    return state


def test_starting_carries_the_goal_and_the_stopping_condition():
    """The two fields that make this a different aggregate from an ask.

    `AskConversationState` is four fields with nowhere to put either, which is
    the spec's §1 argument for not re-prompting it. Red against an event that
    carries the topic and lets the model hold the goal in its context -- a
    stopping condition decided inside an LLM's context is one nothing can test.
    """
    events = decide(
        StartSocraticDialogue(
            dialogue_id=DIALOGUE_ID,
            project_id=PROJECT_ID,
            topic="the Nicene settlement",
            goal="understand what the creed actually settled",
            stopping_condition="the reader distinguishes the settlement from its politics",
            opening_prompt="What do you already believe about it?",
            opened_at=OPENED_AT,
        ),
        initial_state(),
    )

    assert [type(e) for e in events] == [SocraticDialogueStarted]
    assert events[0].aggregate_id == DIALOGUE_ID
    assert events[0].project_id == PROJECT_ID
    assert events[0].goal == "understand what the creed actually settled"
    assert (
        events[0].stopping_condition
        == "the reader distinguishes the settlement from its politics"
    )


def test_starting_folds_to_a_state_that_knows_what_it_is_for():
    state = _with(STARTED)

    assert state.dialogue_id == DIALOGUE_ID
    assert state.project_id == PROJECT_ID
    assert state.topic == "the Nicene settlement"
    assert state.goal == "understand what the creed actually settled"
    assert state.is_started
    assert not state.is_concluded
    assert state.turns == 0
    assert state.observations == []


def test_starting_twice_is_refused():
    with pytest.raises(CommandRejectedError, match="already started"):
        decide(
            StartSocraticDialogue(
                dialogue_id=DIALOGUE_ID,
                project_id=PROJECT_ID,
                topic="t",
                goal="g",
                stopping_condition="s",
                opening_prompt="p",
                opened_at=OPENED_AT,
            ),
            _with(STARTED),
        )


def test_a_turn_before_the_dialogue_started_is_refused():
    """Nothing may be first but the start, which is what lets the projection
    treat a turn against an unknown dialogue as a log it never saw the head of
    rather than as a case to handle."""
    with pytest.raises(CommandRejectedError, match="not started"):
        decide(
            RecordSocraticTurn(dialogue_id=DIALOGUE_ID, reply="hi", prompt="why?"),
            initial_state(),
        )


def test_a_turn_pairs_the_reader_s_answer_with_the_dialogue_s_response():
    """The field-naming ruling and the pairing, which are two claims.

    `prompt` is what the *dialogue* said and `reply` is what the reader
    answered -- the ordinary sense of both words, and the inverse of
    `AskTurnRecorded`, because this surface runs in the opposite direction.

    And a turn pairs the reader's answer with the response it drew, not a
    question with its own answer. That is one executor call -- `reply` in,
    `prompt` out -- and it stores every utterance exactly once. The pairing
    that seems more natural leaves the newest question belonging to no turn,
    which then has to be stored a second time.

    Red against an implementation that reads the fields the other way round.
    That failure produces a transcript which still reads as a conversation --
    just one where the reader asks all the questions -- so nothing but this
    assertion would notice.
    """
    events = decide(
        RecordSocraticTurn(
            dialogue_id=DIALOGUE_ID,
            reply="It settled Arianism.",
            prompt="Settled by whom, though?",
            citations=(("source", "s1"),),
        ),
        _with(STARTED),
    )

    assert [type(e) for e in events] == [SocraticTurnRecorded]
    assert events[0].aggregate_id == DIALOGUE_ID
    assert events[0].reply == "It settled Arianism."
    assert events[0].prompt == "Settled by whom, though?"
    assert events[0].citations == [("source", "s1")]


def test_turns_count_up_as_they_fold():
    """A count and not the texts. Which question is outstanding is a read
    concern -- the last turn's `prompt` -- and no decision in this module needs
    it, so the state does not carry it and cannot disagree with the log."""
    state = _with(
        STARTED,
        SocraticTurnRecorded(aggregate_id=DIALOGUE_ID, reply="b", prompt="c?"),
        SocraticTurnRecorded(aggregate_id=DIALOGUE_ID, reply="d", prompt="e?"),
    )

    assert state.turns == 2


def test_an_observation_is_kept_and_not_merely_counted():
    """The state has to express "this dialogue is trying to reach X and has not
    yet", and a counter cannot. Red against `observations: int`, which folds
    cheaply and answers nothing the stopping condition needs."""
    state = _with(
        STARTED,
        SocraticProgressObserved(
            aggregate_id=DIALOGUE_ID,
            observation="distinguished the creed from the council",
            evidence="attempt",
            detail="mcq nicene-1 correct",
        ),
    )

    assert state.observations == ["distinguished the creed from the council"]


def test_concluding_records_why():
    events = decide(
        ConcludeSocraticDialogue(dialogue_id=DIALOGUE_ID, reason="met"), _with(STARTED)
    )

    assert [type(e) for e in events] == [SocraticDialogueConcluded]
    assert events[0].reason == "met"


def test_a_concluded_dialogue_takes_no_more_turns():
    """The terminal status is the point of having one. A dialogue that reached
    its stopping condition and then accepted three more exchanges has a
    stopping condition in name only. Red against a `decide` that matches on
    `status="new"` alone and lets everything else through -- which is exactly
    what `AskConversation.decide` does, correctly, for a surface with no end.
    """
    concluded = _with(
        STARTED, SocraticDialogueConcluded(aggregate_id=DIALOGUE_ID, reason="met")
    )

    assert concluded.is_concluded
    for command in (
        RecordSocraticTurn(dialogue_id=DIALOGUE_ID, reply="yes", prompt="one more?"),
        ObserveSocraticProgress(dialogue_id=DIALOGUE_ID, observation="late"),
        ConcludeSocraticDialogue(dialogue_id=DIALOGUE_ID, reason="abandoned"),
    ):
        with pytest.raises(CommandRejectedError, match="concluded"):
            decide(command, concluded)


def test_evolve_ignores_an_event_it_has_no_rule_for():
    """Total, like every other fold here: an event from another aggregate that
    somehow reached this stream leaves the state alone rather than raising
    inside a replay."""
    from research_team.domain.ask_conversation import AskTurnRecorded

    state = _with(STARTED)

    assert (
        evolve(state, AskTurnRecorded(aggregate_id=DIALOGUE_ID, question="q", answer="a"))
        == state
    )


def test_starting_a_concluded_dialogue_says_so_rather_than_saying_already_started():
    """The refusal message matches the state, for `Start` as for everything else.

    Unreachable in practice -- ids are server-minted, so a second start against
    a concluded dialogue means a bug upstream -- and that is the point: the only
    thing at stake is whether the error tells that person the truth. Red against
    the arm order this file was first written with, where `Start` was caught by
    its own catch-all above the concluded check and reported "already started"
    while the comment beside it claimed concluded was checked first.
    """
    concluded = _with(
        STARTED, SocraticDialogueConcluded(aggregate_id=DIALOGUE_ID, reason="met")
    )

    with pytest.raises(CommandRejectedError, match="already concluded"):
        decide(
            StartSocraticDialogue(
                dialogue_id=DIALOGUE_ID,
                project_id=PROJECT_ID,
                topic="t",
                goal="g",
                stopping_condition="s",
                opening_prompt="p",
                opened_at=OPENED_AT,
            ),
            concluded,
        )
