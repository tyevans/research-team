"""The both-ends test CLAUDE.md's co-mention-channel entry calls for:
`ArtGeneratorPort` has exactly one production adapter (`ModelSvgArtist`), and
a port with one adapter and no test driving both ends over real data is two
things never checked against each other.

Simpler than `test_outline_over_a_real_ingest.py`'s full HTTP round trip on
purpose: `ArtGeneratorPort` has no cache/route to round-trip through the way
outlines do (no `_LazyOutlineCache`-equivalent transposition risk to catch),
so a direct call against `ModelSvgArtist.generate` with real anchors, a real
model and the real `SvgSanitiser` it already calls internally is what "both
ends over real data" requires here -- nothing stubbed.
"""

import httpx
import pytest
from langchain_openai import ChatOpenAI

from research_team.domain.learning_area import AreaMember
from research_team.infrastructure.knowledge.svg_artist import ModelSvgArtist

pytestmark = pytest.mark.asyncio

# Same live endpoint and model as test_outline_over_a_real_ingest.py -- see
# that file's comment for why this profile and not `qwen3.8-27b-mtp`.
_LIVE_BASE_URL = "http://192.168.1.14:8080/v1/"
_LIVE_MODEL = "qwen3.8-27b-64k-txt"


def _live_model_unreachable_reason() -> str | None:
    try:
        response = httpx.post(
            f"{_LIVE_BASE_URL}chat/completions",
            json={
                "model": _LIVE_MODEL,
                "messages": [{"role": "user", "content": "say hi"}],
                "temperature": 0,
            },
            timeout=60.0,
        )
    except httpx.HTTPError as error:
        return f"{_LIVE_BASE_URL} is not reachable: {error}"
    if response.status_code != 200:
        return (
            f"{_LIVE_MODEL} at {_LIVE_BASE_URL} answered "
            f"{response.status_code}: {response.text}"
        )
    return None


_ANCHORS = [
    AreaMember(entity_id="1", name="Zefram Cochrane", entity_type="person", centrality=1.0),
    AreaMember(entity_id="2", name="The Phoenix", entity_type="artifact", centrality=0.9),
    AreaMember(entity_id="3", name="Warp Drive Theory", entity_type="concept", centrality=0.8),
    AreaMember(entity_id="4", name="First Contact Day", entity_type="event", centrality=0.7),
    AreaMember(entity_id="5", name="Vulcan", entity_type="location", centrality=0.6),
]


async def test_a_real_model_produces_a_sanitised_svg_and_description():
    """Skips loudly, not silently, when no live model answers -- a silently
    skipped both-ends test is the same nothing the port already had."""
    unreachable = _live_model_unreachable_reason()
    if unreachable is not None:
        pytest.skip(f"no live model to drive the real artist against: {unreachable}")

    model = ChatOpenAI(
        model=_LIVE_MODEL,
        base_url=_LIVE_BASE_URL,
        api_key="not-needed",
        temperature=0,
    )
    artist = ModelSvgArtist(model)

    draft = await artist.generate("Warp propulsion", _ANCHORS)

    # A live model can genuinely refuse a well-formed request (see
    # ModelBlurbWriter's own live tests for the same tolerance) -- but a
    # refusal must still be loud, not indistinguishable from a passing
    # assertion nobody looked at.
    assert draft is not None, "the live model refused every attempt at this prompt"
    assert "<svg" in draft.svg
    assert draft.description.strip() != ""
