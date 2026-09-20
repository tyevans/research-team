"""The model profile and role selection HTTP contract.

Tests the profile CRUD and role-to-profile selection endpoints mounted on
the settings router.
"""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from research_team.domain.providers import ProbeOutcome, ProbeResult
from research_team.infrastructure.settings.profiles import ModelProfileStore
from research_team.infrastructure.settings.secrets import AesGcmSecretBox
from research_team.infrastructure.settings.store import SettingsStore
from research_team.interfaces.web.app import create_app
from research_team.interfaces.web.settings import SettingsDeps


class RecordingProbe:
    """A double for the network, not for the adapter."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str | None]] = []

    async def probe(self, provider, api_key, base_url=None):
        self.seen.append((provider.id, api_key))
        return ProbeResult(
            provider_id=provider.id,
            outcome=ProbeOutcome.OK,
            detail="answered 200",
            models=("some-model",),
            latency_ms=12,
        )


@pytest.fixture
def probe() -> RecordingProbe:
    return RecordingProbe()


@pytest.fixture
def client(tmp_path, probe) -> TestClient:
    path = str(tmp_path / "settings.db")
    deps = SettingsDeps(
        store=SettingsStore(path),
        secrets=AesGcmSecretBox("a-test-key-nobody-uses-in-anger"),
        probe=probe,
        profiles=ModelProfileStore(path),
    )
    return TestClient(
        create_app(service=Mock(), feed=Mock(), turns=Mock(), settings=deps),
        raise_server_exceptions=False,
    )


@pytest.fixture
def client_without_profiles(tmp_path, probe) -> TestClient:
    """Settings wired, profiles not. The half-wired state a build reaches on
    its way to being wired, and the one where a 503 for the whole endpoint
    would hide the half that works."""
    deps = SettingsDeps(
        store=SettingsStore(str(tmp_path / "settings.db")),
        secrets=AesGcmSecretBox("a-test-key-nobody-uses-in-anger"),
        probe=probe,
    )
    return TestClient(
        create_app(service=Mock(), feed=Mock(), turns=Mock(), settings=deps),
        raise_server_exceptions=False,
    )


def test_a_profile_is_stored_and_read_back(client):
    written = client.put(
        "/api/profiles/project/p1/groq-fast",
        json={
            "provider_id": "groq",
            "model": "llama-3.3-70b-versatile",
            "credential_key": "provider_key.groq",
            "parameters": {"temperature": 0},
        },
    )
    assert written.status_code == 200

    body = client.get("/api/profiles?project=p1").json()
    (profile,) = body["profiles"]
    assert profile["name"] == "groq-fast"
    assert profile["provider_id"] == "groq"
    assert profile["model"] == "llama-3.3-70b-versatile"
    assert profile["credential_key"] == "provider_key.groq"
    assert profile["parameters"] == {"temperature": 0}
    assert profile["scope"] == "project"


def test_a_profile_naming_a_provider_that_does_not_exist_is_refused(client):
    response = client.put(
        "/api/profiles/project/p1/nope", json={"provider_id": "evilcorp", "model": "m"}
    )

    assert response.status_code == 422


def test_a_profile_credential_must_be_a_secret(client):
    """`credential_key` is what a call is authenticated with. Pointing it at an
    ordinary setting would put a non-secret on the credential path and render a
    secret-shaped field in the UI that is not one."""
    response = client.put(
        "/api/profiles/project/p1/wrong",
        json={"provider_id": "groq", "model": "m", "credential_key": "model"},
    )

    assert response.status_code == 422
    assert "not a secret" in response.json()["detail"]


def test_selecting_a_profile_for_a_role_changes_only_that_role(client):
    """The defect this closes, and the reason it is asserted as a pair.

    Research and extraction both resolved from `model`, so choosing a cheap
    extraction model silently repointed the research agent at it. Asserting
    only that extraction moved would pass under the old, shared mapping.
    """
    client.put(
        "/api/profiles/project/p1/groq-fast",
        json={"provider_id": "groq", "model": "llama-3.3-70b-versatile"},
    )
    client.put("/api/profiles/project/p1/roles/extraction", json={"profile": "groq-fast"})

    body = client.get("/api/profiles?project=p1").json()
    roles = {row["role"]: row for row in body["roles"]}

    assert roles["extraction"]["model"] == "llama-3.3-70b-versatile"
    assert roles["extraction"]["profile"] == "groq-fast"
    assert roles["extraction"]["layer"] == "project"
    assert roles["research"]["model"] != "llama-3.3-70b-versatile"
    assert roles["research"]["profile"] is None


def test_every_role_reports_the_setting_it_falls_back_to(client):
    body = client.get("/api/profiles?project=p1").json()
    roles = {row["role"]: row for row in body["roles"]}

    assert set(roles) == {"research", "extraction", "curation", "embedding", "vision"}
    assert roles["extraction"]["setting_key"] == "extraction_model"
    assert roles["research"]["setting_key"] == "model"
    # No two roles fall back to one setting -- five roles sharing four keys is
    # four roles, which is what extraction and research were before this branch.
    keys = [row["setting_key"] for row in roles.values()]
    assert len(set(keys)) == len(keys)


def test_a_project_may_select_a_profile_the_tenant_defined(client):
    """The reason profiles and selections are two walks rather than one.

    Folding the selection into the profile row would force a project to
    redefine a profile in order to use it, which is the opposite of what a
    shared team credential is for.
    """
    client.put(
        "/api/profiles/tenant/t1/shared",
        json={"provider_id": "openai", "model": "gpt-4o-mini"},
    )
    client.put("/api/profiles/project/p1/roles/curation", json={"profile": "shared"})

    roles = {
        row["role"]: row
        for row in client.get("/api/profiles?project=p1&tenant=t1").json()["roles"]
    }

    assert roles["curation"]["model"] == "gpt-4o-mini"
    assert roles["curation"]["layer"] == "project"


def test_a_project_profile_shadows_a_tenant_one_of_the_same_name(client):
    for scope, model in (("tenant/t1", "tenant-model"), ("project/p1", "project-model")):
        client.put(
            f"/api/profiles/{scope}/shared",
            json={"provider_id": "openai", "model": model},
        )
    client.put("/api/profiles/project/p1/roles/curation", json={"profile": "shared"})

    body = client.get("/api/profiles?project=p1&tenant=t1").json()

    assert [profile["model"] for profile in body["profiles"]] == ["project-model"]
    roles = {row["role"]: row for row in body["roles"]}
    assert roles["curation"]["model"] == "project-model"


def test_a_selection_pointing_at_nothing_is_reported_rather_than_ignored(client):
    """A role silently repointed at the default model is the exact failure this
    feature exists to prevent, so a dangling selection is named."""
    client.put("/api/profiles/project/p1/roles/vision", json={"profile": "deleted-one"})

    body = client.get("/api/profiles?project=p1").json()
    roles = {row["role"]: row for row in body["roles"]}

    assert roles["vision"]["dangling"] == "deleted-one"
    assert roles["vision"]["profile"] is None


def test_deleting_a_profile_leaves_the_selection_dangling_rather_than_unpicking_it(client):
    """A delete that silently unpicked a role would be a second, invisible
    write -- and a more specific scope may define the same name, in which case
    the selection is still correct."""
    client.put(
        "/api/profiles/project/p1/groq-fast",
        json={"provider_id": "groq", "model": "llama-3.3-70b-versatile"},
    )
    client.put("/api/profiles/project/p1/roles/extraction", json={"profile": "groq-fast"})

    assert client.delete("/api/profiles/project/p1/groq-fast").status_code == 204

    body = client.get("/api/profiles?project=p1").json()
    roles = {row["role"]: row for row in body["roles"]}
    assert roles["extraction"]["dangling"] == "groq-fast"


def test_clearing_a_role_falls_back_to_its_setting(client):
    client.put(
        "/api/profiles/project/p1/groq-fast",
        json={"provider_id": "groq", "model": "llama-3.3-70b-versatile"},
    )
    client.put("/api/profiles/project/p1/roles/extraction", json={"profile": "groq-fast"})

    assert client.delete("/api/profiles/project/p1/roles/extraction").status_code == 204

    body = client.get("/api/profiles?project=p1").json()
    roles = {row["role"]: row for row in body["roles"]}
    assert roles["extraction"]["profile"] is None
    assert roles["extraction"]["dangling"] is None


def test_deleting_a_profile_that_was_never_defined_is_a_404(client):
    assert client.delete("/api/profiles/project/p1/nope").status_code == 404


def test_clearing_a_role_that_was_never_selected_is_a_404(client):
    assert client.delete("/api/profiles/project/p1/roles/vision").status_code == 404


def test_a_role_that_does_not_exist_is_a_422_naming_the_five(client):
    response = client.put("/api/profiles/project/p1/roles/astrology", json={"profile": "x"})

    assert response.status_code == 422
    assert "extraction" in response.json()["detail"]


def test_profiles_answer_with_no_store_wired(client_without_profiles):
    """An unwired profile store still resolves every role from its setting.

    503-ing the whole endpoint would hide the half that works, and the roles
    are what a settings page needs first.
    """
    body = client_without_profiles.get("/api/profiles?project=p1").json()

    assert body["profiles"] == []
    assert len(body["roles"]) == 5
    assert all(row["profile"] is None for row in body["roles"])
