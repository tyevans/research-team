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
    RESOLUTION_ORDER,
    SETTINGS,
    Scope,
    SettingError,
    SettingType,
    mask,
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


def _keys_requested(path: Path) -> set[str]:
    """Every registry key `config.py` asks for, from its syntax tree.

    The other half of the contract, and the half that matters now that
    `config.py` names almost no variables: a reader calls `_text("model")`, and
    a typo there is a `KeyError` at import time for a constant and at call time
    for a reader. Import time is loud; call time is one route 500ing on a
    setting nobody exercises in the suite.
    """
    tree = ast.parse(path.read_text())
    helpers = {"_value", "_text", "_optional", "_int", "_float", "_flag", "_choices"}
    helpers |= {"_builtin", "_builtin_text", "_builtin_int", "_builtin_float"}
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


def test_the_key_scan_found_the_readers_it_is_supposed_to_guard():
    """Same argument as the scan above: zero keys would pass silently."""
    assert len(KEYS_REQUESTED) >= 30, KEYS_REQUESTED


@pytest.mark.parametrize("key", KEYS_REQUESTED)
def test_every_key_config_asks_for_is_declared(key):
    """A misspelled key is a reader that raises the first time it is called.

    Renaming a declaration without renaming its reader turns this red naming
    the key, at collection time rather than on whichever request happened to
    touch it.
    """
    assert key in BY_KEY, f"config.py asks for {key!r}, which SETTINGS does not declare"
