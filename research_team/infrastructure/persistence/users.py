"""The mirror of who has signed in, and what the IdP said about them.

Its own module rather than another thousand lines in `read_models.py`,
following `topics.py`'s split-by-subject argument: that file answers "what
happened" and "what do we hold", and this one answers "who is here", which is
a question with its own vocabulary and its own lifetime.

**Why a table at all, when Zitadel already knows.** Two reasons, and neither
is caching for its own sake. First, rendering an account menu needs a display
name and an avatar on every page load, and a userinfo request per page load
puts the IdP on the critical path of the console. Second -- and this is the
one that outlives the first -- W-B's tenancy and authorization work needs to
name a user in a row and a tuple, and a foreign system's subject string is not
something a join can be built on. `users.subject` is the seam.

What this table is *not*: authoritative. Every column here is a copy of
something Zitadel owns, deliberately stale between sign-ins. Nothing may
decide anything on `email` here that it would not decide on a claim; the
`tests/infrastructure/test_user_read_model.py` docstrings say so where it
matters.
"""

import asyncio
from uuid import UUID

import aiosqlite
from eventsource import (
    DeclarativeProjection,
    InMemoryEventBus,
    ReadModel,
    SQLCheckpointRepository,
    SQLDLQRepository,
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

from research_team.domain.user import UserProfileChanged, UserSignedIn, stream_id_for
from research_team.infrastructure.persistence.read_models import (
    LOCAL_RETRY_POLICY,
    apply_schema,
)


class UserRow(ReadModel):
    """One person, as the identity provider last described them.

    Keyed on `stream_id_for(subject)` rather than on a minted id, so that the
    row id and the aggregate id are the same value. That is not tidiness: it
    means the projection can write a row for a subject it has never seen
    without a lookup, which is what makes first sign-in a single upsert rather
    than a read-modify-write with a race in the middle.
    """

    __table_name__ = "users"

    subject: str
    """The OIDC `sub` claim, and the only column here that is a real key.

    Stable for the lifetime of an account within one issuer, which is exactly
    the promise the spec makes and exactly why nothing keys on `email`: an
    address is reassignable and a subject is not. A build that keyed on email
    would hand a departed employee's projects to whoever inherited the
    address.
    """

    tenant_id: str
    """The Zitadel organisation id this person's account lives in.

    A `str`, not a `UUID`: Zitadel org ids are snowflake-shaped decimal
    strings. W-B owns what a tenant means and what may be scoped to one; this
    column exists now so that work has something to join on rather than a
    backfill to run against a log that never carried the value.
    """

    email: str = ""
    display_name: str = ""
    avatar_url: str = ""
    first_seen_at: str = ""
    """When this instance first saw the person, not when the account was made.

    **Named `first_seen_at` and not `created_at`, and that is forced rather
    than chosen.** `ReadModel` already declares `created_at`/`updated_at`/
    `deleted_at`, and `SQLiteReadModelRepository` coerces those three column
    names to `datetime` on the way out of the database. Declaring a `str`
    field called `created_at` shadows the base's without changing the
    repository's coercion, so every read raises a pydantic
    `string_type` error -- measured, not reasoned: four tests in
    `tests/integration/test_a_sign_in_reaches_the_user_read_model.py` failed
    that way before the rename. The base's own `created_at` would have been
    close to the right value, and is deliberately not relied on: it is the
    library's row bookkeeping, and this column is a domain observation that
    happens to coincide with it today.

    Those differ, sometimes by a lot -- an account provisioned in Zitadel in
    January and first used here in June has one of each -- and this is
    deliberately the second. "First seen here" is a fact this system observed;
    "account created" is a fact it would be copying, and a copy of a fact is
    the thing the module docstring says this table must not pretend to own.
    """

    last_seen_at: str = ""

    @staticmethod
    def row_id(subject: str) -> UUID:
        return stream_id_for(subject)


class UserStore:
    """The `users` table and the connection it owns.

    No `feature`/`unfeature`-shaped verbs: everything a caller wants from this
    table is either "the row for this subject" or "apply what the log said",
    and the second is the projection's business alone.
    """

    def __init__(self, connection: aiosqlite.Connection, rows: ReadModelRepository) -> None:
        self._connection = connection
        self._rows = rows

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> "UserStore":
        connection = await aiosqlite.connect(db_path)
        await apply_schema(connection, UserRow)
        # `apply_schema` reconciles columns, not indexes -- the same note
        # `EntityDefinitionStore.open` carries. Unlike that one this index is
        # not about scan cost (a `users` table is small by construction, one
        # row per human) but about the uniqueness the key implies being
        # visible to the database rather than only to `row_id`. It is a plain
        # index and not a UNIQUE one, deliberately: a projection replaying
        # from a checkpoint re-writes rows it has already written, and a
        # unique violation there would dead-letter a routine replay.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_users_subject ON {UserRow.table_name()}(subject)"
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, UserRow, tracer)
        return cls(connection, rows)

    async def get(self, subject: str) -> UserRow | None:
        row = await self._rows.get(UserRow.row_id(subject))
        if row is None or row.deleted_at is not None:
            return None
        return row

    async def observe_sign_in(self, event: UserSignedIn) -> None:
        """Write or refresh the row a sign-in implies.

        Upsert rather than insert-or-update-branch, and the branch that *does*
        exist is only about `first_seen_at`: the first sign-in sets it and every
        later one must leave it alone, or "first seen" would silently become
        "last seen" and the column would be a duplicate of its neighbour.
        """
        existing = await self._rows.get(UserRow.row_id(event.subject))
        await self._rows.save(
            UserRow(
                id=UserRow.row_id(event.subject),
                subject=event.subject,
                tenant_id=event.tenant_id,
                email=event.email,
                display_name=event.display_name,
                avatar_url=event.avatar_url,
                first_seen_at=(
                    existing.first_seen_at
                    if existing is not None and existing.first_seen_at
                    else event.signed_in_at
                ),
                last_seen_at=event.signed_in_at,
            )
        )

    async def observe_profile_change(self, event: UserProfileChanged) -> None:
        """Apply new claims without touching `last_seen_at`.

        Separated from `observe_sign_in` rather than sharing an upsert, and
        the difference is the whole reason the two events are separate: a
        profile change is not activity. Folding it into the sign-in path would
        make an administrator renaming somebody in Zitadel look, in this
        table, exactly like that person using the system.

        A change for a subject with no row is written as one anyway, rather
        than skipped. A replay from an arbitrary checkpoint can deliver a
        change whose sign-in is behind the checkpoint, and a projection that
        raised there would dead-letter an ordinary rebuild -- the same
        argument `CatalogFeatureStore.unfeature` makes for tolerating a delete
        of nothing.
        """
        existing = await self._rows.get(UserRow.row_id(event.subject))
        await self._rows.save(
            UserRow(
                id=UserRow.row_id(event.subject),
                subject=event.subject,
                tenant_id=event.tenant_id,
                email=event.email,
                display_name=event.display_name,
                avatar_url=event.avatar_url,
                first_seen_at=(
                    existing.first_seen_at
                    if existing is not None and existing.first_seen_at
                    else event.changed_at
                ),
                last_seen_at=(
                    existing.last_seen_at if existing is not None else event.changed_at
                ),
            )
        )

    async def list(self) -> list[UserRow]:
        """Everybody, most recently seen first.

        Nothing in W-A renders this. It exists because W-B's role-assignment
        UI needs "who could I grant this to", and a store with a `get` and no
        `list` would have that work reaching past this class into the table.
        """
        return await self._rows.find(
            Query(
                filters=[Filter(field="deleted_at", operator="is_null")],
                order_by="last_seen_at",
                order_direction="desc",
            )
        )

    async def truncate(self) -> None:
        await self._connection.execute(f"DELETE FROM {UserRow.table_name()}")
        await self._connection.commit()

    async def close(self) -> None:
        await self._connection.close()


