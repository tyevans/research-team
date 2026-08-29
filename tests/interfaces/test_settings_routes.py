"""The settings and provider HTTP contract.

W-C1 builds the console's settings page against these shapes on a separate
branch, so the field names are asserted here rather than left to be read off
the router -- a response shape two branches agree about by inspection is one
they will eventually disagree about. `docs/reference/settings-api.md` is the
prose form of the same contract.

The app is built through `create_app` rather than by mounting the router
directly: the router being registered is half of what can go wrong, and a test
that skips `create_app` cannot see the half where it is not.
"""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from research_team.domain.providers import PROVIDERS, ProbeOutcome, ProbeResult
from research_team.infrastructure.settings.secrets import AesGcmSecretBox
from research_team.infrastructure.settings.store import SettingsStore
from research_team.interfaces.web.app import create_app
from research_team.interfaces.web.settings import SettingsDeps


class RecordingProbe:
    """A double for the *network*, not for the adapter.

    The adapter itself is exercised against a real endpoint in
    `tests/integration/test_provider_probe_reaches_a_real_endpoint.py`, which
    is the test CLAUDE.md's port-with-one-adapter rule asks for. What this
    stands in for here is the internet, which a route test may not have.
    """

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
    deps = SettingsDeps(
        store=SettingsStore(str(tmp_path / "settings.db")),
        secrets=AesGcmSecretBox("a-test-key-nobody-uses-in-anger"),
        probe=probe,
    )
    return TestClient(
        create_app(service=Mock(), feed=Mock(), turns=Mock(), settings=deps),
        raise_server_exceptions=False,
    )


def test_the_schema_describes_every_setting_a_form_needs(client):
    body = client.get("/api/settings/schema").json()

    assert body["scopes"] == ["project", "user", "tenant"]
    assert {role["role"] for role in body["roles"]} >= {"research", "embedding", "vision"}

    fields = {
        setting["key"]: setting for group in body["groups"] for setting in group["settings"]
    }
    model = fields["model"]
    assert model["env_var"] == "AGENT_MODEL"
    assert model["type"] == "string"
    assert model["label"]
    assert model["description"]
    assert model["default"] == "qwen3.6-27b-mtp"
    assert sorted(model["scopes"]) == ["project", "tenant", "user"]

    assert fields["context"]["choices"] == ["full", "elide", "compact", "delegate"]
    assert fields["pgvector_dsn"]["scopes"] == ["tenant"]


def test_the_schema_publishes_no_secret_default(client):
    """`api_key` ships with a placeholder default, and publishing it anyway
    would make "the schema never carries a secret" a claim with an exception
    in it -- which is the kind of exception a later, real default slips through."""
    body = client.get("/api/settings/schema").json()
    secrets = [
        setting
        for group in body["groups"]
        for setting in group["settings"]
        if setting["secret"]
    ]

    assert secrets, "no secret settings in the schema at all -- the test proves nothing"
    assert all(setting["default"] is None for setting in secrets)


def test_a_resolved_read_says_which_layer_supplied_each_value(client):
    body = client.get("/api/settings/resolved?project=p1").json()

    assert body["scope_chain"] == [{"scope": "project", "scope_id": "p1"}]
    layers = {row["key"]: row["layer"] for row in body["settings"]}
    assert layers["model"] in ("default", "environment")
    assert set(body["settings"][0]) >= {"key", "value", "layer", "scope_id", "secret"}


def test_writing_an_override_changes_the_layer_and_the_value(client):
    """Both, and the layer is the half a value-only assertion would miss: a
    build that wrote nothing and resolved from the environment could still
    return the value the caller just posted, if the two agreed."""
    written = client.put("/api/settings/project/p1/model", json={"value": "my-model"})
    assert written.status_code == 200
    assert written.json()["stored"] is True

    row = _row(client.get("/api/settings/resolved?project=p1").json(), "model")
    assert row["value"] == "my-model"
    assert row["layer"] == "project"
    assert row["scope_id"] == "p1"


def test_a_project_override_is_invisible_to_another_project(client):
    """The scope is a key, not decoration. A store that ignored `scope_id`
    passes every single-project test in this file."""
    client.put("/api/settings/project/p1/model", json={"value": "mine"})

    row = _row(client.get("/api/settings/resolved?project=p2").json(), "model")

    assert row["value"] != "mine"
    assert row["layer"] == "default"


