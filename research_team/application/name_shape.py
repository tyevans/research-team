"""Telling an entity name that names a *thing* from one that asserts a *claim*.

Extraction returns entity names, and some of them are sentences. Measured on
2026-08-22 over a 326-entity graph built from five Wikipedia articles: names
like `The word chloroplast is derived from the Greek words chloros (green) and
plastes (the one who forms)` and `Conspirators arrested in the city` sit in the
graph as nodes. `docs/design/curriculum-input-quality.md` §2 records why -- the
`fact` entity type asked for exactly that, with a sentence as its example -- and
that type is now gone. This module exists because deleting it is not the fix
anyone can rely on: the model still wants to express what it read, and a
proposition refiled under `concept` is the same defect wearing a type that
cannot be deleted.

So the point of this module is **measurement first and naming second**. It
gives a cheap, deterministic verdict on the *shape* of a name, which
`area_projection` uses to avoid naming a learning area after a sentence, and
which the `__main__` below turns into a figure a person can compare across
ingests.

**What it is, precisely.** Four closed-vocabulary signals over whitespace
tokens. No part of speech tagger, no model, no dependency -- because this has
to run inside a pure projection that is forbidden both, and because a heuristic
whose whole definition fits in one screen is one a reader can argue with. Each
signal is reported separately by `signals` so that a rise in the total can be
attributed rather than merely noticed.

**What it catches:** copular and auxiliary clauses (`X is derived from Y`),
complement and relative clauses (`Observation that X resembles Y`), names
carrying an internal determiner (`Conspirators arrested in **the** city`,
`Tollers carry **a** narrow founding gene pool`), and anything simply too long
to be a noun phrase.

**What it misses, and these are real:**

- A finite lexical verb with no auxiliary and no determiner -- `Chloroplasts
  divide by fission` scores clean. Catching those needs a tagger.
- Gerund event names -- `Naming of chloroplastids` is not a proposition by this
  measure and reads like one to a person. It is a noun phrase, so the measure is
  right by its own definition and unhelpful by the one that matters.

**What it wrongly flags:** titles of works that are sentences or contain
determiners -- `Gone with the Wind`, `The Man Who Knew Too Much` -- and long
formal organisation names. Both are noun phrases naming real things. The bias
is deliberate: this feeds a *name chooser* that falls back gracefully, so a
false positive costs one candidate and a false negative ships a sentence as a
directory name.

This is a proxy. It is not a claim about grammar, and a figure it produces is
comparable to another figure it produced, not to a linguist.
"""

from __future__ import annotations

#: Finite auxiliary and copular forms. Closed class on purpose: the open class
#: of lexical verbs cannot be listed, and guessing at one by suffix ("-ed",
#: "-s") mistakes every plural noun and hyphenated participle in the graph for
#: a verb. An auxiliary appearing anywhere but first is close to conclusive
#: evidence of a finite clause.
FINITE_VERBS = frozenset(
    (
        *("is", "are", "was", "were", "be", "been", "being", "am"),
        *("has", "have", "had"),
        *("do", "does", "did"),
        *("can", "could", "will", "would", "may", "might", "must", "shall", "should"),
    )
)

#: Complementisers, relative pronouns and subordinating conjunctions. `that` is
#: the one that earns this signal its place -- it is what turns
#: `Observation that chloroplasts resemble cyanobacteria` from a two-word noun
#: phrase into a proposition, and no other signal here sees it.
SUBORDINATORS = frozenset(
    (
        "that",
        "which",
        "who",
        "whom",
        "whose",
        "because",
        "when",
        "while",
        "whether",
        "why",
        "how",
        "after",
        "before",
    )
)

#: Articles. Flagged only when they appear *after* the first token: a leading
#: `The` is ordinary in the name of a thing (`The Hague`, `The Beatles`),
#: whereas a determiner in the middle means the name has a second noun phrase
#: inside it, which is prose rather than a name.
DETERMINERS = frozenset(("a", "an", "the"))

#: The determiner signal is off below this many tokens. Measured, not guessed:
#: without it the 326-entity graph reported `Cato the Younger` and
#: `chlorophyll a` as clause-shaped, which is the epithet-and-suffix pattern
#: that short names use a determiner for. Above four tokens an internal
#: determiner stops being an epithet and starts being a second noun phrase.
#: It does not clear the signal entirely -- `Collapse of the Roman Republic` is
#: five tokens and a perfectly good event name, and is still flagged.
DETERMINER_MIN_WORDS = 5

#: Above this many whitespace tokens, a name is treated as clause-shaped
#: whatever else it looks like. Set from the longest genuine noun-phrase entity
#: names in the measured graph (`Andreas Franz Wilhelm Schimper`, four;
#: `Nova Scotia Duck Tolling Retriever Club of Canada`, eight) with a token of
#: room, so it fires on prose and not on a formal title.
MAX_NAME_WORDS = 9


def signals(name: str) -> frozenset[str]:
    """Which shape signals `name` trips, by name.

    Returned as a set rather than reduced to a boolean so the `__main__`
    breakdown can attribute a change: a rise in "verb" between two ingests is a
    different story about the extractor than a rise in "long".
    """
    tokens = [t.strip("(),.;:\"'").lower() for t in name.split()]
    tokens = [t for t in tokens if t]
    if not tokens:
        return frozenset()
    tail = tokens[1:]
    found = set()
    if len(tokens) > MAX_NAME_WORDS:
        found.add("long")
    if any(t in FINITE_VERBS for t in tail):
        found.add("verb")
    if any(t in SUBORDINATORS for t in tail):
        found.add("subordinator")
    if len(tokens) >= DETERMINER_MIN_WORDS and any(t in DETERMINERS for t in tail):
        found.add("determiner")
    return frozenset(found)


def clause_shaped(name: str) -> bool:
    """Whether `name` reads as a claim rather than as the name of a thing.

    Any one signal is enough. They are not independent evidence to be summed --
    each is separately close to conclusive on its own, and requiring two would
    mean `The word chloroplast is derived from...` (verb, determiner, long:
    three) and `Observation that chloroplasts resemble cyanobacteria`
    (subordinator: one) were treated differently, when they are the same defect.
    """
    return bool(signals(name))


def _report(names: list[str]) -> str:
    """The breakdown `__main__` prints. Separated so a test can read it."""
    flagged = [n for n in names if clause_shaped(n)]
    lines = [
        f"{len(names)} entity names, {len(flagged)} clause-shaped "
        f"({(100.0 * len(flagged) / len(names)) if names else 0.0:.1f}%)",
        "",
        "by signal (a name may trip several):",
    ]
    for signal in ("verb", "subordinator", "determiner", "long"):
        count = sum(1 for n in names if signal in signals(n))
        lines.append(f"  {signal:<13} {count:>4}")
    lines += ["", "flagged names, longest first:"]
    lines += [f"  {n}" for n in sorted(flagged, key=lambda n: (-len(n), n))]
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover - a measurement tool, not a path
    # Reads the graph endpoint's JSON on stdin rather than opening a database,
    # for the reason `docs/design/curriculum-input-quality.md` §5 gives: this
    # machine holds one model at a time and opening a project is not free. The
    # server that already has the project open is the cheapest reader there is.
    #
    #   curl -s localhost:8931/api/projects/$PID/graph \
    #     | uv run python -m research_team.application.name_shape
    import json
    import sys

    payload = json.load(sys.stdin)
    print(_report([e["name"] for e in payload["entities"]]))
