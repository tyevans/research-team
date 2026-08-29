"""That the authorizer and the tenancy projection are actually wired.

Two claims, and each names a failure CLAUDE.md records.

1. **`AGENT_AUTH` selects an adapter, and off selects a real one.** The
   alternative -- registering the check only when auth is on -- is the
   silent-default trap: "never wired" and "working" become indistinguishable to
   a test, and the first time the real path runs against route 74 is in
   somebody's browser. So off has to produce a `PermissiveAuthorizer`, not a
   `None`, and on has to produce the role table.

2. **The projection is started, not merely constructed.** An event no
   projection handles counts as APPLIED, so a build whose `TenantRunner` was
   built and never started answers every membership question with `None` --
   which reads exactly like "this person has no role". Asserting that `start()`
   did not raise would pass in that build; only a stored row proves it.

Slice B1 wires this and nothing calls it. That is stated in `Application`'s
docstring for `authorizer` and it is the reason this file exists now rather than
with the routes: a port wired and unread is precisely the shape that ships
inert.
"""

from uuid import uuid4

import pytest

from research_team.application.authorization import (
    PermissiveAuthorizer,
    Resource,
    RoleTableAuthorizer,
    Subject,
)
from research_team.domain.settings import SettingError
from research_team.domain.tenant import MemberAdded, TenantCreated, tenant_aggregate_id
from research_team.infrastructure import config

TENANT = "org-42"
ALICE = "sub-alice"


async def test_auth_off_wires_a_permissive_authorizer_rather_than_nothing(build_application):
    """The default in every configuration today, including the whole suite."""
    application = await build_application()
    assert isinstance(application.authorizer, PermissiveAuthorizer)
    assert await application.authorizer.check(
        Subject(""), "project.admin", Resource.project(uuid4(), TENANT)
    )


async def test_auth_on_wires_the_role_table_and_the_admin_subjects(
    build_application, monkeypatch
):
    """The one line slice B6 flips. Read here so that when B6 flips it, the
    change is the *value* of a variable and not the shape of the wiring."""
    monkeypatch.setenv("AGENT_AUTH", "on")
    monkeypatch.setenv("AGENT_ADMIN_SUBJECTS", " sub-root , sub-ops ")
    application = await build_application()
    assert isinstance(application.authorizer, RoleTableAuthorizer)
    assert application.authorizer.admin_subjects == frozenset({"sub-root", "sub-ops"})
    # And it refuses by default, which the permissive one cannot do. Without
    # this the test above would pass against a build that wired the permissive
    # adapter in both branches.
    assert (
        await application.authorizer.check(
            Subject(ALICE), "project.read", Resource.project(uuid4(), TENANT)
        )
        is False
    )


@pytest.mark.parametrize("value", ["off", "", "ON ", " on"])
async def test_only_the_word_on_turns_authorization_on(build_application, monkeypatch, value):
    """Case-folded and stripped, because operators type into a shell."""
    monkeypatch.setenv("AGENT_AUTH", value)
    application = await build_application()
    expected = RoleTableAuthorizer if value.strip().lower() == "on" else PermissiveAuthorizer
    assert isinstance(application.authorizer, expected)


@pytest.mark.parametrize("value", ["yes", "1", "true", "enabled"])
def test_a_value_that_is_neither_on_nor_off_is_refused_rather_than_guessed(monkeypatch, value):
    """`AGENT_AUTH` is an enum, not a boolean, and this is why.

    Under `SettingType.BOOLEAN` every value here would read as `True`, which
    sounds harmless until the mirror case: the same forgiveness makes a typo
    that turns authorization *off* silent. The two directions are not
    symmetric -- one is an outage somebody fixes in a second and the other is a
    security incident nobody sees -- so the parser refuses everything it was not
    told about, in both directions.
    """
    monkeypatch.setenv("AGENT_AUTH", value)
    with pytest.raises(SettingError):
        config.authorization_enabled()


async def test_the_tenancy_projection_follows_the_log_in_a_started_application(
    build_application,
):
    """A stored row, not a call that returned.

    Red if `tenants.start()` is removed from `Application.start()`: the
    `MemberAdded` still applies -- nothing subscribed rejects it -- and the
    lookup below raises or answers `None`, which is the shape a permission
    refusal takes when the wiring is missing rather than when the person is.
    """
    application = await build_application()
    event = MemberAdded(
        aggregate_id=tenant_aggregate_id(TENANT),
        tenant_id=TENANT,
        subject=ALICE,
        role="admin",
    )
    created = TenantCreated(
        aggregate_id=tenant_aggregate_id(TENANT), tenant_id=TENANT, name="Acme"
    )
    # Through the composed application's own runner -- the same object B4's
    # sharing routes will drive -- so the event reaches the store and the bus
    # production wires, not ones this test assembled. An append through a second
    # connection to the same file was tried first and never arrived: nothing here
    # polls, so the publish is what wakes the subscription.
    await application.tenants.record(created, event)
    await application.tenants.caught_up()

    assert await application.tenants.membership_role(TENANT, ALICE) == "admin"
    # And the checker built over that runner agrees -- the two halves meeting
    # inside a real application rather than in a test's own wiring.
    check = RoleTableAuthorizer(application.tenants)
    assert await check.check(
        Subject(ALICE), "project.admin", Resource.project(uuid4(), TENANT)
    )
