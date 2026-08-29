"""The settings and provider HTTP surface.

Its own module and its own router, for `export.py`'s reason: `create_app` is
five thousand lines of closures and six more routes inside it would be six
hundred lines nobody can find.

**The response shapes here are a contract.** W-C1 builds the settings UI over
them on a separate branch, so they are written down in
`docs/reference/settings-api.md` rather than left to be read off this file, and
`tests/interfaces/test_settings_routes.py` asserts the field names.

**Scope ids are explicit path parameters and nothing authorizes them.** A
caller may name any project, user or tenant and this module will read or write
it. That is deliberate for one branch only: W-A owns identity and W-B owns
authorization, and inventing a `CurrentUser` here would be a second answer to a
question another branch is answering now. **W-B is the branch that makes these
routes check that the caller may touch the scope it named** -- every route
below carries that note, and the check belongs at the top of each one.

The one thing that is *not* deferred is secrecy: a secret setting's value never
appears in a response from this module, whatever the caller is allowed to read.
That is enforced by `Resolved.value` being `None` for a secret rather than by a
rule each route remembers -- see `application/settings.py`.
"""

from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from research_team.application.settings import (
    ModelProfileService,
    ModelProfileStorePort,
    ProviderProbePort,
    Resolved,
    ResolvedRole,
    SecretBoxPort,
    SettingsResolver,
    SettingsStorePort,
    StoredProfile,
)
from research_team.domain.providers import PROVIDERS, Provider, UnknownProvider, provider_for
from research_team.domain.settings import (
    CONNECTIONS,
    PROVIDER_KEY_GROUP,
    RESOLUTION_ORDER,
    ROLE_MODEL_KEYS,
    SETTINGS,
    ModelProfile,
    ModelRole,
    Scope,
    ScopeRef,
    SettingError,
    SettingSpec,
    dynamic_specs,
)


@dataclass(frozen=True)
class SettingsDeps:
    """What the settings routes need. Everything is built in composition.

    `store` and `secrets` are optional because both are: a deployment with no
    settings database still serves the schema and the provider catalogue (which
    are static), and one with no `AGENT_SETTINGS_KEY` still reads and writes
    every non-secret setting. Answering 503 for the whole surface because one
    half is unwired would hide the half that works.
    """

    store: SettingsStorePort | None = None
    secrets: SecretBoxPort | None = None
    probe: ProviderProbePort | None = None
    profiles: ModelProfileStorePort | None = None

    async def close(self) -> None:
        """Release both stores' connections.

        Here rather than as two steps in `Application.close`, because
        `test_every_close_step_has_a_partial_build_resource` resolves a step
        through the `Application(...)` keyword that filled the attribute, and
        `self.settings.store.close` has one component too many to resolve. One
        method on the thing composition already passes as a unit keeps the two
        lists derivable from each other, which is the whole point of that test.

        `getattr` rather than a `close()` on the ports: both are deliberately
        dumb about scopes, keys and strings (see `SettingsStorePort`), and a
        lifecycle method on the Protocol would oblige every test double to grow
        one for a resource it does not hold. The production adapters are the
        only implementations that own a connection, and they are the only ones
        this needs to find.

        This is not decoration. `aiosqlite` starts a **non-daemon** worker
        thread per connection, so one unclosed store keeps `threading._shutdown`
        waiting and the interpreter never exits -- B5 and B100's symptom, and
        measured on this branch: CI's `pytest` job finished the suite in 6m26s
        and then sat for a further 78 minutes before being cancelled, with the
        runner reporting orphan `uv` and `pytest` processes.
        """
        for store in (self.store, self.profiles):
            closer = getattr(store, "close", None)
            if closer is not None:
                await closer()


class SettingValue(BaseModel):
    """A write. One field, and it is a string.

    Strings rather than a typed union because every value arrives as text from
    a form anyway, and one parser -- `SettingSpec.parse` -- is what keeps the
    HTTP layer and the environment layer agreeing about what `"on"` means.
    """

    value: str


class ProfileBody(BaseModel):
    """A model profile, minus its name -- the name is the path segment.

    `parameters` is an open dict because it is provider-specific (`temperature`,
    `top_p`, Anthropic's `thinking`, vLLM's `chat_template_kwargs`) and a
    catalogue cannot enumerate what fifteen providers accept. It is stored and
    handed back whole; nothing here interprets it.
    """

    provider_id: str
    model: str
    credential_key: str | None = None
    base_url: str | None = None
    parameters: dict = {}


class RoleBody(BaseModel):
    profile: str


class ProbeRequest(BaseModel):
    api_key: str | None = None
    base_url: str | None = None


