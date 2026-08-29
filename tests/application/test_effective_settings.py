"""What a project's extraction actually runs on, over the real stores.

No doubles anywhere in the chain, for the reason `test_settings_resolution.py`
gives at length and CLAUDE.md's "Events" section states as a rule: both stores
here have exactly one production adapter, so a stub on one side and a unit test
on the other would prove the two halves work and could not prove they meet.

The assertions are about the *bundle a run would be built from* -- the model
name, the endpoint, the credential, the chunk size -- never about whether a
cache was cleared. A test that asserts on the cache passes with the invalidation
correct and the consumption unwired, which is the whole defect this branch
exists to close.
"""

import asyncio
from uuid import UUID

import pytest

from research_team.application.effective import (
    EffectiveSettings,
    ExtractionSettings,
    ResearchSettings,
    SettingsRevision,
)
from research_team.application.settings import SettingsResolver
from research_team.domain.settings import ModelProfile, ModelRole, Scope, ScopeRef
from research_team.infrastructure import config
from research_team.infrastructure.settings.profiles import ModelProfileStore
from research_team.infrastructure.settings.secrets import AesGcmSecretBox
from research_team.infrastructure.settings.store import SettingsStore
from research_team.interfaces.web.settings import SettingsDeps

PROJECT_ID = UUID("0f4a1c6e-2b7d-4a51-9c33-5d8e17b04a92")
OTHER_ID = UUID("8c21ba50-4f19-4d6c-b3a7-6e0d92f15c48")
#: The ref the resolver walks. `str(project_id)` and nothing else -- if this
#: spelling and `EffectiveSettings._chain`'s ever diverge, every test here
#: passes against rows nothing reads.
PROJECT = ScopeRef(scope=Scope.PROJECT, scope_id=str(PROJECT_ID))


@pytest.fixture
def revision() -> SettingsRevision:
    return SettingsRevision()


@pytest.fixture
async def stores(tmp_path, revision):
    """Both stores over one database and one counter, exactly as composition
    builds them. Sharing the counter is the part under test in
    `test_a_role_selection_reaches_the_next_run`: selecting a profile touches
    only the profile table, and a per-table counter would leave the bundle
    stale after it."""
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


async def _write(store, key: str, value: str, ref: ScopeRef = PROJECT) -> None:
    await store.put(ref, key, value)


# --- the headless path, which must not move --------------------------------


async def test_no_store_and_no_project_is_exactly_what_config_answers():
    """The CLI and every test that never names a project.

    Asserted against `config` rather than against literals: a literal here
    would pass with `config` changed underneath it, and "the headless answer
    drifted from the process answer" is precisely the failure this branch is
    obliged not to cause. Would fail if `EffectiveSettings` grew a default of
    its own for any of these eight.
    """
    resolved = await EffectiveSettings().extraction(None)

    assert resolved == ExtractionSettings(
        model=config.extraction_model(),
        base_url=config.base_url(),
        api_key=config.api_key(),
        thinking=config.extraction_thinking(),
        concurrency=config.extraction_concurrency(),
        chunk_size=config.extraction_chunk_size(),
        consolidation_batch=config.consolidation_batch_size(),
        knowledge_domain=config.knowledge_domain(),
    )


async def test_a_store_with_nothing_in_it_still_answers_the_process_values(effective):
    """A wired deployment that nobody has configured behaves as an unwired one.

    Separate from the test above because the two go through different code:
    this one reads the override table and finds nothing, that one has no table
    to read. Both have to land on the same answer or a fresh install changes
    behaviour the day the settings database is created.
    """
    assert await effective.extraction(None) == await EffectiveSettings().extraction(None)


# --- a project override taking effect --------------------------------------


async def test_a_project_scoped_extraction_model_is_the_one_a_run_would_use(effective, stores):
    settings, _ = stores
    await _write(settings, "extraction_model", "a-cheap-extractor")

    assert (await effective.extraction(PROJECT_ID)).model == "a-cheap-extractor"


async def test_the_extraction_knobs_are_per_project(effective, stores):
    settings, _ = stores
    await _write(settings, "extraction_chunk_size", "512")
    await _write(settings, "extraction_concurrency", "2")
    await _write(settings, "consolidation_batch", "5")
    await _write(settings, "knowledge_domain", "roman_history")

    resolved = await effective.extraction(PROJECT_ID)

    assert (resolved.chunk_size, resolved.concurrency, resolved.consolidation_batch) == (
        512,
        2,
        5,
    )
    assert resolved.knowledge_domain == "roman_history"


