"""Resolution, over the real store and the real secret box.

`SettingsStorePort` and `SecretBoxPort` each have exactly one production
adapter, which CLAUDE.md's "Events" section names as the shape that ships
broken: a stub on one side and a unit test on the other prove the two halves
work and cannot prove they meet. The co-mention channel produced nothing for a
whole feature that way. So every test here drives `SettingsResolver` against a
`SettingsStore` on a real SQLite file and an `AesGcmSecretBox` with a real key
-- no doubles anywhere in the chain.

The environment is supplied explicitly rather than through `monkeypatch.setenv`
so a test that means "the environment says X" is not also a statement about the
process the suite runs in.
"""

import pytest

from research_team.application.settings import SettingsResolver
from research_team.domain.settings import (
    DEFAULT_LAYER,
    ENVIRONMENT_LAYER,
    Scope,
    ScopeRef,
    SettingError,
)
from research_team.infrastructure.settings.secrets import PREFIX, AesGcmSecretBox
from research_team.infrastructure.settings.store import SettingsStore

PROJECT = ScopeRef(scope=Scope.PROJECT, scope_id="project-1")
USER = ScopeRef(scope=Scope.USER, scope_id="user-1")
TENANT = ScopeRef(scope=Scope.TENANT, scope_id="tenant-1")
CHAIN = [PROJECT, USER, TENANT]


@pytest.fixture
async def store(tmp_path) -> SettingsStore:
    opened = await SettingsStore.open(str(tmp_path / "settings.db"))
    yield opened
    await opened.close()


@pytest.fixture
def box() -> AesGcmSecretBox:
    return AesGcmSecretBox("a-test-key-nobody-uses-in-anger")


def _resolver(store, box=None, environ=None) -> SettingsResolver:
    return SettingsResolver(store, box, environ if environ is not None else {})


async def test_nothing_stored_and_nothing_in_the_environment_is_the_default(store):
    resolved = await _resolver(store).resolve("model", CHAIN)

    assert resolved.value == "qwen3.6-27b-mtp"
    assert resolved.layer == DEFAULT_LAYER
    assert resolved.scope_id is None


async def test_the_environment_beats_the_default_and_says_so(store):
    resolved = await _resolver(store, environ={"AGENT_MODEL": "from-env"}).resolve(
        "model", CHAIN
    )

    assert resolved.value == "from-env"
    assert resolved.layer == ENVIRONMENT_LAYER


async def test_a_tenant_override_beats_the_environment(store):
    """The layer that changed, not just the value.

    Asserting only the value would pass if the environment layer were deleted
    entirely and the tenant row happened to hold the same string, which is the
    case this pair of assertions separates.
    """
    resolver = _resolver(store, environ={"AGENT_MODEL": "from-env"})
    await resolver.write(TENANT, "model", "from-tenant")

    resolved = await resolver.resolve("model", CHAIN)

    assert resolved.value == "from-tenant"
    assert resolved.layer == "tenant"
    assert resolved.scope_id == "tenant-1"


async def test_the_project_wins_over_the_user_which_wins_over_the_tenant(store):
    """All three set at once -- the case that distinguishes the orders.

    A test with one override set is passed by every ordering of the three, which
    is the CLAUDE.md "a formula correct on every case a test naturally reaches"
    trap: the property that separates the candidate walks is *several layers
    holding a value at the same time*, so this sets all three and then removes
    them one at a time.
    """
    resolver = _resolver(store)
    await resolver.write(TENANT, "model", "tenant-model")
    await resolver.write(USER, "model", "user-model")
    await resolver.write(PROJECT, "model", "project-model")

    assert (await resolver.resolve("model", CHAIN)).value == "project-model"

    await resolver.clear(PROJECT, "model")
    assert (await resolver.resolve("model", CHAIN)).value == "user-model"

    await resolver.clear(USER, "model")
    assert (await resolver.resolve("model", CHAIN)).value == "tenant-model"

    await resolver.clear(TENANT, "model")
    assert (await resolver.resolve("model", CHAIN)).layer == DEFAULT_LAYER


async def test_a_chain_given_in_the_wrong_order_still_resolves_project_first(store):
    """The order is the feature, and a caller cannot supply a different one.

    Reverting `resolve_all`'s `RESOLUTION_ORDER` filter to "walk the chain as
    given" turns this red; without it the test would pass under both
    implementations, because every other test here builds the chain correctly.
    """
    resolver = _resolver(store)
    await resolver.write(TENANT, "model", "tenant-model")
    await resolver.write(PROJECT, "model", "project-model")

    backwards = [TENANT, USER, PROJECT]

    assert (await resolver.resolve("model", backwards)).value == "project-model"


