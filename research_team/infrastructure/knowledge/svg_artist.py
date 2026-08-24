"""`ArtGeneratorPort` over a LangChain chat model.

Follows `blurb_writer.ModelBlurbWriter`'s shape: the raw `BaseChatModel`
taken directly, one call, a whole-reply refusal on anything the parse or the
sanitiser is not sure of. Two things a text writer does not have to do: split
one reply into two parts (the SVG and its description), and run the result
through `SvgSanitiser` before it is ever allowed into a `DraftArt` -- see
`generate`'s docstring for why that call is not optional.
"""

import re
from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from research_team.application.course_catalog import DraftArt
from research_team.domain.learning_area import AreaMember
from research_team.infrastructure.knowledge.anchors import anchor_lines
from research_team.infrastructure.knowledge.svg_sanitiser import SvgSanitiser

_PROMPT = """\
Draw a flat vector illustration for a course currently labelled "{title}"
after its most central entity -- that label is a placeholder, not a title
to keep.

It covers these entities, which a knowledge graph clustered together --
draw from what they suggest about the course, not from what you already
know about the subject in general:
{anchor_lines}

Reply in exactly this shape, nothing before or after it:
One `<svg>` element, with an explicit `viewBox` attribute, no `width` or
`height` attribute, no embedded text or `<text>` elements, and no
references to anything outside the document (no `<image>`, no `href`, no
external fonts).
Then a line starting exactly with "Description:" followed by one sentence
describing what the illustration shows.
"""

# The description line is the unambiguous split point between the two parts
# of the reply -- `re.DOTALL` so the SVG half, which is itself multi-line, is
# captured whole. Anchored to the *last* such line (greedy `.*` before the
# marker) rather than the first, in case a description sentence itself
# happens to contain the literal word "Description:" -- unlikely, but the
# SVG markup is the part correctness depends on, so it gets the benefit of
# the doubt.
_SVG_AND_DESCRIPTION = re.compile(
    r"\A(?P<svg>.*)\n+Description:\s*(?P<description>.+)\Z", re.DOTALL
)


class ModelSvgArtist:
    """`ArtGeneratorPort` over whichever chat model composition hands it.

    Takes the raw `BaseChatModel` directly for `ModelBlurbWriter`'s exact
    reason -- this module already sits in `infrastructure/`, so there is no
    layer above it `tests/test_architecture.py` needs kept free of
    LangChain's vocabulary.
    """

    def __init__(self, model: BaseChatModel) -> None:
        self._model = model
        self._sanitiser = SvgSanitiser()

    async def generate(self, title: str, anchors: Sequence[AreaMember]) -> DraftArt | None:
        prompt = _PROMPT.format(title=title, anchor_lines=anchor_lines(anchors))
        response = await self._model.ainvoke([HumanMessage(prompt)])
        reply = str(response.content).strip()
        if not reply:
            return None

        match = _SVG_AND_DESCRIPTION.search(reply)
        if match is None:
            # No "Description:" marker at all -- per `ArtGeneratorPort`'s
            # docstring, a reply with nothing for the search key to read is
            # refused whole, not stored with an empty description.
            return None
        svg_text = match.group("svg").strip()
        description = match.group("description").strip()
        if not svg_text or not description:
            return None

        # A model's reply commonly wraps the SVG in a fenced code block --
        # strip a leading/trailing ``` fence if present, since the sanitiser
        # parses XML and a fence around it is not valid XML.
        svg_text = re.sub(r"\A```(?:xml|svg|html)?\n?", "", svg_text)
        svg_text = re.sub(r"\n?```\Z", "", svg_text).strip()

        # This is the one place a generated SVG is validated before it is
        # allowed to exist as a `DraftArt` -- `ArtStore.put`'s docstring
        # explicitly does not re-check on write because this call already
        # did. Never return unsanitised markup: a refusal here is a whole
        # generation refusal, not a partial success.
        sanitised = self._sanitiser.sanitise(svg_text)
        if sanitised is None:
            return None

        return DraftArt(svg=sanitised, description=description)