class UserProjection(DeclarativeProjection):
    """Keeps `users` level with what the IdP has told us.

    Two handlers and no more. In particular there is no handler for "user
    deleted": nothing in this system deletes a person, because the deletion
    happens in Zitadel and this log never hears about it. A departed account
    simply stops signing in, and its row goes stale in place. That is a real
    gap rather than an omission to fix here -- reaping rows needs either a
    Zitadel webhook or a reconciliation pass, both of which are W-B's problem
    once there is something (project ownership) that a stale row could wrongly
    keep hold of.
    """

    def __init__(
        self,
        store: UserStore,
        checkpoint_repo=None,
        dlq_repo=None,
        tracer=None,
    ) -> None:
        self._store = store
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(UserSignedIn)
    async def _signed_in(self, event: UserSignedIn) -> None:
        await self._store.observe_sign_in(event)

    @handles(UserProfileChanged)
    async def _profile_changed(self, event: UserProfileChanged) -> None:
        await self._store.observe_profile_change(event)


class UserRunner:
    """Keeps the `users` table following the log, and answers from it.

    A runner of the same shape as every other projection here, and built for
    the reason `EntityDefinitionRunner`'s comment in `composition.py` gives: a
    projection wired somewhere other than beside its neighbours is a
    projection somebody forgets to start, and one nobody started is an empty
    read model that raises nothing. That failure is unusually quiet for this
    table -- the callback still appends `UserSignedIn`, still mints a session
    cookie, and still signs the person in. Only `/api/me` comes back describing
    a stranger. `tests/integration/test_a_sign_in_reaches_the_user_read_model.py`
    asserts the *row*, never that the request succeeded.
    """

    def __init__(
        self,
        store: SQLiteEventStore,
        db_path: str,
        bus: InMemoryEventBus,
        tracer=None,
    ) -> None:
        self._store = store
        self._db_path = db_path
        self._bus = bus
        self._tracer = tracer
        self._users: UserStore | None = None
        self._manager: SubscriptionManager | None = None
        self._subscription = None
        self._checkpoints: SQLCheckpointRepository | None = None
        self._dlq: SQLDLQRepository | None = None
        self._engine: AsyncEngine | None = None

    @property
    def projection_name(self) -> str:
        return UserProjection.__name__

    async def start(self) -> None:
        """Open the table and start following the log.

        The same shape as `EntityDefinitionRunner.start`, including touching
        the event store first so `projection_checkpoints` exists before
        anything reads it.
        """
        if self._manager is not None:
            return
        await self._store.current_position()
        engine = create_async_engine(f"sqlite+aiosqlite:///{self._db_path}")
        self._engine = engine
        self._checkpoints = SQLCheckpointRepository(engine)
        self._dlq = SQLDLQRepository(engine)
        self._users = await UserStore.open(self._db_path, self._tracer)
        projection = UserProjection(self._users, self._checkpoints, self._dlq, self._tracer)
        self._manager = SubscriptionManager(
            self._store, self._bus, self._checkpoints, dlq_repo=self._dlq, tracer=self._tracer
        )
        self._subscription = await self._manager.subscribe(
            projection, SubscriptionConfig(start_from="checkpoint")
        )
        results = await self._manager.start()
        failures = {name: err for name, err in results.items() if err is not None}
        if failures:
            raise RuntimeError(f"the user projection failed to start: {failures}")

    async def get(self, subject: str) -> UserRow | None:
        """This subject's mirrored row, or None if nobody by that subject has
        ever signed in here.

        Delegated rather than handing the store out through a property, for
        `EntityDefinitionRunner.get`'s reason: `rebuild()` closes the store and
        opens another, and a caller holding the old one would go on calling a
        closed connection, silently, after a repair.
        """
        if self._users is None:
            raise RuntimeError("the user projection has not been started")
        return await self._users.get(subject)

    async def list(self) -> list[UserRow]:
        if self._users is None:
            raise RuntimeError("the user projection has not been started")
        return await self._users.list()

    # The return annotation is quoted, and it has to be: this class defines a
    # method named `list` above, which shadows the builtin inside the class
    # body, so an unquoted `list[DLQEntry]` here subscripts that method and
    # raises `TypeError: 'function' object is not subscriptable` at import
    # time. Quoting defers the lookup to a scope where `list` is the builtin
    # again. Renaming the method was the alternative and was rejected: `list`
    # is what every other store and runner in this package calls it, and one
    # inconsistently named for a scoping accident is worse than one comment.
    async def failures(self, limit: int = 100) -> "list[DLQEntry]":
        if self._dlq is None:
            return []
        return await self._dlq.get_failed_events(
            projection_name=self.projection_name, limit=limit
        )

    async def rebuild(self) -> None:
        """Truncate and replay.

        Truncating is safe here, unlike `EntityDefinitionRunner.rebuild`:
        every column in `users` is derived from an event on this log. Nothing
        writes into this table except the projection -- there is no `put` --
        so a replay restores it exactly.
        """
        if self._manager is None:
            raise RuntimeError("the user projection has not been started")
        await self._manager.stop()
        for entry in await self.failures(limit=1000):
            await self._dlq.mark_resolved(entry.id, resolved_by="rebuild")
        await self._checkpoints.reset_checkpoint(self.projection_name)
        await self._users.truncate()
        self._manager = None
        self._subscription = None
        await self._users.close()
        self._users = None
        await self.start()
        await self.caught_up()

    async def caught_up(self, timeout: float = 10.0) -> None:
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
        raise TimeoutError(f"the user projection did not reach {target} within {timeout}s")

    async def stop(self) -> None:
        if self._manager is not None:
            await self._manager.stop()
            self._manager = None
        if self._users is not None:
            await self._users.close()
            self._users = None
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