async def test_one_projects_override_does_not_reach_another(effective, stores):
    settings, _ = stores
    await _write(settings, "extraction_model", "a-cheap-extractor")

    assert (await effective.extraction(OTHER_ID)).model == config.extraction_model()


async def test_an_unset_extraction_model_still_falls_back_to_the_chat_model(effective, stores):
    """The documented behaviour of `AGENT_EXTRACTION_MODEL`, preserved when the
    chat model is the thing overridden. Would fail if the fallback were moved
    into the registry as a default -- which is the obvious simplification and
    would make a project setting only `model` see extraction stay on the
    built-in."""
    settings, _ = stores
    await _write(settings, "model", "a-project-wide-choice")

    assert (await effective.extraction(PROJECT_ID)).model == "a-project-wide-choice"


async def test_a_project_scoped_credential_is_the_one_a_call_would_carry(effective, stores):
    # Written through `SettingsResolver.write`, not through the store: the
    # resolver is what seals, and a ciphertext put into the table by any other
    # route is one nothing can decrypt.
    resolver = SettingsResolver(
        stores[0], AesGcmSecretBox("a-test-key-nobody-uses-in-anger"), {}
    )
    await resolver.write(PROJECT, "api_key", "sk-project-only")

    assert (await effective.extraction(PROJECT_ID)).api_key == "sk-project-only"


# --- staleness -------------------------------------------------------------


async def test_a_changed_extraction_model_reaches_the_next_run(effective, stores):
    """The failure this design is against: a cached bundle outliving the write
    that should have replaced it.

    Read once (which populates the cache), write, read again. The assertion is
    the model a run would be built with, not that a cache was cleared -- a
    cache-clearing assertion passes with the invalidation correct and the
    consumption unwired. Proved red by removing the `_revision.bump()` from
    `SettingsStore.put`: the second read returns the first model.
    """
    settings, _ = stores
    await _write(settings, "extraction_model", "the-first-choice")
    assert (await effective.extraction(PROJECT_ID)).model == "the-first-choice"

    await _write(settings, "extraction_model", "the-second-choice")

    assert (await effective.extraction(PROJECT_ID)).model == "the-second-choice"


async def test_clearing_an_override_reaches_the_next_run_too(effective, stores):
    settings, _ = stores
    await _write(settings, "extraction_model", "the-first-choice")
    await effective.extraction(PROJECT_ID)

    assert await settings.clear(PROJECT, "extraction_model") is True

    assert (await effective.extraction(PROJECT_ID)).model == config.extraction_model()


async def test_a_role_selection_reaches_the_next_run(effective, stores):
    """The case a per-table counter would miss.

    Selecting a profile writes to the *profile* table and never touches the
    override table, so a bundle cached before the selection would go on serving
    the setting underneath it. One counter shared by both stores is what makes
    this pass; proved red by giving `ModelProfileStore` its own.
    """
    settings, profiles = stores
    await _write(settings, "extraction_model", "the-setting")
    assert (await effective.extraction(PROJECT_ID)).model == "the-setting"

    await profiles.put_profile(
        PROJECT,
        ModelProfile(name="cheap", provider_id="openai", model="gpt-4o-mini"),
    )
    await profiles.select(PROJECT, ModelRole.EXTRACTION, "cheap")

    assert (await effective.extraction(PROJECT_ID)).model == "gpt-4o-mini"


# --- profiles --------------------------------------------------------------


async def test_a_selected_profile_carries_its_endpoint_and_its_credential(effective, stores):
    """All three move together, or a run sends an Anthropic model name to a
    local vLLM with a key neither accepts."""
    settings, profiles = stores
    resolver = SettingsResolver(
        settings, AesGcmSecretBox("a-test-key-nobody-uses-in-anger"), {}
    )
    await resolver.write(PROJECT, "provider_key.anthropic", "sk-ant-project")
    await profiles.put_profile(
        PROJECT,
        ModelProfile(
            name="claude",
            provider_id="anthropic",
            model="claude-sonnet-4-5",
            credential_key="provider_key.anthropic",
            base_url="https://api.anthropic.com/v1/",
        ),
    )
    await profiles.select(PROJECT, ModelRole.EXTRACTION, "claude")

    resolved = await effective.extraction(PROJECT_ID)

    assert resolved.model == "claude-sonnet-4-5"
    assert resolved.base_url == "https://api.anthropic.com/v1/"
    assert resolved.api_key == "sk-ant-project"


