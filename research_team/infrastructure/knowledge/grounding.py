"""The one check catalog copy can run without spans, shared by two writers.

Lifted out of `blurb_writer.py` unchanged when the outline writer needed the
same predicate. Two copies of it would drift, and this one is the copy that
survived three rounds of review -- the comments below are the record of which
false-accepts were traded for which false-refusals, and are the reason the
lists here are exactly the size they are.

**Weaker than `entity_definitions`, on purpose, and said so rather than
implied to be equivalent.** That module grounds every claim in a citation --
a span of a passage the model was shown -- because it has passages to cite
and an offset scheme (`Citation.source_id, start, end`) built to check them
against. Catalog copy has neither: it is prose about a cluster, not an answer
built from shown material, so there is nothing for a citation to point at and
no `_verified` to run.

What is left, without spans, is names. A model asked to write catalog copy
about "Warp drive" will happily bring in Captain Kirk from what it read on
the internet years ago, and that copy is indistinguishable at a glance from
copy built from this project's own cluster -- which is exactly why a reader
would trust it. Copy naming an entity the corpus did not put in this area
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
test, against exactly the anchors `blurb_writer`'s docstring uses as its
example (`Warp drive`, `Zefram Cochrane`). `SENTENCE_OPENERS` is the fix:
only the specific words a catalog prompt's own phrasing ("Follow...",
"Join...", "The...") is likely to produce are exempt, and only when they open
a sentence. Everything else -- including a name -- is checked like any other
capitalised run, wherever in the reply it appears.

**Two costs, not one, and the second was found by a second review pass.** A
legitimate sentence opener the list does not know is refused, not accepted --
that much *is* this check's usual failure direction. But `SENTENCE_OPENERS`
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

**Check each field of a structured reply separately, never a joined string.**
`SENTENCE_SPLIT` splits on terminal punctuation and a heading carries none,
so joining a heading to the paragraph beneath it makes `"Origins"` and
`"Cochrane's first flight."` read as one sentence, yielding the single run
`Origins Cochrane's` -- which no anchor name contains, refusing every outline
that has a capitalised heading. Which is every outline. `outline_writer`
calls this once per field and concatenates.
"""

import re
from collections.abc import Sequence

from research_team.application.course_authoring import PROMPT_ANCHORS
from research_team.domain.learning_area import AreaMember

__all__ = [
    "CAPITALISED_RUN",
    "FIRST_WORD",
    "PROMPT_ANCHORS",
    "SENTENCE_OPENERS",
    "SENTENCE_SPLIT",
    "anchor_lines",
    "ungrounded_runs",
]

#: How many of an area's anchors are named in the prompt.
#:
#: `course_authoring.PROMPT_ANCHORS` itself rather than a second constant
#: equal to it: an area with sixty members does not become a better course by
#: having all sixty listed in two sentences of copy, it becomes copy with no
#: focus. The anchors are ranked by centrality within the area, so the first
#: twelve are the twelve the graph says the area is actually about. This
#: module previously carried its own copy of the number with a comment saying
#: it matched -- a comment is not a check, and the import is.

#: A run of capitalised words: one leading capitalised word, then as many
#: capitalised words as follow it, so "United Federation of Planets" is one
#: run rather than three separated by a lowercase "of". `[A-Z]` requires the
#: ASCII case this corpus's entity names are already in; a title-cased name
#: in another script would not match this pattern, which is a narrower
#: problem than this task takes on.
CAPITALISED_RUN = re.compile(r"[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)*")

#: Splits the reply into sentences so a run's *first* word can be told apart
#: from a mid-sentence one. Deliberately simple -- a period, question mark or
#: exclamation point followed by space -- because the input here is a model's
#: own two sentences of prose, not arbitrary text with abbreviations to trip
#: it up.
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

