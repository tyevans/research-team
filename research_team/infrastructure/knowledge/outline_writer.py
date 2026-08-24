"""`OutlineTextPort` over a LangChain chat model.

The same grounding check the blurb runs (`grounding.ungrounded_runs`, and its
docstring for why that check is the only one available without spans), plus
the two things a structured artifact adds: a shape that can fail to parse,
and a count of sections that can be too few or too many.

**The fields are checked one at a time and never joined.** `SENTENCE_SPLIT`
splits on terminal punctuation and a heading carries none, so a heading
concatenated to the paragraph below it reads as one sentence: "Zefram
Cochrane" followed by "Warp drive theory..." yields the single run "Zefram
Cochrane Warp", which no anchor name contains, and every outline with a
capitalised heading is refused. Which is every outline.
`test_a_capitalised_heading_does_not_run_into_the_summary_beneath_it` is the
one test that separates this implementation from the joined one -- a reply
whose sections are flat prose passes under both.
"""

import re
from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from research_team.application.course_catalog import DraftOutline
from research_team.domain.learning_area import AreaMember
from research_team.infrastructure.knowledge.grounding import anchor_lines, ungrounded_runs

#: The floor, below which this is not a different artifact from the blurb.
#:
#: Two sections is a blurb with bullets, and the card already carries a blurb.
#: A reply under the floor is refused rather than padded here -- inventing the
#: third section is exactly the ungrounded copy the rest of this module exists
#: to keep out.
MIN_SECTIONS = 3

#: The ceiling, above which the tail is padding.
#:
#: Truncated rather than refused, and the direction is deliberate: the extra
#: sections are usually real and simply thin, so refusing throws away a whole
#: model call over a formatting excess. Truncation happens *before* grounding,
#: so a padded seventh section naming an entity the cluster does not hold
#: cannot refuse an outline whose visible six are sound -- text no reader will
#: see should not be able to veto text every reader will.
MAX_SECTIONS = 6

_PROMPT = """\
Write the outline of a course titled "{title}".

It covers these entities, which a knowledge graph clustered together --
work from what they suggest about the course, not from what you already
know about the subject in general:
{anchor_lines}

Answer in exactly this shape:

One sentence saying what a learner will be able to do at the end.

## First section heading
One or two sentences on what this section covers.

## Second section heading
One or two sentences on what this section covers.

Between {min_sections} and {max_sections} sections. No bullet lists, no
numbering, no heading above the opening sentence, and no text after the last
section.
"""

#: A section heading: a `##` line, at any indent a model might add.
_HEADING = re.compile(r"^\s*#{2,}\s*(.+?)\s*$")


def _parse(reply: str) -> DraftOutline | None:
    """The reply as a promise and its sections, or `None` if it is neither.

    A local model returns prose instead of the asked-for structure often
    enough that this is the ordinary path rather than the edge case, so every
    failure here is a `None` and not an exception.

    A heading with nothing under it fails the whole parse rather than
    becoming a section with an empty summary: an empty summary reaches a
    reader as a heading with a blank space below it, which reads as a
    rendering fault rather than as missing copy.
    """
    promise_lines: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    for line in reply.splitlines():
        heading = _HEADING.match(line)
        if heading:
            sections.append((heading.group(1), []))
        elif line.strip():
            (sections[-1][1] if sections else promise_lines).append(line.strip())
    promise = " ".join(promise_lines)
    if not promise or not sections:
        return None
    if any(not summary for _, summary in sections):
        return None
    return DraftOutline(
        promise=promise,
        sections=tuple((heading, " ".join(summary)) for heading, summary in sections),
    )


class ModelOutlineWriter:
    """`OutlineTextPort` over whichever chat model composition hands it.

    Takes the raw `BaseChatModel` for `ModelBlurbWriter`'s reason: this module
    is already in `infrastructure/`, so a second indirection would cost a file
    and buy `tests/test_architecture.py` nothing.
    """

    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

    @property
    def model_name(self) -> str:
        """Which model wrote an outline, for `CourseOutlineRow.model`.

        Read defensively and falling back rather than raising, because the
        value exists only for provenance: a local model's LangChain wrapper
        carries neither `model_name` nor `model` reliably, and a stored class
        name is worth more than an exception thrown while caching an outline
        that generated correctly.
        """
        return (
            getattr(self._model, "model_name", None)
            or getattr(self._model, "model", None)
            or type(self._model).__name__
        )

    async def write(self, title: str, anchors: Sequence[AreaMember]) -> DraftOutline | None:
        prompt = _PROMPT.format(
            title=title,
            anchor_lines=anchor_lines(anchors),
            min_sections=MIN_SECTIONS,
            max_sections=MAX_SECTIONS,
        )
        response = await self._model.ainvoke([HumanMessage(prompt)])
        draft = _parse(str(response.content).strip())
        if draft is None or len(draft.sections) < MIN_SECTIONS:
            return None
        draft = DraftOutline(draft.promise, draft.sections[:MAX_SECTIONS])
        # Field by field, never joined -- see the module docstring. The runs
        # are concatenated rather than short-circuited so a future caller
        # that wants to report *what* was ungrounded has the whole list; the
        # cost is checking a few more strings after the first failure, on
        # text that is already in memory.
        ungrounded = ungrounded_runs(draft.promise, anchors)
        for heading, summary in draft.sections:
            ungrounded += ungrounded_runs(heading, anchors)
            ungrounded += ungrounded_runs(summary, anchors)
        if ungrounded:
            return None
        return draft
