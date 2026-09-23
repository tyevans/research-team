"""Projection for tenants, memberships, project grants, and invitations."""

from datetime import UTC, datetime

from eventsource import (
    DeclarativeProjection,
    handles,
)
from eventsource.ports.readmodels import ReadModelRepository

from research_team.infrastructure.persistence.tenant_models import (
    InvitationRow,
    MembershipRow,
    ProjectGrantRow,
    TenantRow,
)
from research_team.tenancy.domain.tenant import (
    InvitationAccepted,
    InvitationCreated,
    InvitationRevoked,
    MemberAdded,
    MemberRemoved,
    MemberRoleChanged,
    OwnershipTransferred,
    ProjectGrantAdded,
    ProjectGrantRevoked,
    TenantCreated,
)

__all__ = ["TenantProjection"]


class TenantProjection(DeclarativeProjection):
    """Applies the tenant events to the four tables.

    One projection over four tables rather than four projections, for
    `TopicProjection`'s mechanical reason: a subscription advances only on
    events its projection handles, so four subscriptions over one stream would
    leave three of them at positions that mean nothing, and anything waiting for
    all four to catch up would wait forever. One subscription has one position,
    which is a question with an answer.

    Every handler loads, mutates and writes back, so replaying from a checkpoint
    slightly behind re-derives the same values rather than accumulating them --
    the idempotence `SessionSummaryProjection` relies on.
    """

    def __init__(
        self,
        tenants: ReadModelRepository[TenantRow],
        memberships: ReadModelRepository[MembershipRow],
        grants: ReadModelRepository[ProjectGrantRow],
        invitations: ReadModelRepository[InvitationRow],
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
        retry_policy=None,
    ) -> None:
        self._tenants = tenants
        self._memberships = memberships
        self._grants = grants
        self._invitations = invitations
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=retry_policy,
            tracer=tracer,
        )

    @handles(TenantCreated)
    async def _on_tenant_created(self, event: TenantCreated) -> None:
        await self._tenants.save(
            TenantRow(
                id=TenantRow.row_id(event.tenant_id),
                tenant_id=event.tenant_id,
                name=event.name,
                kind=event.kind,
                created_by=event.created_by,
            )
        )

    @handles(MemberAdded)
    async def _on_member_added(self, event: MemberAdded) -> None:
        await self._save_membership(
            event.tenant_id, event.subject, event.role, event.granted_by, event.occurred_at
        )

    @handles(MemberRoleChanged)
    async def _on_role_changed(self, event: MemberRoleChanged) -> None:
        await self._save_membership(
            event.tenant_id, event.subject, event.role, event.changed_by, event.occurred_at
        )

    @handles(MemberRemoved)
    async def _on_member_removed(self, event: MemberRemoved) -> None:
        # Deleted, not flagged. The row's absence is what makes "remove member"
        # true: the checker asks for a role in the resource's tenant and gets
        # nothing, whatever the holder's cookie still says.
        await self._memberships.delete(MembershipRow.row_id(event.tenant_id, event.subject))

    @handles(OwnershipTransferred)
    async def _on_transfer(self, event: OwnershipTransferred) -> None:
        # Two rows from one event. The old owner becomes an `admin` rather than
        # losing the tenant: transferring is handing over the last word, not
        # ejecting the person who built the organisation, and a transfer that
        # locked the previous owner out would have no undo.
        await self._save_membership(
            event.tenant_id, event.to_subject, "owner", event.from_subject, event.occurred_at
        )
        await self._save_membership(
            event.tenant_id, event.from_subject, "admin", event.to_subject, event.occurred_at
        )

    @handles(ProjectGrantAdded)
    async def _on_grant_added(self, event: ProjectGrantAdded) -> None:
        await self._grants.save(
            ProjectGrantRow(
                id=ProjectGrantRow.row_id(event.project_id, event.subject),
                project_id=event.project_id,
                tenant_id=event.tenant_id,
                subject=event.subject,
                role=event.role,
                granted_at=event.occurred_at,
                granted_by=event.granted_by,
            )
        )

    @handles(ProjectGrantRevoked)
    async def _on_grant_revoked(self, event: ProjectGrantRevoked) -> None:
        await self._grants.delete(ProjectGrantRow.row_id(event.project_id, event.subject))

    @handles(InvitationCreated)
    async def _on_invited(self, event: InvitationCreated) -> None:
        await self._invitations.save(
            InvitationRow(
                id=event.event_id,
                tenant_id=event.tenant_id,
                email=event.email.strip().lower(),
                role=event.role,
                token=event.token,
                invited_by=event.invited_by,
                expires_at=event.expires_at,
            )
        )

    @handles(InvitationAccepted)
    async def _on_accepted(self, event: InvitationAccepted) -> None:
        row = await self._invitations.get(event.invitation_id)
        if row is None:
            # An acceptance whose invitation this build cannot find. Ignored
            # rather than raised: a projection that refuses one event stops
            # following the log for every other tenant too, and the membership
            # this acceptance also produced is carried by its own `MemberAdded`.
            return
        row.accepted_at = event.occurred_at
        row.accepted_by = event.subject
        await self._invitations.save(row)

    @handles(InvitationRevoked)
    async def _on_revoked(self, event: InvitationRevoked) -> None:
        row = await self._invitations.get(event.invitation_id)
        if row is None:
            return
        row.revoked_at = event.occurred_at
        await self._invitations.save(row)

    async def _save_membership(
        self,
        organisation_id: str,
        subject: str,
        role: str,
        granted_by: str,
        at: datetime | None,
    ) -> None:
        # `organisation_id` rather than `tenant_id`, so the assignment below
        # cannot be written `tenant_id=tenant_id` -- the one spelling that hides
        # which of the two concepts is being passed. See `domain/tenant.py`.
        await self._memberships.save(
            MembershipRow(
                id=MembershipRow.row_id(organisation_id, subject),
                tenant_id=organisation_id,
                subject=subject,
                role=role,
                granted_at=at or datetime.now(UTC),
                granted_by=granted_by,
            )
        )
