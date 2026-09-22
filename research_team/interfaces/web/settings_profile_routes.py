"""HTTP routes for model profiles and provider testing."""

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from research_team.interfaces.web.settings_deps import SettingsDeps
from research_team.settings.application import (
    ModelProfileService,
    ResolvedRole,
    SettingsResolver,
    StoredProfile,
)
from research_team.settings.domain import (
    ModelProfile,
    ModelRole,
    ScopeRef,
    SettingError,
)
from research_team.settings.domain.providers import (
    PROVIDERS,
    Provider,
    UnknownProvider,
    provider_for,
)

__all__ = [
    "ProbeRequest",
    "ProfileBody",
    "RoleBody",
    "register_profile_and_provider_routes",
]


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
        "incompatible": resolved.incompatible,
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


def register_profile_and_provider_routes(
    router: APIRouter,
    deps: SettingsDeps,
    chain_builder: Callable[[str | None, str | None, str | None], list[ScopeRef]],
    scope_ref_builder: Callable[[str, str], ScopeRef],
    resolver_builder: Callable[[], SettingsResolver],
) -> None:
    """Register profile management and provider test routes onto router."""

    def _profiles() -> ModelProfileService:
        return ModelProfileService(deps.profiles, resolver_builder())

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
        chain = chain_builder(project, user, tenant)
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
        ref = scope_ref_builder(scope, scope_id)
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
        ref = scope_ref_builder(scope, scope_id)
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
    async def select_role(
        scope: str,
        scope_id: str,
        role: str,
        body: RoleBody,
        project: str | None = None,
        user: str | None = None,
        tenant: str | None = None,
    ) -> dict:
        """Point a role at a profile.

        W-B: authorize `scope`/`scope_id` here before writing.
        """
        ref = scope_ref_builder(scope, scope_id)
        chain = chain_builder(project, user, tenant)
        try:
            await _profiles().select(
                ref, _role(role), body.profile, chain=chain if chain else None
            )
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
        ref = scope_ref_builder(scope, scope_id)
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
