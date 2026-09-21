"""Domain tests for User decider aggregate, state, and identity observations."""

from uuid import uuid4

import pytest
from eventsource import CommandRejectedError, DomainEvent

from research_team.tenancy.domain.user import (
    RecordSignIn,
    UpdateUserProfile,
    UserProfileChanged,
    UserSignedIn,
    UserState,
    decide,
    evolve,
    initial_state,
    stream_id_for,
)

ALICE = "sub-alice"
TENANT = "org-100"


def test_first_sign_in_emits_user_signed_in():
    state = initial_state()
    [event] = decide(
        RecordSignIn(
            subject=ALICE,
            tenant_id=TENANT,
            email="alice@example.com",
            display_name="Alice A",
            avatar_url="https://example.com/alice.png",
            signed_in_at="2026-09-21T00:00:00Z",
        ),
        state,
    )

    assert isinstance(event, UserSignedIn)
    assert event.aggregate_id == stream_id_for(ALICE)
    assert event.subject == ALICE
    assert event.tenant_id == TENANT
    assert event.email == "alice@example.com"
    assert event.display_name == "Alice A"
    assert event.signed_in_at == "2026-09-21T00:00:00Z"

    evolved = evolve(state, event)
    assert evolved.subject == ALICE
    assert evolved.tenant_id == TENANT
    assert evolved.email == "alice@example.com"
    assert evolved.display_name == "Alice A"
    assert evolved.sign_in_count == 1
    assert evolved.last_signed_in_at == "2026-09-21T00:00:00Z"


def test_subsequent_sign_in_with_changed_claims_emits_both_events():
    state = initial_state()
    state = evolve(
        state,
        UserSignedIn(
            aggregate_id=stream_id_for(ALICE),
            subject=ALICE,
            tenant_id=TENANT,
            email="alice@example.com",
            display_name="Alice A",
            avatar_url="https://example.com/alice.png",
            signed_in_at="2026-09-21T00:00:00Z",
        ),
    )

    events = decide(
        RecordSignIn(
            subject=ALICE,
            tenant_id=TENANT,
            email="alice.new@example.com",
            display_name="Alice B",
            avatar_url="https://example.com/alice.png",
            signed_in_at="2026-09-21T01:00:00Z",
        ),
        state,
    )

    assert len(events) == 2
    assert isinstance(events[0], UserSignedIn)
    assert isinstance(events[1], UserProfileChanged)
    assert events[1].email == "alice.new@example.com"
    assert events[1].display_name == "Alice B"
    assert events[1].changed_at == "2026-09-21T01:00:00Z"

    evolved = state
    for e in events:
        evolved = evolve(evolved, e)

    assert evolved.email == "alice.new@example.com"
    assert evolved.display_name == "Alice B"
    assert evolved.sign_in_count == 2
    assert evolved.last_signed_in_at == "2026-09-21T01:00:00Z"


def test_subsequent_sign_in_with_identical_claims_emits_only_signed_in():
    state = initial_state()
    state = evolve(
        state,
        UserSignedIn(
            aggregate_id=stream_id_for(ALICE),
            subject=ALICE,
            tenant_id=TENANT,
            email="alice@example.com",
            display_name="Alice A",
            avatar_url="https://example.com/alice.png",
            signed_in_at="2026-09-21T00:00:00Z",
        ),
    )

    events = decide(
        RecordSignIn(
            subject=ALICE,
            tenant_id=TENANT,
            email="alice@example.com",
            display_name="Alice A",
            avatar_url="https://example.com/alice.png",
            signed_in_at="2026-09-21T01:00:00Z",
        ),
        state,
    )

    assert len(events) == 1
    assert isinstance(events[0], UserSignedIn)

    evolved = evolve(state, events[0])
    assert evolved.sign_in_count == 2


def test_recording_sign_in_with_empty_subject_or_tenant_is_rejected():
    state = initial_state()
    with pytest.raises(CommandRejectedError, match="subject cannot be empty"):
        decide(RecordSignIn(subject="  ", tenant_id=TENANT), state)

    with pytest.raises(CommandRejectedError, match="tenant_id cannot be empty"):
        decide(RecordSignIn(subject=ALICE, tenant_id="  "), state)


def test_update_user_profile_emits_event_only_on_actual_difference():
    state = UserState(
        subject=ALICE,
        tenant_id=TENANT,
        email="alice@example.com",
        display_name="Alice",
    )

    # Identical claims: no-op
    assert (
        decide(
            UpdateUserProfile(
                subject=ALICE,
                tenant_id=TENANT,
                email="alice@example.com",
                display_name="Alice",
            ),
            state,
        )
        == []
    )

    # Difference in display name: emits event
    [event] = decide(
        UpdateUserProfile(
            subject=ALICE,
            tenant_id=TENANT,
            email="alice@example.com",
            display_name="Alice Henderson",
            changed_at="2026-09-21T02:00:00Z",
        ),
        state,
    )
    assert isinstance(event, UserProfileChanged)
    assert event.display_name == "Alice Henderson"

    evolved = evolve(state, event)
    assert evolved.display_name == "Alice Henderson"


def test_stream_id_is_deterministic_and_distinct():
    id1 = stream_id_for("sub-1")
    id2 = stream_id_for("sub-1")
    id3 = stream_id_for("sub-2")

    assert id1 == id2
    assert id1 != id3


def test_evolve_ignores_unrecognized_events():
    state = initial_state()
    assert evolve(state, DomainEvent(aggregate_id=uuid4(), aggregate_type="Unknown")) is state
