"""Appends what a completed sign-in observed, and publishes it.

Not bound to one subject at construction, unlike `EventStoreCatalogFeatureRecorder`
next door. That adapter is per-project because the only project a caller may
write to is the one it was handed; here the subject is not a scope a caller
should be confined to but the *content* of the observation, and it arrives
from a verified token rather than from a caller's argument. Binding it would
mean one recorder per person per request, which is an object per HTTP call for
no safety this does not already have.
"""

from datetime import UTC, datetime

from eventsource import ExpectedVersion, InMemoryEventBus, StreamId
from eventsource.adapters.sqlite import SQLiteEventStore

from research_team.domain.user import (
    USER_AGGREGATE_TYPE,
    UserProfileChanged,
    UserSignedIn,
    stream_id_for,
)
from research_team.infrastructure.identity.oidc import Claims
from research_team.infrastructure.persistence.users import UserRow


class EventStoreUserRecorder:
    """Turns verified claims into events on the log.

    The `changed` decision is made here rather than in the projection, and
    that placement is the interesting part. A projection cannot decide to
    append -- it is downstream of the log by definition -- so "only write
    `UserProfileChanged` when something actually changed" has to be a
    *writer's* judgement, made against the read model the writer can see. That
    makes this class the one place where a read model is read in order to
    decide what to write, which is normally a smell; it is accepted because
    the alternative is an event per sign-in per claim and a log where the
    presence of `UserProfileChanged` means nothing.
    """

    def __init__(
        self,
        store: SQLiteEventStore,
        publisher: InMemoryEventBus,
        users,
    ) -> None:
        self._store = store
        self._publisher = publisher
        # The started `UserRunner`, not a `UserStore`: `rebuild()` closes the
        # store and opens another, and a recorder holding the old one would
        # compare new claims against a closed connection. Same argument
        # `EntityDefinitionRunner.get`'s docstring makes for delegating.
        self._users = users

    async def record_sign_in(self, claims: Claims) -> UserSignedIn:
        """Append `UserSignedIn`, plus `UserProfileChanged` if anything moved.

        In that order, and the order matters on first sign-in: the sign-in
        event is what creates the row, so a profile change appended first
        would be applied to nothing and then immediately overwritten. On a
        first sign-in nothing has changed by definition, so only one event is
        written -- which is what makes a `UserProfileChanged` on the log always
        mean a genuine difference.
        """
        now = datetime.now(UTC).isoformat()
        existing: UserRow | None = await self._users.get(claims.subject)

        signed_in = UserSignedIn(
            aggregate_id=stream_id_for(claims.subject),
            subject=claims.subject,
            tenant_id=claims.tenant_id,
            email=claims.email,
            display_name=claims.display_name,
            avatar_url=claims.avatar_url,
            signed_in_at=now,
        )
        await self._append(signed_in)

        if existing is not None and _differs(existing, claims):
            await self._append(
                UserProfileChanged(
                    aggregate_id=stream_id_for(claims.subject),
                    subject=claims.subject,
                    tenant_id=claims.tenant_id,
                    email=claims.email,
                    display_name=claims.display_name,
                    avatar_url=claims.avatar_url,
                    changed_at=now,
                )
            )
        return signed_in

    async def _append(self, event: UserSignedIn | UserProfileChanged) -> None:
        await self._store.append(
            StreamId(stream_id_for(event.subject), USER_AGGREGATE_TYPE),
            [event],
            # `any_()`, following `EventStoreCatalogFeatureRecorder`: this
            # stream protects no invariant, and a person with two tabs open
            # signing in twice must not have the second attempt fail on a
            # version race about a fact neither request cares about.
            ExpectedVersion.any_(),
        )
        # Appending is not delivering. `SubscriptionManager` catches a
        # projection up from the store and then follows the bus, so an append
        # nobody publishes reaches a running projection only on the next
        # restart. Left out, sign-in answers 200, the cookie is set, and
        # `/api/me` reports nobody -- which reads exactly like the projection
        # having never been wired at all.
        await self._publisher.publish([event])


def _differs(row: UserRow, claims: Claims) -> bool:
    """Whether the mirror disagrees with what the token just said.

    Compares every mirrored claim, `tenant_id` included. That last one is the
    surprising member of the set and it is deliberate: Zitadel can move a user
    between organisations, and a mirror that noticed a new display name but
    not a new org would leave W-B's tenancy scoping keyed on a stale value --
    silently, since nothing else re-reads it.

    `first_seen_at` and `last_seen_at` are excluded because they are this
    system's own observations rather than the IdP's claims, and comparing them
    would make every sign-in a profile change.
    """
    return (
        row.tenant_id != claims.tenant_id
        or row.email != claims.email
        or row.display_name != claims.display_name
        or row.avatar_url != claims.avatar_url
    )
