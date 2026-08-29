"""The registry covers what `config.py` reads, derived rather than listed.

CLAUDE.md's "Checkpoints over model output" section is about a Python check
over text a model wrote, and the durable half of it applies here word for word:
**a contract that has to be remembered is documentation; the test is the
contract.** A hand-written list of "these forty-five variables have
declarations" is correct for exactly one commit -- the commit that writes it --
and the forty-sixth variable enters silently.

So the population comes from the *source* of the modules that read the
environment, walked as a syntax tree, and every `AGENT_*` string found in them
has to be either declared in `SETTINGS` or excused by name in
`ENVIRONMENT_ONLY` with a reason attached. Adding a variable to `config.py`
without doing one of those two fails here, naming it.
"""

import ast
from pathlib import Path

import pytest

from research_team.domain.settings import (
    BY_ENV,
    BY_KEY,
    ENVIRONMENT_ONLY,
    PROVIDER_KEY_GROUP,
    PROVIDER_KEY_PREFIX,
    RESOLUTION_ORDER,
    ROLE_MODEL_KEYS,
    SETTINGS,
    ModelRole,
    Scope,
    SettingError,
    SettingType,
    dynamic_spec_for,
    dynamic_specs,
    mask,
    provider_key,
    resolve_spec,
    spec_for,
)

PACKAGE = Path(__file__).resolve().parent.parent.parent / "research_team"

#: The modules allowed to read the environment at all. `config.py` is the
#: documented edge; the settings package is where the encryption key is read,
#: which is the one variable that cannot be a setting.
READERS = (
    PACKAGE / "infrastructure" / "config.py",
    PACKAGE / "infrastructure" / "settings" / "secrets.py",
)


def _named_variables(path: Path) -> set[str]:
    """Every `AGENT_*` literal in a module, from its syntax tree.

    A string constant rather than specifically an `os.getenv` argument, and
    deliberately so: after this branch `config.py` reaches the environment
    through the registry, so a variable *named* anywhere in it -- in a reader,
    in an error message, in a docstring -- is a variable this project talks
    about and therefore one a reader can be told about. Over-inclusive on
    purpose: the cost of a false positive is one line in `ENVIRONMENT_ONLY`
    with a sentence in it, and the cost of a false negative is the whole point
    of the test.
    """
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for word in node.value.replace("=", " ").replace("`", " ").split():
                if word.startswith("AGENT_"):
                    found.add(word.rstrip(".,:;'\"!)"))
    return found


ALL_NAMED = sorted({name for path in READERS for name in _named_variables(path)})


def test_the_scan_found_the_variables_it_is_supposed_to_guard():
    """The guard above is worthless if the scan finds nothing.

    A syntax-tree walk that matches no strings passes every parametrised case
    below by collecting zero of them, which reads exactly like success -- the
    "a test that silently checks nothing is not cheap to reinstate" argument
    `tests/test_architecture.py` makes about its deleted exemption.

    Twenty is a floor, not a count, so adding or removing one variable does not
    fail it -- and it is twenty rather than forty-five because most variables
    are no longer *named* in `config.py` at all. They are reached by key
    through the registry, which `test_every_key_config_asks_for_is_declared`
    covers; what is left as a literal here is the excused paths and the readers
    that raise naming a variable.
    """
    assert len(ALL_NAMED) >= 20, ALL_NAMED
    assert "AGENT_MODEL" in ALL_NAMED
    assert "AGENT_DB" in ALL_NAMED


@pytest.mark.parametrize("name", ALL_NAMED)
def test_every_environment_variable_config_reads_is_declared_or_excused(name):
    """Each variable is a setting, or is environment-only with a reason.

    Reverting a declaration out of `SETTINGS` turns this red for that variable
    and nothing else; that is what it is for.
    """
    if name in ENVIRONMENT_ONLY:
        assert ENVIRONMENT_ONLY[name].strip(), f"{name} is excused with no reason"
        assert name not in BY_ENV, f"{name} is both declared and excused"
        return
    assert name in BY_ENV, (
        f"{name} is read but has no declaration in SETTINGS and no entry in "
        f"ENVIRONMENT_ONLY -- add one, with the reason if it is the latter"
    )


