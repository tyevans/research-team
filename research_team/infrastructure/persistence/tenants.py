"""Tenants, memberships, project grants and invitations, as four tables.

**In its own module, not in `read_models.py`.** That file is over five thousand
lines and is the most contended read-model file in the tree; a fourth
workstream editing it concurrently is a merge nobody wins. The split is by
subject as well as by size, the way `topics.py` splits: these four tables answer
"who may reach this", which is a question with its own vocabulary and its own
consumer (`application/authorization.py`).

**Membership is projected, not stored.** W-C0's settings store deliberately has
no projection -- a setting's current value is the whole of what anyone asks. Who
is in an organisation is the opposite kind of fact: its history is the point,
"when did this person gain admin and who granted it" is a question somebody
will ask, and `/rebuild` must be able to re-derive the answer from the log. So
these four follow `SessionSummaryProjection`'s shape rather than the settings
store's.

**`tenant_id` here is an organisation, never a project.** See
`domain/tenant.py`'s module docstring for the naming hazard in full: redstring
uses the same name for a project id, dozens of times, confined to
`infrastructure/knowledge/`. The two never appear in the same function, and
`ProjectGrantRow` is the only row here that holds both -- with the project id
spelled `project_id`, which is what keeps the seam readable.
"""

from datetime import datetime
from uuid import UUID

import aiosqlite
from eventsource import (
    DomainEvent,
    ExpectedVersion,
    StreamId,
)
from eventsource.adapters.sqlite.readmodels import SQLiteReadModelRepository
from eventsource.ports.readmodels import Query, ReadModelRepository
from eventsource.ports.readmodels.query import Filter

from research_team.infrastructure.persistence.read_models import (
    apply_schema,
)
from research_team.infrastructure.persistence.store_base import BaseProjectionRunner
from research_team.infrastructure.persistence.tenant_models import (
    TENANT_ROW_MODELS,
    InvitationRow,
    MembershipRow,
    ProjectGrantRow,
    TenantRow,
)
from research_team.infrastructure.persistence.tenant_projection import TenantProjection
from research_team.tenancy.domain.tenant import (
    LOCAL_SUBJECT,
    LOCAL_TENANT,
    MemberAdded,
    TenantCreated,
    tenant_aggregate_id,
)

__all__ = [
    "TENANT_ROW_MODELS",
    "InvitationRow",
    "MembershipRow",
    "ProjectGrantRow",
    "TenantProjection",
    "TenantRow",
    "TenantRunner",
    "TenantStore",
]


