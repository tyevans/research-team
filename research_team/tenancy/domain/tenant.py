"""A tenant: the organisation a project belongs to, and who may reach it.

A tenant is a Zitadel organisation, mirrored locally as a row. Zitadel is the
system of record for who belongs to an organisation; this project mirrors
enough to answer authorization without a network hop, and nothing more.

**A tenant id is a `str` everywhere in this repository, never a `UUID`.**
Zitadel org ids are snowflake-shaped decimal strings, and `UserSignedIn.tenant_id`
was already written as a `str` for that reason. Do not convert one at any
boundary.

The naming hazard, stated once and loudly
-----------------------------------------
**`tenant_id` already means "project id" in this repository.** It is
redstring's vocabulary -- `domain/project.py`'s docstring says "the project id
is also redstring's `tenant_id`", and the name appears dozens of times inside
`infrastructure/knowledge/` and in the projection handlers that read
`event.tenant_id` off a redstring event.

The decision: the new concept takes the name, and redstring's keeps it too,
confined to `infrastructure/knowledge/` and the redstring event handlers.
Renaming redstring's is not available -- it is a library parameter name.
Renaming ours is available but wrong: Zitadel, the docs, and every future
reader mean an organisation by it.

What makes this survivable rather than merely tolerable is that the two never
appear in the same function. The mitigation is mechanical: at every call into
redstring the argument is written `tenant_id=project_id` -- never
`tenant_id=tenant_id`, never positionally -- so the seam is visible at the call
site. `tests/test_tenant_naming_seam.py` greps for the collapsed spelling and
fails on it.

**And the collision reaches inside the event envelope.** `eventsource`'s own
`DomainEvent` already declares `tenant_id: UUID | None`, and in this repository
that inherited field holds a *project* id -- `read_models.py`'s redstring
handlers read `event.tenant_id` and mean the project, and `app.py:5992` does the
same for the SSE feed. Every event below therefore **overrides** the envelope
field with `tenant_id: str`, meaning an organisation. That is deliberate, and
these are the two things that make it safe rather than merely allowed:

- Nothing in this tree reads `event.tenant_id` generically. The one call site
  that reads it off an arbitrary event (`app.py:5992`) is guarded by
  `aggregate_type in KNOWLEDGE_CATEGORIES`, and these events are `"Tenant"`.
- The events table's `tenant_id` column is `TEXT`, so a Zitadel org id stores
  and reads back unchanged. `test_a_tenant_event_stores_its_org_id_as_text` is
  the measurement rather than the reasoning.

The cost, stated: the events table's `tenant_id` column now holds project UUIDs
for most rows and org ids for these. Nothing queries that column in this
repository, and anything that starts to must filter by `aggregate_type` first.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4, uuid5

from eventsource import CommandRejectedError, DeciderAggregate, DomainEvent, register_event
from pydantic import BaseModel, Field

TENANT_NAMESPACE = UUID("8c4a1e37-5b62-4d09-9f13-7a0e2d6b8c41")
"""Namespace for every id derived from a tenant id or a (tenant, subject) pair.

One namespace for the aggregate id and for all four row types, distinguished by
the string fed to `uuid5` (`"tenant:..."`, `"member:..."`, and so on). A second
namespace would buy nothing: the prefixes already make a collision between two
kinds impossible, and a namespace per kind is four constants to keep in step.
"""

LOCAL_TENANT = "local"
"""The tenant every project belongs to when `AGENT_AUTH` is off.

Not `""`. An empty string is what an uninitialised field looks like, so a bug
that left `tenant_id` empty would be indistinguishable from correct local
operation -- and the check that reads it would refuse for a reason nobody could
name. A word that means something is a word a person can search for.
"""

LOCAL_SUBJECT = "local"
"""The actor recorded when `AGENT_AUTH` is off, for `LOCAL_TENANT`'s reason.

A subject is a Zitadel `sub` claim when auth is on. With auth off there is no
identity service and exactly one person, so attributing their writes to a named
constant is honest where attributing them to `None` is a field nobody can query.
"""

TenantKind = Literal["personal", "shared"]
"""Display only.

The onboarding copy needs to tell a fresh personal tenant apart from a shared
one; nothing in the permission check reads this. Stated because a `kind` column
beside a permission system invites a special case, and the special case is what
turns a two-row check into a policy.
"""

TenantRole = Literal["owner", "admin", "member", "guest"]
"""A person's standing in an organisation. See `application/authorization.py`
for what each one may do -- the ladder is declared there, with the matrix, so
the roles and the permissions they imply cannot drift apart in two files."""

ProjectRole = Literal["owner", "editor", "runner", "viewer"]
"""A person's standing on one project, independent of their tenant role."""


