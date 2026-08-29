"""The provider catalogue: fifteen endpoints, one adapter, mostly data.

**Most of these speak the OpenAI wire protocol**, and that is the load-bearing
fact about this module. `POST {base_url}chat/completions` with a bearer token
and `GET {base_url}models` is the whole interface for OpenAI, Mistral, Groq,
Together, Fireworks, DeepSeek, xAI, OpenRouter, Ollama, LM Studio and vLLM --
eleven of the fifteen. So the catalogue is a table of base urls and
capabilities rather than eleven adapters, and
`infrastructure/settings/probe.py` has one code path for all of them.

The four that are genuinely different, and why:

- **Anthropic** — `x-api-key` and `anthropic-version` headers instead of
  `Authorization: Bearer`, and `/v1/models` rather than `/models`. Close enough
  to probe with the same client and different headers; not close enough to call
  OpenAI-compatible.
- **Google Gemini** — its own `generativelanguage` surface with the key as a
  query parameter. Google *also* publishes an OpenAI-compatible shim, and this
  catalogue points at the native one because the shim does not carry the
  embedding models.
- **Azure OpenAI** — OpenAI's request bodies at a per-resource host, addressed
  by *deployment name* rather than model name, with `api-version` required on
  every call and `api-key` as the header. The body is compatible; nothing about
  the addressing is.
- **AWS Bedrock** — SigV4 request signing over a region host, and no bearer
  token at all. It needs three credentials rather than one and cannot be
  probed with an API key, which is why `connection_test` is `SIGNED` for it.

`capabilities` is what the provider *offers*, not what a particular model does:
a catalogue cannot know whether `gpt-4o-mini` was given vision, and pretending
otherwise would put a wrong claim in a picker. It answers "is it worth offering
an embedding role for this provider at all".

Domain-layer data, so nothing here reaches the network. The probe that does is
an infrastructure adapter over `ProviderProbePort`.
"""

from dataclasses import dataclass
from enum import StrEnum


class Capability(StrEnum):
    CHAT = "chat"
    EMBEDDINGS = "embeddings"
    VISION = "vision"
    TOOLS = "tools"


class Auth(StrEnum):
    """How a credential is presented. The axis the eleven agree on and the
    four do not."""

    BEARER = "bearer"
    """`Authorization: Bearer <key>`. The OpenAI-compatible eleven."""

    HEADER_KEY = "header_key"
    """A named header carrying the raw key -- Anthropic's `x-api-key`, Azure's
    `api-key`."""

    QUERY_KEY = "query_key"
    """The key as a query parameter. Gemini's native surface."""

    SIGNED = "signed"
    """Request signing, not a token. Bedrock's SigV4, which needs an access key,
    a secret and a region, and which no bearer-shaped probe can stand in for."""

    NONE = "none"
    """No credential. Ollama and LM Studio serve on localhost with no auth by
    default; a key may still be set and is sent when it is."""


@dataclass(frozen=True)
class Credential:
    """One field a provider needs before it can be called.

    `setting_key` names the *secret setting* that holds it rather than the
    value, for `ModelProfile.credential_key`'s reason -- a structure that can
    carry a key is one that gets logged with a key in it. Empty means the
    provider's credential has no home in the built-in registry yet and a
    bring-your-own-model profile supplies it.
    """

    name: str
    label: str
    secret: bool = True
    required: bool = True
    setting_key: str | None = None


@dataclass(frozen=True)
class Provider:
    id: str
    display_name: str
    base_url: str
    """The shape, not necessarily a working address. For the hosted providers
    this is the real endpoint; for Azure and Bedrock it carries `{}` markers
    naming what the operator has to fill in, which is the honest thing to show
    in a form."""

    auth: Auth
    openai_compatible: bool
    capabilities: frozenset[Capability]
    credentials: tuple[Credential, ...]
    models_path: str = "models"
    """Relative to `base_url`, for the connection test's list call. Empty means
    the provider offers no list and the test has to do a round trip instead."""

    notes: str = ""


