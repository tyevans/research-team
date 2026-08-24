"""`ModelSvgArtist` against a stubbed model: the reply-parsing and the
sanitiser-refusal wiring, without a live endpoint. `test_svg_artist_live.py`
is the both-ends test with a real model."""

from langchain_core.messages import AIMessage

from research_team.domain.learning_area import AreaMember
from research_team.infrastructure.knowledge.svg_artist import ModelSvgArtist

_ANCHOR = AreaMember(entity_id="1", name="Warp Drive", entity_type="concept", centrality=1.0)


class _StubModel:
    def __init__(self, reply: str) -> None:
        self._reply = reply

    async def ainvoke(self, messages):
        return AIMessage(self._reply)


async def test_a_well_formed_reply_is_parsed_and_sanitised():
    reply = (
        "<svg viewBox='0 0 100 100'><circle cx='50' cy='50' r='40' fill='#123456'/></svg>\n"
        "Description: A glowing circle representing a warp core."
    )
    artist = ModelSvgArtist(_StubModel(reply))

    draft = await artist.generate("Warp propulsion", [_ANCHOR])

    assert draft is not None
    assert "<svg" in draft.svg
    assert draft.description == "A glowing circle representing a warp core."


async def test_a_reply_with_no_description_marker_is_refused():
    reply = "<svg viewBox='0 0 100 100'><circle cx='50' cy='50' r='40'/></svg>"
    artist = ModelSvgArtist(_StubModel(reply))

    draft = await artist.generate("Warp propulsion", [_ANCHOR])

    assert draft is None


async def test_an_empty_description_is_refused():
    reply = "<svg viewBox='0 0 100 100'><circle cx='50' cy='50' r='40'/></svg>\nDescription: "
    artist = ModelSvgArtist(_StubModel(reply))

    draft = await artist.generate("Warp propulsion", [_ANCHOR])

    assert draft is None


async def test_an_empty_reply_is_refused():
    artist = ModelSvgArtist(_StubModel(""))

    draft = await artist.generate("Warp propulsion", [_ANCHOR])

    assert draft is None


async def test_svg_the_sanitiser_refuses_refuses_the_whole_generation():
    # A <script> tag is not in the sanitiser's allowlist -- SvgSanitiser
    # refuses the whole document, and generate() must propagate that as a
    # whole-generation refusal rather than storing the unsanitised markup.
    reply = (
        "<svg viewBox='0 0 100 100'><script>alert(1)</script></svg>\nDescription: Malicious."
    )
    artist = ModelSvgArtist(_StubModel(reply))

    draft = await artist.generate("Warp propulsion", [_ANCHOR])

    assert draft is None


async def test_a_fenced_code_block_around_the_svg_is_stripped_before_sanitising():
    reply = (
        "```xml\n<svg viewBox='0 0 100 100'><rect width='10' height='10'/></svg>\n```\n"
        "Description: A small square."
    )
    artist = ModelSvgArtist(_StubModel(reply))

    draft = await artist.generate("Warp propulsion", [_ANCHOR])

    assert draft is not None
    assert "```" not in draft.svg