TENANT_AGGREGATE_TYPE = "Tenant"
"""The stream these events are appended to, named rather than spelled twice.

Every other aggregate type here is reachable as `SomeAggregate.aggregate_type`.
There is no `Tenant` aggregate class to ask -- membership is projected from
events the sharing routes append directly, with no invariant a decider would
protect -- so the constant stands in for the class attribute, exactly as
`ONTOLOGY_AGGREGATE_TYPE` does and for the same reason: the feed-coverage guard
in `persistence/event_store.py` needs something to name that cannot drift from
the events' own default.
"""


def tenant_aggregate_id(tenant_id: str) -> UUID:
    """The stream a tenant's events live on, derived from its org id.

    Derived rather than random for the reason every other derived id here is
    derived (memory: "Derive ids, don't let the model pick"): a tenant id
    arrives from Zitadel, and the alternative is a lookup table mapping org ids
    to stream ids, which is a second source of truth about which stream a
    tenant has.
    """
    return uuid5(TENANT_NAMESPACE, f"tenant:{tenant_id}")


@register_event
class TenantCreated(DomainEvent):
    """Creation event. Must be the first event on the stream.

    `aggregate_id` is a UUID because the library requires one; the *tenant id*
    is the `tenant_id` field, a Zitadel org id, and it is what every other
    event and every row keys on. The two are related by
    `tenant_aggregate_id()`, which derives one from the other, so a tenant's
    stream is findable from its org id without a lookup table.
    """

    aggregate_type: str = TENANT_AGGREGATE_TYPE
    tenant_id: str
    name: str
    kind: TenantKind = "shared"
    created_by: str = LOCAL_SUBJECT


@register_event
class MemberAdded(DomainEvent):
    """A subject gained a role in a tenant, or had an existing one replaced.

    One event for "added" and "re-added" on purpose: the row id is derived from
    `(tenant_id, subject)`, so a second grant to the same person replaces the
    first rather than accumulating. A separate `MemberReAdded` would be a
    second spelling of one fact.
    """

    aggregate_type: str = TENANT_AGGREGATE_TYPE
    tenant_id: str
    subject: str
    role: TenantRole
    granted_by: str = LOCAL_SUBJECT


@register_event
class MemberRoleChanged(DomainEvent):
    """An existing member's role was changed. Carries the old role so the log
    answers "what were they before" without a fold."""

    aggregate_type: str = TENANT_AGGREGATE_TYPE
    tenant_id: str
    subject: str
    role: TenantRole
    previous_role: TenantRole
    changed_by: str = LOCAL_SUBJECT


@register_event
class MemberRemoved(DomainEvent):
    """A subject no longer belongs to a tenant.

    Removes the row, which is what makes "remove member" true rather than a
    lie: the check resolves the *resource's* tenant and asks whether this
    subject has a role in it, so a stale cookie naming the tenant grants
    nothing the moment this row is gone.
    """

    aggregate_type: str = TENANT_AGGREGATE_TYPE
    tenant_id: str
    subject: str
    removed_by: str = LOCAL_SUBJECT


@register_event
class OwnershipTransferred(DomainEvent):
    """The tenant's `owner` moved from one subject to another.

    Both subjects on one event so the log answers "who was owner on date D"
    without folding every role change. The projection writes two rows from it.
    """

    aggregate_type: str = TENANT_AGGREGATE_TYPE
    tenant_id: str
    from_subject: str
    to_subject: str


@register_event
class ProjectGrantAdded(DomainEvent):
    """A subject was given a role on one project.

    The per-project share. This is what makes a tenant member a `viewer` on one
    project and an `editor` on another, and it is the only way a `guest` reaches
    a project at all.
    """

    aggregate_type: str = TENANT_AGGREGATE_TYPE
    tenant_id: str
    project_id: UUID
    subject: str
    role: ProjectRole
    granted_by: str = LOCAL_SUBJECT


@register_event
class ProjectGrantRevoked(DomainEvent):
    """A subject's role on one project was withdrawn."""

    aggregate_type: str = TENANT_AGGREGATE_TYPE
    tenant_id: str
    project_id: UUID
    subject: str
    revoked_by: str = LOCAL_SUBJECT


