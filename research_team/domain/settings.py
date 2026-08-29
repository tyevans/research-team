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

from dataclasses import dataclass, field
from enum import StrEnum


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


class SettingError(ValueError):
    """A value that is not valid for its declaration.

    Its own type so the HTTP layer can answer 422 without matching on message
    text, and so a bad *stored* value -- one written before a declaration
    narrowed -- is distinguishable from a bug.
    """


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


#: Deployment-wide, and deliberately not per-project or per-user. Anything
#: scoped this way is read before a request exists, or names a shared backing
#: service, so a per-project answer is either meaningless or a way for one
#: project to move everyone's data.
_DEPLOYMENT = (Scope.TENANT,)


SETTINGS: tuple[SettingSpec, ...] = (
    # --- models and endpoints ---------------------------------------------
    _spec(
        "AGENT_MODEL",
        SettingType.STRING,
        "qwen3.6-27b-mtp",
        "Chat model",
        "The model the research agent talks to.",
        "Models",
    ),
    _spec(
        "AGENT_BASE_URL",
        SettingType.STRING,
        "http://localhost:8080/v1/",
        "Base URL",
        "An OpenAI-compatible endpoint. See the provider catalogue for shapes.",
        "Models",
    ),
    _spec(
        "AGENT_API_KEY",
        SettingType.STRING,
        "not-needed",
        "API key",
        "Credential for the chat endpoint. Stored encrypted; never read back.",
        "Models",
        secret=True,
    ),
    _spec(
        "AGENT_CURATION_MODEL",
        SettingType.STRING,
        None,
        "Curation model",
        "Runs the media-curation chain. Falls back to the chat model when unset.",
        "Models",
    ),
    _spec(
        "AGENT_VISION_MODEL",
        SettingType.STRING,
        None,
        "Vision model",
        "Describes frames and images. Unset means no vision at all.",
        "Models",
    ),
    _spec(
        "AGENT_EMBEDDING_MODEL",
        SettingType.STRING,
        "nomic-embed-text",
        "Embedding model",
        "Turns text into vectors. Not the chat model -- see its reader's docstring.",
        "Embeddings",
    ),
    _spec(
        "AGENT_EMBEDDING_DIMENSION",
        SettingType.INTEGER,
        768,
        "Embedding dimension",
        "This model's vector width. A property of the model, not a taste.",
        "Embeddings",
        minimum=1,
    ),
    _spec(
        "AGENT_EMBEDDING_BASE_URL",
        SettingType.STRING,
        None,
        "Embedding base URL",
        "Where embedding requests go. Falls back to the chat endpoint.",
        "Embeddings",
    ),
    _spec(
        "AGENT_EMBEDDING_API_KEY",
        SettingType.STRING,
        None,
        "Embedding API key",
        "Credential for the embedding endpoint. Falls back to the chat key.",
        "Embeddings",
        secret=True,
    ),
    _spec(
        "AGENT_TRANSCRIBER_URL",
        SettingType.STRING,
        None,
        "Transcriber URL",
        "A whisper.cpp server. Unset means audio is perceived without speech.",
        "Perception",
    ),
    _spec(
        "AGENT_TRANSCRIBER_MODEL",
        SettingType.STRING,
        None,
        "Transcriber model",
        "The ASR revision. Part of the capability fingerprint, so it has no default.",
        "Perception",
        required_when="a transcriber URL is set",
    ),
    # --- context management ------------------------------------------------
    _spec(
        "AGENT_CONTEXT",
        SettingType.ENUM,
        "full",
        "Context mode",
        "How a conversation that outgrows the window is managed.",
        "Context",
        choices=("full", "elide", "compact", "delegate"),
    ),
    _spec(
        "AGENT_CONTEXT_TRIGGER",
        SettingType.INTEGER,
        120_000,
        "Compaction trigger",
        "Approximate tokens of conversation `compact` tolerates before summarising.",
        "Context",
        minimum=1,
    ),
    _spec(
        "AGENT_CONTEXT_KEEP_MESSAGES",
        SettingType.INTEGER,
        20,
        "Messages kept",
        "How many recent messages `compact` leaves out of the summary.",
        "Context",
        minimum=0,
    ),
    _spec(
        "AGENT_CONTEXT_KEEP_RESULTS",
        SettingType.INTEGER,
        6,
        "Tool results kept",
        "How many recent tool results `elide` leaves whole.",
        "Context",
        minimum=0,
    ),
    _spec(
        "AGENT_CONTEXT_CLEAR_OVER",
        SettingType.INTEGER,
        2_000,
        "Clear results over",
        "How long an older tool result may be before `elide` replaces it outright.",
        "Context",
        minimum=1,
    ),
    # --- knowledge and extraction ------------------------------------------
    _spec(
        "AGENT_KNOWLEDGE_DOMAIN",
        SettingType.STRING,
        "research_corpus",
        "Knowledge schema",
        "This project's schema id, a redstring one, or `auto` to classify per document.",
        "Extraction",
    ),
    _spec(
        "AGENT_EXTRACTION_CONCURRENCY",
        SettingType.INTEGER,
        8,
        "Extraction concurrency",
        "Extraction calls in flight per document. Lower it against a quota'd endpoint.",
        "Extraction",
        minimum=1,
    ),
    _spec(
        "AGENT_EXTRACTION_CHUNK_SIZE",
        SettingType.INTEGER,
        2_000,
        "Extraction chunk size",
        "Characters per chunk. Smaller extracts more and costs consolidation calls.",
        "Extraction",
        minimum=200,
    ),
    _spec(
        "AGENT_EXTRACTION_THINKING",
        SettingType.BOOLEAN,
        False,
        "Extraction thinking",
        "Let the extraction model reason first. Off: measured worse precision, 5x slower.",
        "Extraction",
    ),
    _spec(
        "AGENT_CONSOLIDATION_BATCH",
        SettingType.INTEGER,
        25,
        "Consolidation batch",
        "Entities decided together in one consolidation pass.",
        "Extraction",
        minimum=1,
    ),
    _spec(
        "AGENT_CATALOG_SWEEP_CONCURRENCY",
        SettingType.INTEGER,
        1,
        "Catalog sweep concurrency",
        "Candidates a blurb or art sweep works on at once. 1 bought all that was measurable.",
        "Extraction",
        minimum=1,
    ),
    # --- stores --------------------------------------------------------------
    _spec(
        "AGENT_GRAPH_STORE",
        SettingType.ENUM,
        "memory",
        "Graph store",
        "What backs the knowledge graph.",
        "Stores",
        choices=("memory", "neo4j"),
        scopes=_DEPLOYMENT,
    ),
    _spec(
        "AGENT_VECTOR_STORE",
        SettingType.ENUM,
        "memory",
        "Vector store",
        "What backs entity embeddings. `none` drops consolidation's third feature.",
        "Stores",
        choices=("none", "memory", "pgvector"),
        scopes=_DEPLOYMENT,
    ),
    _spec(
        "AGENT_CHUNK_STORE",
        SettingType.ENUM,
        "memory",
        "Chunk store",
        "What backs the document-chunk corpus.",
        "Stores",
        choices=("none", "memory", "postgres"),
        scopes=_DEPLOYMENT,
    ),
    _spec(
        "AGENT_PGVECTOR_DSN",
        SettingType.STRING,
        None,
        "pgvector DSN",
        "Where the vectors live. No default: a silent localhost connection writes "
        "to somebody's development database.",
        "Stores",
        scopes=_DEPLOYMENT,
        secret=True,
        required_when="the vector store is pgvector",
    ),
    _spec(
        "AGENT_NEO4J_URI",
        SettingType.STRING,
        "bolt://localhost:7687",
        "Neo4j URI",
        "The bolt endpoint.",
        "Stores",
        scopes=_DEPLOYMENT,
    ),
    _spec(
        "AGENT_NEO4J_USER",
        SettingType.STRING,
        "neo4j",
        "Neo4j user",
        "The account to connect as.",
        "Stores",
        scopes=_DEPLOYMENT,
    ),
    _spec(
        "AGENT_NEO4J_PASSWORD",
        SettingType.STRING,
        None,
        "Neo4j password",
        "No default. A store that comes up on `neo4j/neo4j` connects to somebody's server.",
        "Stores",
        scopes=_DEPLOYMENT,
        secret=True,
        required_when="the graph store is neo4j",
    ),
    _spec(
        "AGENT_NEO4J_DATABASE",
        SettingType.STRING,
        None,
        "Neo4j database",
        "Which database within the server. Unset means the server's own default.",
        "Stores",
        scopes=_DEPLOYMENT,
    ),
    # --- search ---------------------------------------------------------------
    _spec(
        "AGENT_SEARXNG_URL",
        SettingType.STRING,
        None,
        "SearXNG URL",
        "Unset means the agent gets no network tool at all.",
        "Search",
    ),
    _spec(
        "AGENT_SEARXNG_RESULTS",
        SettingType.INTEGER,
        5,
        "SearXNG results",
        "How many results reach the model. Capped because context is the cost.",
        "Search",
        minimum=1,
    ),
    # --- perception and media -------------------------------------------------
    _spec(
        "AGENT_PERCEPTION_MAX_CHARS",
        SettingType.INTEGER,
        500_000,
        "Perception budget",
        "Characters of derived text. Equal to the document cap, deliberately.",
        "Perception",
        minimum=1,
    ),
    _spec(
        "AGENT_MEDIA_RECONCILE_INTERVAL",
        SettingType.NUMBER,
        300.0,
        "Media reconcile interval",
        "Seconds between sweeps for proposals stuck at `accepted`.",
        "Media",
        scopes=_DEPLOYMENT,
        minimum=1,
    ),
    _spec(
        "AGENT_BLOB_SWEEP_GRACE",
        SettingType.NUMBER,
        86_400.0,
        "Blob sweep grace",
        "How long an unreferenced blob must sit before the sweep may delete it.",
        "Media",
        scopes=_DEPLOYMENT,
        minimum=1,
    ),
    # --- observability ---------------------------------------------------------
    _spec(
        "AGENT_TRACING",
        SettingType.BOOLEAN,
        False,
        "Tracing",
        "Export OTLP traces. Off unless something is collecting them.",
        "Observability",
        scopes=_DEPLOYMENT,
    ),
    _spec(
        "AGENT_OTLP_ENDPOINT",
        SettingType.STRING,
        "http://localhost:4318/v1/traces",
        "OTLP endpoint",
        "Where traces are sent.",
        "Observability",
        scopes=_DEPLOYMENT,
    ),
    _spec(
        "AGENT_SERVICE_NAME",
        SettingType.STRING,
        "research-team",
        "Service name",
        "What this process calls itself in a trace.",
        "Observability",
        scopes=_DEPLOYMENT,
    ),
    _spec(
        "AGENT_INTERACTION_LOG",
        SettingType.BOOLEAN,
        True,
        "Interaction log",
        "Record what the user did in the console. The one default-on switch here.",
        "Observability",
        scopes=_DEPLOYMENT,
    ),
)


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


