"""Tests for ModelProfile validation and role capability checks."""

import pytest

from research_team.settings.domain import (
    ROLE_CAPABILITIES,
    Capability,
    ModelProfile,
    ModelRole,
    SettingError,
    provider_for,
    provider_supports_role,
)


def test_valid_model_profile_passes_validation():
    profile = ModelProfile(
        name="test-profile",
        provider_id="openai",
        model="gpt-4o",
        base_url="https://api.openai.com/v1/",
        credential_key="provider_key.openai",
        parameters={"temperature": 0.7, "max_tokens": 1000},
    )
    profile.validate()


def test_empty_name_is_rejected():
    profile = ModelProfile(
        name="   ",
        provider_id="openai",
        model="gpt-4o",
    )
    with pytest.raises(SettingError, match="needs a name"):
        profile.validate()


def test_empty_provider_id_is_rejected():
    profile = ModelProfile(
        name="test",
        provider_id="  ",
        model="gpt-4o",
    )
    with pytest.raises(SettingError, match="needs a provider_id"):
        profile.validate()


def test_empty_model_is_rejected():
    profile = ModelProfile(
        name="test",
        provider_id="openai",
        model="",
    )
    with pytest.raises(SettingError, match="needs a model"):
        profile.validate()


def test_invalid_base_url_scheme_is_rejected():
    profile = ModelProfile(
        name="test",
        provider_id="openai",
        model="gpt-4o",
        base_url="ftp://example.com",
    )
    with pytest.raises(SettingError, match="must start with http:// or https://"):
        profile.validate()

    profile2 = ModelProfile(
        name="test",
        provider_id="openai",
        model="gpt-4o",
        base_url="invalid-url",
    )
    with pytest.raises(SettingError, match="must start with http:// or https://"):
        profile2.validate()


def test_parameters_must_have_string_keys():
    profile = ModelProfile(
        name="test",
        provider_id="openai",
        model="gpt-4o",
        parameters={"": "empty_key"},  # type: ignore[dict-item]
    )
    with pytest.raises(SettingError, match="keys must be non-empty strings"):
        profile.validate()


def test_role_capabilities_mapping():
    assert ROLE_CAPABILITIES[ModelRole.RESEARCH] == Capability.CHAT
    assert ROLE_CAPABILITIES[ModelRole.EXTRACTION] == Capability.CHAT
    assert ROLE_CAPABILITIES[ModelRole.CURATION] == Capability.CHAT
    assert ROLE_CAPABILITIES[ModelRole.EMBEDDING] == Capability.EMBEDDINGS
    assert ROLE_CAPABILITIES[ModelRole.VISION] == Capability.VISION


def test_provider_supports_role():
    openai = provider_for("openai")
    assert provider_supports_role(openai, ModelRole.RESEARCH) is True
    assert provider_supports_role(openai, ModelRole.EXTRACTION) is True
    assert provider_supports_role(openai, ModelRole.CURATION) is True
    assert provider_supports_role(openai, ModelRole.EMBEDDING) is True
    assert provider_supports_role(openai, ModelRole.VISION) is True

    deepseek = provider_for("deepseek")
    assert provider_supports_role(deepseek, ModelRole.RESEARCH) is True
    assert provider_supports_role(deepseek, ModelRole.EXTRACTION) is True
    assert provider_supports_role(deepseek, ModelRole.CURATION) is True
    # DeepSeek only supports CHAT and TOOLS
    assert provider_supports_role(deepseek, ModelRole.EMBEDDING) is False
    assert provider_supports_role(deepseek, ModelRole.VISION) is False

    groq = provider_for("groq")
    assert provider_supports_role(groq, ModelRole.RESEARCH) is True
    assert provider_supports_role(groq, ModelRole.VISION) is True
    # Groq has no embeddings
    assert provider_supports_role(groq, ModelRole.EMBEDDING) is False