@register_event
class InvitationCreated(DomainEvent):
    """Someone was invited to a tenant by email address.

    Keyed by **email**, not by subject, because the invitee may have no account
    yet. Claimed either by the single-use `token` or by a verified email claim
    at sign-in; B4 owns both paths, and the `email_verified` condition on the
    second is load-bearing -- without it anyone who can register an account
    claiming an address they do not control can accept an invitation sent to it.
    """

    aggregate_type: str = TENANT_AGGREGATE_TYPE
    tenant_id: str
    email: str
    role: TenantRole
    token: str
    invited_by: str = LOCAL_SUBJECT
    expires_at: datetime | None = None


@register_event
class InvitationAccepted(DomainEvent):
    """An invitation was claimed. Carries the subject that claimed it, which is
    the first moment the invitee has an identity to record."""

    aggregate_type: str = TENANT_AGGREGATE_TYPE
    tenant_id: str
    invitation_id: UUID
    subject: str


@register_event
class InvitationRevoked(DomainEvent):
    """An open invitation was withdrawn before it was claimed."""

    aggregate_type: str = TENANT_AGGREGATE_TYPE
    tenant_id: str
    invitation_id: UUID
    revoked_by: str = LOCAL_SUBJECT


TENANT_EVENTS: tuple[type[DomainEvent], ...] = (
    TenantCreated,
    MemberAdded,
    MemberRoleChanged,
    MemberRemoved,
    OwnershipTransferred,
    ProjectGrantAdded,
    ProjectGrantRevoked,
    InvitationCreated,
    InvitationAccepted,
    InvitationRevoked,
)
"""Every event this aggregate writes.

Declared once so the projection's coverage can be asserted by introspection
rather than by a hand-written list -- the same reason
`authoring_checkpoints.CHECKPOINT_MARKERS` exists. A tenth event added without
a handler fails `test_the_projection_handles_every_tenant_event` at collection
rather than by leaving a read model silently empty (CLAUDE.md, "An event no
projection handles counts as APPLIED, not rejected").
"""


@dataclass(frozen=True)
class CreateTenant:
    tenant_id: str
    name: str
    kind: TenantKind = "shared"
    created_by: str = LOCAL_SUBJECT


@dataclass(frozen=True)
class AddMember:
    subject: str
    role: TenantRole
    granted_by: str = LOCAL_SUBJECT


@dataclass(frozen=True)
class ChangeMemberRole:
    subject: str
    role: TenantRole
    changed_by: str = LOCAL_SUBJECT


@dataclass(frozen=True)
class RemoveMember:
    subject: str
    removed_by: str = LOCAL_SUBJECT


@dataclass(frozen=True)
class TransferOwnership:
    from_subject: str
    to_subject: str


@dataclass(frozen=True)
class AddProjectGrant:
    project_id: UUID
    subject: str
    role: ProjectRole
    granted_by: str = LOCAL_SUBJECT


@dataclass(frozen=True)
class RevokeProjectGrant:
    project_id: UUID
    subject: str
    revoked_by: str = LOCAL_SUBJECT


@dataclass(frozen=True)
class CreateInvitation:
    email: str
    role: TenantRole
    token: str
    invited_by: str = LOCAL_SUBJECT
    expires_at: datetime | None = None
    invitation_id: UUID | None = None


@dataclass(frozen=True)
class AcceptInvitation:
    invitation_id: UUID
    subject: str


@dataclass(frozen=True)
class RevokeInvitation:
    invitation_id: UUID
    revoked_by: str = LOCAL_SUBJECT


TenantCommand = (
    CreateTenant
    | AddMember
    | ChangeMemberRole
    | RemoveMember
    | TransferOwnership
    | AddProjectGrant
    | RevokeProjectGrant
    | CreateInvitation
    | AcceptInvitation
    | RevokeInvitation
)


class TenantState(BaseModel):
    """Derivable state from a tenant's event stream."""

    tenant_id: str | None = None
    name: str = ""
    kind: TenantKind = "shared"
    created_by: str = ""
    is_created: bool = False
    owner_subject: str | None = None
    members: dict[str, TenantRole] = Field(default_factory=dict)
    project_grants: dict[tuple[UUID, str], ProjectRole] = Field(default_factory=dict)
    invitations: dict[UUID, dict[str, Any]] = Field(default_factory=dict)


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


class Tenant(DeciderAggregate[TenantState, TenantCommand]):
    """The Tenant aggregate imperative shell."""

    aggregate_type = TENANT_AGGREGATE_TYPE

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)