class TenantStore:
    """The four tables and the connection they share.

    Mirrors `TopicStore`: opening it applies every model's DDL through
    `apply_schema`, so there is no migration step to run and forget. `CREATE
    TABLE IF NOT EXISTS` does nothing to a table that already exists, which is
    how a field added to a read model went missing from every database opened
    before the change -- see `apply_schema`'s docstring for that incident.
    """

    def __init__(
        self,
        connection: aiosqlite.Connection,
        tenants: ReadModelRepository[TenantRow],
        memberships: ReadModelRepository[MembershipRow],
        grants: ReadModelRepository[ProjectGrantRow],
        invitations: ReadModelRepository[InvitationRow],
        projection: TenantProjection,
    ) -> None:
        self._connection = connection
        self._tenants = tenants
        self._memberships = memberships
        self._grants = grants
        self._invitations = invitations
        self.projection = projection

    @classmethod
    async def open(
        cls,
        db_path: str,
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
        retry_policy=None,
    ) -> "TenantStore":
        connection = await aiosqlite.connect(db_path)
        for model in TENANT_ROW_MODELS:
            await apply_schema(connection, model)
        # Every read below is a point lookup by a natural key the generated
        # schema does not index. Two of them are on the request path of every
        # authorized route, so this is the difference between a table scan per
        # check and an index seek per check.
        await connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tenant_memberships_lookup "
            f"ON {MembershipRow.table_name()}(tenant_id, subject)"
        )
        await connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_project_grants_lookup "
            f"ON {ProjectGrantRow.table_name()}(project_id, subject)"
        )
        await connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tenant_invitations_tenant "
            f"ON {InvitationRow.table_name()}(tenant_id)"
        )
        await connection.commit()
        tenants = SQLiteReadModelRepository(connection, TenantRow, tracer)
        memberships = SQLiteReadModelRepository(connection, MembershipRow, tracer)
        grants = SQLiteReadModelRepository(connection, ProjectGrantRow, tracer)
        invitations = SQLiteReadModelRepository(connection, InvitationRow, tracer)
        return cls(
            connection,
            tenants,
            memberships,
            grants,
            invitations,
            TenantProjection(
                tenants,
                memberships,
                grants,
                invitations,
                checkpoint_repo,
                dlq_repo,
                tracer,
                retry_policy,
            ),
        )

    async def tenant(self, tenant_id: str) -> TenantRow | None:
        return await self._tenants.get(TenantRow.row_id(tenant_id))

    async def membership_role(self, tenant_id: str, subject: str) -> str | None:
        """This subject's role in this tenant, or `None`.

        The `GrantReader` half that `RoleTableAuthorizer` calls on every check.
        A point read of a derived id, so there is no ordering question and no
        second row to disagree with the first.
        """
        row = await self._memberships.get(MembershipRow.row_id(tenant_id, subject))
        return row.role if row is not None else None

    async def project_grant_role(self, project_id: UUID | str, subject: str) -> str | None:
        """This subject's role on this project, or `None`."""
        row = await self._grants.get(ProjectGrantRow.row_id(project_id, subject))
        return row.role if row is not None else None

    async def members(self, tenant_id: str) -> list[MembershipRow]:
        rows = await self._memberships.find(
            Query(filters=[Filter(field="tenant_id", operator="eq", value=tenant_id)])
        )
        return sorted(rows, key=lambda row: (row.granted_at or datetime.min, row.subject))

    async def memberships_of(self, subject: str) -> list[MembershipRow]:
        """Every tenant this subject belongs to. What `GET /api/tenants` reads."""
        rows = await self._memberships.find(
            Query(filters=[Filter(field="subject", operator="eq", value=subject)])
        )
        return sorted(rows, key=lambda row: row.tenant_id)

    async def project_grants(self, project_id: UUID) -> list[ProjectGrantRow]:
        rows = await self._grants.find(
            Query(filters=[Filter(field="project_id", operator="eq", value=str(project_id))])
        )
        return sorted(rows, key=lambda row: row.subject)

    async def invitations(self, tenant_id: str) -> list[InvitationRow]:
        rows = await self._invitations.find(
            Query(filters=[Filter(field="tenant_id", operator="eq", value=tenant_id)])
        )
        return sorted(rows, key=lambda row: (row.created_at, str(row.id)))

    async def truncate(self) -> None:
        for model in TENANT_ROW_MODELS:
            await self._connection.execute(f"DELETE FROM {model.table_name()}")
        await self._connection.commit()

    async def close(self) -> None:
        await self._connection.close()


