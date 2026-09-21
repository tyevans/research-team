"""Tests for authorization scoping, lifecycle-aware checks, and batching."""

from uuid import uuid4

from research_team.tenancy.application.authorization import (
    DenyAllAuthorizer,
    PermissiveAuthorizer,
    Resource,
    RoleTableAuthorizer,
    Subject,
    has_project_role,
    has_tenant_role,
)

TENANT = "org-1"
ALICE = "sub-alice"
PROJECT = uuid4()


class FakeGrants:
    def __init__(self, memberships=None, grants=None):
        self.memberships = memberships or {}
        self.grants = grants or {}

    async def membership_role(self, tenant_id: str, subject: str) -> str | None:
        return self.memberships.get((tenant_id, subject))

    async def project_grant_role(self, project_id: str, subject: str) -> str | None:
        return self.grants.get((str(project_id), subject))


def test_role_ladder_hierarchy_helpers():
    assert has_project_role("owner", "viewer") is True
    assert has_project_role("owner", "runner") is True
    assert has_project_role("owner", "editor") is True
    assert has_project_role("owner", "owner") is True

    assert has_project_role("editor", "runner") is True
    assert has_project_role("editor", "owner") is False
    assert has_project_role("runner", "editor") is False
    assert has_project_role("viewer", "runner") is False
    assert has_project_role("unknown", "viewer") is False
    assert has_project_role(None, "viewer") is False

    assert has_tenant_role("owner", "guest") is True
    assert has_tenant_role("owner", "admin") is True
    assert has_tenant_role("admin", "member") is True
    assert has_tenant_role("member", "admin") is False
    assert has_tenant_role("guest", "member") is False
    assert has_tenant_role("unknown", "guest") is False
    assert has_tenant_role(None, "guest") is False


async def test_archived_project_is_read_only():
    """An archived project allows reads but refuses writes and runs even for owners."""
    authorizer = RoleTableAuthorizer(
        FakeGrants(
            memberships={(TENANT, ALICE): "member"},
            grants={(str(PROJECT), ALICE): "owner"},
        )
    )

    archived_res = Resource.project(PROJECT, TENANT, status="archived")
    active_res = Resource.project(PROJECT, TENANT, status="active")

    principal = Subject(ALICE)

    # In active project, owner has write, run, read
    assert await authorizer.check(principal, "project.read", active_res) is True
    assert await authorizer.check(principal, "project.write", active_res) is True
    assert await authorizer.check(principal, "project.run", active_res) is True
    assert await authorizer.check(principal, "session.read", active_res) is True
    assert await authorizer.check(principal, "session.write", active_res) is True

    # In archived project, owner still has read, but write/run are frozen
    assert await authorizer.check(principal, "project.read", archived_res) is True
    assert await authorizer.check(principal, "session.read", archived_res) is True
    assert await authorizer.check(principal, "project.write", archived_res) is False
    assert await authorizer.check(principal, "project.run", archived_res) is False
    assert await authorizer.check(principal, "session.write", archived_res) is False


async def test_check_all_evaluates_in_order():
    authorizer = RoleTableAuthorizer(
        FakeGrants(
            memberships={(TENANT, ALICE): "member"},
            grants={(str(PROJECT), ALICE): "editor"},
        )
    )
    res = Resource.project(PROJECT, TENANT)
    principal = Subject(ALICE)

    checks = [
        ("project.read", res),
        ("project.write", res),
        ("project.admin", res),  # editor lacks admin
    ]

    results = await authorizer.check_all(principal, checks)
    assert results == [True, True, False]

    # Permissive and deny all
    permissive = PermissiveAuthorizer()
    assert await permissive.check_all(principal, checks) == [True, True, True]

    deny_all = DenyAllAuthorizer()
    assert await deny_all.check_all(principal, checks) == [False, False, False]


async def test_filter_resources():
    p1, p2, p3 = uuid4(), uuid4(), uuid4()
    authorizer = RoleTableAuthorizer(
        FakeGrants(
            memberships={(TENANT, ALICE): "member"},
            grants={
                (str(p1), ALICE): "editor",
                (str(p2), ALICE): "viewer",
                # p3 has no grant
            },
        )
    )
    resources = [
        Resource.project(p1, TENANT),
        Resource.project(p2, TENANT),
        Resource.project(p3, TENANT),
    ]
    principal = Subject(ALICE)

    # Filtering for read: p1 and p2 have read, p3 does not
    can_read = await authorizer.filter_resources(principal, "project.read", resources)
    assert can_read == [resources[0], resources[1]]

    # Filtering for write: only p1 has write
    can_write = await authorizer.filter_resources(principal, "project.write", resources)
    assert can_write == [resources[0]]

    # Permissive and deny all
    permissive = PermissiveAuthorizer()
    assert await permissive.filter_resources(principal, "project.read", resources) == resources

    deny_all = DenyAllAuthorizer()
    assert await deny_all.filter_resources(principal, "project.read", resources) == []
