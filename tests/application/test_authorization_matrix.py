"""The permission matrix, asserted over its whole cross-product.

CLAUDE.md: "when a test's inputs and the formula's branches are chosen by the
same person in the same hour, the test tends to sample the cases the formula
already handles." A permission matrix is the worst case of that -- the obvious
test is four allows, one per role, over the permission each role was invented
for, and it passes against a checker that returns `True` unconditionally.

So every test here that judges an allow is **parametrised over the full
(role x permission) product** and asserts the denial as loudly as the grant.
`test_the_matrix_is_exactly_this_table` is the one that would fail if somebody
widened a role by a single verb, and it is written as a literal table rather
than derived from `PROJECT_ROLE_PERMISSIONS`, because a test that derives its
expectation from the thing under test asserts only that a dict equals itself.
"""

from uuid import uuid4

import pytest

from research_team.application.authorization import (
    PERMISSIONS,
    PROJECT_ROLE_ORDER,
    TENANT_ROLE_ORDER,
    DenyAllAuthorizer,
    PermissiveAuthorizer,
    Resource,
    RoleTableAuthorizer,
    Subject,
    stronger_project_role,
)

TENANT = "org-42"
PROJECT = uuid4()
ALICE = "sub-alice"


class FakeGrants:
    """A `GrantReader` over two dicts.

    Deliberately not the real store: this file is about the *table*, and a
    SQLite round trip per parametrised case would make 200 cases slow without
    testing anything the table is responsible for. The question of whether the
    real writer and the real checker meet is a different question, asked by
    `tests/integration/test_authorization_over_real_grants.py`, because a stub
    on one side and a unit test on the other prove the two halves work and
    cannot prove they meet (CLAUDE.md, "A port with one adapter...").
    """

    def __init__(self, memberships=None, grants=None):
        self.memberships = memberships or {}
        self.grants = grants or {}

    async def membership_role(self, tenant_id: str, subject: str) -> str | None:
        return self.memberships.get((tenant_id, subject))

    async def project_grant_role(self, project_id: str, subject: str) -> str | None:
        return self.grants.get((str(project_id), subject))


def authorizer(memberships=None, grants=None, admins=frozenset()):
    return RoleTableAuthorizer(FakeGrants(memberships, grants), admins)


# --- The table itself ------------------------------------------------------

PROJECT_MATRIX: dict[str, frozenset[str]] = {
    "viewer": frozenset({"project.read"}),
    "runner": frozenset({"project.read", "project.run"}),
    "editor": frozenset({"project.read", "project.write", "project.run"}),
    "owner": frozenset({"project.read", "project.write", "project.run", "project.admin"}),
}

TENANT_MATRIX: dict[str, frozenset[str]] = {
    "guest": frozenset({"tenant.read"}),
    "member": frozenset({"tenant.read", "project.create"}),
    "admin": frozenset({"tenant.read", "tenant.admin", "project.create"}),
    "owner": frozenset({"tenant.read", "tenant.admin", "tenant.own", "project.create"}),
}

PROJECT_PERMISSIONS = sorted(
    p for p in PERMISSIONS if p.startswith("project.") and p != "project.create"
)
TENANT_PERMISSIONS = sorted(
    p for p in PERMISSIONS if p.startswith("tenant.") or p == "project.create"
)


@pytest.mark.parametrize("role", PROJECT_ROLE_ORDER)
@pytest.mark.parametrize("permission", PROJECT_PERMISSIONS)
async def test_a_project_grant_allows_exactly_its_row_of_the_matrix(role, permission):
    """Every cell, allow and deny. The denials are the half that matters:
    an authorizer that answered `True` unconditionally would pass a test that
    only checked the allows, and so would one that ignored the role."""
    check = authorizer(grants={(str(PROJECT), ALICE): role})
    expected = permission in PROJECT_MATRIX[role]
    assert (
        await check.check(Subject(ALICE), permission, Resource.project(PROJECT, TENANT))
        is expected
    )


