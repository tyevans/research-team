"""What a setting *is*, before anyone stores or resolves one.

The project's configuration was ~60 `AGENT_*` environment variables read at
process start, every one of them global (`infrastructure/config.py`). Most are
not process-level facts: which model authors a course, how wide a chunk is,
which key talks to which endpoint -- those belong to a person or a project, and
two projects on one process should be able to disagree about them.

So a setting gets a *declaration* here rather than only a reader over
`os.getenv`. The declaration carries the things a reader cannot: what the value
means to a human, which scopes are allowed to set it, whether it is a secret,
and what a valid value looks like. That is what makes a settings UI possible
without a second, hand-written description of the same forty-odd knobs -- and
what makes the registry testable, since a checkpoint over a hand-written list
is worth exactly one commit (CLAUDE.md, "Checkpoints over model output").

**The environment is a layer, not a legacy.** `SettingSpec.env_var` is not a
migration note; it is the name of the layer that answers when no scope has an
override. A headless CLI run, a test that sets `AGENT_MODEL`, and a container
configured entirely by environment all keep working, because the lowest two
layers of resolution are exactly what this module already describes: the
environment variable, then `default`.

Nothing here imports anything outside the standard library. A setting
declaration is data; the store, the resolver, the encryption and the HTTP
surface are all elsewhere.
"""

from dataclasses import dataclass
from enum import StrEnum

from research_team.settings.domain.models import (
    CONNECTIONS as CONNECTIONS,
)
from research_team.settings.domain.models import (
    ROLE_MODEL_KEYS as ROLE_MODEL_KEYS,
)
from research_team.settings.domain.models import (
    Connection as Connection,
)
from research_team.settings.domain.models import (
    ModelProfile as ModelProfile,
)
from research_team.settings.domain.models import (
    ModelRole as ModelRole,
)
from research_team.settings.domain.models import (
    SettingError as SettingError,
)


class Scope(StrEnum):
    """Who a value belongs to. Ordered most-specific first by `RESOLUTION_ORDER`.

    A `str` enum rather than a bare `Enum` because these round-trip through
    JSON and a SQLite column, and a value that serialises as `"project"` in
    both directions is one fewer conversion to get wrong.
    """

    PROJECT = "project"
    USER = "user"
    TENANT = "tenant"


#: Most specific first. Resolution walks this list and stops at the first layer
#: holding a value, then falls through to the environment and the built-in
#: default. Written down once here rather than in the resolver, because the
#: HTTP contract reports *which* layer answered and the two orders must be the
#: same order -- a provenance label derived from a different list than the walk
#: is a label that can lie.
RESOLUTION_ORDER: tuple[Scope, ...] = (Scope.PROJECT, Scope.USER, Scope.TENANT)

#: The two layers below every scope. Named as strings rather than `Scope`
#: members on purpose: neither is a scope anyone can write an override at, and
#: making them members would put them in every "which scopes may set this"
#: list and in the UI's scope picker.
ENVIRONMENT_LAYER = "environment"
DEFAULT_LAYER = "default"


class SettingType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM = "enum"


