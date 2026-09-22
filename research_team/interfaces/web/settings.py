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

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from research_team.interfaces.web.settings_deps import SettingsDeps
from research_team.interfaces.web.settings_profile_routes import (
    register_profile_and_provider_routes,
)
from research_team.settings.application import (
    ModelProfileService,
    Resolved,
    SettingsResolver,
)
from research_team.settings.domain import (
    CONNECTIONS,
    PROVIDER_KEY_GROUP,
    RESOLUTION_ORDER,
    ROLE_MODEL_KEYS,
    SETTINGS,
    Scope,
    ScopeRef,
    SettingError,
    SettingSpec,
    dynamic_specs,
)

__all__ = [
    "SettingsDeps",
    "settings_router",
]


class SettingValue(BaseModel):
    """A write. One field, and it is a string.

    Strings rather than a typed union because every value arrives as text from
    a form anyway, and one parser -- `SettingSpec.parse` -- is what keeps the
    HTTP layer and the environment layer agreeing about what `"on"` means.
    """

    value: str


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

    def _profiles() -> ModelProfileService:
        return ModelProfileService(deps.profiles, _resolver())

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

    @router.get("/settings/diagnostics")
    async def settings_diagnostics(
        project: str | None = None,
        user: str | None = None,
        tenant: str | None = None,
    ) -> dict:
        """Run diagnostics on settings and profiles for this scope chain.

        W-B: authorize `project`, `user` and `tenant` here before reading.
        """
        chain = _chain(project, user, tenant)
        diagnostics = await _resolver().diagnose(chain, _profiles())
        return {
            "scope_chain": [
                {"scope": ref.scope.value, "scope_id": ref.scope_id} for ref in chain
            ],
            "healthy": diagnostics.healthy,
            "error_count": diagnostics.error_count,
            "warning_count": diagnostics.warning_count,
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity.value,
                    "message": issue.message,
                    "key": issue.key,
                    "scope": issue.scope,
                    "scope_id": issue.scope_id,
                    "role": issue.role,
                    "profile": issue.profile,
                }
                for issue in diagnostics.issues
            ],
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

    register_profile_and_provider_routes(router, deps, _chain, _scope_ref, _resolver)

    return router


def _scope_ref(scope: str, scope_id: str) -> ScopeRef:
    try:
        return ScopeRef(scope=Scope(scope), scope_id=scope_id)
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail=f"{scope!r} is not one of {', '.join(s.value for s in RESOLUTION_ORDER)}",
        ) from error