_KEY = Credential(name="api_key", label="API key")


def _openai_like(
    id_: str,
    display_name: str,
    base_url: str,
    capabilities: tuple[Capability, ...],
    notes: str = "",
    auth: Auth = Auth.BEARER,
    credentials: tuple[Credential, ...] = (_KEY,),
) -> Provider:
    """One of the eleven. A helper rather than eleven literals, so that
    "OpenAI-compatible" is asserted in one place and cannot be typed wrong."""
    return Provider(
        id=id_,
        display_name=display_name,
        base_url=base_url,
        auth=auth,
        openai_compatible=True,
        capabilities=frozenset(capabilities),
        credentials=credentials,
        notes=notes,
    )


_CHAT_TOOLS = (Capability.CHAT, Capability.TOOLS)
_CHAT_TOOLS_VISION = (Capability.CHAT, Capability.TOOLS, Capability.VISION)
_EVERYTHING = (
    Capability.CHAT,
    Capability.TOOLS,
    Capability.VISION,
    Capability.EMBEDDINGS,
)


PROVIDERS: tuple[Provider, ...] = (
    _openai_like(
        "openai",
        "OpenAI",
        "https://api.openai.com/v1/",
        _EVERYTHING,
    ),
    Provider(
        id="anthropic",
        display_name="Anthropic",
        base_url="https://api.anthropic.com/v1/",
        auth=Auth.HEADER_KEY,
        openai_compatible=False,
        capabilities=frozenset(_CHAT_TOOLS_VISION),
        credentials=(_KEY,),
        notes=(
            "`x-api-key` plus a required `anthropic-version` header, and no "
            "embedding models. Probed with the same client and different headers."
        ),
    ),
    Provider(
        id="google",
        display_name="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/",
        auth=Auth.QUERY_KEY,
        openai_compatible=False,
        capabilities=frozenset(_EVERYTHING),
        credentials=(_KEY,),
        notes=(
            "The native surface, with the key as a query parameter. Google also "
            "publishes an OpenAI-compatible shim; this points at the native one "
            "because the shim does not carry the embedding models."
        ),
    ),
    _openai_like(
        "mistral",
        "Mistral",
        "https://api.mistral.ai/v1/",
        _EVERYTHING,
    ),
    _openai_like(
        "groq",
        "Groq",
        "https://api.groq.com/openai/v1/",
        _CHAT_TOOLS_VISION,
        notes="No embeddings. Fast, and rate-limited by tokens per minute.",
    ),
    _openai_like(
        "together",
        "Together AI",
        "https://api.together.xyz/v1/",
        _EVERYTHING,
    ),
    _openai_like(
        "fireworks",
        "Fireworks AI",
        "https://api.fireworks.ai/inference/v1/",
        _EVERYTHING,
    ),
    _openai_like(
        "deepseek",
        "DeepSeek",
        "https://api.deepseek.com/v1/",
        _CHAT_TOOLS,
        notes="Chat and tools only; no embedding or vision endpoint.",
    ),
    _openai_like(
        "xai",
        "xAI",
        "https://api.x.ai/v1/",
        _CHAT_TOOLS_VISION,
    ),
    _openai_like(
        "openrouter",
        "OpenRouter",
        "https://openrouter.ai/api/v1/",
        _EVERYTHING,
        notes=(
            "A router, so its capability set is the union of everything it "
            "fronts and says less about any one model than the others do."
        ),
    ),
    _openai_like(
        "ollama",
        "Ollama",
        "http://localhost:11434/v1/",
        _EVERYTHING,
        auth=Auth.NONE,
        credentials=(Credential(name="api_key", label="API key", required=False),),
        notes="Local, unauthenticated by default. One model per pull, several resident.",
    ),
    _openai_like(
        "lmstudio",
        "LM Studio",
        "http://localhost:1234/v1/",
        (Capability.CHAT, Capability.TOOLS, Capability.EMBEDDINGS),
        auth=Auth.NONE,
        credentials=(Credential(name="api_key", label="API key", required=False),),
        notes="Local. Serves whatever is loaded in the app, which `models` reports.",
    ),
    _openai_like(
        "vllm",
        "vLLM",
        "http://localhost:8000/v1/",
        _EVERYTHING,
        auth=Auth.NONE,
        credentials=(Credential(name="api_key", label="API key", required=False),),
        notes=(
            "Self-hosted, and the shape this project's own default endpoint "
            "already has. Serves one model per process, so `models` returns one row."
        ),
    ),
    Provider(
        id="azure_openai",
        display_name="Azure OpenAI",
        base_url="https://{resource}.openai.azure.com/openai/deployments/{deployment}/",
        auth=Auth.HEADER_KEY,
        openai_compatible=False,
        capabilities=frozenset(_EVERYTHING),
        credentials=(
            _KEY,
            Credential(name="resource", label="Resource name", secret=False),
            Credential(name="deployment", label="Deployment name", secret=False),
            Credential(
                name="api_version",
                label="API version",
                secret=False,
                required=True,
            ),
        ),
        models_path="",
        notes=(
            "OpenAI's request bodies at a per-resource host, addressed by "
            "deployment name rather than model name, with `api-version` required "
            "on every call. The body is compatible; the addressing is not, which "
            "is why this is not marked OpenAI-compatible -- a caller that "
            "believed the flag would send a `model` field to a URL that ignores it."
        ),
    ),
    Provider(
        id="bedrock",
        display_name="AWS Bedrock",
        base_url="https://bedrock-runtime.{region}.amazonaws.com/",
        auth=Auth.SIGNED,
        openai_compatible=False,
        capabilities=frozenset(_EVERYTHING),
        credentials=(
            Credential(name="access_key_id", label="Access key ID"),
            Credential(name="secret_access_key", label="Secret access key"),
            Credential(name="region", label="Region", secret=False),
        ),
        models_path="",
        notes=(
            "SigV4 signing rather than a token, three credentials rather than "
            "one, and no bearer-shaped probe can stand in for it. The connection "
            "test reports `unsupported` rather than guessing."
        ),
    ),
)