@dataclass(frozen=True)
class ModelProfile:
    """A named (provider, model, credentials, parameters) triple, selectable per role.

    Today the five model settings above -- chat, curation, vision, embedding,
    and whatever extraction happens to use -- are separate strings that all
    default to one endpoint, so "my Anthropic key for authoring and my local
    vLLM for extraction" is not expressible: the api key is one variable.

    A profile is the unit that makes it expressible. `credential_key` names a
    *secret setting*; it does not carry the secret. A profile is read back to a
    browser whole, and a structure that could hold a key is a structure that
    will eventually be logged with one in it.
    """

    name: str
    provider_id: str
    model: str
    credential_key: str | None = None
    base_url: str | None = None
    parameters: dict[str, object] = field(default_factory=dict)


class ModelRole(StrEnum):
    """The jobs a profile can be selected for.

    Exactly the five the environment variables already distinguish, so this
    enum adds no new concept -- it names the one that was implicit in having
    five variables.
    """

    RESEARCH = "research"
    EXTRACTION = "extraction"
    CURATION = "curation"
    EMBEDDING = "embedding"
    VISION = "vision"


#: Which setting a role's model name resolves from when no profile is selected.
#: The bridge that keeps profiles additive: a deployment that never defines one
#: behaves exactly as it did, through the same reader.
ROLE_MODEL_KEYS: dict[ModelRole, str] = {
    ModelRole.RESEARCH: "model",
    ModelRole.EXTRACTION: "model",
    ModelRole.CURATION: "curation_model",
    ModelRole.EMBEDDING: "embedding_model",
    ModelRole.VISION: "vision_model",
}