@pytest.mark.parametrize("spec", SETTINGS, ids=[spec.key for spec in SETTINGS])
def test_a_key_is_its_variable_name_and_nothing_else(spec):
    """The relationship, not a table of pairs.

    `_spec` derives one from the other, so this can only fail if someone
    constructs a `SettingSpec` directly -- which is the case worth catching,
    because a hand-made key is a key the UI and the environment disagree about.
    """
    assert spec.key == spec.env_var.removeprefix("AGENT_").lower()


@pytest.mark.parametrize("spec", SETTINGS, ids=[spec.key for spec in SETTINGS])
def test_every_declaration_is_usable_by_a_form(spec):
    """A label, a description, a group and at least one scope.

    These are what W-C1 renders. A setting with an empty description is a field
    with no help text, which is how a settings page becomes forty inputs nobody
    dares touch.
    """
    assert spec.label.strip()
    assert spec.description.strip()
    assert spec.group.strip()
    assert spec.scopes
    assert spec.scopes <= set(RESOLUTION_ORDER)
    if spec.type is SettingType.ENUM:
        assert spec.choices, f"{spec.key} is an enum with no choices"
        assert spec.default in spec.choices


@pytest.mark.parametrize(
    "spec", [spec for spec in SETTINGS if spec.default is not None], ids=lambda s: s.key
)
def test_every_default_survives_its_own_validation(spec):
    """A default outside its own declared range is a setting that refuses the
    value it ships with -- which nobody notices until the first person tries to
    save the form without changing that field."""
    assert spec.validate(spec.default) == spec.default


def test_an_unknown_key_is_a_setting_error_not_a_key_error():
    """The route answers 422 off this type. A `KeyError` would be a 500."""
    with pytest.raises(SettingError):
        spec_for("no_such_setting")


def test_a_boolean_reads_the_words_operators_type():
    spec = BY_KEY["tracing"]
    for word in ("1", "true", "TRUE", " yes ", "on"):
        assert spec.parse(word) is True, word
    for word in ("0", "false", "no", "OFF"):
        assert spec.parse(word) is False, word
    with pytest.raises(SettingError):
        spec.parse("perhaps")


def test_an_integer_below_its_minimum_is_refused():
    """`extraction_chunk_size` has a floor because below some size extraction
    stops finding more and starts manufacturing duplicate identities -- see the
    reader's docstring. A form that accepted 1 would be offering that."""
    with pytest.raises(SettingError):
        BY_KEY["extraction_chunk_size"].parse("10")


def test_a_secret_reports_presence_and_four_characters_at_most():
    """The masking is a property, not a convention.

    Both directions matter: an absent secret must not claim to be set, and a
    present one must not travel. `sk-live-abcd1234` yields four characters --
    enough to tell two keys apart, and a prefix would have identified only the
    vendor.
    """
    absent = mask(None)
    assert absent.present is False
    assert absent.last_four is None
    assert absent.display == "not set"

    present = mask("sk-live-abcd1234")
    assert present.present is True
    assert present.last_four == "1234"
    assert "abcd" not in present.display
    assert "sk-live" not in present.display


def test_a_short_secret_publishes_no_characters_at_all():
    """Four of a six-character secret is most of it. The threshold is the
    reason `mask` has a branch rather than a slice."""
    short = mask("abc123")
    assert short.present is True
    assert short.last_four is None
    assert short.display == "set"


def test_the_scopes_a_deployment_setting_offers_exclude_a_project():
    """A pgvector DSN moves where every project's vectors live. Offering it on
    a project form would let one project point the process at another
    database, which is the reason `_DEPLOYMENT` exists."""
    assert BY_KEY["pgvector_dsn"].scopes == {Scope.TENANT}
    assert Scope.PROJECT in BY_KEY["model"].scopes


