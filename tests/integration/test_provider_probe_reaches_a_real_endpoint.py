"""`HttpProviderProbe` against a real OpenAI-compatible server.

Deselected by default; run with `-m integration`.

`ProviderProbePort` has exactly one production adapter, which CLAUDE.md's
"Events" section names as the shape that ships broken: a stub on one side and a
unit test on the other prove the two halves work and cannot prove they meet.
The co-mention channel produced nothing for a whole feature that way, and it
would be very easy to do here -- a probe whose url is assembled wrong (a
doubled or missing `/`, `models` against a base that already ends in `/v1/`)
answers 404 in exactly the way a wrong credential does, and a stubbed httpx
would never notice.

So this drives the real adapter at the real local endpoint and asserts on the
*model list it comes back with*, which is the thing no double can fake.

**It does not change the configured model, and does not ask for a completion.**
The whole point of a list call is that it costs nothing to run: no tokens, no
generation, and nothing about the server's state is touched. See
`infrastructure/settings/probe.py` for why the connection test is a list rather
than a round trip.
"""

import pytest

from research_team.domain.providers import ProbeOutcome, provider_for
from research_team.infrastructure.settings.probe import HttpProviderProbe

pytestmark = pytest.mark.integration

#: The endpoint this project's local runs actually use. Named here rather than
#: taken from `config.base_url()` on purpose: reading the configuration would
#: make this test pass against whatever the developer happened to have set,
#: including a stub, which is the one thing it exists to rule out.
LOCAL_ENDPOINT = "http://192.168.1.14:8080/v1/"


async def test_the_probe_lists_models_from_the_local_endpoint():
    """A real 200 with a real model name in it.

    Asserting `outcome is OK` alone would pass against any server that answers
    200 to anything, including one serving a static page -- so the assertion is
    that the body parsed into at least one model name. That is what proves the
    envelope reader and the url assembly agree with a real OpenAI-compatible
    server rather than with the shape this project imagined.
    """
    result = await HttpProviderProbe().probe(
        provider_for("vllm"), api_key=None, base_url=LOCAL_ENDPOINT
    )

    assert result.outcome is ProbeOutcome.OK, result.detail
    assert result.models, "the endpoint answered 200 but no model name was parsed out"
    assert result.latency_ms is not None


async def test_an_endpoint_that_is_not_there_is_unreachable_rather_than_an_error():
    """The two outcomes a person acts on differently: a wrong address and a
    refused credential. This is the first; port 1 has nothing listening.

    Not a stub, for this file's reason -- the mapping from an httpx exception
    to `UNREACHABLE` is adapter behaviour, and a double would be asserting that
    the double raises.
    """
    result = await HttpProviderProbe(timeout=2.0).probe(
        provider_for("vllm"), api_key=None, base_url="http://127.0.0.1:1/v1/"
    )

    assert result.outcome is ProbeOutcome.UNREACHABLE
    assert "127.0.0.1" not in result.detail


async def test_bedrock_is_refused_before_anything_is_sent():
    """`unsupported`, not a guess. SigV4 is not a bearer token, and a probe
    that reported `unauthorized` for it would send someone hunting a key that
    was never the problem. Reaches no network, so it runs here beside the two
    that do rather than pretending to be a unit test of the same code path."""
    result = await HttpProviderProbe().probe(provider_for("bedrock"), api_key="anything")

    assert result.outcome is ProbeOutcome.UNSUPPORTED
