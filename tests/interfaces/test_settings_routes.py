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
from research_team.domain.settings import RESOLUTION_ORDER, SETTINGS, dynamic_specs
from research_team.infrastructure.settings.profiles import ModelProfileStore
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


def _writable_scope(spec) -> str:
    """The most specific scope this setting may be written at.

    Needed because two declared secrets -- the pgvector DSN and the Neo4j
    password -- are tenant-only, so a population written entirely at project
    scope would have got a 422 for them and asserted nothing about the two
    secrets whose exposure would matter most. Found by running it.
    """
    for scope in RESOLUTION_ORDER:
        if scope in spec.scopes:
            return scope.value
    raise AssertionError(f"{spec.key} can be written nowhere")


#: Every secret the system has, with a scope it may be written at: the four
#: declared plus every secret credential the provider catalogue implies.
#: Derived rather than listed, so a sixteenth provider or a fifth declared
#: secret is covered the day it is written -- the masking property is not a
#: thing anyone has to remember to extend.
SECRET_CASES = [
    (spec.key, _writable_scope(spec)) for spec in (*SETTINGS, *dynamic_specs()) if spec.secret
]


def test_the_secret_population_covers_both_kinds():
    """The parametrisation below is worthless if it collects one kind.

    A `dynamic_specs()` that returned nothing would leave the property testing
    exactly what it tested before the dynamic namespace existed, and passing --
    the shape of "a checkpoint that matches anything cannot tell a phase that
    worked from one that stopped".
    """
    keys = [key for key, _ in SECRET_CASES]
    assert any(not key.startswith("provider_key.") for key in keys)
    assert any(key.startswith("provider_key.") for key in keys)
    assert len(keys) > 10


@pytest.mark.parametrize(("key", "scope"), SECRET_CASES, ids=[key for key, _ in SECRET_CASES])
def test_a_secret_never_leaves_a_read_endpoint(client, key, scope):
    """The property, asserted over the whole response body rather than one field.

    A future field that happened to carry the value -- a "current value" hint, a
    diff, an error message quoting the input -- would pass a per-field
    assertion and fail this one. Both the plaintext and the stored ciphertext
    are checked: the ciphertext is not a credential, but publishing it hands an
    offline attacker everything but the key.

    Parametrised over the whole secret population rather than given a case per
    kind, on the coordinator's instruction and for the reason that makes it
    right: a dynamic provider credential is a `SettingSpec` like any other, so
    if it needed its own case something would be branching on it, and the
    branch is what would eventually be wrong.
    """
    secret = "sk-live-abcd1234"
    stored = client.put(f"/api/settings/{scope}/s1/{key}", json={"value": secret})
    assert stored.status_code == 200, stored.text

    read = f"/api/settings/resolved?{scope}=s1"
    raw = client.get(read).text

    assert secret not in raw
    assert "aesgcm:" not in raw

    row = _row(client.get(read).json(), key)
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


# --- provider credentials: the dynamic namespace -------------------------


def test_a_groq_credential_has_somewhere_to_live(client):
    """The hole this branch closes, stated as the test that would have caught it.

    Before the dynamic namespace, `PUT` answered 422 for every key outside the
    forty-one declared, and exactly four of those were secrets -- all of them
    for this project's own endpoints. So the catalogue enumerated fifteen
    providers and the registry enumerated four secrets, and bring-your-own-model
    could be *described* and not *stored*.
    """
    written = client.put(
        "/api/settings/project/p1/provider_key.groq", json={"value": "gsk_abcd1234"}
    )

    assert written.status_code == 200

    body = client.get("/api/settings/resolved?project=p1").json()
    row = _row(body, "provider_key.groq.api_key")
    assert row["secret"] is True
    assert row["masked"]["last_four"] == "1234"
    assert row["layer"] == "project"


def test_the_bare_form_and_the_named_form_are_one_row(client):
    """`provider_key.groq` normalises to `provider_key.groq.api_key`.

    Not cosmetic: the key is hashed into the storage row id, so if the two
    spellings did not normalise, writing through one and clearing through the
    other would leave a credential nobody could see or remove.
    """
    client.put("/api/settings/project/p1/provider_key.groq", json={"value": "gsk_abcd1234"})

    cleared = client.delete("/api/settings/project/p1/provider_key.groq.api_key")
    assert cleared.status_code == 204

    body = client.get("/api/settings/resolved?project=p1").json()
    row = _row(body, "provider_key.groq.api_key")
    assert row["masked"]["present"] is False


def test_a_provider_id_that_is_not_in_the_catalogue_is_refused(client):
    """The id lands in a storage key and a URL segment. Free text there is
    unvalidated input in a storage key, which this project has been bitten by
    before -- and it would also let a caller mint unbounded rows."""
    response = client.put(
        "/api/settings/project/p1/provider_key.evilcorp", json={"value": "x"}
    )

    assert response.status_code == 422
    assert "evilcorp" in response.json()["detail"]


def test_a_provider_with_three_credentials_will_not_guess_which(client):
    """Bedrock declares an access key id, a secret access key and a region, so
    the trailing segment is real rather than decorative. Guessing is the
    difference between storing a secret access key and storing it under the
    id's name and spending an afternoon on why signing fails."""
    response = client.put("/api/settings/project/p1/provider_key.bedrock", json={"value": "x"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "access_key_id" in detail and "secret_access_key" in detail and "region" in detail


def test_a_credential_the_provider_does_not_declare_is_refused(client):
    response = client.put(
        "/api/settings/project/p1/provider_key.groq.password", json={"value": "x"}
    )

    assert response.status_code == 422


def test_a_non_secret_credential_is_stored_in_the_clear(client):
    """A region is not a secret, and masking it would make the settings page
    unreadable for the two providers that need the most from it. Secrecy comes
    from the credential's own declaration, not from the key's prefix."""
    client.put(
        "/api/settings/project/p1/provider_key.bedrock.region", json={"value": "us-east-1"}
    )

    row = _row(
        client.get("/api/settings/resolved?project=p1").json(), "provider_key.bedrock.region"
    )
    assert row["secret"] is False
    assert row["value"] == "us-east-1"


def test_the_schema_carries_the_provider_credentials_in_their_own_group(client):
    body = client.get("/api/settings/schema").json()

    assert body["provider_credential_group"] == "Provider credentials"
    group = next(g for g in body["groups"] if g["name"] == body["provider_credential_group"])
    keys = {setting["key"] for setting in group["settings"]}

    # One per declared credential across the catalogue, not one per provider.
    assert "provider_key.groq.api_key" in keys
    assert "provider_key.bedrock.secret_access_key" in keys
    assert "provider_key.azure_openai.deployment" in keys
    assert len(keys) == len(dynamic_specs())


# --- model profiles ------------------------------------------------------


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