def _key_helpers(tree: ast.Module) -> set[str]:
    """The reader helpers, from the module rather than from a list here.

    This used to be eleven names written out, and that is the one
    hand-maintained list in this file load-bearing enough to bite: a twelfth
    helper added to `config.py` would not be scanned, so every key requested
    through it would escape `test_every_key_config_asks_for_is_declared`
    silently -- the test would keep passing on the eleven it still knew about,
    which is exactly the shape CLAUDE.md's "a checkpoint that matches anything
    cannot tell a phase that worked from one that stopped" warns about.

    The signature is the definition: a helper is a module-level private
    function whose first parameter is `key`. That is what makes `_text("model")`
    a registry lookup rather than an ordinary call, so deriving from it means a
    new helper is scanned the moment it is written.
    """
    found = set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("_"):
            continue
        args = node.args.posonlyargs + node.args.args
        if args and args[0].arg == "key":
            found.add(node.name)
    return found


def _keys_requested(path: Path) -> set[str]:
    """Every registry key `config.py` asks for, from its syntax tree.

    The other half of the contract, and the half that matters now that
    `config.py` names almost no variables: a reader calls `_text("model")`, and
    a typo there is a `KeyError` at import time for a constant and at call time
    for a reader. Import time is loud; call time is one route 500ing on a
    setting nobody exercises in the suite.
    """
    tree = ast.parse(path.read_text())
    helpers = _key_helpers(tree)
    requested: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in helpers
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            requested.add(node.args[0].value)
    return requested


KEYS_REQUESTED = sorted(_keys_requested(PACKAGE / "infrastructure" / "config.py"))


KEY_HELPERS = sorted(
    _key_helpers(ast.parse((PACKAGE / "infrastructure" / "config.py").read_text()))
)


def test_the_key_scan_found_the_readers_it_is_supposed_to_guard():
    """Same argument as the scan above: zero keys would pass silently.

    Both floors, because the scan can now come up empty two ways -- no keys, or
    no helpers to find them through -- and the second is the quieter one.
    """
    assert len(KEYS_REQUESTED) >= 30, KEYS_REQUESTED
    assert len(KEY_HELPERS) >= 8, KEY_HELPERS
    assert "_text" in KEY_HELPERS


@pytest.mark.parametrize("key", KEYS_REQUESTED)
def test_every_key_config_asks_for_is_declared(key):
    """A misspelled key is a reader that raises the first time it is called.

    Renaming a declaration without renaming its reader turns this red naming
    the key, at collection time rather than on whichever request happened to
    touch it.
    """
    assert key in BY_KEY, f"config.py asks for {key!r}, which SETTINGS does not declare"


# --- the dynamic namespace, and how it stays out of the registry ---------


def test_a_provider_key_is_not_a_declared_setting():
    """The two populations are disjoint, and `SETTINGS` is the fixed one.

    **How they stay separate, stated because the test above depends on it.**
    `SETTINGS` is a literal tuple built at import; nothing appends to it at
    runtime, and `spec_for` reads `BY_KEY`, which is derived from it once. So a
    dynamic key cannot enter the registry, and
    `test_every_environment_variable_config_reads_is_declared_or_excused`
    cannot be satisfied by one -- the synthesised
    `AGENT_PROVIDER_KEY_GROQ_API_KEY` appears in no module's source, so the
    scan never sees it, and if it somehow did, `BY_ENV` would not contain it
    and the test would fail rather than pass.

    The direction that would be dangerous is the other one: a `spec_for` that
    fell through to `dynamic_spec_for` would make any provider-shaped key look
    declared. That is why the fall-through lives in `resolve_spec` instead, and
    why this test asserts `spec_for` still refuses.
    """
    assert not any(key.startswith(f"{PROVIDER_KEY_PREFIX}.") for key in BY_KEY)
    with pytest.raises(SettingError):
        spec_for(provider_key("groq", "api_key"))


