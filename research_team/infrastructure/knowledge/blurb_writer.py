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

**Sentence-initial exemption is a closed, maintained list, not "whatever word
opens a sentence".** An earlier version of this check exempted every
sentence's first word unconditionally, on the reasoning that capitalisation
there is a rule of English grammar rather than a claim about an entity. That
reasoning is only true of *some* first words. A model is free to open its
second sentence with a bare proper noun ("Kirk later commanded the ship.")
and a blanket exemption let it straight through -- caught by review, not by a
test, against exactly the anchors this module's own docstring uses as its
example (`Warp drive`, `Zefram Cochrane`). `_SENTENCE_OPENERS` is the fix:
only the specific words the prompt's own phrasing ("Follow...", "Meet...",
"The...") is likely to produce are exempt, and only when they open a
sentence. Everything else -- including a name -- is checked like any other
capitalised run, wherever in the reply it appears.

**Two costs, not one, and the second was found by a second review pass.** A
legitimate sentence opener the list does not know is refused, not accepted --
that much *is* the module's usual failure direction. But `_SENTENCE_OPENERS`
strips only the matched opener word and leaves the rest of the sentence to be
checked, so a sentence whose *entire* ungrounded content is one word
identical to a list entry is invisible to this check: "Explore chronicled the
frontier. It uses the Warp drive." strips "Explore" as an opener, finds
nothing else capitalised in that sentence to flag, and is accepted --
even if "Explore" were standing in for an invented ship name. This is a
genuine false *accept*, not the refusal direction the rest of this module
claims for itself, and it is not eliminated by this list: eliminating it
would mean telling "Explore chronicled the frontier" (a name, subject of a
sentence) apart from "Explore the frontier" (an imperative opener, no
subject at all) -- a parse this check deliberately does not attempt, because
the alternative to a short, wrong-in-one-direction list is a longer, wrong-
in-two-directions parser.
`tests/infrastructure/test_blurb_writer.py::test_a_single_word_opener_identical_to_an_ungrounded_name_is_not_caught`
pins this residual rather than leaving it to be rediscovered. The list stays
short precisely because that residual exists: padding it toward "anything
that looks like an ordinary word" only grows the set of words this blind
spot applies to.
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

#: The only words exempt from the check when they open a sentence.
#:
#: Not "whatever word happens to be capitalised at a sentence's start" --
#: that was the previous version of this check, and it let a bare invented
#: name straight through whenever it opened the reply's second sentence
#: ("Kirk later commanded the ship."), because nothing distinguished an
#: ordinary opener from a name that happened to occupy the same position.
#:
#: This list is the words the prompt in `_PROMPT` actually invites -- an
#: article, a demonstrative, or one of the imperative verbs catalog copy
#: reaches for ("Follow...", "Join..."). It is finite and known to be
#: incomplete: an opener outside it is refused, not accepted, which is the
#: usual failure direction in this module.
#:
#: **Deliberately excludes `discover`, `master`, `trace` and `meet`.** Those
#: four read as ordinary imperatives in "Discover the frontier," but they are
#: also plausible titles or names on their own -- "Discover" as a ship,
#: "Master" as a rank, "Meet" as a person's name is a stretch but "Trace" and
#: "Discover" are not. `follow`, `join`, `learn` and `explore` cover the same
#: rhetorical need (a two-sentence blurb inviting the reader in) without that
#: overlap, and dropping the riskier four fails toward refusal -- a legitimate
#: blurb reaching for "Discover..." as its opener is refused here, which is
#: accepted as the cost of not reopening the false-accept below on words most
#: likely to double as invented proper nouns.
#:
#: Growing this list toward "any word that looks ordinary" would undo the
#: fix: an invented proper noun looks exactly as ordinary as a real opener
#: until the anchors are already known. And even at this size the list is
#: not free of the false-accept it was narrowed to reduce -- see the module
#: docstring's second cost, and
#: `test_a_single_word_opener_identical_to_an_ungrounded_name_is_not_caught`.
_SENTENCE_OPENERS = frozenset(
    {
        "the",
        "a",
        "an",
        "this",
        "these",
        "from",
        "in",
        "follow",
        "join",
        "learn",
        "explore",
    }
)

#: The sentence's first word, so it can be tested against `_SENTENCE_OPENERS`
#: and stripped only when it is one of them.
_FIRST_WORD = re.compile(r"[A-Z][\w'-]*")


def _anchor_lines(anchors: Sequence[AreaMember]) -> str:
    return "\n".join(f"- {m.name} ({m.entity_type})" for m in anchors[:PROMPT_ANCHORS])


def _ungrounded_runs(reply: str, anchors: Sequence[AreaMember]) -> list[str]:
    """Capitalised runs in `reply` that no anchor name contains.

    A sentence's first word is stripped before matching only when it is one
    of `_SENTENCE_OPENERS` -- an ordinary opener the prompt invites, not any
    word that happens to be capitalised there. A first word outside that
    list is left in place and checked like any other run, which is what
    catches a bare invented name opening a non-first sentence.
    """
    names_lower = [a.name.lower() for a in anchors]
    ungrounded = []
    for sentence in _SENTENCE_SPLIT.split(reply.strip()):
        first = _FIRST_WORD.match(sentence)
        # Stripping only the matched word (not merging it into the run below)
        # is what keeps "Join Captain Kirk..." from exempting "Captain Kirk"
        # along with "Join": the two are exempted and checked separately.
        rest = (
            sentence[first.end() :]
            if first and first.group().lower() in _SENTENCE_OPENERS
            else sentence
        )
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