@pytest.mark.parametrize("role", TENANT_ROLE_ORDER)
@pytest.mark.parametrize("permission", TENANT_PERMISSIONS)
async def test_a_tenant_membership_allows_exactly_its_row_of_the_matrix(role, permission):
    check = authorizer(memberships={(TENANT, ALICE): role})
    expected = permission in TENANT_MATRIX[role]
    assert await check.check(Subject(ALICE), permission, Resource.tenant(TENANT)) is expected


@pytest.mark.parametrize("role", PROJECT_ROLE_ORDER)
def test_the_project_matrix_is_exactly_this_table(role):
    """Written out by hand rather than derived from the module under test.

    Deriving the expectation from `PROJECT_ROLE_PERMISSIONS` would assert that a
    dict equals itself, and would go green on any widening of any role.
    """
    from research_team.application.authorization import PROJECT_ROLE_PERMISSIONS

    assert PROJECT_ROLE_PERMISSIONS[role] == PROJECT_MATRIX[role]


@pytest.mark.parametrize("role", TENANT_ROLE_ORDER)
def test_the_tenant_matrix_is_exactly_this_table(role):
    from research_team.application.authorization import TENANT_ROLE_PERMISSIONS

    assert TENANT_ROLE_PERMISSIONS[role] == TENANT_MATRIX[role]


# --- The two calls the design says not to soften ---------------------------


@pytest.mark.parametrize("permission", PROJECT_PERMISSIONS)
@pytest.mark.parametrize("role", ["member", "guest"])
async def test_a_tenant_member_reaches_nothing_in_another_members_project(role, permission):
    """The non-obvious call, and the one a future reader is most likely to
    "fix": belonging to an organisation grants **no** implicit access to the
    projects inside it.

    Parametrised over every project permission including `project.read`, which
    is the one somebody would relax first. If this test starts failing because
    a `member` gained implicit read, that is a product decision and it needs the
    argument in `TENANT_ROLE_IMPLIES_PROJECT_ROLE` answered, not deleted.
    """
    check = authorizer(memberships={(TENANT, ALICE): role})
    assert (
        await check.check(Subject(ALICE), permission, Resource.project(PROJECT, TENANT))
        is False
    )


@pytest.mark.parametrize("role", ["admin", "owner"])
@pytest.mark.parametrize("permission", PROJECT_PERMISSIONS)
async def test_a_tenant_admin_is_implicitly_owner_of_every_project_in_it(role, permission):
    """An organisation needs somebody who can reach a project whose creator
    left, so `admin` and `owner` are implicit project `owner`s -- all four
    project permissions, with no grant row at all."""
    check = authorizer(memberships={(TENANT, ALICE): role})
    assert (
        await check.check(Subject(ALICE), permission, Resource.project(PROJECT, TENANT))
        is True
    )


async def test_a_tenant_admin_of_another_tenant_reaches_nothing():
    """The implication is scoped to the tenant the *resource* belongs to.

    Would pass trivially if the checker looked the membership up by the
    principal's own active tenant, which is the mistake `Principal` is narrowed
    to one attribute to make unavailable.
    """
    check = authorizer(memberships={("some-other-org", ALICE): "owner"})
    assert (
        await check.check(Subject(ALICE), "project.read", Resource.project(PROJECT, TENANT))
        is False
    )


async def test_a_viewer_cannot_start_a_run_that_spends_the_tenants_money():
    """`project.run` split from `project.write` is the other call not to
    soften. A viewer starting a course-authoring run spends somebody else's
    model budget through a route whose name reads like an ordinary write."""
    check = authorizer(grants={(str(PROJECT), ALICE): "viewer"})
    assert (
        await check.check(Subject(ALICE), "project.run", Resource.project(PROJECT, TENANT))
        is False
    )


