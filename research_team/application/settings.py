"""Resolving a setting, and the two ports that make it possible.

Resolution is the whole feature: a value is looked for at the project, then the
user, then the tenant, then the environment, then the built-in default, and the
first layer holding one wins. Every reader in the system asks for a key and a
scope and gets back a value *and the name of the layer that supplied it* --
the provenance is not diagnostic decoration, it is what a settings UI shows
beside each field so a person can tell "this project overrides it" from "this
is just the default".

**Where the environment sits, and why it is not a migration step.** It is the
layer below every scope and above the built-in default. That is what keeps a
headless CLI run configured entirely by `AGENT_*` working unchanged, keeps the
existing test suite passing without a settings database, and gives an operator
somewhere to put a value that no scope should be able to override.

Two ports, both with exactly one production adapter, so both are covered by a
test that drives the real writer against the real reader -- CLAUDE.md, "Events",
on why a stub on one side and a unit test on the other proves nothing:

- `SettingsStorePort` -- the override rows. `infrastructure/settings/store.py`.
- `SecretBoxPort` -- encryption at rest. `infrastructure/settings/secrets.py`.

And a third, `ProviderProbePort`, whose adapter reaches the network; its
"drives both ends over real data" test is the `integration`-marked one against
the local endpoint.
"""

import os
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from research_team.domain.providers import (
    ProbeResult,
    Provider,
    UnknownProvider,
    provider_for,
)
from research_team.domain.settings import (
    DEFAULT_LAYER,
    ENVIRONMENT_LAYER,
    RESOLUTION_ORDER,
    ROLE_MODEL_KEYS,
    MaskedSecret,
    ModelProfile,
    ModelRole,
    Override,
    Scope,
    ScopeRef,
    SettingError,
    SettingSpec,
    mask,
    resolve_spec,
)


class SettingsStorePort(Protocol):
    """Where overrides live. Three calls, and none of them resolves anything.

    Deliberately dumb: the store knows scopes, keys and strings. Resolution
    order, typing, validation and secrecy are all `SettingsResolver`'s, so a
    second store (Postgres, for a deployment that outgrows SQLite) cannot
    quietly disagree with the first about what `project` beats.
    """

    async def overrides(self, refs: Iterable[ScopeRef]) -> list[Override]: ...

    async def put(self, ref: ScopeRef, key: str, value: str) -> None: ...

    async def clear(self, ref: ScopeRef, key: str) -> bool:
        """True if a row was removed. False means there was nothing to clear,
        which the route reports as 404 rather than pretending it did work."""
        ...


class SecretBoxPort(Protocol):
    """Encryption at rest for secret settings.

    A port rather than a function so that a deployment with a KMS can supply
    one, and so the no-key case is an explicit adapter rather than an `if` in
    the resolver.
    """

    def seal(self, plaintext: str) -> str: ...

    def open(self, ciphertext: str) -> str | None:
        """The plaintext, or `None` when it cannot be decrypted.

        `None` rather than an exception because the realistic cause is a
        rotated or absent `AGENT_SETTINGS_KEY`, which makes *every* stored
        secret unreadable at once. Raising there would 500 the whole settings
        page; `None` lets the resolver fall through to the environment layer
        and report the secret as unreadable beside the one field it affects.
        """
        ...


class ProviderProbePort(Protocol):
    """Ask a provider whether these credentials work. Reaches the network."""

    async def probe(
        self, provider: Provider, api_key: str | None, base_url: str | None = None
    ) -> ProbeResult: ...


@dataclass(frozen=True)
class Resolved:
    """One setting's answer, with the layer that gave it.

    `value` is `None` for a secret -- always, and regardless of whether one is
    stored. A reader that wants the plaintext calls `secret()`, which is a
    separate method with no HTTP surface above it; that asymmetry is the
    mechanism behind "a secret never comes back out of a read endpoint" rather
    than a rule somebody has to remember at each route.
    """

    key: str
    value: object | None
    layer: str
    """One of `Scope`'s values, `environment`, or `default`."""

    scope_id: str | None = None
    """Which project/user/tenant supplied it, when a scope did."""

    secret: bool = False
    masked: MaskedSecret | None = None


