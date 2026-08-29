"""Model profiles and role selections, behind `ModelProfileStorePort`.

Two tables rather than JSON in a settings value, and the reason is that a
profile is a *record*: it has a provider, a model, a credential key and a
parameter bag, each of which something validates. Packing that into the
`value` column of `setting_overrides` would have been fewer moving parts and
would have made every one of those fields unqueryable and unvalidated -- and
the credential key in particular has to be checked against the catalogue
before it is stored, which is not a thing a string column does.

No projection here either, for `SettingsStore`'s reason, and both tables open
lazily for the same event-loop reason. See that module.

**Two tables and not one.** A profile is a definition and a role selection is
a *reference to* one, and they resolve differently: a project may select a
profile a tenant defined. Folding the selection into the profile row would
force a project to redefine the profile in order to use it, which is the
opposite of what a scope chain is for.
"""

import asyncio
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID, uuid5

import aiosqlite
from eventsource import ReadModel
from eventsource.adapters.sqlite.readmodels import SQLiteReadModelRepository
from eventsource.ports.readmodels import Filter, Query, ReadModelRepository

from research_team.application.settings import RoleSelection, StoredProfile
from research_team.domain.settings import ModelProfile, ModelRole, Scope, ScopeRef
from research_team.infrastructure.persistence.read_models import apply_schema

PROFILE_NAMESPACE = UUID("7c4e2a90-1b6d-5f34-8a07-e35b91c6d248")


class ModelProfileRow(ReadModel):
    """One named profile at one scope.

    `parameters` is a JSON string for `EntityDefinitionRow.citations`' reason:
    it is handed to the browser whole and passed to a client builder whole, and
    nothing in between iterates it, so decoding it into a column shape would be
    work with no reader.

    `credential_key` and `base_url` are empty strings rather than nullable
    columns. SQLite tolerates either; an empty string keeps `find` filters and
    the row's own equality free of three-valued logic, and the boundary that
    builds a `ModelProfile` turns them back into `None`.
    """

    __table_name__ = "model_profiles"

    scope: str
    scope_id: str
    name: str
    provider_id: str
    model: str
    credential_key: str = ""
    base_url: str = ""
    parameters: str = "{}"
    updated_at: datetime

    @staticmethod
    def row_id(scope: Scope, scope_id: str, name: str) -> UUID:
        return uuid5(PROFILE_NAMESPACE, f"profile:{scope.value}:{scope_id}:{name}")


class RoleSelectionRow(ReadModel):
    """Which profile a scope has chosen for one role."""

    __table_name__ = "model_role_selections"

    scope: str
    scope_id: str
    role: str
    profile_name: str
    updated_at: datetime

    @staticmethod
    def row_id(scope: Scope, scope_id: str, role: ModelRole) -> UUID:
        return uuid5(PROFILE_NAMESPACE, f"role:{scope.value}:{scope_id}:{role.value}")


def _decoded(parameters: str) -> dict:
    """The parameter bag, or an empty one.

    A malformed column answers `{}` rather than raising, for
    `definition_cache._citations_of`'s reason: `put_profile` is the only writer
    and it encodes from a dict, but the cost of being wrong differs sharply by
    direction -- a profile that comes back with no parameters still names a
    provider and a model, where an exception here would 500 the settings page
    and keep 500ing it until someone found the row by hand.
    """
    try:
        payload = json.loads(parameters)
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