async def test_a_scope_the_declaration_forbids_is_refused(store):
    """`pgvector_dsn` is tenant-scoped: a project override would let one project
    point every project's vectors at another database."""
    with pytest.raises(SettingError, match="tenant"):
        await _resolver(store).write(PROJECT, "pgvector_dsn", "postgres://x/y")


async def test_a_value_the_declaration_refuses_never_reaches_the_store(store):
    """Validation is the resolver's, before the store sees anything.

    The second assertion is the one that matters: a refusal that still wrote
    would leave a row that resolves to the default, which looks exactly like no
    row at all until someone tries to clear it.
    """
    resolver = _resolver(store)
    with pytest.raises(SettingError):
        await resolver.write(PROJECT, "extraction_chunk_size", "10")

    assert await store.overrides([PROJECT]) == []


async def test_clearing_something_that_was_never_set_says_so(store):
    """False, not a silent success -- the route turns it into a 404, because
    clearing a key that was never set is almost always a misspelled key."""
    assert await _resolver(store).clear(PROJECT, "model") is False


async def test_a_stored_secret_is_ciphertext_in_the_table(store, box):
    """The row, not the API. This is the "encrypted at rest" claim itself.

    Reading the plaintext back out of `store.overrides` would pass a test that
    only checked the endpoint's masking, because the endpoint would still mask
    a value that was stored in the clear.
    """
    resolver = _resolver(store, box)
    await resolver.write(PROJECT, "api_key", "sk-live-abcd1234")

    (row,) = await store.overrides([PROJECT])

    assert row.value.startswith(PREFIX)
    assert "sk-live-abcd1234" not in row.value


async def test_a_resolved_secret_carries_a_mask_and_no_value(store, box):
    resolver = _resolver(store, box)
    await resolver.write(PROJECT, "api_key", "sk-live-abcd1234")

    resolved = await resolver.resolve("api_key", CHAIN)

    assert resolved.secret is True
    assert resolved.value is None
    assert resolved.masked is not None
    assert resolved.masked.last_four == "1234"


async def test_the_plaintext_is_reachable_only_through_the_secret_call(store, box):
    """The asymmetry that makes the read boundary structural.

    `resolve` cannot return it; `secret` can, and has no HTTP surface above it.
    """
    resolver = _resolver(store, box)
    await resolver.write(PROJECT, "api_key", "sk-live-abcd1234")

    assert await resolver.secret("api_key", CHAIN) == "sk-live-abcd1234"


async def test_asking_for_a_non_secret_through_the_secret_call_is_refused(store, box):
    """Otherwise `secret()` would become a general-purpose read path that
    happens to be spelled differently."""
    with pytest.raises(SettingError):
        await _resolver(store, box).secret("model", CHAIN)


async def test_a_secret_written_under_another_key_falls_through_rather_than_shadowing(
    store, box
):
    """Rotating `AGENT_SETTINGS_KEY` must not take down the environment layer.

    Measured here rather than reasoned: the row stays, the new box cannot read
    it, and the endpoint keeps working off the environment. Without the
    fall-through the same request answers `None` and every call using that
    credential fails with nothing naming the cause.
    """
    await _resolver(store, box).write(PROJECT, "api_key", "sk-live-abcd1234")

    rotated = _resolver(
        store,
        AesGcmSecretBox("a-different-key"),
        environ={"AGENT_API_KEY": "from-env"},
    )

    assert await rotated.secret("api_key", CHAIN) == "from-env"
    resolved = await rotated.resolve("api_key", CHAIN)
    assert resolved.masked is not None
    assert resolved.masked.present is False


async def test_writing_a_secret_with_no_key_configured_refuses_by_name(store):
    """Naming the variable, because the alternative -- storing it in the clear
    -- is the failure `build_secret_box` returns `None` to avoid."""
    with pytest.raises(SettingError, match="AGENT_SETTINGS_KEY"):
        await _resolver(store, None).write(PROJECT, "api_key", "sk-live-abcd1234")


async def test_a_stored_value_that_no_longer_parses_falls_back_to_the_default(store):
    """A declaration can narrow under a row nobody touched.

    Written through the store directly, because the resolver would refuse it --
    which is the point: the bad row can only have arrived from an older build.
    A refusal here would make one stale row 500 the whole settings page.
    """
    await store.put(PROJECT, "context", "clever")

    resolved = await _resolver(store).resolve("context", CHAIN)

    assert resolved.value == "full"
    assert resolved.layer == "project"


