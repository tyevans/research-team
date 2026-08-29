"""Who may do what, to which resource.

The whole of this project's authorization model: two role ladders, one
permission matrix, and a port with two adapters. Read
`docs/design/tenancy-and-authorization.md` sections 3, 4 and 6 for the argument;
this module is the argument's result, and the parts of it that are decisions
rather than mechanism are marked as such below.

**A role table, not a tuple store.** Zanzibar-shaped machinery -- a schema
language, a rewrite-rule evaluator, a check API and a cache with an
invalidation story -- earns its complexity on nested objects of arbitrary
depth, on groups within groups, on reverse indexes at scale, or on several
services that must agree. This project has none of the four: the object graph is
tenant -> project -> session, depth two and fixed at compile time; there are no
groups; the readers of a project are two indexed `SELECT`s; and it is one
process over one SQLite file with an in-process lock.

**The grant *shape* is kept anyway.** Every grant is stored as
`(subject, relation, object_type, object_id)` -- `MembershipRow` is
`(subject, role, "tenant", tenant_id)` and `ProjectGrantRow` is the same over
`project`. Nothing in this module reads a grant any other way, and `Resource`
below is that tuple's right-hand half. The point is that reversing the decision
is a new `Authorizer` adapter over the same rows, not a data migration and not
118 route edits. If teams-within-a-tenant, or sharing below a project, or a
second process reading these permissions ever lands, that is the moment to
revisit -- and those three, written down, are what turn the reversal into a
decision rather than a drift.
"""

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from research_team.domain.tenant import ProjectRole, TenantRole

Permission = Literal[
    "project.read",
    "project.write",
    "project.run",
    "project.admin",
    "project.create",
    "session.read",
    "session.write",
    "tenant.read",
    "tenant.admin",
    "tenant.own",
    "instance.admin",
]

PERMISSIONS: frozenset[str] = frozenset(
    (
        "project.read",
        "project.write",
        "project.run",
        "project.admin",
        "project.create",
        "session.read",
        "session.write",
        "tenant.read",
        "tenant.admin",
        "tenant.own",
        "instance.admin",
    )
)
"""Every permission a route may name, as data.

The verbs were derived from the 118 routes in `app.py`, not invented. A string
outside this set is not an unknown permission to be resolved leniently -- it is
a typo, and `RoleTableAuthorizer` refuses it (see `check`).
"""

ObjectType = Literal["tenant", "project", "instance"]


@dataclass(frozen=True)
class Resource:
    """What a permission is being asked about: the right-hand half of a grant
    tuple, plus the one edge a check has to walk.

    `tenant_id` on a project resource is the tenant that project belongs to,
    resolved by the caller before the port is asked. That resolution is a read
    of `ProjectRow` (B2) or of `SessionSummaryRow` then `ProjectRow`, and it
    lives in the `Requires` dependency (B3) rather than here for a plain
    reason: an `Authorizer` that did its own lookups would need a handle on
    every read model in the tree, and the port would stop being swappable.

    Frozen, because a resource is what the request named. Nothing downstream
    of the resolution should be able to rewrite which object is being checked.
    """

    object_type: ObjectType
    object_id: str
    tenant_id: str | None = None
    """The tenant that owns `object_id`. Equal to `object_id` for a tenant
    resource; `None` for the instance, which belongs to no tenant."""

    @classmethod
    def tenant(cls, organisation_id: str) -> "Resource":
        """The parameter is `organisation_id`, not `tenant_id`, on purpose.

        `tenant_id=tenant_id` is the spelling `tests/test_tenant_naming_seam.py`
        forbids, because at a call site written that way there is no way to tell
        redstring's project-shaped `tenant_id` from this one. Naming the
        parameter differently means the forbidden spelling cannot be written
        here even by accident, and the field it fills keeps the name the design
        chose.
        """
        return cls(object_type="tenant", object_id=organisation_id, tenant_id=organisation_id)

    @classmethod
    def project(cls, project_id: UUID | str, organisation_id: str) -> "Resource":
        """`organisation_id` for `tenant`'s reason. Note that this is the one
        signature in the tree that takes both concepts at once, which is exactly
        why neither may be spelled ambiguously."""
        return cls(object_type="project", object_id=str(project_id), tenant_id=organisation_id)

    @classmethod
    def instance(cls) -> "Resource":
        """The whole installation: `/api/summaries/rebuild`, `/api/corpus/rebuild`,
        `/api/workers`.

        Not a tenant role, and that is deliberate. Those routes act across every
        tenant, so a tenant `owner` rebuilding the corpus would be rebuilding
        everyone's -- calling that a tenant permission would be a lie the matrix
        told. See `RoleTableAuthorizer.admin_subjects`.
        """
        return cls(object_type="instance", object_id="")


