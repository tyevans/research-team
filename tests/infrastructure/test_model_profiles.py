"""Model profiles and role selection, over the real store.

`ModelProfileStorePort` has exactly one production adapter, which is the shape
CLAUDE.md's "Events" section names as the one that ships broken -- so every
test here drives `ModelProfileService` against a `ModelProfileStore` on a real
SQLite file, with a real `SettingsResolver` over a real `SettingsStore`
underneath it. No doubles.

What that buys over a fake store, concretely: the JSON round trip of
`parameters`, the empty-string-for-`None` convention on `credential_key` and
`base_url`, and the `datetime` column that `SettingsStore` got wrong first time
are all adapter behaviour a fake would have been free to get right.
"""

import pytest

from research_team.application.settings import ModelProfileService, SettingsResolver
from research_team.domain.settings import (
    ModelProfile,
    ModelRole,
    Scope,
    ScopeRef,
    SettingError,
)
from research_team.infrastructure.settings.profiles import ModelProfileStore
from research_team.infrastructure.settings.store import SettingsStore

PROJECT = ScopeRef(scope=Scope.PROJECT, scope_id="project-1")
USER = ScopeRef(scope=Scope.USER, scope_id="user-1")
TENANT = ScopeRef(scope=Scope.TENANT, scope_id="tenant-1")
CHAIN = [PROJECT, USER, TENANT]


@pytest.fixture
async def service(tmp_path):
    """The service over both real stores, sharing one database file.

    Two stores and one file, which is what composition does: the settings the
    roles fall back to and the profiles that override them have to be read
    against the same scopes, and splitting the file would make a test that
    passes say nothing about the wiring that ships.
    """
    path = str(tmp_path / "settings.db")
    profiles = ModelProfileStore(path)
    settings = SettingsStore(path)
    yield ModelProfileService(profiles, SettingsResolver(settings, None, {}))
    await profiles.close()
    await settings.close()


def _profile(name: str = "groq-fast", **overrides) -> ModelProfile:
    fields = {
        "name": name,
        "provider_id": "groq",
        "model": "llama-3.3-70b-versatile",
    }
    fields.update(overrides)
    return ModelProfile(**fields)


async def test_a_profile_survives_the_round_trip_whole(service):
    """Every field, including the two that are not stored as themselves.

    `credential_key` and `base_url` go to the table as empty strings and come
    back as `None`, and `parameters` goes as JSON. A fake store would have
    handed back the object it was given and proved none of that.
    """
    await service.put(
        TENANT,
        _profile(
            credential_key="provider_key.groq",
            base_url="https://api.groq.com/openai/v1/",
            parameters={"temperature": 0, "top_p": 0.9},
        ),
    )

    (stored,) = await service.profiles(CHAIN)

    assert stored.profile.name == "groq-fast"
    assert stored.profile.provider_id == "groq"
    assert stored.profile.credential_key == "provider_key.groq"
    assert stored.profile.base_url == "https://api.groq.com/openai/v1/"
    assert stored.profile.parameters == {"temperature": 0, "top_p": 0.9}
    assert stored.scope is Scope.TENANT


async def test_an_absent_credential_comes_back_as_none_not_an_empty_string(service):
    """The convention the column uses must not leak.

    An empty string here would be a `credential_key` that looks set, and
    `resolve_spec("")` raises -- so the leak would surface as a 500 on the next
    write rather than as a wrong-looking form field.
    """
    await service.put(TENANT, _profile())

    (stored,) = await service.profiles(CHAIN)

    assert stored.profile.credential_key is None
    assert stored.profile.base_url is None


async def test_a_profile_naming_no_catalogue_provider_is_refused(service):
    """`provider_id` selects an adapter and is stored. Free text there is
    unvalidated input in a storage key."""
    with pytest.raises(SettingError, match="evilcorp"):
        await service.put(TENANT, _profile(provider_id="evilcorp"))


async def test_a_profile_credential_must_name_a_secret(service):
    """It is what a call is authenticated with. Pointing it at an ordinary
    setting would put a non-secret on the credential path."""
    with pytest.raises(SettingError, match="not a secret"):
        await service.put(TENANT, _profile(credential_key="model"))


async def test_a_profile_may_name_a_dynamic_provider_credential(service):
    """The pairing the whole branch exists for: fifteen providers, and a
    credential key for each of them that a profile can point at."""
    await service.put(TENANT, _profile(credential_key="provider_key.groq"))

    (stored,) = await service.profiles(CHAIN)

    assert stored.profile.credential_key == "provider_key.groq"


async def test_a_project_profile_shadows_a_tenant_one_of_the_same_name(service):
    """One name, one entry -- the more specific.

    Returning both would make the list disagree with the resolution it
    describes, and a form rendering two rows called `shared` cannot say which
    one a role would get.
    """
    await service.put(TENANT, _profile("shared", model="tenant-model"))
    await service.put(PROJECT, _profile("shared", model="project-model"))

    visible = await service.profiles(CHAIN)

    assert [stored.profile.model for stored in visible] == ["project-model"]
    assert visible[0].scope is Scope.PROJECT