def _spec_view(spec: SettingSpec) -> dict:
    return {
        "key": spec.key,
        "env_var": spec.env_var,
        "type": spec.type.value,
        "label": spec.label,
        "description": spec.description,
        "group": spec.group,
        "secret": spec.secret,
        # A secret's default is withheld like any other secret value. The
        # built-in defaults here are placeholders (`not-needed`) rather than
        # real credentials, and publishing them anyway would make "the schema
        # never carries a secret" a claim with an exception in it.
        "default": None if spec.secret else spec.default,
        "choices": list(spec.choices),
        "minimum": spec.minimum,
        "maximum": spec.maximum,
        "required_when": spec.required_when,
        "scopes": sorted(scope.value for scope in spec.scopes),
    }


def _resolved_view(resolved: Resolved) -> dict:
    view = {
        "key": resolved.key,
        "value": resolved.value,
        "layer": resolved.layer,
        "scope_id": resolved.scope_id,
        "secret": resolved.secret,
    }
    if resolved.masked is not None:
        view["masked"] = {
            "present": resolved.masked.present,
            "last_four": resolved.masked.last_four,
            "display": resolved.masked.display,
        }
    return view


def _profile_view(stored: StoredProfile) -> dict:
    return {
        "scope": stored.scope.value,
        "scope_id": stored.scope_id,
        "name": stored.profile.name,
        "provider_id": stored.profile.provider_id,
        "model": stored.profile.model,
        "credential_key": stored.profile.credential_key,
        "base_url": stored.profile.base_url,
        "parameters": stored.profile.parameters,
    }


def _role_view(resolved: ResolvedRole) -> dict:
    return {
        "role": resolved.role.value,
        "model": resolved.model,
        "layer": resolved.layer,
        "scope_id": resolved.scope_id,
        "setting_key": resolved.setting_key,
        "profile": None if resolved.profile is None else resolved.profile.name,
        "dangling": resolved.dangling,
    }


def _provider_view(provider: Provider) -> dict:
    return {
        "id": provider.id,
        "display_name": provider.display_name,
        "base_url": provider.base_url,
        "auth": provider.auth.value,
        "openai_compatible": provider.openai_compatible,
        # Sorted so the response is stable: a `frozenset` iterates in hash
        # order, which differs between runs and would make every snapshot of
        # this endpoint disagree with the last one for no reason.
        "capabilities": sorted(capability.value for capability in provider.capabilities),
        "credentials": [
            {
                "name": credential.name,
                "label": credential.label,
                "secret": credential.secret,
                "required": credential.required,
                "setting_key": credential.setting_key,
            }
            for credential in provider.credentials
        ],
        "notes": provider.notes,
    }


def _chain(project: str | None, user: str | None, tenant: str | None) -> list[ScopeRef]:
    """The scope chain, in resolution order, dropping the ones not named.

    Built here rather than taken from the caller so a request cannot ask for
    user-before-project by reordering its query string -- the order is the
    feature, and `RESOLUTION_ORDER` is the only statement of it.
    """
    named = {Scope.PROJECT: project, Scope.USER: user, Scope.TENANT: tenant}
    return [
        ScopeRef(scope=scope, scope_id=named[scope])
        for scope in RESOLUTION_ORDER
        if named[scope]
    ]


