from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eventsource import CommandRejectedError, DomainEvent

from research_team.domain.ask_conversation import (
    AskConversationStarted,
    AskConversationState,
    AskTurnRecorded,
    RecordAskTurn,
    StartAskConversation,
    decide,
    evolve,
    initial_state,
)

PROJECT_ID = uuid4()
CONVERSATION_ID = uuid4()
OPENED_AT = datetime(2026, 8, 16, tzinfo=UTC)


def _with(*events: DomainEvent) -> AskConversationState:
    state = initial_state()
    for event in events:
        state = evolve(state, event)
    return state


def test_starting_a_conversation_produces_the_started_event():
    events = decide(
        StartAskConversation(
            conversation_id=CONVERSATION_ID, project_id=PROJECT_ID, opened_at=OPENED_AT
        ),
        initial_state(),
    )

    assert [type(e) for e in events] == [AskConversationStarted]
    assert events[0].aggregate_id == CONVERSATION_ID
    assert events[0].project_id == PROJECT_ID
    assert events[0].opened_at == OPENED_AT


def test_starting_folds_to_a_started_state():
    state = _with(
        AskConversationStarted(
            aggregate_id=CONVERSATION_ID, project_id=PROJECT_ID, opened_at=OPENED_AT
        )
    )

    assert state.conversation_id == CONVERSATION_ID
    assert state.project_id == PROJECT_ID
    assert state.is_started
    assert state.turns == 0


def test_recording_a_turn_produces_the_turn_event_with_its_citations():
    state = _with(
        AskConversationStarted(
            aggregate_id=CONVERSATION_ID, project_id=PROJECT_ID, opened_at=OPENED_AT
        )
    )

    events = decide(
        RecordAskTurn(
            conversation_id=CONVERSATION_ID,
            question="who wrote this?",
            answer="the corpus says X",
            citations=(("source", "s1"),),
        ),
        state,
    )

    assert [type(e) for e in events] == [AskTurnRecorded]
    assert events[0].aggregate_id == CONVERSATION_ID
    assert events[0].question == "who wrote this?"
    assert events[0].answer == "the corpus says X"
    assert events[0].citations == [("source", "s1")]


def test_recording_a_turn_folds_to_an_incremented_turn_count():
    state = _with(
        AskConversationStarted(
            aggregate_id=CONVERSATION_ID, project_id=PROJECT_ID, opened_at=OPENED_AT
        ),
        AskTurnRecorded(
            aggregate_id=CONVERSATION_ID,
            question="q1",
            answer="a1",
            citations=[],
        ),
        AskTurnRecorded(
            aggregate_id=CONVERSATION_ID,
            question="q2",
            answer="a2",
            citations=[],
        ),
    )

    assert state.turns == 2


def test_recording_a_turn_against_a_conversation_never_started_is_refused():
    with pytest.raises(CommandRejectedError):
        decide(
            RecordAskTurn(
                conversation_id=CONVERSATION_ID,
                question="q",
                answer="a",
                citations=(),
            ),
            initial_state(),
        )


def test_starting_a_conversation_that_already_started_is_refused():
    state = _with(
        AskConversationStarted(
            aggregate_id=CONVERSATION_ID, project_id=PROJECT_ID, opened_at=OPENED_AT
        )
    )

    with pytest.raises(CommandRejectedError):
        decide(
            StartAskConversation(
                conversation_id=CONVERSATION_ID, project_id=PROJECT_ID, opened_at=OPENED_AT
            ),
            state,
        )
