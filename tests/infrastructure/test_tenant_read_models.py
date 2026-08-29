"""The four tenancy tables, over a real event store and a real projection.

The property that matters is that the rows agree with the log: a membership is
what the events say it is, a removal removes, and `/rebuild` re-derives all four
tables from nothing. Every test here appends real events and reads the real
tables -- there is no in-memory double, because the thing most likely to be
wrong is the projection's handler coverage, and a double would supply it.
"""

from uuid import uuid4

import pytest

from research_team.domain.tenant import (
    TENANT_EVENTS,
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
    tenant_aggregate_id,
)
from research_team.infrastructure.persistence.tenants import (
    TenantProjection,
    TenantRunner,
)

TENANT = "org-42"
ALICE = "sub-alice"
BOB = "sub-bob"


async def append(runner, *events):
    """Through `TenantRunner.record`, the production writer.

    Not a hand-rolled `store.append` beside it: a fixture that writes the same
    events a different way could not see the real writer stop publishing, and
    the publish is what wakes the subscription. This is the arrange phase using
    the collaborator the code under test depends on, deliberately -- what it
    must not do is write the *rows*, which is the step the projection owns.
    """
    await runner.record(*events)


def created(**kwargs):
    return TenantCreated(
        aggregate_id=tenant_aggregate_id(TENANT),
        tenant_id=TENANT,
        name="Acme Research",
        **kwargs,
    )


@pytest.fixture
async def runner(db_path, store, publisher):
    started = TenantRunner(store, db_path, publisher)
    await started.start()
    yield started
    await started.stop()


def test_the_projection_handles_every_tenant_event():
    """Derived by introspection from `TENANT_EVENTS`, not from a hand-written
    list.

    CLAUDE.md: an event no projection handles counts as APPLIED, not rejected --
    nothing raises, nothing logs, and the read model is silently empty. So the
    coverage has to be asserted mechanically. An eleventh event added to
    `domain/tenant.py` without a handler fails here rather than by leaving
    somebody's access unrecorded.
    """
    handled = {
        getattr(attribute, "_handles_event_type", None)
        for attribute in vars(TenantProjection).values()
    }
    # Read off `@handles`'s own marker rather than off a list in this file. A
    # list here would be the hand-written pair CLAUDE.md's checkpoint section
    # warns about: it goes stale in exactly the commit that adds the event.
    assert TenantCreated in handled, "the marker `@handles` sets has been renamed"
    missing = [event.__name__ for event in TENANT_EVENTS if event not in handled]
    assert not missing, f"no handler for {missing}"


async def test_a_created_tenant_becomes_a_row(runner):
    await append(runner, created(kind="personal", created_by=ALICE))
    await runner.caught_up()
    row = await runner.tenants.tenant(TENANT)
    assert row is not None
    assert (row.tenant_id, row.name, row.kind, row.created_by) == (
        TENANT,
        "Acme Research",
        "personal",
        ALICE,
    )


async def test_a_tenant_event_stores_its_org_id_as_text(runner, store, publisher, db_path):
    """The measurement behind `domain/tenant.py`'s envelope-override note.

    These events override `DomainEvent.tenant_id`, which is `UUID | None` and
    means *the project* everywhere else in this repository. The events table's
    column is `TEXT`, so a Zitadel org id -- a decimal snowflake string, not a
    UUID -- has to store and read back unchanged. Reasoning said it would; this
    is the check.
    """
    snowflake = "284327498327498273"
    await append(
        runner,
        TenantCreated(
            aggregate_id=tenant_aggregate_id(snowflake), tenant_id=snowflake, name="Snowflake"
        ),
    )
    await runner.caught_up()
    row = await runner.tenants.tenant(snowflake)
    assert row is not None and row.tenant_id == snowflake


async def test_a_second_grant_to_the_same_person_replaces_the_first(runner):
    """The derived row id doing its job. A random id would leave two rows and
    `membership_role` would answer with whichever came back first -- a demotion
    that silently did not take."""
    await append(
        runner,
        created(),
        MemberAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            subject=ALICE,
            role="admin",
        ),
        MemberRoleChanged(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            subject=ALICE,
            role="member",
            previous_role="admin",
        ),
    )
    await runner.caught_up()
    assert await runner.tenants.membership_role(TENANT, ALICE) == "member"
    assert len(await runner.tenants.members(TENANT)) == 1


async def test_removing_a_member_removes_the_row(runner):
    """The row's absence is what makes "remove member" true rather than a lie:
    the checker asks for a role in the resource's tenant and gets nothing,
    whatever a stale cookie still says."""
    await append(
        runner,
        created(),
        MemberAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            subject=ALICE,
            role="admin",
        ),
        MemberRemoved(
            aggregate_id=tenant_aggregate_id(TENANT), tenant_id=TENANT, subject=ALICE
        ),
    )
    await runner.caught_up()
    assert await runner.tenants.membership_role(TENANT, ALICE) is None
    assert await runner.tenants.members(TENANT) == []


