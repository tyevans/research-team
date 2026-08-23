"""`BlurbTextPort` over a LangChain chat model, and the one check it can run.

**Weaker than `entity_definitions`, on purpose, and said so rather than
implied to be equivalent.** That module grounds every claim in a citation --
a span of a passage the model was shown -- because it has passages to cite
and an offset scheme (`Citation.source_id, start, end`) built to check them
against. A blurb has neither: it is two sentences of catalog copy about a
cluster, not an answer built from shown material, so there is nothing for a
citation to point at and no `_verified` to run.

What is left, without spans, is names. A model asked to write catalog copy
about "Warp drive" will happily bring in Captain Kirk from what it read on
the internet years ago, and that copy is indistinguishable at a glance from
copy built from this project's own cluster -- which is exactly why a reader
would trust it. A blurb naming an entity the corpus did not put in this area
promises a course the corpus cannot teach. So the check here is: every
capitalised run in the reply must appear, case-insensitively, as a substring
of some anchor's name. Fail one run and the whole reply is refused.

**Deliberately conservative in the refusing direction.** A refused blurb
costs a card its copy -- the caller falls back to no blurb, or tries again --
and only that direction is recoverable by a second click. An accepted
ungrounded blurb costs a reader their trust, silently, and there is no click
that gets it back. Given a choice between refusing real copy sometimes and
admitting invented copy sometimes, this exists to make the first mistake
rather than the second.

**And it does make the first mistake.** The check is substring-against-name,
not synonym-aware: "Zefram Cochrane" shortened to "Cochrane" passes (a real
substring), but a legitimate paraphrase like "the Inventor" for the same
person does not, because "Inventor" appears in no anchor's name.
`tests/infrastructure/test_blurb_writer.py::test_a_legitimate_shortening_the_check_still_refuses`
pins exactly this case rather than leaving it to be rediscovered as a bug
report. Making the check cleverer -- stemming, a synonym list, an entity
linker -- was considered and rejected for this task: every one of those tools
can itself hallucinate a match, which is the failure this check exists to
rule out, not reintroduce one layer down.
"""

import re
from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from research_team.domain.learning_area import AreaMember

#: How many of an area's anchors are named in the prompt.
#:
#: Matches `course_authoring.PROMPT_ANCHORS`: an area with sixty members does
#: not become a better course by having all sixty listed in two sentences of
#: copy, it becomes copy with no focus. The anchors are ranked by centrality
#: within the area, so the first twelve are the twelve the graph says the
#: area is actually about.
PROMPT_ANCHORS = 12

_PROMPT = """\
Write catalog copy for a course titled "{title}".

It covers these entities, which a knowledge graph clustered together --
work from what they suggest about the course, not from what you already
know about the subject in general:
{anchor_lines}

Two sentences of marketing copy for a course catalog card. No heading, no
lists, no quotation marks around the whole thing.
"""

#: A run of capitalised words: one leading capitalised word, then as many
#: capitalised words as follow it, so "United Federation of Planets" is one
#: run rather than three separated by a lowercase "of". `[A-Z]` requires the
#: ASCII case this corpus's entity names are already in; a title-cased name
#: in another script would not match this pattern, which is a narrower
#: problem than this task takes on.
_CAPITALISED_RUN = re.compile(r"[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)*")

#: Splits the reply into sentences so a run's *first* word can be told apart
#: from a mid-sentence one. Deliberately simple -- a period, question mark or
#: exclamation point followed by space -- because the input here is a model's
#: own two sentences of prose, not arbitrary text with abbreviations to trip
#: it up.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _anchor_lines(anchors: Sequence[AreaMember]) -> str:
    return "\n".join(f"- {m.name} ({m.entity_type})" for m in anchors[:PROMPT_ANCHORS])


def _ungrounded_runs(reply: str, anchors: Sequence[AreaMember]) -> list[str]:
    """Capitalised runs in `reply` that no anchor name contains.

    Sentence-initial words are exempt at the start of *each* sentence, not
    just the reply's first word -- otherwise every ordinary sentence after
    the first would flag its own opening word as an invented entity, which
    would refuse nearly every two-sentence reply regardless of what it said.
    """
    names_lower = [a.name.lower() for a in anchors]
    ungrounded = []
    for sentence in _SENTENCE_SPLIT.split(reply.strip()):
        # Drop the sentence's own first word before matching runs, rather
        # than matching over the whole sentence and discarding the first
        # *run*: a sentence-initial word immediately followed by a real
        # proper noun ("Join Captain Kirk...") is one contiguous capitalised
        # run under `_CAPITALISED_RUN`, and discarding that whole run would
        # exempt "Captain Kirk" along with "Join".
        _, _, rest = sentence.partition(" ")
        for match in _CAPITALISED_RUN.finditer(rest):
            run = match.group()
            if not any(run.lower() in name for name in names_lower):
                ungrounded.append(run)
    return ungrounded


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

    async def write(self, title: str, anchors: Sequence[AreaMember]) -> str | None:
        prompt = _PROMPT.format(title=title, anchor_lines=_anchor_lines(anchors))
        response = await self._model.ainvoke([HumanMessage(prompt)])
        reply = str(response.content).strip()
        if not reply:
            # Refused rather than stored as an empty blurb -- see
            # `entity_definitions`'s identical reasoning for `define()`: a
            # reader sees "no blurb yet", not a blank card that looks broken.
            return None
        if _ungrounded_runs(reply, anchors):
            return None
        return reply