BY_ID: dict[str, Provider] = {provider.id: provider for provider in PROVIDERS}


class UnknownProvider(ValueError):
    """An id no catalogue entry answers to. Its own type so the route can
    answer 404 without matching on message text."""


def provider_for(provider_id: str) -> Provider:
    try:
        return BY_ID[provider_id]
    except KeyError as error:
        raise UnknownProvider(f"no provider named {provider_id!r}") from error


class ProbeOutcome(StrEnum):
    """What a connection test found. Four outcomes rather than a boolean,
    because "we could not tell" and "it said no" want different next steps
    from the person reading the result."""

    OK = "ok"
    UNAUTHORIZED = "unauthorized"
    UNREACHABLE = "unreachable"
    UNSUPPORTED = "unsupported"
    """The provider cannot be probed with what the catalogue knows -- Bedrock,
    whose credentials are a signing pair rather than a token."""

    ERROR = "error"


@dataclass(frozen=True)
class ProbeResult:
    """A structured answer, not a message.

    `models` is what the list call returned, capped by the adapter: OpenRouter
    answers with several hundred rows and none of them helps a person confirm
    that a key works. `detail` is for the human and is never the credential --
    see `infrastructure/settings/probe.py`, which redacts before constructing
    one of these.
    """

    provider_id: str
    outcome: ProbeOutcome
    detail: str = ""
    models: tuple[str, ...] = ()
    latency_ms: int | None = None

    @property
    def ok(self) -> bool:
        return self.outcome is ProbeOutcome.OK