async def test_a_selection_naming_a_profile_nobody_defines_falls_back_and_does_not_raise(
    effective, stores
):
    """`dangling`, from the run's side. Refusing here would take extraction
    down for a stale selection; the form is where a person can see and fix it."""
    settings, profiles = stores
    await _write(settings, "extraction_model", "the-setting")
    await profiles.select(PROJECT, ModelRole.EXTRACTION, "a-profile-that-was-deleted")

    assert (await effective.extraction(PROJECT_ID)).model == "the-setting"


async def test_selecting_a_profile_for_another_role_does_not_move_extraction(
    effective, stores
):
    """Five roles whose keys collide are four roles -- the same property
    `test_no_two_roles_resolve_from_one_setting` holds in the registry, asserted
    here against the bundle a run is built from."""
    settings, profiles = stores
    await _write(settings, "extraction_model", "the-setting")
    await profiles.put_profile(
        PROJECT, ModelProfile(name="big", provider_id="openai", model="gpt-4o")
    )
    await profiles.select(PROJECT, ModelRole.RESEARCH, "big")

    assert (await effective.extraction(PROJECT_ID)).model == "the-setting"


# --- consumption -----------------------------------------------------------


async def test_the_resolved_bundle_is_what_the_extraction_client_is_built_from(
    effective, stores
):
    """The half a resolution test cannot see.

    Every assertion above would pass with `EffectiveSettings` correct and
    nothing consuming it -- which is exactly the state this branch found the
    settings store in, and the shape CLAUDE.md's "Events" section warns about.
    So this one goes through `build_extraction_model`, the function
    `open_graph` calls, and reads the three fields off the client it returns.

    `open_graph` itself is not called here: it needs a graph store, an event
    store and a project. What makes *that* wiring non-silent is that
    `effective_settings` is a bare name in `composition.py` -- a build that
    never constructed it raises `NameError` on the first attach rather than
    quietly resolving nothing.
    """
    from research_team.infrastructure.agent.deep_agent import build_extraction_model

    resolver = SettingsResolver(
        stores[0], AesGcmSecretBox("a-test-key-nobody-uses-in-anger"), {}
    )
    await resolver.write(PROJECT, "extraction_model", "a-cheap-extractor")
    await resolver.write(PROJECT, "base_url", "http://elsewhere:9000/v1/")
    await resolver.write(PROJECT, "api_key", "sk-project-only")

    client = build_extraction_model(await effective.extraction(PROJECT_ID))

    assert client.model_name == "a-cheap-extractor"
    assert str(client.openai_api_base) == "http://elsewhere:9000/v1/"
    assert client.openai_api_key.get_secret_value() == "sk-project-only"


def test_no_settings_is_the_client_config_would_have_built():
    """`build_extraction_model()` with no argument is the headless path, and it
    has to stay byte-identical to what it built before this branch. Would fail
    if the `settings is None` branch were removed in favour of always going
    through `EffectiveSettings` -- which is tempting and would put a
    `SettingsResolver` construction on a synchronous call path."""
    from research_team.infrastructure.agent.deep_agent import build_extraction_model

    client = build_extraction_model()

    assert client.model_name == config.extraction_model()
    assert str(client.openai_api_base) == config.base_url()


# --- teardown --------------------------------------------------------------


async def test_closing_the_settings_deps_releases_both_stores_threads(tmp_path):
    """The regression that cost this branch an 84-minute CI job.

    `aiosqlite` starts a **non-daemon** worker thread per connection, so an
    unclosed store keeps `threading._shutdown` waiting and the interpreter
    never exits. Until this branch the override table was opened only by a
    settings *route*, so almost no test opened it and the omission was free.
    Resolution now happens at `open_graph`, which every attach reaches.

    Measured rather than reasoned, 2026-08-29: CI's `pytest` job finished the
    suite in 6m26s (`1 failed, 4120 passed`) and then sat a further 78 minutes
    before being cancelled, with the runner reporting orphan `uv` and `pytest`
    processes. The count below is the same probe, in a test: two threads open,
    zero after `close()`.

    Counting threads rather than asserting `store._connection is None`, because
    the private attribute is the mechanism and the thread is the harm -- an
    adapter that nulled the handle without joining its worker would pass the
    first assertion and hang the process exactly as before.
    """
    import threading

    def non_daemon() -> int:
        return len([t for t in threading.enumerate() if not t.daemon])

    path = str(tmp_path / "settings.db")
    base = non_daemon()
    deps = SettingsDeps(
        store=await SettingsStore.open(path),
        profiles=await ModelProfileStore.open(path),
    )
    assert non_daemon() == base + 2

    await deps.close()
    await asyncio.sleep(0.1)

    assert non_daemon() == base


