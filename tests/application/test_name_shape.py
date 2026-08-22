"""What the clause-shape proxy must and must not flag.

The measure is a heuristic, so the tests that matter are the ones that pin its
*boundaries*: a set of signals wide enough to catch every sentence in a real
graph is trivially achievable by flagging everything, and the whole value of
the thing is that it does not. Every real name below was taken from the
326-entity graph measured on 2026-08-22 (`docs/design/curriculum-input-quality.md`),
not invented, because an invented sentence is one written by the same person
who wrote the signal list -- the failure `CLAUDE.md` records under
"a formula correct on every case a test naturally reaches".
"""

import pytest

from research_team.application.name_shape import (
    DETERMINER_MIN_WORDS,
    MAX_NAME_WORDS,
    _report,
    clause_shaped,
    signals,
)

#: Real entity names from the measured graph that are propositions.
PROPOSITIONS = (
    "The word chloroplast is derived from the Greek words chloros (green)",
    "Chloroplasts are only found in plants, algae, and some species",
    "Observation that chloroplasts resemble cyanobacteria",
    "Conspirators arrested in the city",
    "A typical plant cell contains about 10 to 100 chloroplasts",
)

#: Real entity names from the same graph that name things. Four of the five
#: are the ones a careless signal set gets wrong: two carry an internal
#: determiner, one is a four-token personal name, one is a bare noun with a
#: trailing single letter that looks like an article.
THINGS = (
    "Andreas Franz Wilhelm Schimper",
    "Cato the Younger",
    "chlorophyll a",
    "Catilinarian conspiracy",
    "glaucophyte chloroplast lineage",
)


@pytest.mark.parametrize("name", PROPOSITIONS)
def test_a_proposition_is_clause_shaped(name):
    """Every sentence-shaped name in the measured graph trips a signal.

    Proved red on 2026-08-22 by emptying `SUBORDINATORS`: exactly one of the
    five goes green-to-red, `Observation that chloroplasts resemble
    cyanobacteria`, which is the only name here that no other signal reaches.
    That one is the whole reason the subordinator list exists.

    Emptying `FINITE_VERBS` instead fails **none of these five**, because every
    proposition in this graph long enough to contain an auxiliary is also long
    enough to trip `long`. That is a real fact about the measure and it is
    recorded rather than hidden: on this corpus the verb signal is redundant.
    `test_a_short_proposition_needs_the_verb_signal` is where it earns its
    place, on a constructed name, and is labelled as constructed.
    """
    assert clause_shaped(name)


@pytest.mark.parametrize("name", THINGS)
def test_a_thing_is_not_clause_shaped(name):
    """Names of things survive the measure.

    This is the half that is easy to lose. Proved red on 2026-08-22 by setting
    `DETERMINER_MIN_WORDS = 2`, the obvious simplification: `Cato the Younger`
    and `chlorophyll a` both fail, which is the epithet-and-suffix pattern the
    threshold exists for. Setting `MAX_NAME_WORDS = 3` instead fails
    `Andreas Franz Wilhelm Schimper` and `glaucophyte chloroplast lineage`.
    """
    assert not clause_shaped(name)


def test_a_leading_article_is_not_by_itself_a_signal():
    """A name that opens with `The` is still the name of a thing.

    The determiner signal reads the tail rather than the whole name, and this
    is the distinction it is drawn for. Both names are **constructed**: no
    entity in the measured graph opens with an article and is five tokens or
    longer, so nothing real separates the two loops. The first is the schema's
    own `organization` example with an article on the front.

    Proved red on 2026-08-22 by changing `tail` to `tokens` in the determiner
    check -- the simpler loop, and the one someone will write when tidying
    this. With `The Hague` alone (the first draft of this test) that break
    passed, because two tokens is below `DETERMINER_MIN_WORDS` and the
    determiner branch never ran.
    """
    assert not clause_shaped("The Nova Scotia Duck Tolling Retriever Club")
    assert not clause_shaped("The Hague")
    assert clause_shaped("Chloroplasts are found in the leaves of plants")


def test_a_short_proposition_needs_the_verb_signal():
    """A claim too short to trip `long` and carrying no article or `that`.

    **Constructed, not measured** -- see
    `test_a_proposition_is_clause_shaped` for why that matters: this graph
    contains no name the verb signal alone catches, so this is the signal's
    only defence and it is a hypothesis about corpora other than this one.
    Proved red on 2026-08-22 by emptying `FINITE_VERBS`.
    """
    assert signals("Chloroplasts are green") == frozenset({"verb"})


def test_length_alone_condemns_a_name():
    """Past `MAX_NAME_WORDS` nothing else has to fire.

    A name with no auxiliary, no subordinator and no internal determiner can
    still be prose. Fails if the length signal is dropped in favour of
    requiring a grammatical cue.
    """
    long_name = " ".join(f"w{i}" for i in range(MAX_NAME_WORDS + 1))
    assert signals(long_name) == frozenset({"long"})


def test_the_signals_are_reported_separately():
    """A rise in the figure has to be attributable to a signal.

    The single boolean is what the projection uses; the breakdown is what a
    person reads across two ingests. Fails against an implementation that
    returns only the first signal found, which is the obvious short-circuit.
    """
    assert signals("The word chloroplast is derived from the Greek words") >= {
        "verb",
        "determiner",
    }


def test_the_report_counts_and_names_what_it_flagged():
    """The measurement output is a figure plus the evidence for it.

    A percentage with no list behind it cannot be checked by the person it is
    shown to, which is how "the propositions stopped" gets believed without
    being true.
    """
    report = _report(["Cato the Younger", "Conspirators arrested in the city"])
    assert "2 entity names, 1 clause-shaped (50.0%)" in report
    assert "Conspirators arrested in the city" in report
    assert "determiner       1" in report


def test_an_empty_name_trips_nothing():
    """Degenerate input answers rather than raising.

    `signals` indexes `tokens[1:]`, and an entity whose name is whitespace is
    not hypothetical -- `slugify` in `area_projection` exists because names
    that fold to nothing reach this layer.
    """
    assert signals("   ") == frozenset()
    assert not clause_shaped("")


def test_the_determiner_threshold_is_the_one_documented():
    """A guard on the constant the two boundary tests above are written against.

    If someone moves `DETERMINER_MIN_WORDS`, the two real names it was measured
    to rescue should be re-measured rather than silently reclassified.
    """
    assert DETERMINER_MIN_WORDS == 5
    assert len(signals("Cato the Younger")) == 0