async def test_a_transfer_moves_the_owner_and_leaves_the_previous_one_an_admin(runner):
    """Two rows from one event. The old owner is not ejected: transferring is
    handing over the last word, and a transfer that locked the previous owner
    out would have no undo."""
    await append(
        runner,
        created(),
        MemberAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            subject=ALICE,
            role="owner",
        ),
        MemberAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            subject=BOB,
            role="admin",
        ),
        OwnershipTransferred(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            from_subject=ALICE,
            to_subject=BOB,
        ),
    )
    await runner.caught_up()
    assert await runner.tenants.membership_role(TENANT, BOB) == "owner"
    assert await runner.tenants.membership_role(TENANT, ALICE) == "admin"


async def test_a_project_grant_is_stored_and_revoked(runner):
    project_id = uuid4()
    await append(
        runner,
        created(),
        ProjectGrantAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            project_id=project_id,
            subject=ALICE,
            role="editor",
        ),
    )
    await runner.caught_up()
    assert await runner.tenants.project_grant_role(project_id, ALICE) == "editor"
    assert [row.subject for row in await runner.tenants.project_grants(project_id)] == [ALICE]

    await append(
        runner,
        ProjectGrantRevoked(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            project_id=project_id,
            subject=ALICE,
        ),
    )
    await runner.caught_up()
    assert await runner.tenants.project_grant_role(project_id, ALICE) is None


async def test_a_grant_on_one_project_says_nothing_about_another(runner):
    """The per-project share is per project. Would pass trivially if
    `ProjectGrantRow.row_id` keyed on the subject alone -- which is the shape a
    copy of `MembershipRow.row_id` would have."""
    granted, other = uuid4(), uuid4()
    await append(
        runner,
        created(),
        ProjectGrantAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            project_id=granted,
            subject=ALICE,
            role="owner",
        ),
    )
    await runner.caught_up()
    assert await runner.tenants.project_grant_role(granted, ALICE) == "owner"
    assert await runner.tenants.project_grant_role(other, ALICE) is None


async def test_an_invitation_is_stored_accepted_and_revoked(runner):
    invited = InvitationCreated(
        aggregate_id=tenant_aggregate_id(TENANT),
        tenant_id=TENANT,
        email="  New.Person@Example.COM ",
        role="member",
        token="t0ken",
        invited_by=ALICE,
    )
    second = InvitationCreated(
        aggregate_id=tenant_aggregate_id(TENANT),
        tenant_id=TENANT,
        email="other@example.com",
        role="guest",
        token="t0ken2",
        invited_by=ALICE,
    )
    await append(runner, created(), invited, second)
    await runner.caught_up()
    rows = {row.id: row for row in await runner.tenants.invitations(TENANT)}
    assert len(rows) == 2
    # Normalised on the way in, because an invitation is matched against an
    # email claim later and `New.Person@Example.COM` is a spelling a person
    # will actually type.
    assert rows[invited.event_id].email == "new.person@example.com"

    await append(
        runner,
        InvitationAccepted(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            invitation_id=invited.event_id,
            subject=BOB,
        ),
        InvitationRevoked(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            invitation_id=second.event_id,
        ),
    )
    await runner.caught_up()
    rows = {row.id: row for row in await runner.tenants.invitations(TENANT)}
    assert rows[invited.event_id].accepted_by == BOB
    assert rows[invited.event_id].accepted_at is not None
    assert rows[second.event_id].revoked_at is not None
    assert rows[second.event_id].accepted_at is None


async def test_an_acceptance_for_an_unknown_invitation_does_not_stop_the_projection(runner):
    """A projection that refuses one event stops following the log for every
    other tenant too, and the membership an acceptance also produces is carried
    by its own `MemberAdded`. So this is ignored, and the test is that the
    *next* event still lands."""
    await append(
        runner,
        created(),
        InvitationAccepted(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            invitation_id=uuid4(),
            subject=BOB,
        ),
        MemberAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            subject=BOB,
            role="member",
        ),
    )
    await runner.caught_up()
    assert await runner.tenants.membership_role(TENANT, BOB) == "member"
    assert await runner.failures() == []


async def test_rebuild_rederives_every_table_from_the_log(runner):
    """Safe because none of the four holds original information. All four go
    together because they share a checkpoint."""
    project_id = uuid4()
    await append(
        runner,
        created(),
        MemberAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            subject=ALICE,
            role="admin",
        ),
        ProjectGrantAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            project_id=project_id,
            subject=BOB,
            role="viewer",
        ),
        InvitationCreated(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            email="x@example.com",
            role="member",
            token="tok",
        ),
    )
    await runner.caught_up()
    await runner.tenants.truncate()
    assert await runner.tenants.membership_role(TENANT, ALICE) is None

    await runner.rebuild()

    assert await runner.tenants.tenant(TENANT) is not None
    assert await runner.tenants.membership_role(TENANT, ALICE) == "admin"
    assert await runner.tenants.project_grant_role(project_id, BOB) == "viewer"
    assert len(await runner.tenants.invitations(TENANT)) == 1


async def test_reading_before_start_says_so_rather_than_answering_nothing(
    db_path, store, publisher
):
    """An unstarted runner must raise, not answer `None`. `None` from an
    unwired projection is indistinguishable from "this person has no role",
    which is a refusal nobody can trace to its cause."""
    unstarted = TenantRunner(store, db_path, publisher)
    with pytest.raises(RuntimeError):
        _ = unstarted.tenants