class TenantRunner(BaseProjectionRunner[TenantStore]):
    """Keeps the four tenancy tables following the log.

    A runner of its own, beside the other projections over the same store, for
    the reason `TopicRunner` gives: `rebuild()` stops a manager, truncates its
    tables and resets its checkpoint, and tables that can fail independently
    have to be repairable independently. Repairing the topic queue must not take
    authorization down with it, and the reverse matters more.
    """

    _label = "tenant"
    _store_class = TenantStore
    _projection_class = TenantProjection

    @property
    def tenants(self) -> TenantStore:
        return self.store

    @property
    def _tenants(self) -> TenantStore | None:
        return self._store_instance

    async def seed_local_tenant(self) -> bool:
        """Give `LOCAL_TENANT` a row and `LOCAL_SUBJECT` an `owner` membership.

        `ProjectCreated.tenant_id` is required (B2) and is the string `"local"`
        when `AGENT_AUTH` is off, so without this the off configuration points
        every project at a tenant that does not exist. The design calls that
        "the foreign concept dangling", and the cost of leaving it is not a
        crash -- it is that the *on* path and the *off* path stop being the same
        code with a different final bool, which is the one property that makes
        the permissive adapter worth having.

        Returns whether it wrote. Guarded by a read rather than left idempotent:
        the row ids are derived, so a second append would overwrite rather than
        duplicate, but it would still put two more events on the log on every
        process start forever, and a log that grows when nothing happened is a
        log nobody can read a history out of.

        **Not personal-tenant provisioning.** W-A mirrors a Zitadel org id onto
        `users.tenant_id` and nothing creates an organisation; doing that on
        first sign-in is B6's, and it needs the management API this has no
        business calling. This is the auth-off case only, where there is no
        principal at all and the tenant id comes from a constant.
        """
        if await self.tenants.tenant(LOCAL_TENANT) is not None:
            return False
        stream = tenant_aggregate_id(LOCAL_TENANT)
        await self.record(
            TenantCreated(
                aggregate_id=stream,
                tenant_id=LOCAL_TENANT,
                name="This installation",
                kind="personal",
                created_by=LOCAL_SUBJECT,
            ),
            MemberAdded(
                aggregate_id=stream,
                tenant_id=LOCAL_TENANT,
                subject=LOCAL_SUBJECT,
                role="owner",
            ),
        )
        await self.caught_up()
        return True

    async def record(self, *events: DomainEvent) -> None:
        """Append tenancy events and wake the subscription.

        The write half of this store. It lives on the runner rather than on
        `TenantStore` because the store owns the *tables*, and the events go to
        the log -- writing them through the thing that reads the projection
        would invite somebody to write a row and skip the event, which is the
        one move that makes `/rebuild` lose data.

        Publishes on the same bus the subscription listens to, and that is not
        optional: nothing here polls the store, so an append with no publish
        leaves the row unwritten until some other event happens to wake the
        subscription. Measured while writing
        `tests/test_authorization_wiring.py`, where an append through a second
        connection to the same file never arrived at all.

        `ExpectedVersion.any_()`: a tenant's stream protects no invariant this
        projection depends on -- every handler loads, mutates and writes back --
        and two admins granting two different people concurrently should not
        make one of them fail on a version race they have no reason to care
        about. The rules that *do* need a version check (one owner per tenant,
        a transfer target who is already an admin) are B4's, and they belong in
        the route that has both the old and the new state to compare.
        """
        for event in events:
            await self._store.append(
                StreamId(event.aggregate_id, "Tenant"), [event], ExpectedVersion.any_()
            )
        await self._bus.publish(list(events))

    async def membership_role(self, organisation_id: str, subject: str) -> str | None:
        """`GrantReader`, delegated to the store.

        The runner rather than the store is what `composition.py` hands the
        checker, because the store does not exist until `start()` and the
        `Application` is frozen -- constructing the authorizer around a store
        that is not open yet is not available. Delegating here keeps the
        indirection to two lines instead of a wrapper class, and keeps the
        checker reading through the *same* connection the members page reads
        through: two connections would be two views of who is a member, and the
        permission answer and the rendered list could disagree.

        Raises rather than answering `None` when the projection has not started.
        `None` means "no role", and a build that never started this would
        otherwise refuse everybody with no way to tell that apart from a person
        who genuinely has no membership.
        """
        return await self.tenants.membership_role(organisation_id, subject)

    async def project_grant_role(self, project_id: UUID | str, subject: str) -> str | None:
        """`GrantReader`, delegated to the store. See `membership_role`."""
        return await self.tenants.project_grant_role(project_id, subject)
