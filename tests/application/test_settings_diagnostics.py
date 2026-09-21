"""Tests for settings diagnostics and configuration health check."""

import pytest

from research_team.infrastructure.settings.profiles import ModelProfileStore
from research_team.infrastructure.settings.secrets import AesGcmSecretBox
from research_team.infrastructure.settings.store import SettingsStore
from research_team.settings.application import (
    DiagnosticSeverity,
    ModelProfileService,
    SettingsResolver,
)
from research_team.settings.domain import (
    ModelProfile,
    ModelRole,
    Scope,
    ScopeRef,
    SettingError,
)

PROJECT = ScopeRef(scope=Scope.PROJECT, scope_id="project-1")
CHAIN = [PROJECT]


@pytest.fixture
async def setup_env(tmp_path):
    path = str(tmp_path / "settings.db")
    box = AesGcmSecretBox("correct-key-32-bytes-long-secret")
    settings = SettingsStore(path)
    profiles = ModelProfileStore(path)
    resolver = SettingsResolver(settings, box, {})
    profile_service = ModelProfileService(profiles, resolver)
    yield settings, profiles, box, resolver, profile_service
    await profiles.close()
    await settings.close()


async def test_diagnostics_on_empty_store_is_healthy(setup_env):
    _, _, _, resolver, profile_service = setup_env
    diagnostics = await resolver.diagnose(CHAIN, profile_service)

    assert diagnostics.healthy is True
    assert diagnostics.error_count == 0
    assert len(diagnostics.issues) == 0


async def test_diagnostics_catches_unreadable_secret(setup_env):
    settings, _, _, _, profile_service = setup_env
    # Stored secret sealed with a different key that cannot be decrypted
    bad_box = AesGcmSecretBox("wrong-key-32-bytes-long-secret--")
    ciphertext = bad_box.seal("super-secret")
    await settings.put(PROJECT, "api_key", ciphertext)

    # Use resolver with original key
    different_resolver = SettingsResolver(
        settings, AesGcmSecretBox("correct-key-32-bytes-long-secret"), {}
    )
    diagnostics = await different_resolver.diagnose(CHAIN, profile_service)

    assert diagnostics.healthy is False
    assert diagnostics.error_count >= 1
    unreadable = [i for i in diagnostics.issues if i.code == "unreadable_secret"]
    assert len(unreadable) == 1
    assert unreadable[0].key == "api_key"
    assert unreadable[0].severity == DiagnosticSeverity.ERROR


async def test_diagnostics_catches_dangling_profile(setup_env):
    _, profiles, _, resolver, profile_service = setup_env
    await profiles.select(PROJECT, ModelRole.RESEARCH, "nonexistent-profile")

    diagnostics = await resolver.diagnose(CHAIN, profile_service)

    dangling = [i for i in diagnostics.issues if i.code == "dangling_profile"]
    assert len(dangling) == 1
    assert dangling[0].role == "research"
    assert dangling[0].profile == "nonexistent-profile"
    assert dangling[0].severity == DiagnosticSeverity.WARNING


async def test_diagnostics_catches_incompatible_profile(setup_env):
    _, profiles, _, resolver, profile_service = setup_env
    # Define a deepseek profile (which only supports chat, not embeddings)
    deepseek_profile = ModelProfile(
        name="deepseek-fast",
        provider_id="deepseek",
        model="deepseek-chat",
    )
    await profiles.put_profile(PROJECT, deepseek_profile)
    # Directly store selection bypassing select() check
    await profiles.select(PROJECT, ModelRole.EMBEDDING, "deepseek-fast")

    diagnostics = await resolver.diagnose(CHAIN, profile_service)

    assert diagnostics.healthy is False
    incompatible = [i for i in diagnostics.issues if i.code == "incompatible_profile"]
    assert len(incompatible) == 1
    assert incompatible[0].role == "embedding"
    assert incompatible[0].profile == "deepseek-fast"
    assert incompatible[0].severity == DiagnosticSeverity.ERROR


async def test_service_select_refuses_incompatible_profile(setup_env):
    _, _, _, _, profile_service = setup_env
    # Define deepseek profile
    deepseek_profile = ModelProfile(
        name="deepseek-fast",
        provider_id="deepseek",
        model="deepseek-chat",
    )
    await profile_service.put(PROJECT, deepseek_profile)

    # Trying to select it for embedding should fail fast
    with pytest.raises(SettingError, match="does not support embedding role"):
        await profile_service.select(PROJECT, ModelRole.EMBEDDING, "deepseek-fast")


async def test_diagnostics_catches_missing_conditional_transcriber_model(setup_env):
    settings, _, _, resolver, profile_service = setup_env
    # Set transcriber_url without transcriber_model
    await settings.put(PROJECT, "transcriber_url", "http://localhost:8080")

    diagnostics = await resolver.diagnose(CHAIN, profile_service)

    assert diagnostics.healthy is False
    missing = [i for i in diagnostics.issues if i.code == "missing_conditional_setting"]
    assert any(i.key == "transcriber_model" for i in missing)


async def test_diagnostics_catches_invalid_stored_value(setup_env):
    settings, _, _, resolver, profile_service = setup_env
    # Store invalid integer value for context_trigger
    await settings.put(PROJECT, "context_trigger", "not-a-number")

    diagnostics = await resolver.diagnose(CHAIN, profile_service)

    invalid = [i for i in diagnostics.issues if i.code == "invalid_stored_value"]
    assert len(invalid) == 1
    assert invalid[0].key == "context_trigger"
    assert invalid[0].severity == DiagnosticSeverity.WARNING


async def test_diagnostics_catches_unknown_setting_override(setup_env):
    settings, _, _, resolver, profile_service = setup_env
    await settings.put(PROJECT, "completely_unknown_key", "some-value")

    diagnostics = await resolver.diagnose(CHAIN, profile_service)

    unknown = [i for i in diagnostics.issues if i.code == "unknown_setting_override"]
    assert len(unknown) == 1
    assert unknown[0].key == "completely_unknown_key"
    assert unknown[0].severity == DiagnosticSeverity.WARNING
