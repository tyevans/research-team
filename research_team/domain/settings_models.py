"""Model profiles, role mappings, and connections for settings.

Decomposes settings.py by extracting ModelProfile, ModelRole, ROLE_MODEL_KEYS,
Connection, and CONNECTIONS into settings_models.py.
"""

from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "CONNECTIONS",
    "ROLE_MODEL_KEYS",
    "Connection",
    "ModelProfile",
    "ModelRole",
]


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
    ModelRole.EXTRACTION: "extraction_model",
    ModelRole.CURATION: "curation_model",
    ModelRole.EMBEDDING: "embedding_model",
    ModelRole.VISION: "vision_model",
}
"""Five roles, five keys, and **no two roles share one**.

Extraction used to map to `model`, which made the role enum a lie in the one
place it mattered: picking a cheap extraction model silently repointed the
research agent at it, because there was only ever one string. Five
independently selectable roles whose keys collide are four roles.

`extraction_model` falls back to the chat model when unset, exactly as
`curation_model` does and for the same reason -- the two jobs run against the
same endpoint on a default install, and a required variable for a role nobody
has customised would be a new way for a fresh clone not to start. What changes
is that customising one no longer moves the other.

`test_no_two_roles_resolve_from_one_setting` is what holds this.
"""


@dataclass(frozen=True)
class Connection:
    """A model, an endpoint and a credential that are dialled together.

    What makes a connection testable is that all three keys are declared: a
    role with a model name but no endpoint of its own borrows the chat one, so
    "test this role" and "test the chat connection" would be the same request
    sent twice under different names. Two roles have their own three today --
    research and embedding -- which is why this is a tuple of two rather than a
    map over all five.

    `group` is the registry group whose form the test belongs under, and it is
    stored rather than derived at the call site so the console can ask "does
    this group have a connection" without holding a key list of its own. That
    is the constraint `domain/settings/spec.ts` states from the other end:
    the frontend hand-writes no setting keys, so anything it needs to know
    about a key has to arrive on the wire.
    """

    role: ModelRole
    group: str
    model_key: str
    base_url_key: str
    api_key_key: str


#: The connections a person can test from the settings form.
#:
#: Derived from nothing -- these five-way relationships are not implied by any
#: other structure here -- so `test_every_connection_names_declared_settings`
#: checks each key against `BY_KEY` and each `group` against the spec's own,
#: which is the population check CLAUDE.md's "two structures that must agree"
#: section asks for. A sixth connection added with a typo'd key fails there
#: rather than rendering a test button that 422s.
CONNECTIONS: tuple[Connection, ...] = (
    Connection(
        role=ModelRole.RESEARCH,
        group="Models",
        model_key="model",
        base_url_key="base_url",
        api_key_key="api_key",
    ),
    Connection(
        role=ModelRole.EMBEDDING,
        group="Embeddings",
        model_key="embedding_model",
        base_url_key="embedding_base_url",
        api_key_key="embedding_api_key",
    ),
)
