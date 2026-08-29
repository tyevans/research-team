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

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid5

from eventsource import DomainEvent, register_event

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