class ModelProfileStore:
    """`ModelProfileStorePort` over SQLite. Two tables, one connection."""

    def __init__(self, db_path: str, tracer=None) -> None:
        self._db_path = db_path
        self._tracer = tracer
        self._connection: aiosqlite.Connection | None = None
        self._profiles: ReadModelRepository | None = None
        self._roles: ReadModelRepository | None = None
        self._opening = asyncio.Lock()

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> "ModelProfileStore":
        store = cls(db_path, tracer)
        await store._ensure()
        return store

    async def _ensure(self) -> tuple[ReadModelRepository, ReadModelRepository]:
        if self._profiles is not None and self._roles is not None:
            return self._profiles, self._roles
        async with self._opening:
            if self._profiles is not None and self._roles is not None:
                return self._profiles, self._roles
            connection = await aiosqlite.connect(self._db_path)
            for model in (ModelProfileRow, RoleSelectionRow):
                await apply_schema(connection, model)
                # `apply_schema` reconciles columns, not indexes. Every read
                # here filters on the scope pair, so without these each page
                # load scans every other tenant's profiles.
                await connection.execute(
                    f"CREATE INDEX IF NOT EXISTS idx_{model.table_name()}_scope "
                    f"ON {model.table_name()}(scope, scope_id)"
                )
            await connection.commit()
            self._connection = connection
            self._profiles = SQLiteReadModelRepository(
                connection, ModelProfileRow, self._tracer
            )
            self._roles = SQLiteReadModelRepository(connection, RoleSelectionRow, self._tracer)
            return self._profiles, self._roles

    async def profiles(self, refs: Iterable[ScopeRef]) -> list[StoredProfile]:
        rows_repo, _ = await self._ensure()
        found: list[StoredProfile] = []
        for ref in refs:
            rows = await rows_repo.find(
                Query(
                    filters=[
                        Filter.eq("scope", ref.scope.value),
                        Filter.eq("scope_id", ref.scope_id),
                    ],
                    order_by="name",
                )
            )
            found.extend(
                StoredProfile(
                    scope=Scope(row.scope),
                    scope_id=row.scope_id,
                    profile=ModelProfile(
                        name=row.name,
                        provider_id=row.provider_id,
                        model=row.model,
                        credential_key=row.credential_key or None,
                        base_url=row.base_url or None,
                        parameters=_decoded(row.parameters),
                    ),
                )
                for row in rows
            )
        return found

    async def put_profile(self, ref: ScopeRef, profile: ModelProfile) -> None:
        rows, _ = await self._ensure()
        await rows.save(
            ModelProfileRow(
                id=ModelProfileRow.row_id(ref.scope, ref.scope_id, profile.name),
                scope=ref.scope.value,
                scope_id=ref.scope_id,
                name=profile.name,
                provider_id=profile.provider_id,
                model=profile.model,
                credential_key=profile.credential_key or "",
                base_url=profile.base_url or "",
                parameters=json.dumps(profile.parameters),
                updated_at=datetime.now(UTC),
            )
        )

    async def delete_profile(self, ref: ScopeRef, name: str) -> bool:
        rows, _ = await self._ensure()
        row_id = ModelProfileRow.row_id(ref.scope, ref.scope_id, name)
        if await rows.get(row_id) is None:
            return False
        await rows.delete(row_id)
        return True

    async def selections(self, refs: Iterable[ScopeRef]) -> list[RoleSelection]:
        _, roles = await self._ensure()
        found: list[RoleSelection] = []
        for ref in refs:
            rows = await roles.find(
                Query(
                    filters=[
                        Filter.eq("scope", ref.scope.value),
                        Filter.eq("scope_id", ref.scope_id),
                    ]
                )
            )
            found.extend(
                RoleSelection(
                    scope=Scope(row.scope),
                    scope_id=row.scope_id,
                    role=ModelRole(row.role),
                    profile_name=row.profile_name,
                )
                for row in rows
            )
        return found

    async def select(self, ref: ScopeRef, role: ModelRole, profile_name: str) -> None:
        _, roles = await self._ensure()
        await roles.save(
            RoleSelectionRow(
                id=RoleSelectionRow.row_id(ref.scope, ref.scope_id, role),
                scope=ref.scope.value,
                scope_id=ref.scope_id,
                role=role.value,
                profile_name=profile_name,
                updated_at=datetime.now(UTC),
            )
        )

    async def clear_selection(self, ref: ScopeRef, role: ModelRole) -> bool:
        _, roles = await self._ensure()
        row_id = RoleSelectionRow.row_id(ref.scope, ref.scope_id, role)
        if await roles.get(row_id) is None:
            return False
        await roles.delete(row_id)
        return True

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None
            self._profiles = None
            self._roles = None
