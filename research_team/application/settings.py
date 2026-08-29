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

from research_team.domain.providers import ProbeResult, Provider
from research_team.domain.settings import (
    DEFAULT_LAYER,
    ENVIRONMENT_LAYER,
    RESOLUTION_ORDER,
    MaskedSecret,
    Override,
    Scope,
    ScopeRef,
    SettingError,
    SettingSpec,
    mask,
    spec_for,
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
            spec = spec_for(key)
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
        spec = spec_for(key)
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
        spec = spec_for(key)
        if ref.scope not in spec.scopes:
            raise SettingError(
                f"{key} cannot be set at {ref.scope.value} scope "
                f"(allowed: {', '.join(sorted(s.value for s in spec.scopes))})"
            )
        if self._store is None:
            raise SettingError("no settings store is wired")
        value = spec.parse(raw)
        if spec.secret:
            if self._secrets is None:
                raise SettingError(
                    "AGENT_SETTINGS_KEY is not set, so secrets cannot be stored"
                )
            await self._store.put(ref, key, self._secrets.seal(str(value)))
            return
        await self._store.put(ref, key, spec.serialise(value))

    async def clear(self, ref: ScopeRef, key: str) -> bool:
        spec = spec_for(key)
        if self._store is None:
            raise SettingError("no settings store is wired")
        return await self._store.clear(ref, spec.key)
