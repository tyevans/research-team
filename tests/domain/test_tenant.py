"""Domain tests for Tenant decider aggregate and invariants."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from eventsource import CommandRejectedError, DomainEvent

from research_team.tenancy.domain.tenant import (
    AcceptInvitation,
    AddMember,
    AddProjectGrant,
    ChangeMemberRole,
    CreateInvitation,
    CreateTenant,
    InvitationAccepted,
    InvitationCreated,
    InvitationRevoked,
    MemberAdded,
    MemberRemoved,
    MemberRoleChanged,
    OwnershipTransferred,
    ProjectGrantAdded,
    ProjectGrantRevoked,
    RemoveMember,
    RevokeInvitation,
    RevokeProjectGrant,
    TenantCreated,
    TransferOwnership,
    decide,
    evolve,
    initial_state,
    tenant_aggregate_id,
)

TENANT = "org-100"
ALICE = "sub-alice"
BOB = "sub-bob"
CHARLIE = "sub-charlie"


def _created(tenant_id=TENANT, name="Acme", created_by=ALICE):
    state = initial_state()
    for event in decide(
        CreateTenant(tenant_id=tenant_id, name=name, created_by=created_by), state
    ):
        state = evolve(state, event)
    return state


def test_creating_a_tenant_emits_created_and_owner_membership():
    state = initial_state()
    events = decide(CreateTenant(tenant_id=TENANT, name="Acme", created_by=ALICE), state)

    assert len(events) == 2
    assert isinstance(events[0], TenantCreated)
    assert events[0].tenant_id == TENANT
    assert events[0].name == "Acme"
    assert events[0].aggregate_id == tenant_aggregate_id(TENANT)

    assert isinstance(events[1], MemberAdded)
    assert events[1].subject == ALICE
    assert events[1].role == "owner"

    evolved = state
    for e in events:
        evolved = evolve(evolved, e)

    assert evolved.is_created is True
    assert evolved.tenant_id == TENANT
    assert evolved.owner_subject == ALICE
    assert evolved.members == {ALICE: "owner"}


def test_creating_a_tenant_without_creator_emits_only_tenant_created():
    state = initial_state()
    events = decide(CreateTenant(tenant_id=TENANT, name="Acme", created_by=""), state)

    assert len(events) == 1
    assert isinstance(events[0], TenantCreated)

    evolved = evolve(state, events[0])
    assert evolved.is_created is True
    assert evolved.owner_subject is None
    assert evolved.members == {}


def test_creating_a_tenant_twice_is_rejected():
    state = _created()
    with pytest.raises(CommandRejectedError, match="already created"):
        decide(CreateTenant(tenant_id=TENANT, name="Acme", created_by=ALICE), state)


def test_creating_a_tenant_with_empty_id_or_name_is_rejected():
    state = initial_state()
    with pytest.raises(CommandRejectedError, match="tenant id cannot be empty"):
        decide(CreateTenant(tenant_id="  ", name="Acme", created_by=ALICE), state)

    with pytest.raises(CommandRejectedError, match="tenant name cannot be empty"):
        decide(CreateTenant(tenant_id=TENANT, name="  ", created_by=ALICE), state)


def test_commands_before_tenant_creation_are_rejected():
    state = initial_state()
    with pytest.raises(CommandRejectedError, match="tenant not created"):
        decide(AddMember(subject=BOB, role="member"), state)


# --- Memberships -------------------------------------------------------------


def test_adding_a_member_emits_member_added():
    state = _created()
    [event] = decide(AddMember(subject=BOB, role="member", granted_by=ALICE), state)

    assert isinstance(event, MemberAdded)
    assert event.subject == BOB
    assert event.role == "member"

    evolved = evolve(state, event)
    assert evolved.members[BOB] == "member"


def test_adding_a_member_as_owner_is_rejected():
    state = _created()
    with pytest.raises(CommandRejectedError, match="cannot add owner directly"):
        decide(AddMember(subject=BOB, role="owner"), state)


def test_adding_an_existing_member_is_rejected():
    state = _created()
    state = evolve(
        state,
        MemberAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            subject=BOB,
            role="member",
        ),
    )

    with pytest.raises(CommandRejectedError, match="already a member"):
        decide(AddMember(subject=BOB, role="admin"), state)


def test_changing_member_role_emits_member_role_changed():
    state = _created()
    state = evolve(
        state,
        MemberAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            subject=BOB,
            role="member",
        ),
    )

    [event] = decide(ChangeMemberRole(subject=BOB, role="admin", changed_by=ALICE), state)
    assert isinstance(event, MemberRoleChanged)
    assert event.subject == BOB
    assert event.role == "admin"
    assert event.previous_role == "member"

    evolved = evolve(state, event)
    assert evolved.members[BOB] == "admin"


def test_changing_role_of_non_member_is_rejected():
    state = _created()
    with pytest.raises(CommandRejectedError, match="is not a member"):
        decide(ChangeMemberRole(subject=BOB, role="admin"), state)


def test_changing_owner_role_or_changing_to_owner_is_rejected():
    state = _created()
    with pytest.raises(CommandRejectedError, match="cannot change role of owner"):
        decide(ChangeMemberRole(subject=ALICE, role="admin"), state)

    state = evolve(
        state,
        MemberAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            subject=BOB,
            role="member",
        ),
    )
    with pytest.raises(CommandRejectedError, match="cannot change role to owner"):
        decide(ChangeMemberRole(subject=BOB, role="owner"), state)


def test_changing_to_same_role_is_rejected():
    state = _created()
    state = evolve(
        state,
        MemberAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            subject=BOB,
            role="member",
        ),
    )
    with pytest.raises(CommandRejectedError, match="already has role member"):
        decide(ChangeMemberRole(subject=BOB, role="member"), state)


def test_removing_a_member_revokes_associated_project_grants():
    project_id = uuid4()
    state = _created()
    state = evolve(
        state,
        MemberAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            subject=BOB,
            role="member",
        ),
    )
    state = evolve(
        state,
        ProjectGrantAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            project_id=project_id,
            subject=BOB,
            role="editor",
        ),
    )

    events = decide(RemoveMember(subject=BOB, removed_by=ALICE), state)
    assert len(events) == 2
    assert isinstance(events[0], MemberRemoved)
    assert events[0].subject == BOB
    assert isinstance(events[1], ProjectGrantRevoked)
    assert events[1].project_id == project_id
    assert events[1].subject == BOB

    evolved = state
    for e in events:
        evolved = evolve(evolved, e)

    assert BOB not in evolved.members
    assert (project_id, BOB) not in evolved.project_grants


def test_removing_the_owner_is_rejected():
    state = _created()
    with pytest.raises(CommandRejectedError, match="cannot remove the tenant owner"):
        decide(RemoveMember(subject=ALICE), state)


def test_removing_a_non_member_is_rejected():
    state = _created()
    with pytest.raises(CommandRejectedError, match="is not a member"):
        decide(RemoveMember(subject="stranger"), state)


# --- Ownership Transfer ------------------------------------------------------


def test_ownership_transfer_moves_owner_and_retains_previous_as_admin():
    state = _created()
    state = evolve(
        state,
        MemberAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            subject=BOB,
            role="admin",
        ),
    )

    [event] = decide(TransferOwnership(from_subject=ALICE, to_subject=BOB), state)
    assert isinstance(event, OwnershipTransferred)
    assert event.from_subject == ALICE
    assert event.to_subject == BOB

    evolved = evolve(state, event)
    assert evolved.owner_subject == BOB
    assert evolved.members[BOB] == "owner"
    assert evolved.members[ALICE] == "admin"


def test_ownership_transfer_by_non_owner_is_rejected():
    state = _created()
    with pytest.raises(CommandRejectedError, match="is not the current owner"):
        decide(TransferOwnership(from_subject=BOB, to_subject=CHARLIE), state)


def test_ownership_transfer_to_self_is_rejected():
    state = _created()
    with pytest.raises(
        CommandRejectedError, match="cannot transfer ownership to current owner"
    ):
        decide(TransferOwnership(from_subject=ALICE, to_subject=ALICE), state)


# --- Project Grants ----------------------------------------------------------


def test_project_grant_lifecycle():
    project_id = uuid4()
    state = _created()

    [add_event] = decide(
        AddProjectGrant(project_id=project_id, subject=BOB, role="runner", granted_by=ALICE),
        state,
    )
    assert isinstance(add_event, ProjectGrantAdded)
    assert add_event.project_id == project_id
    assert add_event.subject == BOB
    assert add_event.role == "runner"

    evolved = evolve(state, add_event)
    assert evolved.project_grants[(project_id, BOB)] == "runner"

    [revoke_event] = decide(
        RevokeProjectGrant(project_id=project_id, subject=BOB, revoked_by=ALICE), evolved
    )
    assert isinstance(revoke_event, ProjectGrantRevoked)

    revoked = evolve(evolved, revoke_event)
    assert (project_id, BOB) not in revoked.project_grants


def test_revoking_non_existent_project_grant_is_rejected():
    state = _created()
    with pytest.raises(CommandRejectedError, match="no project grant"):
        decide(RevokeProjectGrant(project_id=uuid4(), subject=BOB), state)


# --- Invitations -------------------------------------------------------------


def test_invitation_lifecycle():
    inv_id = uuid4()
    state = _created()

    [inv_event] = decide(
        CreateInvitation(
            email="  Bob@Example.com ",
            role="member",
            token="tok123",
            invited_by=ALICE,
            invitation_id=inv_id,
        ),
        state,
    )
    assert isinstance(inv_event, InvitationCreated)
    assert inv_event.email == "bob@example.com"
    assert inv_event.event_id == inv_id

    invited_state = evolve(state, inv_event)
    assert inv_id in invited_state.invitations
    assert invited_state.invitations[inv_id]["status"] == "open"

    # Accepting invitation claims it and admits member
    accept_events = decide(AcceptInvitation(invitation_id=inv_id, subject=BOB), invited_state)
    assert len(accept_events) == 2
    assert isinstance(accept_events[0], InvitationAccepted)
    assert isinstance(accept_events[1], MemberAdded)
    assert accept_events[1].subject == BOB
    assert accept_events[1].role == "member"

    accepted_state = invited_state
    for e in accept_events:
        accepted_state = evolve(accepted_state, e)

    assert accepted_state.invitations[inv_id]["status"] == "accepted"
    assert accepted_state.members[BOB] == "member"


def test_duplicate_open_invitation_for_same_email_is_rejected():
    state = _created()
    state = evolve(
        state,
        InvitationCreated(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            event_id=uuid4(),
            email="bob@example.com",
            role="member",
            token="t1",
        ),
    )

    with pytest.raises(CommandRejectedError, match="already exists"):
        decide(
            CreateInvitation(email="BOB@example.com", role="member", token="t2"),
            state,
        )


def test_accepting_expired_invitation_is_rejected():
    inv_id = uuid4()
    state = _created()
    state = evolve(
        state,
        InvitationCreated(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            event_id=inv_id,
            email="bob@example.com",
            role="member",
            token="t1",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        ),
    )

    with pytest.raises(CommandRejectedError, match="has expired"):
        decide(AcceptInvitation(invitation_id=inv_id, subject=BOB), state)


def test_revoking_an_invitation():
    inv_id = uuid4()
    state = _created()
    state = evolve(
        state,
        InvitationCreated(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            event_id=inv_id,
            email="bob@example.com",
            role="member",
            token="t1",
        ),
    )

    [event] = decide(RevokeInvitation(invitation_id=inv_id, revoked_by=ALICE), state)
    assert isinstance(event, InvitationRevoked)

    revoked_state = evolve(state, event)
    assert revoked_state.invitations[inv_id]["status"] == "revoked"

    # Accepting a revoked invitation is rejected
    with pytest.raises(CommandRejectedError, match="already revoked"):
        decide(AcceptInvitation(invitation_id=inv_id, subject=BOB), revoked_state)


def test_evolve_ignores_unrecognized_event():
    state = _created()
    assert evolve(state, DomainEvent(aggregate_id=uuid4(), aggregate_type="Unknown")) is state
