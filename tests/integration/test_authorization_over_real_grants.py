"""The real writer and the real checker, over one database.

CLAUDE.md: "A port with one adapter and no test between them is two things that
were never checked against each other." `Authorizer` is exactly that shape --
one port, one production implementation -- and the co-mention channel is the
worked example of how it fails: a projection tested against literal frozensets,
an adapter tested against nothing, and a channel that produced nothing from the
day it merged while every piece passed its own tests.

So nothing here is stubbed. Real events go into a real `SQLiteEventStore`, the
real `TenantProjection` writes the real tables, and `RoleTableAuthorizer` reads
them through the real `TenantStore`. The question being asked is the one neither
half can ask alone: **does the thing that writes a grant produce what the thing
that reads one expects?**

Its counterpart in `tests/application/test_authorization_matrix.py` asserts the
matrix over a dict. This file asserts that the matrix is being fed.
"""

from uuid import uuid4

import pytest

from research_team.application.authorization import (
    PermissiveAuthorizer,
    Resource,
    RoleTableAuthorizer,
    Subject,
)
from research_team.domain.tenant import (
    LOCAL_SUBJECT,
    LOCAL_TENANT,
    MemberAdded,
    MemberRemoved,
    ProjectGrantAdded,
    ProjectGrantRevoked,
    TenantCreated,
    tenant_aggregate_id,
)
from research_team.infrastructure.persistence.tenants import TenantRunner

TENANT = "org-42"
OTHER_TENANT = "org-99"
ALICE = "sub-alice"
BOB = "sub-bob"


@pytest.fixture
async def runner(db_path, store, publisher):
    started = TenantRunner(store, db_path, publisher)
    await started.start()
    yield started
    await started.stop()


@pytest.fixture
def grant(runner):
    """Append tenancy events the way the sharing API (B4) will, then wait.

    Deliberately *not* a fixture that writes rows directly. A fixture that
    seeded `MembershipRow`s would supply the very step the projection is
    responsible for, and this test could then not see the projection go missing
    -- which is the fixture blind spot CLAUDE.md's entity-definitions entry
    describes, one level up. Proven by removing the `MemberAdded` handler:
    eight tests across this file and the read-model file went red.
    """

    async def write(*events):
        await runner.record(*events)
        await runner.caught_up()

    return write


def checker(runner, admins=frozenset()):
    return RoleTableAuthorizer(runner.tenants, admins)


async def test_a_membership_written_as_an_event_unlocks_the_project_it_should(runner, grant):
    """The whole point of the file, in one test: grant a tenant `admin` role
    through the event the sharing API will append, and assert that a project
    permission the checker answers is actually unlocked by it.

    Red without the projection: with `TenantProjection`'s `MemberAdded` handler
    removed, the event still applies (nothing subscribed rejects it), the store
    answers `None`, and this assertion fails. That is the assertion CLAUDE.md
    demands -- that the *data* is there, not that nothing threw.
    """
    project_id = uuid4()
    resource = Resource.project(project_id, TENANT)
    before = checker(runner)
    assert await before.check(Subject(ALICE), "project.read", resource) is False

    await grant(
        TenantCreated(aggregate_id=tenant_aggregate_id(TENANT), tenant_id=TENANT, name="Acme"),
        MemberAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            subject=ALICE,
            role="admin",
        ),
    )

    after = checker(runner)
    assert await after.check(Subject(ALICE), "project.read", resource) is True
    assert await after.check(Subject(ALICE), "project.admin", resource) is True


async def test_a_per_project_share_unlocks_one_project_and_not_the_others(runner, grant):
    """A `guest` reaches a project only through a grant, and only that one."""
    shared, private = uuid4(), uuid4()
    await grant(
        TenantCreated(aggregate_id=tenant_aggregate_id(TENANT), tenant_id=TENANT, name="Acme"),
        MemberAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            subject=BOB,
            role="guest",
        ),
        ProjectGrantAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            project_id=shared,
            subject=BOB,
            role="editor",
        ),
    )
    check = checker(runner)
    assert await check.check(Subject(BOB), "project.write", Resource.project(shared, TENANT))
    assert (
        await check.check(Subject(BOB), "project.read", Resource.project(private, TENANT))
        is False
    )


async def test_revoking_a_grant_takes_the_access_away_immediately(runner, grant):
    """The direction that is easy to leave untested and is the one that matters
    for "remove member" being true rather than a lie."""
    project_id = uuid4()
    resource = Resource.project(project_id, TENANT)
    await grant(
        TenantCreated(aggregate_id=tenant_aggregate_id(TENANT), tenant_id=TENANT, name="Acme"),
        ProjectGrantAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            project_id=project_id,
            subject=BOB,
            role="owner",
        ),
    )
    assert await checker(runner).check(Subject(BOB), "project.admin", resource) is True

    await grant(
        ProjectGrantRevoked(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            project_id=project_id,
            subject=BOB,
        )
    )
    assert await checker(runner).check(Subject(BOB), "project.read", resource) is False