#: What `AGENT_TRACING` and friends have always accepted. Kept as the one
#: definition rather than repeated per reader: `config.py` had three separate
#: spellings of this test, and `interaction_log_enabled` inverted one of them.
TRUE_WORDS = frozenset({"1", "true", "yes", "on"})
FALSE_WORDS = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True)
class SettingSpec:
    """One knob, declared.

    `default` is the built-in -- the bottom layer, and the value the system
    ships with. `None` means genuinely unset, which for some settings (a
    SearXNG url, a vision model) is a meaningful state and not an error; a
    setting that must have a value before its feature runs says so through
    `required_when`, which is prose for a human rather than a rule this module
    enforces. `config.py` still raises for those, at the point of use, where it
    can name the feature that needed it.
    """

    key: str
    """Lower-snake, and mechanically the env var minus `AGENT_`.

    Derived rather than chosen so that nobody has to remember a mapping, and
    so the registry test can check the pair by transformation instead of by
    table."""

    env_var: str
    type: SettingType
    default: object | None
    label: str
    description: str
    scopes: frozenset[Scope]
    """Which scopes may hold an override. Not every setting is per-project: a
    pgvector DSN is a property of the deployment, and offering it on a project
    form would invite a project to point the whole process at another
    database."""

    group: str
    """What the UI puts it under. Purely presentational, and here rather than
    in the frontend so W-C1 does not have to re-describe forty settings."""

    secret: bool = False
    """Never leaves a read endpoint. See `application/settings.py` for what is
    returned in its place and `infrastructure/settings/secrets.py` for how it
    is stored."""

    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    required_when: str | None = None
    """Prose: the condition under which an unset value is a failure. Rendered
    as help text; not enforced here."""

    def parse(self, raw: str) -> object:
        """A string from the environment or an HTTP body, as this setting's type.

        Everything arrives as text -- `os.environ` has no other kind of value,
        and a settings form posts strings -- so parsing lives with the
        declaration rather than at each of the two call sites, which is how
        `config.py` came to have three spellings of "is this true".
        """
        text = raw.strip()
        if self.type is SettingType.BOOLEAN:
            lowered = text.lower()
            if lowered in TRUE_WORDS:
                return True
            if lowered in FALSE_WORDS:
                return False
            raise SettingError(f"{self.key}: {raw!r} is not a boolean")
        if self.type is SettingType.INTEGER:
            try:
                number = int(text)
            except ValueError as error:
                raise SettingError(f"{self.key}: {raw!r} is not an integer") from error
            return self.validate(number)
        if self.type is SettingType.NUMBER:
            try:
                decimal = float(text)
            except ValueError as error:
                raise SettingError(f"{self.key}: {raw!r} is not a number") from error
            return self.validate(decimal)
        if self.type is SettingType.ENUM:
            # Lowercased, because operators type into a shell rather than into
            # a parser -- `AGENT_CONTEXT="  Elide "` has always been accepted
            # and `test_a_mode_is_read_forgivingly` is what says so. Every
            # declared choice is lowercase, which is what makes this safe to do
            # once here rather than per reader.
            return self.validate(text.lower())
        return self.validate(text)

    def validate(self, value: object) -> object:
        """The already-typed value, or `SettingError` naming what is wrong."""
        if self.type is SettingType.ENUM:
            if value not in self.choices:
                raise SettingError(
                    f"{self.key}: {value!r} is not one of {', '.join(self.choices)}"
                )
            return value
        if self.type in (SettingType.INTEGER, SettingType.NUMBER):
            number = float(value)  # type: ignore[arg-type]
            if self.minimum is not None and number < self.minimum:
                raise SettingError(f"{self.key}: {value!r} is below {self.minimum}")
            if self.maximum is not None and number > self.maximum:
                raise SettingError(f"{self.key}: {value!r} is above {self.maximum}")
        return value

    def serialise(self, value: object) -> str:
        """The stored form.

        Booleans go as `on`/`off` so a stored row reads the way the equivalent
        environment variable would -- the table is meant to be greppable by a
        person working out why a project resolved the way it did.
        """
        if isinstance(value, bool):
            return "on" if value else "off"
        return str(value)


def _spec(
    env_var: str,
    type_: SettingType,
    default: object | None,
    label: str,
    description: str,
    group: str,
    *,
    scopes: tuple[Scope, ...] = RESOLUTION_ORDER,
    secret: bool = False,
    choices: tuple[str, ...] = (),
    minimum: float | None = None,
    maximum: float | None = None,
    required_when: str | None = None,
) -> SettingSpec:
    """A declaration, with the key derived from the variable name.

    Deriving rather than passing both is the point: the key and the variable
    cannot drift, and the registry test asserts the relationship instead of a
    list of pairs.
    """
    if not env_var.startswith("AGENT_"):
        raise ValueError(f"{env_var} is not an AGENT_ variable")
    return SettingSpec(
        key=env_var.removeprefix("AGENT_").lower(),
        env_var=env_var,
        type=type_,
        default=default,
        label=label,
        description=description,
        scopes=frozenset(scopes),
        group=group,
        secret=secret,
        choices=choices,
        minimum=minimum,
        maximum=maximum,
        required_when=required_when,
    )


try:
    from research_team.settings.domain.registry import (
        _DEPLOYMENT as _DEPLOYMENT,
    )
    from research_team.settings.domain.registry import (
        SETTINGS as SETTINGS,
    )
except ImportError:
    _DEPLOYMENT = (Scope.TENANT,)
    SETTINGS = ()  # type: ignore[assignment]