async def test_a_runner_may_spend_but_not_edit():
    """The role that makes the split usable. If `runner` gained `project.write`
    the split would have no user and would be deleted at the next tidy-up."""
    check = authorizer(grants={(str(PROJECT), ALICE): "runner"})
    resource = Resource.project(PROJECT, TENANT)
    assert await check.check(Subject(ALICE), "project.run", resource) is True
    assert await check.check(Subject(ALICE), "project.write", resource) is False


# --- Resolution between the two ladders ------------------------------------


@pytest.mark.parametrize("grant", PROJECT_ROLE_ORDER)
@pytest.mark.parametrize("membership", TENANT_ROLE_ORDER)
@pytest.mark.parametrize("permission", PROJECT_PERMISSIONS)
async def test_the_effective_role_is_the_stronger_of_grant_and_implication(
    grant, membership, permission
):
    """The whole 4 x 4 x 4 product of the `max(grant, implied)` rule.

    This is the case a hand-picked test misses: a tenant `admin` who *also*
    holds an explicit `viewer` grant on one project must not be narrowed to
    viewer by it. A checker written as "the grant wins if there is one" passes
    every single-source test above and fails here.
    """
    check = authorizer(
        memberships={(TENANT, ALICE): membership},
        grants={(str(PROJECT), ALICE): grant},
    )
    implied = "owner" if membership in ("admin", "owner") else None
    effective = stronger_project_role(grant, implied)
    expected = permission in PROJECT_MATRIX[effective]
    assert (
        await check.check(Subject(ALICE), permission, Resource.project(PROJECT, TENANT))
        is expected
    )


@pytest.mark.parametrize(
    "permission,project_permission",
    [("session.read", "project.read"), ("session.write", "project.run")],
)
@pytest.mark.parametrize("role", PROJECT_ROLE_ORDER)
async def test_a_session_permission_resolves_against_its_projects_role(
    permission, project_permission, role
):
    """A session belongs to exactly one project, so its permissions are the
    project's. `session.write` maps to `project.run`, not `project.write`: a
    turn calls a model."""
    check = authorizer(grants={(str(PROJECT), ALICE): role})
    expected = project_permission in PROJECT_MATRIX[role]
    assert (
        await check.check(Subject(ALICE), permission, Resource.project(PROJECT, TENANT))
        is expected
    )


async def test_session_write_is_not_merely_project_write_renamed():
    """The distinguishing case, chosen because it is the one that separates the
    two candidate mappings rather than the one that reads most naturally.

    An `editor` holds both `project.write` and `project.run`, so it cannot tell
    the mappings apart. A `runner` holds only `run`, and a `viewer` neither --
    those two are the whole of the evidence.
    """
    resource = Resource.project(PROJECT, TENANT)
    runner = authorizer(grants={(str(PROJECT), ALICE): "runner"})
    viewer = authorizer(grants={(str(PROJECT), ALICE): "viewer"})
    assert await runner.check(Subject(ALICE), "session.write", resource) is True
    assert await viewer.check(Subject(ALICE), "session.write", resource) is False


# --- instance.admin --------------------------------------------------------


async def test_instance_admin_is_a_named_subject_and_not_any_tenant_role():
    """`/api/corpus/rebuild` acts across every tenant, so a tenant `owner`
    holding it would be rebuilding everyone's corpus."""
    check = authorizer(memberships={(TENANT, ALICE): "owner"}, admins=frozenset())
    assert await check.check(Subject(ALICE), "instance.admin", Resource.instance()) is False

    named = authorizer(admins=frozenset({ALICE}))
    assert await named.check(Subject(ALICE), "instance.admin", Resource.instance()) is True


@pytest.mark.parametrize("permission", sorted(PERMISSIONS - {"instance.admin"}))
async def test_no_other_permission_is_answerable_about_the_installation(permission):
    """The instance is not a tenant and holds no roles, so every other verb
    asked of it is a caller error and refused."""
    check = authorizer(memberships={(TENANT, ALICE): "owner"}, admins=frozenset({ALICE}))
    assert await check.check(Subject(ALICE), permission, Resource.instance()) is False


