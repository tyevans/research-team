"""Tenant aggregate decision rules and event evolution.

Extracted from tenant.py to isolate command validation, invariant enforcement,
and state transition rules from event/command/record schema definitions.
"""

from datetime import UTC, datetime
from uuid import uuid4

from eventsource import CommandRejectedError, DomainEvent

from research_team.tenancy.domain.tenant import (
    LOCAL_SUBJECT,
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
    TenantCommand,
    TenantCreated,
    TenantState,
    TransferOwnership,
    tenant_aggregate_id,
)


def initial_state() -> TenantState:
    return TenantState()


def decide(command: TenantCommand, state: TenantState) -> list[DomainEvent]:
    """Which requests are legal on a tenant stream, and what facts they produce."""
    match command, state:
        case CreateTenant(
            tenant_id=t_id, name=name, kind=kind, created_by=creator
        ), TenantState(is_created=False):
            cleaned_id = t_id.strip()
            if not cleaned_id:
                raise CommandRejectedError("tenant id cannot be empty")
            cleaned_name = name.strip()
            if not cleaned_name:
                raise CommandRejectedError("tenant name cannot be empty")

            agg_id = tenant_aggregate_id(cleaned_id)
            events: list[DomainEvent] = [
                TenantCreated(
                    aggregate_id=agg_id,
                    tenant_id=cleaned_id,
                    name=cleaned_name,
                    kind=kind,
                    created_by=creator,
                )
            ]
            if creator:
                events.append(
                    MemberAdded(
                        aggregate_id=agg_id,
                        tenant_id=cleaned_id,
                        subject=creator,
                        role="owner",
                        granted_by=creator,
                    )
                )
            return events

        case CreateTenant(), _:
            raise CommandRejectedError("tenant already created")

        case _, TenantState(is_created=False):
            raise CommandRejectedError("tenant not created")

        case AddMember(subject=subj, role=role, granted_by=granter), _:
            cleaned_sub = subj.strip()
            if not cleaned_sub:
                raise CommandRejectedError("subject cannot be empty")
            if role == "owner":
                raise CommandRejectedError("cannot add owner directly; use TransferOwnership")
            if role not in ("admin", "member", "guest"):
                raise CommandRejectedError(f"invalid tenant role: {role}")
            if cleaned_sub in state.members:
                raise CommandRejectedError(
                    f"subject {cleaned_sub} is already a member; use ChangeMemberRole"
                )

            return [
                MemberAdded(
                    aggregate_id=tenant_aggregate_id(state.tenant_id or ""),
                    tenant_id=state.tenant_id or "",
                    subject=cleaned_sub,
                    role=role,
                    granted_by=granter,
                )
            ]

        case ChangeMemberRole(subject=subj, role=role, changed_by=changer), _:
            if subj not in state.members:
                raise CommandRejectedError(f"subject {subj} is not a member")
            if state.members[subj] == "owner":
                raise CommandRejectedError(
                    "cannot change role of owner directly; use TransferOwnership"
                )
            if role == "owner":
                raise CommandRejectedError(
                    "cannot change role to owner; use TransferOwnership"
                )
            if role not in ("admin", "member", "guest"):
                raise CommandRejectedError(f"invalid tenant role: {role}")
            if state.members[subj] == role:
                raise CommandRejectedError(f"subject {subj} already has role {role}")

            return [
                MemberRoleChanged(
                    aggregate_id=tenant_aggregate_id(state.tenant_id or ""),
                    tenant_id=state.tenant_id or "",
                    subject=subj,
                    role=role,
                    previous_role=state.members[subj],
                    changed_by=changer,
                )
            ]

        case RemoveMember(subject=subj, removed_by=remover), _:
            if subj not in state.members:
                raise CommandRejectedError(f"subject {subj} is not a member")
            if state.members[subj] == "owner":
                raise CommandRejectedError(
                    "cannot remove the tenant owner; transfer ownership first"
                )

            t_id = state.tenant_id or ""
            agg_id = tenant_aggregate_id(t_id)
            events: list[DomainEvent] = [
                MemberRemoved(
                    aggregate_id=agg_id,
                    tenant_id=t_id,
                    subject=subj,
                    removed_by=remover,
                )
            ]
            for p_id, s in state.project_grants:
                if s == subj:
                    events.append(
                        ProjectGrantRevoked(
                            aggregate_id=agg_id,
                            tenant_id=t_id,
                            project_id=p_id,
                            subject=subj,
                            revoked_by=remover,
                        )
                    )
            return events

        case TransferOwnership(from_subject=from_subj, to_subject=to_subj), _:
            if state.owner_subject != from_subj:
                raise CommandRejectedError(f"{from_subj} is not the current owner")
            cleaned_to = to_subj.strip()
            if not cleaned_to:
                raise CommandRejectedError("to_subject cannot be empty")
            if cleaned_to == from_subj:
                raise CommandRejectedError("cannot transfer ownership to current owner")

            return [
                OwnershipTransferred(
                    aggregate_id=tenant_aggregate_id(state.tenant_id or ""),
                    tenant_id=state.tenant_id or "",
                    from_subject=from_subj,
                    to_subject=cleaned_to,
                )
            ]

        case AddProjectGrant(project_id=p_id, subject=subj, role=role, granted_by=granter), _:
            cleaned_sub = subj.strip()
            if not cleaned_sub:
                raise CommandRejectedError("subject cannot be empty")
            if role not in ("owner", "editor", "runner", "viewer"):
                raise CommandRejectedError(f"invalid project role: {role}")

            return [
                ProjectGrantAdded(
                    aggregate_id=tenant_aggregate_id(state.tenant_id or ""),
                    tenant_id=state.tenant_id or "",
                    project_id=p_id,
                    subject=cleaned_sub,
                    role=role,
                    granted_by=granter,
                )
            ]

        case RevokeProjectGrant(project_id=p_id, subject=subj, revoked_by=revoker), _:
            if (p_id, subj) not in state.project_grants:
                raise CommandRejectedError(
                    f"no project grant for subject {subj} on project {p_id}"
                )

            return [
                ProjectGrantRevoked(
                    aggregate_id=tenant_aggregate_id(state.tenant_id or ""),
                    tenant_id=state.tenant_id or "",
                    project_id=p_id,
                    subject=subj,
                    revoked_by=revoker,
                )
            ]

        case CreateInvitation(
            email=email,
            role=role,
            token=token,
            invited_by=inviter,
            expires_at=exp,
            invitation_id=iid,
        ), _:
            if role == "owner":
                raise CommandRejectedError("cannot invite with owner role")
            if role not in ("admin", "member", "guest"):
                raise CommandRejectedError(f"invalid role: {role}")
            norm_email = email.strip().lower()
            if not norm_email:
                raise CommandRejectedError("email cannot be empty")

            for inv in state.invitations.values():
                if inv.get("email") == norm_email and inv.get("status") == "open":
                    raise CommandRejectedError(
                        f"an active invitation already exists for {norm_email}"
                    )

            inv_id = iid or uuid4()
            return [
                InvitationCreated(
                    aggregate_id=tenant_aggregate_id(state.tenant_id or ""),
                    tenant_id=state.tenant_id or "",
                    event_id=inv_id,
                    email=norm_email,
                    role=role,
                    token=token,
                    invited_by=inviter,
                    expires_at=exp,
                )
            ]

        case AcceptInvitation(invitation_id=iid, subject=subj), _:
            if iid not in state.invitations:
                raise CommandRejectedError(f"invitation {iid} not found")
            inv = state.invitations[iid]
            if inv.get("status") != "open":
                raise CommandRejectedError(f"invitation {iid} is already {inv.get('status')}")
            exp = inv.get("expires_at")
            if exp is not None:
                exp_dt = exp if isinstance(exp, datetime) else datetime.fromisoformat(str(exp))
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=UTC)
                if datetime.now(UTC) > exp_dt:
                    raise CommandRejectedError(f"invitation {iid} has expired")
            cleaned_sub = subj.strip()
            if not cleaned_sub:
                raise CommandRejectedError("subject cannot be empty")

            t_id = state.tenant_id or ""
            agg_id = tenant_aggregate_id(t_id)
            return [
                InvitationAccepted(
                    aggregate_id=agg_id,
                    tenant_id=t_id,
                    invitation_id=iid,
                    subject=cleaned_sub,
                ),
                MemberAdded(
                    aggregate_id=agg_id,
                    tenant_id=t_id,
                    subject=cleaned_sub,
                    role=inv["role"],
                    granted_by=inv.get("invited_by", LOCAL_SUBJECT),
                ),
            ]

        case RevokeInvitation(invitation_id=iid, revoked_by=revoker), _:
            if iid not in state.invitations:
                raise CommandRejectedError(f"invitation {iid} not found")
            inv = state.invitations[iid]
            if inv.get("status") != "open":
                raise CommandRejectedError(f"invitation {iid} is already {inv.get('status')}")

            return [
                InvitationRevoked(
                    aggregate_id=tenant_aggregate_id(state.tenant_id or ""),
                    tenant_id=state.tenant_id or "",
                    invitation_id=iid,
                    revoked_by=revoker,
                )
            ]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


