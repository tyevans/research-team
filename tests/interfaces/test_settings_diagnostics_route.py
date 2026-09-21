"""Tests for settings diagnostics and role compatibility web routes."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from research_team.infrastructure.settings.profiles import ModelProfileStore
from research_team.infrastructure.settings.secrets import AesGcmSecretBox
from research_team.infrastructure.settings.store import SettingsStore
from research_team.interfaces.web.app import create_app
from research_team.interfaces.web.settings import SettingsDeps


@pytest.fixture
async def client_and_deps(tmp_path):
    path = str(tmp_path / "settings.db")
    box = AesGcmSecretBox("correct-key-32-bytes-long-secret")
    store = await SettingsStore.open(path)
    profiles = await ModelProfileStore.open(path)
    deps = SettingsDeps(store=store, secrets=box, profiles=profiles)
    app = create_app(service=Mock(), feed=Mock(), turns=Mock(), settings=deps)
    client = TestClient(app)
    yield client, deps, store, profiles
    await deps.close()


def test_diagnostics_endpoint_returns_200_and_schema(client_and_deps):
    client, _, _, _ = client_and_deps
    response = client.get("/api/settings/diagnostics?project=p1")
    assert response.status_code == 200
    body = response.json()
    assert "healthy" in body
    assert body["healthy"] is True
    assert body["error_count"] == 0
    assert body["warning_count"] == 0
    assert "issues" in body
    assert isinstance(body["issues"], list)


def test_selecting_incompatible_profile_returns_422(client_and_deps):
    client, _, _, _ = client_and_deps
    # 1. Create a deepseek profile (chat only, no embeddings)
    create_resp = client.put(
        "/api/profiles/project/p1/deepseek-chat-only",
        json={
            "provider_id": "deepseek",
            "model": "deepseek-chat",
        },
    )
    assert create_resp.status_code == 200

    # 2. Try to select it for embedding role
    select_resp = client.put(
        "/api/profiles/project/p1/roles/embedding",
        json={"profile": "deepseek-chat-only"},
    )
    assert select_resp.status_code == 422
    assert "does not support embedding role" in select_resp.json()["detail"]


def test_profiles_endpoint_includes_incompatible_field(client_and_deps):
    client, _, _, _ = client_and_deps
    response = client.get("/api/profiles?project=p1")
    assert response.status_code == 200
    body = response.json()
    for role in body["roles"]:
        assert "incompatible" in role
        assert role["incompatible"] is None