async def test_the_store_survives_being_reopened(tmp_path, box):
    """The table is real and the rows outlive the process.

    An in-memory double passes every other test in this file; only this one
    fails against one.
    """
    path = str(tmp_path / "settings.db")
    first = SettingsStore(path)
    await SettingsResolver(first, box, {}).write(PROJECT, "model", "persisted")
    await first.close()

    second = SettingsStore(path)
    resolved = await SettingsResolver(second, box, {}).resolve("model", CHAIN)
    await second.close()

    assert resolved.value == "persisted"
    assert resolved.layer == "project"


async def test_a_provider_credential_round_trips_through_the_real_store(store, box):
    """The dynamic namespace, end to end, with nothing stubbed.

    A dynamic spec is an ordinary `SettingSpec`, so this asserts the thing that
    claim implies: encryption, masking and the resolution walk apply to it
    unchanged, through the same code path, with no branch on the key's shape.
    """
    resolver = _resolver(store, box)
    await resolver.write(PROJECT, "provider_key.groq", "gsk_abcd1234")

    (row,) = await store.overrides([PROJECT])
    assert row.value.startswith(PREFIX)
    assert "gsk_abcd1234" not in row.value

    resolved = await resolver.resolve("provider_key.groq.api_key", CHAIN)
    assert resolved.secret is True
    assert resolved.value is None
    assert resolved.masked.last_four == "1234"
    assert await resolver.secret("provider_key.groq", CHAIN) == "gsk_abcd1234"


async def test_the_short_and_long_forms_of_a_provider_key_are_one_row(store, box):
    """Written short, cleared long, and it is the same setting.

    The key is hashed into the storage row id, so two spellings that did not
    normalise would be two rows -- a credential written through one form and
    cleared through the other would be invisible and unremovable. Found by
    running it: `write` stored the caller's raw string until this branch, so
    this failed with a 404 on the clear and an empty read.
    """
    resolver = _resolver(store, box)
    await resolver.write(PROJECT, "provider_key.groq", "gsk_abcd1234")

    assert await resolver.clear(PROJECT, "provider_key.groq.api_key") is True
    assert await store.overrides([PROJECT]) == []


async def test_a_provider_credential_resolves_down_the_chain(store, box):
    """A user's own key beats the tenant's shared one, like any other setting."""
    resolver = _resolver(store, box)
    await resolver.write(TENANT, "provider_key.openai", "sk-tenant-0000")
    await resolver.write(USER, "provider_key.openai", "sk-user-1111")

    assert await resolver.secret("provider_key.openai", CHAIN) == "sk-user-1111"

    await resolver.clear(USER, "provider_key.openai")
    assert await resolver.secret("provider_key.openai", CHAIN) == "sk-tenant-0000"


async def test_a_provider_credential_reads_from_the_environment_too(store):
    """The synthesised variable is real, not a placeholder to satisfy the type.

    A dynamic setting that no container could configure would be the one
    setting in the system with no environment layer, and the resolver would
    need a branch for it -- which is the branch that would eventually be wrong.
    """
    resolver = _resolver(store, environ={"AGENT_PROVIDER_KEY_GROQ_API_KEY": "gsk_from_env"})

    resolved = await resolver.resolve("provider_key.groq", CHAIN)

    assert resolved.layer == ENVIRONMENT_LAYER
    assert resolved.masked.present is True
    assert await resolver.secret("provider_key.groq", CHAIN) == "gsk_from_env"


async def test_a_non_secret_provider_credential_is_readable(store, box):
    """Secrecy is the credential's, not the prefix's. A region masked as a
    secret would make the settings page unreadable for the two providers that
    need the most from it."""
    resolver = _resolver(store, box)
    await resolver.write(TENANT, "provider_key.bedrock.region", "us-east-1")

    resolved = await resolver.resolve("provider_key.bedrock.region", CHAIN)

    assert resolved.secret is False
    assert resolved.value == "us-east-1"


async def test_a_provider_outside_the_catalogue_never_reaches_the_store(store, box):
    """Refused before anything is written, so a caller cannot mint rows for
    provider ids that do not exist."""
    with pytest.raises(SettingError):
        await _resolver(store, box).write(PROJECT, "provider_key.evilcorp", "x")

    assert await store.overrides([PROJECT]) == []