@runtime_checkable
class Principal(Protocol):
    """Whoever is asking. Structural, and deliberately one attribute wide.

    A `Protocol` rather than an import of W-A's `Principal` because this module
    must not depend on the identity workstream's branch to be reviewable or
    testable -- and because the only thing an authorization decision may read
    off a principal is the subject.

    In particular it must **not** read the active tenant from the cookie.
    That value scopes *listing* -- which projects appear in the sidebar -- and
    nothing else. Every check resolves the tenant of the *resource* and asks
    whether this subject has a role in it, because a cookie is a thing the
    holder controls the lifetime of: if a stale `tid` could grant access, a
    person removed from an organisation would keep it until their cookie
    expired, which is what would make "remove member" a lie. Narrowing the
    protocol to `subject` is what makes that mistake unavailable rather than
    merely discouraged.
    """

    @property
    def subject(self) -> str: ...


@dataclass(frozen=True)
class Subject:
    """A bare principal, for callers that hold a subject and nothing else.

    Used by `composition.py` and by tests. Not a stand-in for W-A's richer
    principal -- it satisfies the same protocol, which is the point.
    """

    subject: str


# --- The matrix ------------------------------------------------------------
#
# Two ladders, declared as data so the tests can iterate the whole
# (role x permission) cross-product rather than the handful of cases whoever
# wrote the check happened to be thinking about. CLAUDE.md's warning about a
# test whose inputs and the code's branches are chosen by the same person in
# the same hour applies to a permission matrix with full force: a test that
# asserts the allows it was written beside proves nothing, and the denials are
# the half that matters.

PROJECT_ROLE_ORDER: tuple[ProjectRole, ...] = ("viewer", "runner", "editor", "owner")
"""Weakest first. `runner` sits above `viewer` and below `editor` because it
adds spend to read without adding edit; the ladder is nested, so taking the
stronger of two roles and taking the union of their permissions agree."""

TENANT_ROLE_ORDER: tuple[TenantRole, ...] = ("guest", "member", "admin", "owner")

PROJECT_ROLE_PERMISSIONS: dict[ProjectRole, frozenset[str]] = {
    "viewer": frozenset({"project.read"}),
    "runner": frozenset({"project.read", "project.run"}),
    "editor": frozenset({"project.read", "project.write", "project.run"}),
    "owner": frozenset({"project.read", "project.write", "project.run", "project.admin"}),
}
"""What each project role may do.

**`project.run` is split from `project.write`, and that is the one split that is
not obvious.** Extraction, authoring, ask and dialogue turns all call a model,
and the model credentials are the tenant's. A `viewer` who can start a
course-authoring run over a large topic spends somebody else's money, and does
it through a route whose name (`POST .../curriculum/author`) reads like an
ordinary write. Splitting the verb puts the spend in the matrix rather than in a
bill, and `runner` exists so the split is usable -- somebody who may run
extraction but not edit the corpus is a real role in a research group.

Do not fold `project.run` back into `project.write` to shorten this table.
"""

TENANT_ROLE_PERMISSIONS: dict[TenantRole, frozenset[str]] = {
    "guest": frozenset({"tenant.read"}),
    "member": frozenset({"tenant.read", "project.create"}),
    "admin": frozenset({"tenant.read", "tenant.admin", "project.create"}),
    "owner": frozenset({"tenant.read", "tenant.admin", "tenant.own", "project.create"}),
}
"""What each tenant role may do *to the tenant*.

`project.create` is on this table rather than the project one because a project
that does not exist has no roles: the permission is asked of the tenant the
project would be created in. `guest` is the role that cannot, which is the whole
of what distinguishes it from `member`.

`guest` holding `tenant.read` is deliberate and is narrower than it looks: the
design's matrix reads "member, guest (self only), admin, owner", and the "self
only" half is a *filter on the response* -- a guest listing members sees
themselves. A permission cannot express "this row but not that one", and
encoding it here as a denial would make a guest's own membership unreadable to
them. The filter belongs to the route (B4); this is the gate.
"""