async def test_closing_a_settings_deps_that_never_opened_anything_is_a_no_op():
    """What makes the `close()` step safe to list unconditionally in
    `_PARTIAL_BUILD_RESOURCES`: a build that raises before any settings request
    has a `SettingsDeps` whose stores hold no connection, and an unwind that
    raised there would replace the real error with this one."""
    await SettingsDeps().close()


# --- the agent's own bundle -------------------------------------------------
#
# The defect these are against, in one sentence: `build_model()` answered for
# the process, `_build_application` called it once, and the executor held that
# answer for every project for the life of the process -- so a model saved
# against a project resolved correctly through the API and was read by nothing
# on the turn path. Topic seeding was the surface it was reported from, because
# seeding is a turn and a wrong `base_url` there is a connection error rather
# than a subtly worse answer.


async def test_no_store_and_no_project_is_the_process_answer_for_research():
    """The CLI, the REPL, and every test that never names a project.

    Asserted against `config` rather than literals for the extraction twin's
    reason: a literal passes with `config` changed underneath it, and "the
    headless answer drifted" is the one regression this must not cause.
    """
    resolved = await EffectiveSettings().research(None)

    assert resolved == ResearchSettings(
        model=config.model_name(),
        base_url=config.base_url(),
        api_key=config.api_key(),
    )


async def test_a_project_scoped_chat_model_is_the_one_a_turn_would_use(effective, stores):
    settings, _ = stores
    await _write(settings, "model", "a-better-thinker")

    assert (await effective.research(PROJECT_ID)).model == "a-better-thinker"


async def test_a_project_scoped_endpoint_is_the_one_a_turn_would_dial(effective, stores):
    """The reported symptom, at the layer that decides it.

    A wrong endpoint is not a worse answer, it is a connection error -- which
    is how this defect surfaced: seeding dialled the built-in default however
    the settings page was filled in.
    """
    settings, _ = stores
    await _write(settings, "base_url", "http://192.168.1.14:8080/v1/")

    assert (await effective.research(PROJECT_ID)).base_url == "http://192.168.1.14:8080/v1/"


async def test_one_projects_chat_model_does_not_reach_another(effective, stores):
    settings, _ = stores
    await _write(settings, "model", "only-for-this-one")

    assert (await effective.research(OTHER_ID)).model == config.model_name()


async def test_a_changed_chat_model_reaches_the_next_turn(effective, stores):
    """Read (populating the cache), write, read again.

    The assertion is the model a turn would be built with, never that a cache
    was cleared: a cache assertion passes with the invalidation correct and the
    consumption unwired, which is the exact shape of the defect this closes.
    Proved red by removing `_revision.bump()` from `SettingsStore.put`.
    """
    settings, _ = stores
    await _write(settings, "model", "the-first-choice")
    assert (await effective.research(PROJECT_ID)).model == "the-first-choice"

    await _write(settings, "model", "the-second-choice")

    assert (await effective.research(PROJECT_ID)).model == "the-second-choice"


async def test_a_research_profile_wins_over_the_settings_under_it(effective, stores):
    """Selecting a profile moves all three fields together.

    The half worth asserting is `base_url`: a build that took the model name
    from the profile and the endpoint from the setting underneath would send a
    hosted model's name to a local vLLM, which is the failure the bundle exists
    to make impossible.
    """
    settings, profiles = stores
    await _write(settings, "model", "the-setting-underneath")
    await _write(settings, "base_url", "http://localhost:8080/v1/")
    await profiles.put_profile(
        PROJECT,
        ModelProfile(
            name="hosted",
            provider_id="openai",
            model="gpt-4o",
            base_url="https://api.openai.com/v1/",
        ),
    )
    await profiles.select(PROJECT, ModelRole.RESEARCH, "hosted")

    resolved = await effective.research(PROJECT_ID)

    assert (resolved.model, resolved.base_url) == ("gpt-4o", "https://api.openai.com/v1/")


async def test_selecting_a_research_profile_does_not_move_extraction(effective, stores):
    """Five roles, five selections. A build that read one selection list and
    ignored the role would point extraction at the agent's profile."""
    _, profiles = stores
    await profiles.put_profile(
        PROJECT,
        ModelProfile(
            name="hosted",
            provider_id="openai",
            model="gpt-4o",
            base_url="https://api.openai.com/v1/",
        ),
    )
    await profiles.select(PROJECT, ModelRole.RESEARCH, "hosted")

    assert (await effective.research(PROJECT_ID)).model == "gpt-4o"
    assert (await effective.extraction(PROJECT_ID)).model == config.extraction_model()