#: The only words exempt from the check when they open a sentence.
#:
#: Not "whatever word happens to be capitalised at a sentence's start" --
#: that was the previous version of this check, and it let a bare invented
#: name straight through whenever it opened the reply's second sentence
#: ("Kirk later commanded the ship."), because nothing distinguished an
#: ordinary opener from a name that happened to occupy the same position.
#:
#: This list is the words a catalog prompt actually invites -- an article, a
#: demonstrative, or one of the imperative verbs catalog copy reaches for
#: ("Follow...", "Join..."). It is finite and known to be incomplete: an
#: opener outside it is refused, not accepted, which is the usual failure
#: direction here.
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
SENTENCE_OPENERS = frozenset(
    {
        "the",
        "a",
        "an",
        "this",
        "these",
        "from",
        "in",
        # `by` and `at` join the two prepositions above on the same test the
        # list already applies: a word is exempt when it is ordinary *and* not
        # a plausible proper noun. Both fail the second half only in ways
        # `from` and `in` already do, and neither is a ship, a rank or a name
        # the way the deliberately-excluded `discover`, `master`, `trace` and
        # `meet` are.
        #
        # Added on measurement, not taste: on 2026-08-23 the live model opened
        # an outline's promise with "By the end of this course, a learner will
        # be able to..." and the whole outline was refused on the single run
        # `By`. An outline's promise is one sentence stating an objective, and
        # "By the end..." / "At the end..." is the form that sentence takes in
        # every course description ever written -- so this was not an edge
        # case, it was the modal opening.
        "by",
        "at",
        "follow",
        "join",
        "learn",
        "explore",
    }
)

#: The sentence's first word, so it can be tested against `SENTENCE_OPENERS`
#: and stripped only when it is one of them.
FIRST_WORD = re.compile(r"[A-Z][\w'-]*")


def anchor_lines(anchors: Sequence[AreaMember]) -> str:
    return "\n".join(f"- {m.name} ({m.entity_type})" for m in anchors[:PROMPT_ANCHORS])


def ungrounded_runs(reply: str, anchors: Sequence[AreaMember]) -> list[str]:
    """Capitalised runs in `reply` that no anchor name contains.

    A sentence's first word is stripped before matching only when it is one
    of `SENTENCE_OPENERS` -- an ordinary opener a catalog prompt invites, not
    any word that happens to be capitalised there. A first word outside that
    list is left in place and checked like any other run, which is what
    catches a bare invented name opening a non-first sentence.

    `reply` is one field, not several joined: see the module docstring's last
    paragraph for the fusion a joined string produces at a heading boundary.
    """
    names_lower = [a.name.lower() for a in anchors]
    ungrounded = []
    for sentence in SENTENCE_SPLIT.split(reply.strip()):
        first = FIRST_WORD.match(sentence)
        # Stripping only the matched word (not merging it into the run below)
        # is what keeps "Join Captain Kirk..." from exempting "Captain Kirk"
        # along with "Join": the two are exempted and checked separately.
        rest = (
            sentence[first.end() :]
            if first and first.group().lower() in SENTENCE_OPENERS
            else sentence
        )
        for match in CAPITALISED_RUN.finditer(rest):
            run = match.group()
            if not any(candidate in name for candidate in _forms(run) for name in names_lower):
                ungrounded.append(run)
    return ungrounded


def _forms(run: str) -> tuple[str, ...]:
    """The lowercased forms of `run` that should each count as a match.

    Just the run itself, plus the run with a trailing possessive removed.
    `Cochrane's` is not a substring of `zefram cochrane`, so without this a
    model writing "Cochrane's first flight" -- about an entity the cluster
    holds, named correctly -- is refused as an invention.

    Measured 2026-08-23 against the live model: a genuinely good outline was
    refused twice over `Cochrane's` alone. The blurb writer never hit it
    because two sentences of catalog copy rarely inflect a name; an outline's
    section summaries do it constantly.

    Deliberately only the possessive, and only trailing. Every form added here
    widens what the check accepts, and the check's whole value is that it
    fails toward refusal -- see this module's own notes on which false-accepts
    were traded for which false-refusals.
    """
    lowered = run.lower()
    if lowered.endswith("'s") or lowered.endswith("\u2019s"):
        return (lowered, lowered[:-2])
    return (lowered,)