TENANT_ROLE_IMPLIES_PROJECT_ROLE: dict[TenantRole, ProjectRole | None] = {
    "guest": None,
    "member": None,
    "admin": "owner",
    "owner": "owner",
}
"""What a tenant role grants on every project *in* that tenant.

**A `member` gets no implicit access to other members' projects.** This is the
non-obvious call and it is worth the argument, because the tempting default --
everyone in an organisation reads everything in it -- is what most small-team
tools do. It is wrong here because a project is not a document: it carries a
knowledge graph, a corpus of fetched sources, and model spend. A tenant that
grows past a handful of people gets a sidebar listing every project anyone ever
started, and the fix at that point is a permission change that takes access away
from people who had it, which is the change nobody wants to make. Starting
closed and adding a per-project "visible to the whole organisation" flag later
is the reversible direction; this is not.

`admin` *is* implicit `owner` on every project, because an organisation needs
somebody who can reach a project whose creator left.
"""

SESSION_PERMISSION_ALIASES: dict[str, str] = {
    "session.read": "project.read",
    "session.write": "project.run",
}
"""Session permissions resolve against the session's project.

A session belongs to exactly one project (`SessionStarted.project_id`,
required), so there is no session-level grant to hold and no third object level
to walk. `session.write` maps to `project.run` rather than to `project.write`
for `PROJECT_ROLE_PERMISSIONS`'s reason: a turn calls a model.

The alias is applied here rather than at the call site so that the mapping has
one spelling. `Requires("session.read")` hands this port a *project* resource
that the caller resolved; a session resource never reaches an authorizer.
"""


def permissions_for_project_role(role: ProjectRole | None) -> frozenset[str]:
    """What `role` may do, or nothing at all for `None`.

    Total on unknown input: a role string this build does not know is a role
    that was written by a newer build or by a typo, and neither is something to
    resolve leniently.
    """
    if role is None:
        return frozenset()
    return PROJECT_ROLE_PERMISSIONS.get(role, frozenset())


def permissions_for_tenant_role(role: TenantRole | None) -> frozenset[str]:
    """What `role` may do to its tenant, or nothing at all for `None`."""
    if role is None:
        return frozenset()
    return TENANT_ROLE_PERMISSIONS.get(role, frozenset())


def stronger_project_role(
    left: ProjectRole | None, right: ProjectRole | None
) -> ProjectRole | None:
    """The higher of two rungs, `None` being below every rung.

    This is the `max(role_of(grant), implied_role_of(member))` the design
    writes. It is a max over a ladder rather than a union over permission sets
    because the ladder is nested -- the two agree -- and because a max keeps the
    resolution expressible as one role, which is what a future tuple-backed
    adapter would have to reproduce.
    """
    ranked = [role for role in (left, right) if role in PROJECT_ROLE_ORDER]
    if not ranked:
        return None
    return max(ranked, key=PROJECT_ROLE_ORDER.index)


class GrantReader(Protocol):
    """The two indexed reads the checker needs, and nothing else.

    A `Protocol` so `RoleTableAuthorizer` can be exercised over a dict in a unit
    test *and* over the real projection-fed tables in the test that matters --
    CLAUDE.md's "a port with one adapter and no test between them is two things
    that were never checked against each other" is exactly this shape, and
    `tests/integration/test_authorization_over_real_grants.py` is the answer to
    it: it drives the real event writer and the real checker over one database.
    """

    async def membership_role(self, tenant_id: str, subject: str) -> str | None:
        """This subject's role in this tenant, or `None` if they have none."""
        ...

    async def project_grant_role(self, project_id: str, subject: str) -> str | None:
        """This subject's role on this project, or `None` if they have none."""
        ...


class Authorizer(Protocol):
    """May this principal do this to this resource?

    One question, one bool. The port every route depends on, so that swapping
    the role table for something else later is a new adapter and a wiring
    change rather than an edit to every route.
    """

    async def check(
        self, principal: Principal, permission: str, resource: Resource
    ) -> bool: ...