def evolve(state: TenantState, event: DomainEvent) -> TenantState:
    """Apply domain facts to TenantState."""
    match event:
        case TenantCreated(tenant_id=t_id, name=name, kind=kind, created_by=creator):
            return state.model_copy(
                update={
                    "is_created": True,
                    "tenant_id": t_id,
                    "name": name,
                    "kind": kind,
                    "created_by": creator,
                }
            )

        case MemberAdded(subject=subj, role=role):
            members = dict(state.members)
            members[subj] = role
            owner = subj if role == "owner" else state.owner_subject
            return state.model_copy(update={"members": members, "owner_subject": owner})

        case MemberRoleChanged(subject=subj, role=role):
            members = dict(state.members)
            members[subj] = role
            return state.model_copy(update={"members": members})

        case MemberRemoved(subject=subj):
            members = {s: r for s, r in state.members.items() if s != subj}
            grants = {(p, s): r for (p, s), r in state.project_grants.items() if s != subj}
            return state.model_copy(update={"members": members, "project_grants": grants})

        case OwnershipTransferred(from_subject=from_subj, to_subject=to_subj):
            members = dict(state.members)
            members[to_subj] = "owner"
            members[from_subj] = "admin"
            return state.model_copy(update={"members": members, "owner_subject": to_subj})

        case ProjectGrantAdded(project_id=p_id, subject=subj, role=role):
            grants = dict(state.project_grants)
            grants[(p_id, subj)] = role
            return state.model_copy(update={"project_grants": grants})

        case ProjectGrantRevoked(project_id=p_id, subject=subj):
            grants = {k: v for k, v in state.project_grants.items() if k != (p_id, subj)}
            return state.model_copy(update={"project_grants": grants})

        case InvitationCreated(
            event_id=iid, email=email, role=role, expires_at=exp, invited_by=inviter
        ):
            invs = dict(state.invitations)
            invs[iid] = {
                "email": email,
                "role": role,
                "status": "open",
                "expires_at": exp,
                "invited_by": inviter,
            }
            return state.model_copy(update={"invitations": invs})

        case InvitationAccepted(invitation_id=iid, subject=subj):
            invs = dict(state.invitations)
            if iid in invs:
                invs[iid] = {**invs[iid], "status": "accepted", "accepted_by": subj}
            return state.model_copy(update={"invitations": invs})

        case InvitationRevoked(invitation_id=iid):
            invs = dict(state.invitations)
            if iid in invs:
                invs[iid] = {**invs[iid], "status": "revoked"}
            return state.model_copy(update={"invitations": invs})

        case _:
            return state
