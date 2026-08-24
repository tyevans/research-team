"""`BlurbTextPort` over a LangChain chat model, and the checks it can run.

Used to also run a capitalisation-based grounding check shared with the
outline writer, dropped 2026-08-23 -- see `anchors.py`'s module docstring for
why. What is left is the part specific to a blurb's shape: the prompt, and
the refusals a blurb reply makes on that shape. An empty reply, one with no
separate title line, or a title identical to the cluster's top anchor, is
refused whole.

**The title comes from the same call as the blurb, on purpose.** A second
model call for a title alone would double the cost of a sweep that already
makes one call per candidate, and it would let the title and the blurb
disagree about what the course is about, with nothing able to notice --
`course_catalog.BlurbTextPort`'s docstring carries the same reasoning for
callers that only see the port. `write` returns `DraftBlurb(title, text)` or
`None`; there is no state in between.
"""

import re
from collections.abc import Sequence
from string import punctuation

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from research_team.application.course_catalog import DraftBlurb
from research_team.domain.learning_area import AreaMember
from research_team.infrastructure.knowledge.anchors import anchor_lines

# Sentence case in the prompt below used to be load-bearing for the (now
# removed) grounding check, which read Title Case as every word being an
# ungrounded capitalised run. That reason is gone, but the ask stays: the
# frontend's `titleCase` helper applies casing at display time, and a model
# free to vary between sentence and Title Case would make that helper produce
# inconsistent results across cards.
_PROMPT = """\
Write a title and catalog copy for a course, currently labelled "{title}"
after its most central entity -- that label is a placeholder, not a title
to keep.

It covers these entities, which a knowledge graph clustered together --
work from what they suggest about the course, not from what you already
know about the subject in general:
{anchor_lines}

Reply in exactly this shape, nothing before or after it:
A course title, two to eight words, ordinary sentence capitalisation (not
Title Case), no trailing punctuation, naming the course rather than
repeating a single entity from the list above.
Two sentences of marketing copy for a course catalog card. No heading, no
lists, no quotation marks around the whole thing.
"""

#: A title is one line, so a reply with no second line has no blurb to
#: extract and is refused rather than guessed at.
_TITLE_AND_TEXT = re.compile(r"\A(?P<title>[^\n]+)\n+(?P<text>.+)\Z", re.DOTALL)

#: The word-count band a title must fall in.
#:
#: Tried at 3-8 first, on the brief's literal wording. Measured against real
#: course names, that floor costs the ones already good: "First contact",
#: "Roman law" and "Warp propulsion" are all two words and all refused at 3.
#: The failure a 3-word floor was meant to guard against -- a model handed
#: one dominant entity echoing its name verbatim -- is already caught by the
#: anchor-name check below, which is the better instrument for it: it
#: compares against the actual anchor rather than against a word count that
#: also rejects unrelated two-word titles. Lowered to 2 for that reason.
_MIN_TITLE_WORDS = 2
_MAX_TITLE_WORDS = 8


def _normalised(title: str) -> str:
    """A title stripped of the punctuation and casing the comparison to the
    top anchor's name should not turn on -- "Warp Drive!" and "warp drive"
    both name the same refused title as bare "Warp drive"."""
    return title.strip().strip(punctuation).lower()


class ModelBlurbWriter:
    """`BlurbTextPort` over whichever chat model composition hands it.

    Takes the raw `BaseChatModel` directly rather than routing through a
    narrow adapter the way `entity_definitions.DefinitionTextPort` does --
    this module already sits in `infrastructure/`, so there is no layer above
    it that `tests/test_architecture.py` needs kept free of LangChain's
    vocabulary, and a second indirection here would cost a file without
    buying that test anything.
    """

    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

    @property
    def model_name(self) -> str:
        """Which model wrote a blurb, for `CourseBlurbRow.model`.

        A property of the writer rather than a second return value from
        `write`: returning the name beside the text would lose it on every
        refusal, and `write` refuses often by design.

        **The production model answers on the first term, measured.** On
        2026-08-23 `build_extraction_model()` was probed directly: it returns
        a `ChatOpenAI` carrying both `model_name` and `model`, each equal to
        `config.model_name()`. An earlier version of this docstring claimed
        the opposite -- that a local model's wrapper carries neither
        reliably -- which was asserted about this repository without ever
        being run against it.

        The fallback stays, for the implementer that does need it: a test
        stub, which carries whatever its author gave it. See
        `outline_writer.ModelOutlineWriter.model_name` for the full reasoning
        and for the note about `config.model_name()` being a second route to
        the same string; it is written once, there, rather than twice.
        """
        return (
            getattr(self._model, "model_name", None)
            or getattr(self._model, "model", None)
            or type(self._model).__name__
        )

    async def write(self, title: str, anchors: Sequence[AreaMember]) -> DraftBlurb | None:
        prompt = _PROMPT.format(title=title, anchor_lines=anchor_lines(anchors))
        response = await self._model.ainvoke([HumanMessage(prompt)])
        reply = str(response.content).strip()
        if not reply:
            # Refused rather than stored as an empty blurb -- see
            # `entity_definitions`'s identical reasoning for `define()`: a
            # reader sees "no blurb yet", not a blank card that looks broken.
            return None

        match = _TITLE_AND_TEXT.match(reply)
        if match is None:
            # No second line to be the blurb -- a reply with only a title,
            # or only a blurb and no title line, is refused whole rather
            # than stored with half of it missing.
            return None
        draft_title = match.group("title").strip()
        text = match.group("text").strip()
        if not draft_title or not text:
            return None

        word_count = len(draft_title.split())
        if not (_MIN_TITLE_WORDS <= word_count <= _MAX_TITLE_WORDS):
            return None

        # A model handed one dominant entity returns its name verbatim for
        # the title, and that answer passes `ungrounded_runs` by
        # construction -- it is literally an anchor name. Checked before the
        # grounding pass below, on the normalised form so "Warp Drive!" and
        # "warp drive" both catch the same refusal as bare "Warp drive".
        if anchors and _normalised(draft_title) == _normalised(anchors[0].name):
            return None

        return DraftBlurb(title=draft_title, text=text)