class PermissiveAuthorizer:
    """Yes, always. What `AGENT_AUTH=off` selects.

    **Off means a permissive authorizer, not an absent one**, and the
    distinction is the whole reason this class exists rather than a branch that
    skips the dependency. With the dependency registered only when auth is on,
    the several hundred existing route tests would exercise a code path that
    does not exist in production-with-auth-on, and the first time the real
    dependency ran against route 74 would be in somebody's browser. That is
    CLAUDE.md's silent-default trap in its exact form: "never wired" and
    "working" become indistinguishable to a test.

    With this adapter wired, every existing test runs the real resolution path
    -- path-parameter extraction, project lookup, port call -- and only the
    final bool differs. A single-user local install therefore behaves exactly as
    `main` does today, which is the property that makes this work mergeable
    beside the other workstreams in flight.
    """

    async def check(self, principal: Principal, permission: str, resource: Resource) -> bool:
        return True


class DenyAllAuthorizer:
    """No, always. Not wired anywhere, and that is deliberate.

    It exists so a test can prove that a route's check is *reached* -- an
    assertion that a request succeeds under `PermissiveAuthorizer` passes just
    as well when the check was never wired at all, which is the silent default
    this whole arrangement is arranged against. Swapping this in and expecting
    the refusal is what makes the wiring observable.
    """

    async def check(self, principal: Principal, permission: str, resource: Resource) -> bool:
        return False


class RoleTableAuthorizer:
    """The one production checker: two indexed reads and a table lookup.

    ```
    resolve(subject, project) ->
        grant  = project_grants[(project.id, subject)]
        member = memberships[(project.tenant_id, subject)]
        return max(role_of(grant), implied_role_of(member))
    ```

    **Default-deny on every input it does not understand**: unknown permission
    string, resource with no tenant, principal with no subject, role this build
    does not know. This follows `FetchGrant.covers()`, whose docstring makes the
    argument -- a check that raises on malformed input ends the request with a
    500, and a 500 is a refusal nobody can distinguish from a bug. Return "no"
    and let the route say so.
    """

    def __init__(self, grants: GrantReader, admin_subjects: frozenset[str] = frozenset()):
        self._grants = grants
        self._admin_subjects = admin_subjects

    @property
    def admin_subjects(self) -> frozenset[str]:
        """Who holds `instance.admin`, as a set of Zitadel subjects.

        A setting resolved at environment scope only (`AGENT_ADMIN_SUBJECTS`),
        never from inside a tenant, because a tenant that could name its own
        instance admins could rebuild every other tenant's corpus. Empty means
        nobody, which is the safe reading of an unset variable: with auth off
        the permissive adapter is what answers, so an empty set here never
        locks a local install out of its own rebuild routes.
        """
        return self._admin_subjects

    async def check(self, principal: Principal, permission: str, resource: Resource) -> bool:
        subject = getattr(principal, "subject", "")
        if not subject:
            return False
        if permission not in PERMISSIONS:
            # A permission outside the catalogue is a typo, not a new verb.
            # Resolving it leniently would make `Requires("project.raed")` a
            # route with no check that passes the coverage test.
            return False

        if permission == "instance.admin":
            # Not a role in any tenant. See `Resource.instance`.
            return subject in self._admin_subjects

        permission = SESSION_PERMISSION_ALIASES.get(permission, permission)

        if resource.object_type == "instance":
            # Only `instance.admin` is answerable about the installation, and
            # it returned above.
            return False

        tenant_id = resource.tenant_id
        if not tenant_id:
            # A project whose tenant could not be resolved. Under B2 every
            # project has one, so this is a project row that is missing or a
            # caller that forgot to resolve -- both of which are "no".
            return False

        member_role = _as_tenant_role(await self._grants.membership_role(tenant_id, subject))

        if resource.object_type == "tenant":
            return permission in permissions_for_tenant_role(member_role)

        # A project.
        granted = _as_project_role(
            await self._grants.project_grant_role(resource.object_id, subject)
        )
        implied = TENANT_ROLE_IMPLIES_PROJECT_ROLE.get(member_role) if member_role else None
        effective = stronger_project_role(granted, implied)
        if permission == "project.create":
            # Asked of a tenant, never of a project: creating a project inside
            # an existing one is not a thing this system has. Refusing here
            # rather than silently consulting the project ladder keeps the
            # answer from depending on which resource a caller happened to pass.
            return False
        return permission in permissions_for_project_role(effective)


def _as_project_role(value: str | None) -> ProjectRole | None:
    return value if value in PROJECT_ROLE_ORDER else None  # type: ignore[return-value]


def _as_tenant_role(value: str | None) -> TenantRole | None:
    return value if value in TENANT_ROLE_ORDER else None  # type: ignore[return-value]