#: The variables that stay environment-only, each with the reason. Read by
#: `test_every_environment_variable_config_reads_is_declared_or_excused`, which
#: derives the population from `config.py`'s own source rather than from a list
#: -- so a further variable added tomorrow fails at collection unless it is
#: either declared above or excused here with a sentence.
ENVIRONMENT_ONLY: dict[str, str] = {
    "AGENT_DB": (
        "Where the settings store itself lives. A setting whose value decides "
        "which database holds the settings cannot be read from that database."
    ),
    "AGENT_INTERACTION_DB": (
        "A second database path, resolved before any store opens. AGENT_DB's circularity."
    ),
    "AGENT_BLOB_ROOT": (
        "A filesystem path the process must own before a request exists, and the "
        "hook `tests/conftest.py` uses to keep uploads out of a developer's home."
    ),
    "AGENT_PERCEPTION_ROOT": "A filesystem path, for AGENT_BLOB_ROOT's reason.",
    "AGENT_WEB_HOST": "Bound before the first request, so no request's scope can supply it.",
    "AGENT_WEB_PORT": "Bound before the first request, for AGENT_WEB_HOST's reason.",
    "AGENT_SETTINGS_KEY": (
        "The key secrets are encrypted with. Storing it beside the ciphertext "
        "would make the encryption decorative."
    ),
    # The five remaining identity variables, excused for one reason rather than
    # five. It is stronger than AGENT_WEB_HOST's "bound before the first
    # request": resolution walks project, then user, then tenant, and **a user
    # scope cannot exist before authentication has decided who the user is.** A
    # setting whose value decides how a person is identified cannot be resolved
    # through a scope that identifies them. That is AGENT_DB's circularity with
    # a different store.
    #
    # AGENT_AUTH is *not* here, and the split is worth stating because it looks
    # inconsistent. It is declared above, as an enum, by W-B: what it governs
    # there is which `Authorizer` adapter is wired, which is a deployment fact
    # resolved once at startup. What it governs *here* is `AuthGate`, which runs
    # before routing. Both readings are of the same startup-time value, so one
    # declaration serves both -- and `config.auth_enabled` is where the enum's
    # protection against a silently-unauthenticated typo is enforced for the
    # environment layer, which the declaration alone does not reach.
    "AGENT_OIDC_ISSUER": "Identity configuration, for AGENT_AUTH's circularity.",
    "AGENT_OIDC_SCOPES": "Identity configuration, for AGENT_AUTH's circularity.",
    "AGENT_OIDC_CLIENT_ID": "Identity configuration, for AGENT_AUTH's circularity.",
    "AGENT_OIDC_CLIENT_SECRET": (
        "Identity configuration, for AGENT_AUTH's circularity -- and a secret "
        "whose store would be unreadable without it, per AGENT_SETTINGS_KEY."
    ),
    "AGENT_AUTH_PUBLIC_URL": (
        "The origin the OIDC redirect URI is built from. Deliberately not "
        "derived from a request (see `config.auth_public_url`), so there is no "
        "request-scoped layer it could come from."
    ),
    "AGENT_SESSION_SECRET": (
        "The key session cookies are signed with. Verified on every request "
        "*before* a scope is known, which is AGENT_AUTH's circularity, and a "
        "signing key beside the data it authenticates, which is "
        "AGENT_SETTINGS_KEY's."
    ),
}


BY_KEY: dict[str, SettingSpec] = {spec.key: spec for spec in SETTINGS}
BY_ENV: dict[str, SettingSpec] = {spec.env_var: spec for spec in SETTINGS}


def spec_for(key: str) -> SettingSpec:
    """The declaration for `key`, or `SettingError` -- never a `KeyError`.

    An unknown key arrives from an HTTP path segment, so the caller needs a
    422 rather than a 500, and phrasing that as an exception type here keeps
    the route from matching on message text.
    """
    try:
        return BY_KEY[key]
    except KeyError as error:
        raise SettingError(f"no setting named {key!r}") from error


try:
    from research_team.settings.domain.provider_specs import (
        PROVIDER_KEY_GROUP as PROVIDER_KEY_GROUP,
    )
    from research_team.settings.domain.provider_specs import (
        PROVIDER_KEY_PREFIX as PROVIDER_KEY_PREFIX,
    )
    from research_team.settings.domain.provider_specs import (
        _credential_of as _credential_of,
    )
    from research_team.settings.domain.provider_specs import (
        _provider_env_var as _provider_env_var,
    )
    from research_team.settings.domain.provider_specs import (
        dynamic_spec_for as dynamic_spec_for,
    )
    from research_team.settings.domain.provider_specs import (
        dynamic_specs as dynamic_specs,
    )
    from research_team.settings.domain.provider_specs import (
        provider_key as provider_key,
    )
    from research_team.settings.domain.provider_specs import (
        resolve_spec as resolve_spec,
    )
except ImportError:
    pass


@dataclass(frozen=True)
class ScopeRef:
    """A scope and the thing it names.

    A pair rather than two arguments everywhere, because they are never
    meaningful apart and a route that took them separately could be called
    with a project id under `Scope.USER`.
    """

    scope: Scope
    scope_id: str


@dataclass(frozen=True)
class Override:
    """One stored value.

    `value` is the serialised form for an ordinary setting and the ciphertext
    for a secret -- the table holds no plaintext credential, and the resolver
    is the one place that knows which of the two it is looking at.
    """

    scope: Scope
    scope_id: str
    key: str
    value: str
    updated_at: str


@dataclass(frozen=True)
class MaskedSecret:
    """How a secret is reported to a reader.

    A type rather than a convention: `mask()` below is the only thing that
    crosses the read boundary for a secret setting, and
    `test_a_secret_never_leaves_a_read_endpoint` asserts that neither the
    plaintext nor the ciphertext appears in any response body.
    """

    present: bool
    last_four: str | None = None

    @property
    def display(self) -> str:
        if not self.present:
            return "not set"
        return f"set (…{self.last_four})" if self.last_four else "set"


def mask(plaintext: str | None) -> MaskedSecret:
    """What a read endpoint may say about a secret.

    Last four rather than a prefix: an API key's prefix is usually the
    provider's (`sk-`, `gsk_`), so a prefix identifies the vendor and nothing
    about *which* key it is, which is the opposite of what someone checking "did
    I paste the right one" needs. Four characters is short enough not to help
    guess the rest and long enough to tell two keys apart.

    Under eight characters reports presence and no digits at all -- publishing
    four of a six-character secret would be publishing most of it.
    """
    if not plaintext:
        return MaskedSecret(present=False)
    if len(plaintext) < 8:
        return MaskedSecret(present=True)
    return MaskedSecret(present=True, last_four=plaintext[-4:])
