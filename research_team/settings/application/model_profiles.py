"""Named (provider, model, credentials, parameters) triples, per role, per scope."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from research_team.settings.domain import (
    RESOLUTION_ORDER,
    ROLE_CAPABILITIES,
    ROLE_MODEL_KEYS,
    ModelProfile,
    ModelRole,
    Scope,
    ScopeRef,
    SettingError,
    provider_supports_role,
    resolve_spec,
)
from research_team.settings.domain.providers import (
    BY_ID,
    UnknownProvider,
    provider_for,
)

if TYPE_CHECKING:
    from research_team.settings.application.settings import SettingsResolver

__all__ = [
    "ModelProfileService",
    "ModelProfileStorePort",
    "ResolvedRole",
    "RoleSelection",
    "StoredProfile",
    "_ordered",
]


@dataclass(frozen=True)
class StoredProfile:
    """A profile and the scope that defined it."""

    scope: Scope
    scope_id: str
    profile: ModelProfile


@dataclass(frozen=True)
class RoleSelection:
    """A scope's choice of profile for one role."""

    scope: Scope
    scope_id: str
    role: ModelRole
    profile_name: str


class ModelProfileStorePort(Protocol):
    """Where profiles and role selections live.

    Dumb in the same way `SettingsStorePort` is: it knows scopes, names and
    strings, and has no opinion about which scope wins. `ModelProfileService`
    owns the walk, so the two stores cannot disagree about resolution order.
    """

    async def profiles(self, refs: Iterable[ScopeRef]) -> list[StoredProfile]: ...

    async def put_profile(self, ref: ScopeRef, profile: ModelProfile) -> None: ...

    async def delete_profile(self, ref: ScopeRef, name: str) -> bool: ...

    async def selections(self, refs: Iterable[ScopeRef]) -> list[RoleSelection]: ...

    async def select(self, ref: ScopeRef, role: ModelRole, profile_name: str) -> None: ...

    async def clear_selection(self, ref: ScopeRef, role: ModelRole) -> bool: ...


@dataclass(frozen=True)
class ResolvedRole:
    """What a role resolves to, and how it got there.

    `model` is always populated -- a role always has a model, because the
    settings layer underneath always answers -- so a caller that only wants to
    make a call reads this one field and ignores the rest. The others are for
    the person looking at the form.
    """

    role: ModelRole
    model: str
    layer: str
    """Where the answer came from: a scope's name when a profile was selected
    there, otherwise the layer the role's *setting* resolved from."""

    profile: ModelProfile | None = None
    scope_id: str | None = None
    setting_key: str = ""
    """The setting the model name falls back to. Reported even when a profile
    answered, because it is what the form offers as the way back."""

    dangling: str | None = None
    """The name of a selected profile that no scope in the chain defines.

    Reported rather than silently ignored. A selection pointing at a deleted
    profile is exactly the "silently repointed at something else" failure this
    whole feature exists to prevent -- falling back without saying so would
    send the role to the default model and look like it worked.
    """

    incompatible: str | None = None
    """Explanation if the profile's provider lacks the capability required for the role."""


def _ordered(chain: Iterable[ScopeRef]) -> list[ScopeRef]:
    """The chain in resolution order, dropping scopes not named.

    Shared by both services so there is one statement of the walk. A caller
    that listed user before project would otherwise silently invert the whole
    feature, and the failure looks like "my project override does not apply".
    """
    by_scope = {ref.scope: ref for ref in chain}
    return [by_scope[scope] for scope in RESOLUTION_ORDER if scope in by_scope]