def test_clearing_an_override_falls_back(client):
    client.put("/api/settings/project/p1/model", json={"value": "my-model"})

    assert client.delete("/api/settings/project/p1/model").status_code == 204

    row = _row(client.get("/api/settings/resolved?project=p1").json(), "model")
    assert row["layer"] == "default"


def test_clearing_something_never_set_is_a_404(client):
    """Not a 204. Clearing a key that was never set is almost always a
    misspelled key, and a silent success is how the misspelling survives."""
    assert client.delete("/api/settings/project/p1/model").status_code == 404


def test_a_value_the_declaration_refuses_is_a_422_naming_it(client):
    response = client.put("/api/settings/project/p1/context", json={"value": "clever"})

    assert response.status_code == 422
    assert "full" in response.json()["detail"]


def test_a_scope_the_declaration_forbids_is_a_422(client):
    response = client.put(
        "/api/settings/project/p1/pgvector_dsn", json={"value": "postgres://x/y"}
    )

    assert response.status_code == 422
    assert "tenant" in response.json()["detail"]


def test_an_unknown_setting_is_a_422_not_a_500(client):
    assert client.put("/api/settings/project/p1/nope", json={"value": "x"}).status_code == 422


def test_an_unknown_scope_is_a_422_not_a_500(client):
    response = client.put("/api/settings/galaxy/g1/model", json={"value": "x"})

    assert response.status_code == 422


def test_a_secret_never_leaves_a_read_endpoint(client):
    """The property, asserted over the whole response body rather than one field.

    A future field that happened to carry the value -- a "current value" hint, a
    diff, an error message quoting the input -- would pass a per-field
    assertion and fail this one. Both the plaintext and the stored ciphertext
    are checked: the ciphertext is not a credential, but publishing it hands an
    offline attacker everything but the key.
    """
    secret = "sk-live-abcd1234"
    client.put("/api/settings/project/p1/api_key", json={"value": secret})

    raw = client.get("/api/settings/resolved?project=p1").text

    assert secret not in raw
    assert "aesgcm:" not in raw

    row = _row(client.get("/api/settings/resolved?project=p1").json(), "api_key")
    assert row["value"] is None
    assert row["secret"] is True
    assert row["masked"] == {"present": True, "last_four": "1234", "display": "set (…1234)"}


def test_an_unset_secret_reports_not_set(client):
    row = _row(client.get("/api/settings/resolved?project=p1").json(), "embedding_api_key")

    assert row["masked"]["present"] is False
    assert row["masked"]["display"] == "not set"


def test_the_provider_catalogue_carries_every_declared_provider(client):
    body = client.get("/api/providers").json()

    by_id = {provider["id"]: provider for provider in body["providers"]}
    assert set(by_id) == {provider.id for provider in PROVIDERS}
    assert len(by_id) == 15

    openai = by_id["openai"]
    assert openai["openai_compatible"] is True
    assert openai["auth"] == "bearer"
    assert "chat" in openai["capabilities"]
    assert openai["credentials"][0]["name"] == "api_key"

    # The four that are not OpenAI-compatible, named as data rather than as a
    # count -- a count would pass if the flag moved between two of them.
    incompatible = {pid for pid, row in by_id.items() if not row["openai_compatible"]}
    assert incompatible == {"anthropic", "google", "azure_openai", "bedrock"}


def test_a_connection_test_reports_a_structured_result(client, probe):
    response = client.post("/api/providers/openai/test", json={"api_key": "sk-test"})

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "provider_id": "openai",
        "outcome": "ok",
        "ok": True,
        "detail": "answered 200",
        "models": ["some-model"],
        "latency_ms": 12,
    }
    assert probe.seen == [("openai", "sk-test")]


def test_a_connection_test_for_an_unknown_provider_is_a_404(client):
    assert client.post("/api/providers/nope/test", json={}).status_code == 404


def test_the_static_surface_answers_with_nothing_wired():
    """The schema and the catalogue are data and need no store.

    A build with no settings database still has to serve them, because the
    alternative -- 503 for the whole surface -- hides the half that works and
    makes "never wired" and "no such feature" identical to a caller.
    """
    bare = TestClient(
        create_app(service=Mock(), feed=Mock(), turns=Mock()),
        raise_server_exceptions=False,
    )

    assert bare.get("/api/settings/schema").status_code == 200
    assert bare.get("/api/providers").status_code == 200
    assert bare.post("/api/providers/openai/test", json={}).status_code == 503


def _row(body: dict, key: str) -> dict:
    return next(row for row in body["settings"] if row["key"] == key)