async def test_a_role_with_no_selection_falls_back_to_its_setting(service):
    """And the fallback is reported as such, not dressed as a choice."""
    roles = {resolved.role: resolved for resolved in await service.roles(CHAIN)}

    assert roles[ModelRole.RESEARCH].model == "qwen3.6-27b-mtp"
    assert roles[ModelRole.RESEARCH].profile is None
    assert roles[ModelRole.RESEARCH].layer == "default"
    assert roles[ModelRole.RESEARCH].setting_key == "model"


async def test_selecting_a_profile_moves_one_role_and_not_the_others(service):
    """The defect, asserted as a pair.

    Research and extraction both resolved from `model` until this branch, so
    choosing a cheap extraction model silently repointed the research agent.
    Asserting only that extraction moved passes under the old, shared mapping;
    the second assertion is the one that fails there.
    """
    await service.put(TENANT, _profile())
    await service.select(PROJECT, ModelRole.EXTRACTION, "groq-fast")

    roles = {resolved.role: resolved for resolved in await service.roles(CHAIN)}

    assert roles[ModelRole.EXTRACTION].model == "llama-3.3-70b-versatile"
    assert roles[ModelRole.EXTRACTION].layer == "project"
    assert roles[ModelRole.RESEARCH].model == "qwen3.6-27b-mtp"
    assert roles[ModelRole.RESEARCH].profile is None


async def test_a_project_may_select_a_profile_the_tenant_defined(service):
    """Why the two walks are separate: a shared team credential is defined once
    at the tenant and selected per project. One walk would force every project
    to redefine it."""
    await service.put(TENANT, _profile("shared", provider_id="openai", model="gpt-4o-mini"))
    await service.select(PROJECT, ModelRole.CURATION, "shared")

    roles = {resolved.role: resolved for resolved in await service.roles(CHAIN)}

    assert roles[ModelRole.CURATION].model == "gpt-4o-mini"
    assert roles[ModelRole.CURATION].layer == "project"


async def test_a_more_specific_selection_wins(service):
    """All three scopes selecting at once, then removed one at a time.

    One selection is passed by every ordering of the three -- the CLAUDE.md
    trap about a formula correct on every case a test naturally reaches -- so
    the property that distinguishes the candidate walks is several scopes
    choosing at the same time.
    """
    await service.put(TENANT, _profile("t", model="tenant-model"))
    await service.put(TENANT, _profile("u", model="user-model"))
    await service.put(TENANT, _profile("p", model="project-model"))
    await service.select(TENANT, ModelRole.VISION, "t")
    await service.select(USER, ModelRole.VISION, "u")
    await service.select(PROJECT, ModelRole.VISION, "p")

    async def vision() -> str:
        roles = {resolved.role: resolved for resolved in await service.roles(CHAIN)}
        return roles[ModelRole.VISION].model

    assert await vision() == "project-model"
    await service.clear(PROJECT, ModelRole.VISION)
    assert await vision() == "user-model"
    await service.clear(USER, ModelRole.VISION)
    assert await vision() == "tenant-model"


async def test_a_selection_pointing_at_nothing_is_named_rather_than_ignored(service):
    """A role silently repointed at the default model is the exact failure this
    feature exists to prevent, so a dangling selection is reported.

    The fallback still happens -- a role always has a model, because something
    has to be called -- but the caller is told the selection did not resolve.
    """
    await service.select(PROJECT, ModelRole.VISION, "never-defined")

    roles = {resolved.role: resolved for resolved in await service.roles(CHAIN)}

    assert roles[ModelRole.VISION].dangling == "never-defined"
    assert roles[ModelRole.VISION].profile is None
    assert roles[ModelRole.VISION].model


async def test_deleting_a_profile_leaves_the_selection_pointing_at_it(service):
    """Cascading was rejected: a more specific scope may define the same name,
    in which case the selection is still correct, and a delete that quietly
    unpicked a role would be a second, invisible write."""
    await service.put(PROJECT, _profile())
    await service.select(PROJECT, ModelRole.EXTRACTION, "groq-fast")

    assert await service.delete(PROJECT, "groq-fast") is True

    roles = {resolved.role: resolved for resolved in await service.roles(CHAIN)}
    assert roles[ModelRole.EXTRACTION].dangling == "groq-fast"


async def test_deleting_what_was_never_defined_says_so(service):
    """False, not a silent success -- the route turns it into a 404."""
    assert await service.delete(PROJECT, "nothing") is False
    assert await service.clear(PROJECT, ModelRole.VISION) is False


async def test_profiles_outlive_the_process(tmp_path):
    """The table is real and the rows persist.

    An in-memory double passes every other test in this file; only this one
    fails against one.
    """
    path = str(tmp_path / "settings.db")

    first = ModelProfileStore(path)
    await ModelProfileService(first, SettingsResolver(SettingsStore(path), None, {})).put(
        PROJECT, _profile(parameters={"temperature": 0})
    )
    await first.close()

    second = ModelProfileStore(path)
    service = ModelProfileService(second, SettingsResolver(SettingsStore(path), None, {}))
    (stored,) = await service.profiles(CHAIN)
    await second.close()

    assert stored.profile.model == "llama-3.3-70b-versatile"
    assert stored.profile.parameters == {"temperature": 0}