async def test_removing_a_member_takes_their_implied_project_access_away(runner, grant):
    """An `admin`'s reach over every project in the tenant is implied by a row,
    so removing the row has to remove the reach. If the implication were cached
    anywhere, this is where it would show."""
    project_id = uuid4()
    resource = Resource.project(project_id, TENANT)
    await grant(
        TenantCreated(aggregate_id=tenant_aggregate_id(TENANT), tenant_id=TENANT, name="Acme"),
        MemberAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            subject=ALICE,
            role="admin",
        ),
    )
    assert await checker(runner).check(Subject(ALICE), "project.read", resource) is True

    await grant(
        MemberRemoved(
            aggregate_id=tenant_aggregate_id(TENANT), tenant_id=TENANT, subject=ALICE
        )
    )
    assert await checker(runner).check(Subject(ALICE), "project.read", resource) is False


async def test_a_role_in_one_tenant_reaches_nothing_in_another(runner, grant):
    """The check resolves the tenant of the *resource*. An owner of `org-42`
    asking about a project in `org-99` is refused, whatever their cookie's
    active tenant says -- which is why `Principal` exposes only `subject`."""
    await grant(
        TenantCreated(aggregate_id=tenant_aggregate_id(TENANT), tenant_id=TENANT, name="Acme"),
        MemberAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            subject=ALICE,
            role="owner",
        ),
    )
    check = checker(runner)
    project_id = uuid4()
    assert await check.check(
        Subject(ALICE), "project.read", Resource.project(project_id, TENANT)
    )
    assert (
        await check.check(
            Subject(ALICE), "project.read", Resource.project(project_id, OTHER_TENANT)
        )
        is False
    )


async def test_the_local_constants_resolve_like_any_other_tenant(runner, grant):
    """`LOCAL_TENANT` is a real tenant with a real row, not a special case in
    the checker. Anything that special-cased the string would pass every other
    test in this file and fail here."""
    project_id = uuid4()
    await grant(
        TenantCreated(
            aggregate_id=tenant_aggregate_id(LOCAL_TENANT),
            tenant_id=LOCAL_TENANT,
            name="This installation",
            kind="personal",
            created_by=LOCAL_SUBJECT,
        ),
        MemberAdded(
            aggregate_id=tenant_aggregate_id(LOCAL_TENANT),
            tenant_id=LOCAL_TENANT,
            subject=LOCAL_SUBJECT,
            role="owner",
        ),
    )
    check = checker(runner)
    assert await check.check(
        Subject(LOCAL_SUBJECT), "project.admin", Resource.project(project_id, LOCAL_TENANT)
    )
    assert (
        await check.check(
            Subject("somebody-else"),
            "project.read",
            Resource.project(project_id, LOCAL_TENANT),
        )
        is False
    )


async def test_the_permissive_adapter_answers_where_the_role_table_refuses(runner):
    """The `AGENT_AUTH=off` path, over the same empty database.

    Both adapters run the same resolution path; only the final bool differs.
    That equivalence is what makes the permissive adapter a real authorizer
    rather than a skipped dependency, and this is where the two are compared
    over one store rather than asserted about separately.
    """
    resource = Resource.project(uuid4(), TENANT)
    assert await checker(runner).check(Subject(ALICE), "project.admin", resource) is False
    assert (
        await PermissiveAuthorizer().check(Subject(ALICE), "project.admin", resource) is True
    )


async def test_a_rebuild_restores_every_answer_the_checker_was_giving(runner, grant):
    """`/rebuild` re-derives the tables from the log, so it has to re-derive the
    permissions too. Measured rather than assumed: the checker is asked the same
    three questions before and after, and the answers must match."""
    shared = uuid4()
    await grant(
        TenantCreated(aggregate_id=tenant_aggregate_id(TENANT), tenant_id=TENANT, name="Acme"),
        MemberAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            subject=ALICE,
            role="member",
        ),
        ProjectGrantAdded(
            aggregate_id=tenant_aggregate_id(TENANT),
            tenant_id=TENANT,
            project_id=shared,
            subject=ALICE,
            role="runner",
        ),
    )
    questions = [
        ("project.run", Resource.project(shared, TENANT)),
        ("project.write", Resource.project(shared, TENANT)),
        ("project.create", Resource.tenant(TENANT)),
    ]
    before = [await checker(runner).check(Subject(ALICE), p, r) for p, r in questions]
    assert before == [True, False, True]

    await runner.rebuild()

    after = [await checker(runner).check(Subject(ALICE), p, r) for p, r in questions]
    assert after == before
