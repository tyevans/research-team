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

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid5

import aiosqlite
from eventsource import (
    DeclarativeProjection,
    DomainEvent,
    ExpectedVersion,
    InMemoryEventBus,
    ReadModel,
    SQLCheckpointRepository,
    SQLDLQRepository,
    StreamId,
    create_async_engine,
    handles,
)
from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.readmodels import SQLiteReadModelRepository
from eventsource.application.subscriptions import SubscriptionConfig, SubscriptionManager
from eventsource.ports.dlq import DLQEntry
from eventsource.ports.readmodels import Query, ReadModelRepository
from eventsource.ports.readmodels.query import Filter
from sqlalchemy.ext.asyncio import AsyncEngine

from research_team.domain.tenant import (
    TENANT_NAMESPACE,
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
    TenantKind,
)
from research_team.infrastructure.persistence.read_models import (
    LOCAL_RETRY_POLICY,
    apply_schema,
)


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


class TenantRunner:
    """Keeps the four tenancy tables following the log.

    A runner of its own, beside the other projections over the same store, for
    the reason `TopicRunner` gives: `rebuild()` stops a manager, truncates its
    tables and resets its checkpoint, and tables that can fail independently
    have to be repairable independently. Repairing the topic queue must not take
    authorization down with it, and the reverse matters more.
    """

    def __init__(
        self,
        store: SQLiteEventStore,
        db_path: str,
        bus: InMemoryEventBus,
        tracer=None,
    ):
        self._store = store
        self._db_path = db_path
        self._bus = bus
        self._tracer = tracer
        self._tenants: TenantStore | None = None
        self._manager: SubscriptionManager | None = None
        self._subscription = None
        self._checkpoints: SQLCheckpointRepository | None = None
        self._dlq: SQLDLQRepository | None = None
        self._engine: AsyncEngine | None = None

    @property
    def projection_name(self) -> str:
        """The subscription's name, which is also its checkpoint and DLQ key."""
        return TenantProjection.__name__

    @property
    def tenants(self) -> TenantStore:
        if self._tenants is None:
            raise RuntimeError("the tenant projection has not been started")
        return self._tenants

    async def start(self) -> None:
        """Open the tables and start following the log.

        Touches the event store first for the reason the other runners do: it
        creates `projection_checkpoints` on first connection rather than at
        construction, so reaching for checkpoints before anything has used the
        store finds no table at all.
        """
        if self._manager is not None:
            return
        await self._store.current_position()
        engine = create_async_engine(f"sqlite+aiosqlite:///{self._db_path}")
        self._engine = engine
        self._checkpoints = SQLCheckpointRepository(engine)
        self._dlq = SQLDLQRepository(engine)
        self._tenants = await TenantStore.open(
            self._db_path, self._checkpoints, self._dlq, self._tracer, LOCAL_RETRY_POLICY
        )
        self._manager = SubscriptionManager(
            self._store, self._bus, self._checkpoints, dlq_repo=self._dlq, tracer=self._tracer
        )
        self._subscription = await self._manager.subscribe(
            self._tenants.projection, SubscriptionConfig(start_from="checkpoint")
        )
        results = await self._manager.start()
        failures = {name: err for name, err in results.items() if err is not None}
        if failures:
            raise RuntimeError(f"the tenant projection failed to start: {failures}")

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

    async def failures(self, limit: int = 100) -> list[DLQEntry]:
        """Events this projection could not process.

        A non-empty list means somebody's access is stale in a direction nobody
        is told about -- a removal that did not land reads exactly like a person
        who still has the role.
        """
        if self._dlq is None:
            return []
        return await self._dlq.get_failed_events(
            projection_name=self.projection_name, limit=limit
        )

    async def caught_up(self, timeout: float = 10.0) -> None:
        """Block until the projection has seen everything appended so far.

        Load-bearing rather than a test affordance: a route that grants a role
        and then answers a request has to have the row by the time the next
        check reads it, and the gap between the append and the row is exactly
        where a fresh grant looks like no grant.
        """
        if self._manager is None:
            return
        target = await self._store.current_position()
        if target is None:
            return
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            reached = self._subscription.last_processed_position
            if reached is not None and not reached < target:
                return
            await asyncio.sleep(0.01)
        raise TimeoutError(f"the tenant projection did not reach {target} within {timeout}s")

    async def rebuild(self) -> None:
        """Throw the four tables away and derive them again from the log.

        Safe because none of them holds original information: every field comes
        from an event. All four go together because they share a checkpoint --
        see `TenantProjection`.
        """
        if self._manager is None or self._tenants is None:
            raise RuntimeError("the tenant projection has not been started")
        await self._manager.stop()
        for entry in await self.failures(limit=1000):
            await self._dlq.mark_resolved(entry.id, resolved_by="rebuild")
        await self._tenants.truncate()
        await self._checkpoints.reset_checkpoint(self.projection_name)
        self._manager = None
        self._subscription = None
        await self._tenants.close()
        self._tenants = None
        await self.start()
        await self.caught_up()

    async def stop(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
            self._manager = None
            self._subscription = None
        if self._tenants is not None:
            await self._tenants.close()
            self._tenants = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
