"""`OutlineTextPort` over a LangChain chat model.

Used to also run a capitalisation-based grounding check shared with the
blurb writer, dropped 2026-08-23 -- see `anchors.py`'s module docstring for
why. What is left is the shape checks a structured artifact needs regardless:
a reply that can fail to parse, and a count of sections that can be too few
or too many.
"""

import re
from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from research_team.application.course_catalog import DraftOutline
from research_team.domain.learning_area import AreaMember
from research_team.infrastructure.knowledge.anchors import anchor_lines

#: The floor, below which this is not a different artifact from the blurb.
#:
#: Two sections is a blurb with bullets, and the card already carries a blurb.
#: A reply under the floor is refused rather than padded here -- inventing a
#: third section is not something this module has any business doing.
MIN_SECTIONS = 3

#: The ceiling, above which the tail is padding.
#:
#: Truncated rather than refused, and the direction is deliberate: the extra
#: sections are usually real and simply thin, so refusing throws away a whole
#: model call over a formatting excess.
#:
#: **Before parsing's own veto, which is where this principle was first
#: written down and not held.** `_parse` refuses an outline for a heading with
#: nothing under it, and it did so over *every* heading, including ones past
#: this ceiling -- so six sound sections followed by one stray `##` line were
#: destroyed by the one section no reader would have seen. That is exactly the
#: trailing padding this ceiling exists to absorb: a model that runs out of
#: budget mid-reply stops after a heading, which is the commonest way for a
#: reply to end badly. Found in review on 2026-08-23, by measurement, against
#: a module whose own comment argued the opposite rule two paragraphs up.
#:
#: `_parse` now cuts to this ceiling before it validates, so there is one rule
#: rather than two: past the ceiling nothing about a section can refuse
#: anything, whether it is malformed or merely padding.
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

Write headings in sentence case -- capitalise only the first word and any
proper noun, like "The first warp flight", not "The First Warp Flight".
"""
# Sentence case above used to be load-bearing for the (now removed) grounding
# check, which read Title Case as every word being an ungrounded capitalised
# run. That reason is gone, but the ask stays: the frontend's `titleCase`
# helper applies casing at display time, and a model free to vary between
# sentence and Title Case would make that helper produce inconsistent
# headings across cards.

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
    rendering fault rather than as missing copy. A malformed section is
    refused, in other words, where a merely thin one is kept -- but only
    *within* the ceiling. The cut to `MAX_SECTIONS` happens here, before that
    veto, so nothing past the ceiling can refuse anything; see
    `MAX_SECTIONS`'s own comment for why holding the veto globally was the
    ceiling's argument run backwards.

    Summaries join with a single space, so a section a model wrote as two
    paragraphs stores as one. A paragraph break inside a section summary is
    not a distinction a catalog card renders, and preserving it would invent
    a formatting contract nothing downstream reads.
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
    sections = sections[:MAX_SECTIONS]
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

        **The production model answers on the first term, measured.** On
        2026-08-23 `build_extraction_model()` was probed directly: it returns
        a `ChatOpenAI` carrying both `model_name` and `model`, each equal to
        `config.model_name()` (`'qwen3.6-27b-mtp'` that day). So the fallback
        chain is not there because this repo's wrapper is unreliable -- an
        earlier version of this docstring said that, and it was untrue.

        It is there for the other implementer: a test stub. `_extraction_model`
        returns either the real model or an injected fake, and a fake carries
        whatever its author gave it, which is usually neither attribute. A
        class name is the honest answer for a stub, and it costs nothing that
        the same expression would also absorb a future wrapper that happens to
        expose neither. What it costs is loudness: this property cannot raise,
        so a wrong-but-plausible provenance string would go unnoticed. That is
        accepted because the value exists only for provenance -- an exception
        thrown while caching an outline that generated correctly is worse.

        Note for whoever wires `put`: `config.model_name()` already reaches
        this same string and is read at `composition.py:2130`, `:2567` and
        `:2589`. This property is a third route to it. The three agree today
        (measured, same probe); pick one deliberately rather than discovering
        both later.
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
        # Already cut to `MAX_SECTIONS` by `_parse`, which has to know the
        # ceiling anyway to keep its own veto inside it. Truncating in one
        # place is what stops the two rules disagreeing again.
        draft = _parse(str(response.content).strip())
        if draft is None or len(draft.sections) < MIN_SECTIONS:
            return None
        return draft