class SettingsResolver:
    """Reads settings for a scope chain. The one place resolution order lives.

    Construction takes the chain rather than each call, because a chain
    assembled per call is a chain that can be assembled differently in two
    places -- and "which user was that project read for" is exactly the kind of
    question a wrong answer to is invisible.

    **Scope ids are explicit parameters, not derived from a session.** W-A owns
    identity and W-B owns authorization; nothing here checks that the caller
    may read the scope it named. The route that builds a resolver is where that
    check belongs and where W-B will put it -- see
    `interfaces/web/settings.py`, which carries the same note at each route.
    """

    def __init__(
        self,
        store: SettingsStorePort | None,
        secrets: SecretBoxPort | None = None,
        environ: dict[str, str] | None = None,
    ) -> None:
        self._store = store
        self._secrets = secrets
        #: Captured rather than read through `os.environ` at each call so a
        #: test can supply one. Defaults to the live environment, which is what
        #: keeps `config.py`'s readers working with no store at all.
        self._environ = environ if environ is not None else dict(os.environ)

    async def _stored(self, refs: Iterable[ScopeRef]) -> dict[tuple[Scope, str], Override]:
        if self._store is None:
            return {}
        rows = await self._store.overrides(refs)
        return {(row.scope, row.key): row for row in rows}

    def _from_environment(self, spec: SettingSpec) -> object | None:
        raw = self._environ.get(spec.env_var)
        if raw is None or raw.strip() == "":
            return None
        return spec.parse(raw)

    async def resolve(self, key: str, chain: Iterable[ScopeRef]) -> Resolved:
        """One setting, resolved down the chain.

        `chain` is filtered by `RESOLUTION_ORDER` rather than trusted in the
        order it arrived: a caller that listed user before project would
        otherwise silently invert the whole feature, and the failure would look
        like "my project override does not apply".
        """
        refs = list(chain)
        return (await self.resolve_all([key], refs))[0]

    async def resolve_all(
        self, keys: Iterable[str], chain: Iterable[ScopeRef]
    ) -> list[Resolved]:
        """Several settings over one read of the store.

        The batch form is the one the settings page uses, and it exists so a
        page of forty fields is one query rather than forty.
        """
        refs = list(chain)
        by_scope = {ref.scope: ref for ref in refs}
        ordered = [by_scope[scope] for scope in RESOLUTION_ORDER if scope in by_scope]
        stored = await self._stored(ordered)

        answers: list[Resolved] = []
        for key in keys:
            spec = resolve_spec(key)
            answers.append(self._resolve_one(spec, ordered, stored))
        return answers

    def _resolve_one(
        self,
        spec: SettingSpec,
        ordered: list[ScopeRef],
        stored: dict[tuple[Scope, str], Override],
    ) -> Resolved:
        for ref in ordered:
            row = stored.get((ref.scope, spec.key))
            if row is None:
                continue
            if spec.secret:
                return Resolved(
                    key=spec.key,
                    value=None,
                    layer=ref.scope.value,
                    scope_id=ref.scope_id,
                    secret=True,
                    masked=mask(self._unseal(row.value)),
                )
            return Resolved(
                key=spec.key,
                value=self._parse_stored(spec, row.value),
                layer=ref.scope.value,
                scope_id=ref.scope_id,
            )

        from_env = self._from_environment(spec)
        if from_env is not None:
            if spec.secret:
                return Resolved(
                    key=spec.key,
                    value=None,
                    layer=ENVIRONMENT_LAYER,
                    secret=True,
                    masked=mask(str(from_env)),
                )
            return Resolved(key=spec.key, value=from_env, layer=ENVIRONMENT_LAYER)

        if spec.secret:
            return Resolved(
                key=spec.key,
                value=None,
                layer=DEFAULT_LAYER,
                secret=True,
                masked=mask(None if spec.default is None else str(spec.default)),
            )
        return Resolved(key=spec.key, value=spec.default, layer=DEFAULT_LAYER)

    def _parse_stored(self, spec: SettingSpec, raw: str) -> object | None:
        """A stored string as its declared type, or the default if it no longer
        parses.

        A stored value can stop being valid without anyone touching it -- an
        enum's choices narrow, a minimum rises. Falling back to the default and
        keeping the row is the lesser of the two harms: refusing would make one
        stale row 500 the entire settings page, and deleting it would discard a
        value the operator may want to correct.
        """
        try:
            return spec.parse(raw)
        except SettingError:
            return spec.default

    def _unseal(self, ciphertext: str) -> str | None:
        if self._secrets is None:
            return None
        return self._secrets.open(ciphertext)

    async def secret(self, key: str, chain: Iterable[ScopeRef]) -> str | None:
        """The plaintext of a secret setting, for something about to make a call.

        Separate from `resolve` on purpose, and with nothing above it on the
        HTTP surface: the asymmetry is what makes "a secret never comes back
        out of a read endpoint" structural rather than a convention every new
        route has to remember.
        """
        spec = resolve_spec(key)
        if not spec.secret:
            raise SettingError(f"{key} is not a secret setting")
        refs = list(chain)
        by_scope = {ref.scope: ref for ref in refs}
        ordered = [by_scope[scope] for scope in RESOLUTION_ORDER if scope in by_scope]
        stored = await self._stored(ordered)
        for ref in ordered:
            row = stored.get((ref.scope, spec.key))
            if row is not None:
                plaintext = self._unseal(row.value)
                if plaintext is not None:
                    return plaintext
                # An undecryptable row falls through rather than shadowing the
                # environment. Otherwise rotating AGENT_SETTINGS_KEY would take
                # down every endpoint that had ever had an override, and the
                # environment layer -- which still works -- would be unreachable.
                break
        from_env = self._from_environment(spec)
        if from_env is not None:
            return str(from_env)
        return None if spec.default is None else str(spec.default)

    async def write(self, ref: ScopeRef, key: str, raw: str) -> None:
        """Set an override, validating and (for a secret) sealing first.

        Validation happens here rather than in the store so that every writer
        -- the route, a CLI, a future import -- gets the same refusal. A secret
        is sealed before it reaches the store, so nothing below this line ever
        holds a plaintext credential.
        """
        spec = resolve_spec(key)
        if ref.scope not in spec.scopes:
            raise SettingError(
                f"{key} cannot be set at {ref.scope.value} scope "
                f"(allowed: {', '.join(sorted(s.value for s in spec.scopes))})"
            )
        if self._store is None:
            raise SettingError("no settings store is wired")
        value = spec.parse(raw)
        # `spec.key`, never the `key` the caller passed. They differ for a
        # provider credential written in its short form -- `provider_key.groq`
        # normalises to `provider_key.groq.api_key` -- and the key is hashed
        # into the storage row id, so writing under the raw string and reading
        # under the normalised one puts a credential somewhere nothing can see
        # or remove. Measured, not reasoned: writing through the short form and
        # clearing through the long one answered 404, and the resolved read
        # never saw the row.
        if spec.secret:
            if self._secrets is None:
                raise SettingError(
                    "AGENT_SETTINGS_KEY is not set, so secrets cannot be stored"
                )
            await self._store.put(ref, spec.key, self._secrets.seal(str(value)))
            return
        await self._store.put(ref, spec.key, spec.serialise(value))

    async def clear(self, ref: ScopeRef, key: str) -> bool:
        spec = resolve_spec(key)
        if self._store is None:
            raise SettingError("no settings store is wired")
        return await self._store.clear(ref, spec.key)


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
        self, store: ModelProfileStorePort | None, settings: SettingsResolver
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
        if not profile.name.strip():
            raise SettingError("a profile needs a name")
        try:
            provider_for(profile.provider_id)
        except UnknownProvider as error:
            raise SettingError(str(error)) from error
        if not profile.model.strip():
            raise SettingError("a profile needs a model")
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

    async def select(self, ref: ScopeRef, role: ModelRole, profile_name: str) -> None:
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
                answers.append(
                    ResolvedRole(
                        role=role,
                        model=stored.profile.model,
                        layer=selection.scope.value,
                        profile=stored.profile,
                        scope_id=selection.scope_id,
                        setting_key=key,
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