class ModelProfileService:
    """Named (provider, model, credentials, parameters) triples, per role, per scope.

    The five roles were separate environment variables that all defaulted to
    one endpoint, so "my Anthropic key for authoring and my local vLLM for
    extraction" was not expressible: the api key was one variable. A profile is
    the unit that makes it expressible, and this is where a role becomes a
    model name.

    **Profiles shadow by name; selections resolve by role**, and the two walks
    are separate on purpose: a project may select a profile a *tenant* defined,
    which is the ordinary case for a shared team credential. Folding them
    together would force a project to redefine a profile in order to use it.

    Scope ids are explicit and nothing here authorizes them -- W-B, as
    everywhere else on this surface.
    """

    def __init__(
        self, store: ModelProfileStorePort | None, settings: "SettingsResolver"
    ) -> None:
        self._store = store
        self._settings = settings

    async def profiles(self, chain: Iterable[ScopeRef]) -> list[StoredProfile]:
        """Every profile visible from this chain, most specific definition first.

        A name defined at two scopes appears once: the more specific one, which
        is what a lookup finds. Returning both would make the list disagree with
        the resolution it is supposed to describe.
        """
        if self._store is None:
            return []
        ordered = _ordered(chain)
        rank = {ref.scope: index for index, ref in enumerate(ordered)}
        seen: dict[str, StoredProfile] = {}
        for stored in sorted(await self._store.profiles(ordered), key=lambda s: rank[s.scope]):
            seen.setdefault(stored.profile.name, stored)
        return sorted(seen.values(), key=lambda s: (rank[s.scope], s.profile.name))

    async def put(self, ref: ScopeRef, profile: ModelProfile) -> None:
        """Store a profile, validating the provider and the credential first.

        Both checks are here rather than at the route so every writer gets the
        same refusal, and both concern a string that ends up somewhere it cannot
        be taken back from: `provider_id` selects an adapter, and
        `credential_key` names the secret a call will be made with.
        """
        if self._store is None:
            raise SettingError("no model profile store is wired")
        profile.validate()
        try:
            provider_for(profile.provider_id)
        except UnknownProvider as error:
            raise SettingError(str(error)) from error
        if profile.credential_key is not None:
            spec = resolve_spec(profile.credential_key)
            if not spec.secret:
                # A profile's credential is what a call is authenticated with.
                # Pointing it at an ordinary setting would put a non-secret
                # value on the credential path and -- worse -- render a
                # secret-shaped field in the UI that is not one.
                raise SettingError(
                    f"{profile.credential_key} is not a secret setting, so it "
                    f"cannot be a profile's credential"
                )
        await self._store.put_profile(ref, profile)

    async def delete(self, ref: ScopeRef, name: str) -> bool:
        if self._store is None:
            raise SettingError("no model profile store is wired")
        return await self._store.delete_profile(ref, name)

    async def select(
        self,
        ref: ScopeRef,
        role: ModelRole,
        profile_name: str,
        chain: Iterable[ScopeRef] | None = None,
    ) -> None:
        """Point a role at a profile.

        The profile need not exist yet, deliberately: a selection is resolved
        against the chain at *read* time, and a tenant may legitimately select a
        name a project will define. What is not silent is the other direction --
        a selection resolving to nothing is reported as `dangling`.
        """
        if self._store is None:
            raise SettingError("no model profile store is wired")
        if not profile_name.strip():
            raise SettingError("a role selection needs a profile name")

        # If the profile exists in the scope chain (or at ref), validate capability
        scopes_to_check = list(chain) if chain is not None else [ref]
        stored_profiles = await self._store.profiles(scopes_to_check)
        matching = next((p for p in stored_profiles if p.profile.name == profile_name), None)
        if matching is not None:
            provider = BY_ID.get(matching.profile.provider_id)
            if provider is not None and not provider_supports_role(provider, role):
                req = ROLE_CAPABILITIES.get(role)
                req_str = f" (requires {req.value} capability)" if req else ""
                raise SettingError(
                    f"provider {provider.display_name!r} does not support "
                    f"{role.value} role{req_str}"
                )

        await self._store.select(ref, role, profile_name)

    async def clear(self, ref: ScopeRef, role: ModelRole) -> bool:
        if self._store is None:
            raise SettingError("no model profile store is wired")
        return await self._store.clear_selection(ref, role)

    async def roles(self, chain: Iterable[ScopeRef]) -> list[ResolvedRole]:
        """Every role, resolved. One read of each store.

        The batch form is what the settings page uses: five roles are two
        queries rather than ten.
        """
        ordered = _ordered(chain)
        visible = {stored.profile.name: stored for stored in await self.profiles(ordered)}
        chosen: dict[ModelRole, RoleSelection] = {}
        if self._store is not None:
            rank = {ref.scope: index for index, ref in enumerate(ordered)}
            for selection in sorted(
                await self._store.selections(ordered), key=lambda s: rank[s.scope]
            ):
                chosen.setdefault(selection.role, selection)

        keys = [ROLE_MODEL_KEYS[role] for role in ModelRole]
        resolved = await self._settings.resolve_all(keys, ordered)
        fallbacks = dict(zip(ModelRole, resolved, strict=True))
        chat = str((await self._settings.resolve("model", ordered)).value)

        answers: list[ResolvedRole] = []
        for role in ModelRole:
            fallback = fallbacks[role]
            key = ROLE_MODEL_KEYS[role]
            selection = chosen.get(role)
            stored = visible.get(selection.profile_name) if selection else None
            if selection is not None and stored is not None:
                provider = BY_ID.get(stored.profile.provider_id)
                incompatible: str | None = None
                if provider is not None and not provider_supports_role(provider, role):
                    req = ROLE_CAPABILITIES.get(role)
                    req_str = f"requires {req.value}" if req else "unsupported"
                    incompatible = (
                        f"provider {provider.display_name!r} does not support "
                        f"{role.value} ({req_str})"
                    )
                answers.append(
                    ResolvedRole(
                        role=role,
                        model=stored.profile.model,
                        layer=selection.scope.value,
                        profile=stored.profile,
                        scope_id=selection.scope_id,
                        setting_key=key,
                        incompatible=incompatible,
                    )
                )
                continue
            answers.append(
                ResolvedRole(
                    role=role,
                    # `curation_model`, `extraction_model` and `vision_model`
                    # have no default of their own. Curation and extraction fall
                    # back to the chat model, which is what their readers do, so
                    # the form shows the name a call would actually use rather
                    # than an empty field.
                    model=str(fallback.value) if fallback.value else chat,
                    layer=fallback.layer if fallback.value else "fallback",
                    scope_id=fallback.scope_id if fallback.value else None,
                    setting_key=key,
                    dangling=selection.profile_name if selection is not None else None,
                )
            )
        return answers
