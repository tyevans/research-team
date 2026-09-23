"""Read models for tenants, memberships, project grants, and invitations."""

from datetime import datetime
from uuid import UUID, uuid5

from eventsource import ReadModel

from research_team.tenancy.domain.tenant import (
    TENANT_NAMESPACE,
    TenantKind,
)

__all__ = [
    "TENANT_ROW_MODELS",
    "InvitationRow",
    "MembershipRow",
    "ProjectGrantRow",
    "TenantRow",
]


class TenantRow(ReadModel):
    """One organisation.

    `id` is a UUID because `ReadModel` requires one; `tenant_id` is the Zitadel
    org id and is what everything else keys on. Both, rather than only the
    string, so a row is findable either way without a scan.
    """

    __table_name__ = "tenants"

    tenant_id: str
    name: str
    kind: TenantKind = "shared"
    """Display only -- the onboarding copy needs it and no permission check
    reads it. See `domain/tenant.TenantKind`."""
    created_by: str = ""

    @staticmethod
    def row_id(tenant_id: str) -> UUID:
        return uuid5(TENANT_NAMESPACE, f"tenant:{tenant_id}")


class MembershipRow(ReadModel):
    """A subject's standing in one organisation.

    The grant tuple `(subject, role, "tenant", tenant_id)`, with the object type
    implicit in the table. Written this way so a tuple-backed checker could
    ingest these rows without a data migration -- see
    `application/authorization.py`'s module docstring.
    """

    __table_name__ = "tenant_memberships"

    tenant_id: str
    subject: str
    role: str
    granted_at: datetime | None = None
    granted_by: str = ""

    @staticmethod
    def row_id(tenant_id: str, subject: str) -> UUID:
        """Derived from the pair, so a second grant to the same person replaces
        the first rather than accumulating.

        A random id would leave two rows, and `membership_role` would then
        answer with whichever the repository happened to return first -- a
        demotion that silently did not take.
        """
        return uuid5(TENANT_NAMESPACE, f"member:{tenant_id}:{subject}")


class ProjectGrantRow(ReadModel):
    """A subject's standing on one project, independent of their tenant role.

    The per-project share: this is what makes a tenant member a `viewer` on one
    project and an `editor` on another, and the only way a `guest` reaches a
    project at all.

    `project_id` is a project, `tenant_id` is an organisation. This is the one
    row in the tree that holds both, and the two names mean what they say --
    which is exactly the collision `domain/tenant.py` warns about, made safe
    here by never abbreviating either.
    """

    __table_name__ = "project_grants"

    project_id: UUID
    tenant_id: str
    subject: str
    role: str
    granted_at: datetime | None = None
    granted_by: str = ""

    @staticmethod
    def row_id(project_id: UUID | str, subject: str) -> UUID:
        return uuid5(TENANT_NAMESPACE, f"grant:{project_id}:{subject}")


class InvitationRow(ReadModel):
    """An open, accepted or revoked invitation to a tenant.

    Keyed by email because the invitee may have no account yet. `accepted_at`
    and `revoked_at` are nullable rather than a status string: both are facts
    with a time, and a status column would answer "when" with nothing.
    """

    __table_name__ = "tenant_invitations"

    tenant_id: str
    email: str
    role: str
    token: str
    invited_by: str = ""
    expires_at: datetime | None = None
    accepted_at: datetime | None = None
    accepted_by: str = ""
    revoked_at: datetime | None = None


TENANT_ROW_MODELS: tuple[type[ReadModel], ...] = (
    TenantRow,
    MembershipRow,
    ProjectGrantRow,
    InvitationRow,
)
