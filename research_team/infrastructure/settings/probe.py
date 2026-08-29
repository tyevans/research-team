"""Connection tests, behind `ProviderProbePort`. The one thing here that
reaches the network.

**One code path for eleven of the fifteen providers**, because eleven speak the
OpenAI wire protocol: `GET {base_url}models` with `Authorization: Bearer`. The
catalogue in `domain/providers.py` carries the differences as data -- which
header, which path -- and this module reads them rather than branching on
provider id. Two providers need a genuinely different request (Anthropic's
header pair, Gemini's query parameter) and are handled by the same function
with different headers; two more (Azure, Bedrock) cannot be probed from a base
url and a key alone and report `unsupported` rather than guessing.

**A list call rather than a completion, wherever there is one.** A round trip
through a chat model costs tokens and takes seconds, and the question being
asked is "does this credential reach this endpoint" -- which a 200 from
`models` answers. Where a provider has no list (`models_path` empty), the
result is `unsupported`; a fabricated completion is not a better answer than an
honest "cannot tell".

The port has exactly one adapter, so per CLAUDE.md the test that matters drives
it against a real endpoint --
`tests/integration/test_provider_probe_reaches_a_real_endpoint.py`, marked
`integration`, against the local OpenAI-compatible server. A stub on one side
and a unit test on the other would prove the two halves work and not that they
meet.
"""

import logging
import time

import httpx

from research_team.domain.providers import Auth, ProbeOutcome, ProbeResult, Provider

logger = logging.getLogger(__name__)

#: How many model names travel back. OpenRouter answers with several hundred
#: and none past the first few helps anyone confirm a key works; the cap is
#: about the response body a browser has to render, not about the request.
MAX_MODELS = 25

#: Short on purpose. This runs on a request path with a person watching, and an
#: endpoint that has not answered in ten seconds has told us what we needed to
#: know.
TIMEOUT_SECONDS = 10.0

#: Anthropic requires this header on every call and rejects the request without
#: it. Pinned rather than floating: a version string that drifts with the
#: calendar would make a probe start failing on a day nobody deployed anything.
ANTHROPIC_VERSION = "2023-06-01"


def _request(provider: Provider, api_key: str | None, base_url: str) -> tuple[str, dict, dict]:
    """The url, headers and query for this provider's list call.

    Built from the catalogue's `auth` rather than from the provider id, so
    adding a sixteenth OpenAI-compatible endpoint is a row of data and no code
    at all.
    """
    url = base_url.rstrip("/") + "/" + provider.models_path.lstrip("/")
    headers: dict[str, str] = {}
    params: dict[str, str] = {}
    if provider.auth is Auth.BEARER and api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    elif provider.auth is Auth.HEADER_KEY and api_key:
        # Anthropic's name. Azure's is also `api-key`, and Azure never reaches
        # here -- it has no `models_path` and is refused before this call.
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = ANTHROPIC_VERSION
    elif provider.auth is Auth.QUERY_KEY and api_key:
        params["key"] = api_key
    return url, headers, params


def _names(payload: object) -> tuple[str, ...]:
    """Model names out of whichever envelope this provider used.

    Three shapes in the wild: OpenAI's `{"data": [{"id": ...}]}`, Anthropic's
    same-shaped `data` with `id`, and Gemini's `{"models": [{"name": ...}]}`.
    Anything else yields no names and is not an error -- the outcome is decided
    by the status code, and a body we cannot read still proves the credential
    reached something that answered 200.
    """
    if not isinstance(payload, dict):
        return ()
    rows = payload.get("data") or payload.get("models") or []
    if not isinstance(rows, list):
        return ()
    names = []
    for row in rows:
        if isinstance(row, dict):
            name = row.get("id") or row.get("name")
            if isinstance(name, str):
                names.append(name)
    return tuple(names[:MAX_MODELS])


class HttpProviderProbe:
    """`ProviderProbePort` over httpx."""

    def __init__(self, timeout: float = TIMEOUT_SECONDS) -> None:
        self._timeout = timeout

    async def probe(
        self, provider: Provider, api_key: str | None, base_url: str | None = None
    ) -> ProbeResult:
        if provider.auth is Auth.SIGNED:
            return ProbeResult(
                provider_id=provider.id,
                outcome=ProbeOutcome.UNSUPPORTED,
                detail=(
                    "Bedrock signs requests with SigV4 rather than carrying a token, "
                    "so a key alone cannot be tested from here."
                ),
            )
        if not provider.models_path:
            return ProbeResult(
                provider_id=provider.id,
                outcome=ProbeOutcome.UNSUPPORTED,
                detail=(
                    f"{provider.display_name} is addressed per deployment and offers "
                    "no model list to probe."
                ),
            )
        target = (base_url or provider.base_url).strip()
        if "{" in target:
            return ProbeResult(
                provider_id=provider.id,
                outcome=ProbeOutcome.UNSUPPORTED,
                detail="The base URL still carries placeholders; fill them in first.",
            )

        url, headers, params = _request(provider, api_key, target)
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, headers=headers, params=params)
        except httpx.HTTPError as error:
            # The exception text can carry the url, which for Gemini carries
            # the key as a query parameter. `type(error).__name__` is what a
            # person needs (timeout vs DNS vs TLS) and is the part that cannot
            # contain a credential.
            logger.info(
                "provider probe failed to reach %s: %s", provider.id, type(error).__name__
            )
            return ProbeResult(
                provider_id=provider.id,
                outcome=ProbeOutcome.UNREACHABLE,
                detail=f"{type(error).__name__} reaching {provider.display_name}",
            )

        elapsed_ms = int((time.monotonic() - started) * 1000)
        if response.status_code in (401, 403):
            return ProbeResult(
                provider_id=provider.id,
                outcome=ProbeOutcome.UNAUTHORIZED,
                detail=(
                    f"{provider.display_name} refused the credential ({response.status_code})"
                ),
                latency_ms=elapsed_ms,
            )
        if response.status_code >= 400:
            return ProbeResult(
                provider_id=provider.id,
                outcome=ProbeOutcome.ERROR,
                detail=f"{provider.display_name} answered {response.status_code}",
                latency_ms=elapsed_ms,
            )
        try:
            payload = response.json()
        except ValueError:
            payload = None
        return ProbeResult(
            provider_id=provider.id,
            outcome=ProbeOutcome.OK,
            detail=f"{provider.display_name} answered {response.status_code}",
            models=_names(payload),
            latency_ms=elapsed_ms,
        )