async def test_project_create_is_asked_of_a_tenant_and_refused_of_a_project():
    """A project that does not exist has no roles, so the question is asked of
    the tenant it would be created in. Refusing it of a project keeps the answer
    from depending on which resource a caller happened to pass."""
    check = authorizer(memberships={(TENANT, ALICE): "owner"})
    assert await check.check(Subject(ALICE), "project.create", Resource.tenant(TENANT)) is True
    assert (
        await check.check(Subject(ALICE), "project.create", Resource.project(PROJECT, TENANT))
        is False
    )


# --- Default-deny ----------------------------------------------------------


@pytest.mark.parametrize(
    "case,principal,permission,resource",
    [
        ("no subject", Subject(""), "project.read", Resource.project(PROJECT, TENANT)),
        (
            "unknown permission",
            Subject(ALICE),
            "project.raed",
            Resource.project(PROJECT, TENANT),
        ),
        (
            "unresolved tenant",
            Subject(ALICE),
            "project.read",
            Resource(object_type="project", object_id=str(PROJECT), tenant_id=None),
        ),
    ],
)
async def test_the_checker_refuses_every_input_it_does_not_understand(
    case, principal, permission, resource
):
    """Default-deny, following `FetchGrant.covers()`: a check that raises on
    malformed input ends the request with a 500, and a 500 is a refusal nobody
    can distinguish from a bug. Return "no" and let the route say so.

    The owner membership is present in every case, so none of these passes by
    the subject simply having no access -- each one is refused by the guard it
    names.
    """
    check = authorizer(
        memberships={(TENANT, ALICE): "owner", (TENANT, ""): "owner"},
        grants={(str(PROJECT), ALICE): "owner", (str(PROJECT), ""): "owner"},
    )
    assert await check.check(principal, permission, resource) is False


async def test_a_role_string_this_build_does_not_know_grants_nothing():
    """A role written by a newer build, or a typo in a hand-edited row.
    Neither is something to resolve leniently."""
    check = authorizer(
        memberships={(TENANT, ALICE): "superadmin"},
        grants={(str(PROJECT), ALICE): "editor-in-chief"},
    )
    assert (
        await check.check(Subject(ALICE), "project.read", Resource.project(PROJECT, TENANT))
        is False
    )
    assert await check.check(Subject(ALICE), "tenant.read", Resource.tenant(TENANT)) is False


@pytest.mark.parametrize("permission", sorted(PERMISSIONS))
async def test_a_subject_with_no_rows_anywhere_is_refused_everything(permission):
    check = authorizer()
    for resource in (
        Resource.project(PROJECT, TENANT),
        Resource.tenant(TENANT),
        Resource.instance(),
    ):
        assert await check.check(Subject(ALICE), permission, resource) is False


# --- The two trivial adapters ----------------------------------------------


@pytest.mark.parametrize("permission", sorted(PERMISSIONS))
async def test_the_permissive_authorizer_allows_everything(permission):
    """What `AGENT_AUTH=off` selects. It is a real authorizer rather than a
    skipped dependency so that every existing route test keeps exercising the
    real resolution path -- see the class docstring for the silent-default trap
    this avoids."""
    check = PermissiveAuthorizer()
    assert await check.check(Subject(""), permission, Resource.instance()) is True


@pytest.mark.parametrize("permission", sorted(PERMISSIONS))
async def test_the_deny_all_authorizer_refuses_everything(permission):
    """Not wired anywhere. It exists so a later slice can prove a route's check
    is *reached*, which an assertion under `PermissiveAuthorizer` cannot."""
    check = DenyAllAuthorizer()
    assert await check.check(Subject(ALICE), permission, Resource.instance()) is False