def settings_router(deps: SettingsDeps) -> APIRouter:
    router = APIRouter(prefix="/api")

    def _resolver() -> SettingsResolver:
        return SettingsResolver(deps.store, deps.secrets)

    @router.get("/settings/schema")
    async def settings_schema() -> dict:
        """Every declared setting, grouped for a form.

        Static -- it needs no store and no scope -- which is why it answers even
        on a deployment where nothing else here does. The groups are ordered by
        first appearance in the registry rather than alphabetically, so the
        order of the form is a thing the registry decides and a reviewer can
        see in one file.
        """
        groups: list[dict] = []
        index: dict[str, dict] = {}
        # The declared settings, then the provider credentials the catalogue
        # implies. Both are `SettingSpec`s and are rendered by one code path --
        # a dynamic spec differs from a declared one only in where it was
        # constructed, which is the whole reason `dynamic_spec_for` returns a
        # spec rather than a new type.
        for spec in (*SETTINGS, *dynamic_specs()):
            group = index.get(spec.group)
            if group is None:
                group = {"name": spec.group, "settings": []}
                index[spec.group] = group
                groups.append(group)
            group["settings"].append(_spec_view(spec))
        return {
            "groups": groups,
            "scopes": [scope.value for scope in RESOLUTION_ORDER],
            "roles": [
                {"role": role.value, "setting_key": key}
                for role, key in ROLE_MODEL_KEYS.items()
            ],
            # Which groups can be tested, and with which three keys. On the
            # wire rather than recognised by the client, for the reason the
            # note below gives about `provider_credential_group` and the
            # stronger one `domain/settings/spec.ts` states: the console
            # hand-writes no setting keys at all, so a form that knew "Models
            # is tested with model/base_url/api_key" would be a second, private
            # copy of the registry -- drifting on the commit that renames one.
            "connections": [
                {
                    "role": connection.role.value,
                    "group": connection.group,
                    "model_key": connection.model_key,
                    "base_url_key": connection.base_url_key,
                    "api_key_key": connection.api_key_key,
                }
                for connection in CONNECTIONS
            ],
            # Named rather than left for the client to recognise by prefix.
            # W-C1 renders this group differently -- one row per provider a
            # deployment actually uses, not forty checkboxes -- and a client
            # matching on `"provider_key."` would be a second, private copy of
            # this module's key format.
            "provider_credential_group": PROVIDER_KEY_GROUP,
        }

    @router.get("/settings/resolved")
    async def resolved_settings(
        project: str | None = None,
        user: str | None = None,
        tenant: str | None = None,
    ) -> dict:
        """Every setting's value for this scope chain, with its provenance.

        W-B: authorize `project`, `user` and `tenant` here before reading.

        `layer` is the answer to "why is it that" and is the reason this is one
        endpoint rather than a value endpoint and a separate overrides
        endpoint: a form that shows a value without saying which layer supplied
        it cannot distinguish "this project sets it" from "this is the
        default", and those want different controls.
        """
        chain = _chain(project, user, tenant)
        # Every provider credential, not only the stored ones. A settings page
        # has to be able to show "not set" for a provider nobody has configured
        # yet; listing only what is stored would mean the form could never
        # offer the first one. Bounded at twenty rows by the catalogue.
        keys = [spec.key for spec in (*SETTINGS, *dynamic_specs())]
        answers = await _resolver().resolve_all(keys, chain)
        return {
            "scope_chain": [
                {"scope": ref.scope.value, "scope_id": ref.scope_id} for ref in chain
            ],
            "settings": [_resolved_view(answer) for answer in answers],
        }

    @router.put("/settings/{scope}/{scope_id}/{key}")
    async def write_override(scope: str, scope_id: str, key: str, body: SettingValue) -> dict:
        """Set one override.

        W-B: authorize `scope`/`scope_id` here before writing.

        422 rather than 400 for a value the declaration refuses, matching what
        FastAPI already answers for a malformed body -- a caller should not have
        to tell "the JSON was wrong" from "the number was too small" by status
        code alone, and the detail says which.
        """
        ref = _scope_ref(scope, scope_id)
        try:
            await _resolver().write(ref, key, body.value)
        except SettingError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"scope": ref.scope.value, "scope_id": ref.scope_id, "key": key, "stored": True}

    @router.delete("/settings/{scope}/{scope_id}/{key}", status_code=204)
    async def clear_override(scope: str, scope_id: str, key: str) -> Response:
        """Remove one override, falling back to whatever the next layer says.

        W-B: authorize `scope`/`scope_id` here before writing.

        404 when there was nothing to clear. Clearing a key that was never set
        is almost always a misspelled key, and a 204 there is how the misspelling
        survives to be reported as "the setting will not clear".
        """
        ref = _scope_ref(scope, scope_id)
        try:
            removed = await _resolver().clear(ref, key)
        except SettingError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not removed:
            raise HTTPException(
                status_code=404, detail=f"no {key} override at {scope} {scope_id}"
            )
        return Response(status_code=204)

    def _profiles() -> ModelProfileService:
        return ModelProfileService(deps.profiles, _resolver())

    @router.get("/profiles")
    async def list_profiles(
        project: str | None = None,
        user: str | None = None,
        tenant: str | None = None,
    ) -> dict:
        """The profiles visible from this chain, and what each role resolves to.

        W-B: authorize `project`, `user` and `tenant` here before reading.

        One endpoint rather than two, because the interesting question is the
        pair: a list of profiles says nothing about which is in use, and a list
        of roles with only names in it cannot be rendered without the
        definitions. `dangling` on a role names a selected profile no scope in
        the chain defines -- reported rather than quietly falling back, because
        a role silently repointed at the default model is the exact failure
        this feature exists to prevent.
        """
        chain = _chain(project, user, tenant)
        service = _profiles()
        return {
            "scope_chain": [
                {"scope": ref.scope.value, "scope_id": ref.scope_id} for ref in chain
            ],
            "profiles": [_profile_view(stored) for stored in await service.profiles(chain)],
            "roles": [_role_view(role) for role in await service.roles(chain)],
        }

    @router.put("/profiles/{scope}/{scope_id}/{name}")
    async def write_profile(scope: str, scope_id: str, name: str, body: ProfileBody) -> dict:
        """Define or replace a profile at one scope.

        W-B: authorize `scope`/`scope_id` here before writing.

        The provider id is checked against the catalogue and the credential key
        against the registry, both in the service rather than here, so a CLI or
        an import gets the same refusal.
        """
        ref = _scope_ref(scope, scope_id)
        profile = ModelProfile(
            name=name,
            provider_id=body.provider_id,
            model=body.model,
            credential_key=body.credential_key,
            base_url=body.base_url,
            parameters=body.parameters,
        )
        try:
            await _profiles().put(ref, profile)
        except SettingError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "scope": ref.scope.value,
            "scope_id": ref.scope_id,
            "name": name,
            "stored": True,
        }

    @router.delete("/profiles/{scope}/{scope_id}/{name}", status_code=204)
    async def delete_profile(scope: str, scope_id: str, name: str) -> Response:
        """Remove a profile. 404 when this scope defined none by that name.

        W-B: authorize `scope`/`scope_id` here before writing.

        A role still selecting the deleted name is left selecting it, and reads
        back as `dangling`. Cascading the delete into the selections was
        rejected: a more specific scope may define the same name, in which case
        the selection is still correct, and a delete that silently unpicked a
        role would be a second, invisible write.
        """
        ref = _scope_ref(scope, scope_id)
        try:
            removed = await _profiles().delete(ref, name)
        except SettingError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not removed:
            raise HTTPException(
                status_code=404, detail=f"no profile {name!r} at {scope} {scope_id}"
            )
        return Response(status_code=204)

    @router.put("/profiles/{scope}/{scope_id}/roles/{role}")
    async def select_role(scope: str, scope_id: str, role: str, body: RoleBody) -> dict:
        """Point a role at a profile.

        W-B: authorize `scope`/`scope_id` here before writing.
        """
        ref = _scope_ref(scope, scope_id)
        try:
            await _profiles().select(ref, _role(role), body.profile)
        except SettingError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "scope": ref.scope.value,
            "scope_id": ref.scope_id,
            "role": role,
            "profile": body.profile,
        }

    @router.delete("/profiles/{scope}/{scope_id}/roles/{role}", status_code=204)
    async def clear_role(scope: str, scope_id: str, role: str) -> Response:
        """Stop selecting a profile for a role, falling back to its setting.

        W-B: authorize `scope`/`scope_id` here before writing.
        """
        ref = _scope_ref(scope, scope_id)
        try:
            removed = await _profiles().clear(ref, _role(role))
        except SettingError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not removed:
            raise HTTPException(
                status_code=404, detail=f"no {role} selection at {scope} {scope_id}"
            )
        return Response(status_code=204)

    @router.get("/providers")
    async def list_providers() -> dict:
        """The catalogue. Static data; no credential of any kind appears here."""
        return {"providers": [_provider_view(provider) for provider in PROVIDERS]}

    @router.post("/providers/{provider_id}/test")
    async def test_provider(provider_id: str, body: ProbeRequest) -> dict:
        """Ask a provider whether these credentials reach it.

        W-B: authorize the caller here -- this reaches an arbitrary URL on the
        server's network, which is the one route in this module that does
        anything a firewall cares about.

        The key travels in the request body and is used once; it is not stored
        by this route. A caller testing a key it has already saved sends it
        again rather than this route reading it back out of the store, which
        would be a read path for a secret in all but name.
        """
        try:
            provider = provider_for(provider_id)
        except UnknownProvider as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        if deps.probe is None:
            raise HTTPException(
                status_code=503, detail="no provider probe is wired in this build"
            )
        result = await deps.probe.probe(provider, body.api_key, body.base_url)
        return {
            "provider_id": result.provider_id,
            "outcome": result.outcome.value,
            "ok": result.ok,
            "detail": result.detail,
            "models": list(result.models),
            "latency_ms": result.latency_ms,
        }

    return router


def _role(role: str) -> ModelRole:
    """A role name from a path segment, or a 422 naming the five.

    The same shape as `_scope_ref` below and for the same reason: an enum
    constructed from an untrusted segment raises `ValueError`, which FastAPI
    would answer 500 rather than telling the caller what the five roles are.
    """
    try:
        return ModelRole(role)
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=f"{role!r} is not one of {', '.join(r.value for r in ModelRole)}",
        ) from error


def _scope_ref(scope: str, scope_id: str) -> ScopeRef:
    try:
        return ScopeRef(scope=Scope(scope), scope_id=scope_id)
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=f"{scope!r} is not one of {', '.join(s.value for s in RESOLUTION_ORDER)}",
        ) from error