def test_resolve_spec_reaches_both_populations():
    """One entry point above the domain, two sources beneath it."""
    assert resolve_spec("model").key == "model"
    assert resolve_spec(provider_key("groq")).key == "provider_key.groq.api_key"


@pytest.mark.parametrize("spec", dynamic_specs(), ids=[spec.key for spec in dynamic_specs()])
def test_every_dynamic_credential_is_usable_by_a_form(spec):
    """The same bar the declared settings are held to.

    Parametrised over the catalogue rather than a sample, so a sixteenth
    provider with an empty label fails here rather than rendering as a blank
    row in the settings page.
    """
    assert spec.label.strip()
    assert spec.description.strip()
    assert spec.group == PROVIDER_KEY_GROUP
    assert spec.scopes == set(RESOLUTION_ORDER)
    assert spec.default is None
    # No bounds on a credential: a bound in this registry is a claim about what
    # the system permits, and the only evidence for one is a caller it would
    # break. Nobody can say how long a provider's key is.
    assert spec.minimum is None and spec.maximum is None


def test_a_dynamic_key_normalises_to_its_named_form():
    """`provider_key.groq` and `provider_key.groq.api_key` are one setting.

    The key is hashed into the storage row id, so two spellings that did not
    normalise would be two rows -- and a credential written through one and
    cleared through the other would be invisible and unremovable. That is not
    hypothetical: `SettingsResolver.write` stored the caller's raw string
    until this branch, and this is the assertion that found it.
    """
    assert dynamic_spec_for(provider_key("groq")).key == provider_key("groq", "api_key")


def test_a_provider_id_outside_the_catalogue_is_refused():
    """The id lands in a storage key and a URL segment.

    Free text in a storage key is a shape this project has been bitten by
    before, and it would also let a caller mint unbounded rows in a table
    nothing else bounds.
    """
    with pytest.raises(SettingError, match="evilcorp"):
        dynamic_spec_for("provider_key.evilcorp")


def test_a_provider_with_several_credentials_refuses_to_guess():
    """Bedrock declares three, so the trailing segment is real rather than
    decorative -- and the refusal names all three, because the person reading
    it is deciding which one they meant."""
    with pytest.raises(SettingError) as raised:
        dynamic_spec_for(provider_key("bedrock"))

    message = str(raised.value)
    assert "access_key_id" in message
    assert "secret_access_key" in message
    assert "region" in message


def test_secrecy_comes_from_the_credential_not_the_prefix():
    """A region is not a secret. Masking it would make the settings page
    unreadable for the two providers that need the most from it."""
    assert dynamic_spec_for(provider_key("bedrock", "region")).secret is False
    assert dynamic_spec_for(provider_key("bedrock", "secret_access_key")).secret is True


def test_no_two_roles_resolve_from_one_setting():
    """Five roles sharing four keys is four roles.

    Extraction used to map to `model`, so choosing a cheap extraction model
    silently repointed the research agent at it -- the enum named five roles
    while two of them were one string. Reverting `ROLE_MODEL_KEYS` to that
    turns this red, which is the whole reason it is a test rather than a
    comment.
    """
    keys = list(ROLE_MODEL_KEYS.values())

    assert len(set(keys)) == len(keys) == len(ModelRole)
    assert ROLE_MODEL_KEYS[ModelRole.EXTRACTION] != ROLE_MODEL_KEYS[ModelRole.RESEARCH]


@pytest.mark.parametrize("role", list(ModelRole), ids=lambda r: r.value)
def test_every_role_names_a_declared_setting(role):
    """A role pointing at a key nothing declares is a role that raises the
    first time a settings page is opened."""
    assert ROLE_MODEL_KEYS[role] in BY_KEY
