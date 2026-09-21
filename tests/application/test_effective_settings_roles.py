"""Tests for effective curation, vision, and embedding settings resolution."""

from uuid import UUID

import pytest

from research_team.infrastructure import config
from research_team.infrastructure.settings.profiles import ModelProfileStore
from research_team.infrastructure.settings.secrets import AesGcmSecretBox
from research_team.infrastructure.settings.store import SettingsStore
from research_team.settings.application.effective import (
    CurationSettings,
    EffectiveSettings,
    EmbeddingSettings,
    SettingsRevision,
    VisionSettings,
)
from research_team.settings.domain import ModelProfile, ModelRole, Scope, ScopeRef

PROJECT_ID = UUID("0f4a1c6e-2b7d-4a51-9c33-5d8e17b04a92")
PROJECT = ScopeRef(scope=Scope.PROJECT, scope_id=str(PROJECT_ID))


@pytest.fixture
def revision() -> SettingsRevision:
    return SettingsRevision()


@pytest.fixture
async def stores(tmp_path, revision):
    settings = await SettingsStore.open(str(tmp_path / "settings.db"), revision=revision)
    profiles = await ModelProfileStore.open(str(tmp_path / "settings.db"), revision=revision)
    yield settings, profiles
    await settings.close()
    await profiles.close()


@pytest.fixture
def box() -> AesGcmSecretBox:
    return AesGcmSecretBox("a-test-key-nobody-uses-in-anger")


@pytest.fixture
def effective(stores, box, revision) -> EffectiveSettings:
    settings, profiles = stores
    return EffectiveSettings(store=settings, secrets=box, profiles=profiles, revision=revision)


async def test_headless_curation_vision_and_embedding_match_config():
    effective = EffectiveSettings()

    curation = await effective.curation(None)
    assert curation == CurationSettings(
        model=config.curation_model(),
        base_url=config.base_url(),
        api_key=config.api_key(),
    )

    vision = await effective.vision(None)
    assert vision == VisionSettings(
        model=config.vision_model(),
        base_url=config.base_url(),
        api_key=config.api_key(),
    )

    embedding = await effective.embedding(None)
    assert embedding == EmbeddingSettings(
        model=config.embedding_model(),
        dimension=config.embedding_dimension(),
        base_url=config.embedding_base_url(),
        api_key=config.embedding_api_key(),
    )


async def test_project_curation_override(effective, stores):
    settings, _ = stores
    await settings.put(PROJECT, "curation_model", "custom-curator")

    curation = await effective.curation(PROJECT_ID)
    assert curation.model == "custom-curator"


async def test_project_vision_override(effective, stores):
    settings, _ = stores
    await settings.put(PROJECT, "vision_model", "custom-vision")

    vision = await effective.vision(PROJECT_ID)
    assert vision.model == "custom-vision"


async def test_project_embedding_override(effective, stores):
    settings, _ = stores
    await settings.put(PROJECT, "embedding_model", "text-embedding-3-small")
    await settings.put(PROJECT, "embedding_dimension", "1536")

    embedding = await effective.embedding(PROJECT_ID)
    assert embedding.model == "text-embedding-3-small"
    assert embedding.dimension == 1536


async def test_profile_selection_overrides_curation(effective, stores, box):
    settings, profiles = stores
    # Seal a secret for the profile
    await settings.put(PROJECT, "provider_key.openai.api_key", box.seal("sk-proj-curation"))
    profile = ModelProfile(
        name="curation-profile",
        provider_id="openai",
        model="gpt-4o",
        base_url="https://custom.openai.endpoint/v1/",
        credential_key="provider_key.openai.api_key",
    )
    await profiles.put_profile(PROJECT, profile)
    await profiles.select(PROJECT, ModelRole.CURATION, "curation-profile")

    curation = await effective.curation(PROJECT_ID)
    assert curation.model == "gpt-4o"
    assert curation.base_url == "https://custom.openai.endpoint/v1/"
    assert curation.api_key == "sk-proj-curation"


async def test_profile_selection_overrides_embedding_with_dimension(effective, stores):
    _, profiles = stores
    profile = ModelProfile(
        name="embed-profile",
        provider_id="openai",
        model="text-embedding-3-large",
        parameters={"dimension": 3072},
    )
    await profiles.put_profile(PROJECT, profile)
    await profiles.select(PROJECT, ModelRole.EMBEDDING, "embed-profile")

    embedding = await effective.embedding(PROJECT_ID)
    assert embedding.model == "text-embedding-3-large"
    assert embedding.dimension == 3072


async def test_cache_invalidation_on_revision_bump(effective, stores, revision):
    settings, _ = stores
    initial = await effective.curation(PROJECT_ID)
    assert initial.model == config.curation_model()

    await settings.put(PROJECT, "curation_model", "updated-curation")
    # Store.put bumps revision
    updated = await effective.curation(PROJECT_ID)
    assert updated.model == "updated-curation"
