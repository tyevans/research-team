"""`normalize_for_parsing`: spell a date the way redstring's parser reads it.

The fourth module in this directory written against redstring rather than
through it, after `temporal_rendering.py` and `temporal_interval.py`, and it
exists for a harder reason than either. Those two replace functions that are
merely unexported. This one cannot call the function it is compensating for at
all: `parse_temporal` lives at `redstring.domain.temporal_parsing`, is absent
from `redstring.__all__`, and `tests/test_architecture.py` forbids importing
anything under `redstring.domain.` from `research_team/`. So the correction
has to happen in the *input*, before redstring's own pipeline reaches its
parser -- there is no seam on the other side, because `map_extraction` runs
inside `build_graph` and writes the store and the event together.

**Why it exists.** Measured on 2026-08-15 against the real database, project
"Ancient Rome": 2,525 entities, 8 with a temporal extent. Not because the
model stayed silent -- commit d2aa97c had already added the prompt asking for
dates, and these documents were extracted after it landed -- but because the
parser destroys what the model returns. Two behaviours, both measured against
`parse_temporal` directly with `reference_date` set to the article's
`published_at`, which is what extraction passes:

  '313'          -> 0313-08-25, DAY precision
  'AD 476'       -> 0476-08-25, DAY precision
  'AD 14'        -> 2003-08-14, DAY precision
  '44'           -> 2044-08-25, DAY precision

The month and day are the *article's* publication date, filled in by dateutil
because a bare short number does not look like a year to it. This is not a
dropped date; it is a fabricated one, asserted at DAY precision, and it is in
the database now -- the Edict of Milan is stored as 0313-08-25 with
`original_text` "313", where 25 August is when the Wikipedia article was
published. Zero-padding to four digits is the whole fix, and it was found by
trying it: '0313' parses to 0313-01-01 at YEAR precision.

  'the 19th century'   -> None
  '2nd century AD'     -> None
  'the 2nd century AD' -> None

while a bare '19th century' parses correctly. The leading article and the era
suffix each defeat it on their own. This matters more than it looks: the
prompt in `research_corpus.yaml` offers "the latter half of the 19th century"
as a model answer, so the schema is actively soliciting the form that is
thrown away.

**What it deliberately does not fix.** BC. `TemporalExtent.start_date` is a
`datetime` and `datetime.MINYEAR` is 1, so no year before 1 AD is
representable -- this is a limit of the type, not of the parser, and no amount
of normalising reaches it. `normalize_for_parsing` returns `None` for a BC
expression to say "do not hand this to the parser", which is different from
the parser's own `None` for "this is not a date". The caller must keep the raw
wording rather than discard it; `redstring_adapter.py` stores it on the entity
so the loss is countable and so the dates are still there when a
representation for them is chosen. For the Ancient Rome corpus this is most of
the real dates -- 89 BC mentions across its 11 source documents -- so the rate
this module fixes is the AD-era rate, not the whole one.

**The rewriting is deliberately narrow.** Anything that is not one of the
measured failures is returned unchanged, including prose that is not a date at
all. Deciding what counts as a date is the parser's judgement, and making it
twice in two places is how the two answers start to disagree.
"""

import re

#: Where an entity keeps the temporal expression the model actually wrote.
#:
#: Lives here rather than in `redstring_adapter.py`, which is where it is
#: written, because `temporal_rendering.py` has to read it and importing the
#: adapter to learn a string constant would drag the whole extraction stack
#: into the rendering path. The adapter re-exports it, so the name is still
#: reachable from where a reader of that module would look for it.
RAW_TEMPORAL_PROPERTY = "temporal_expression"

#: Matches a year written with an era, in either order: 'AD 476', '476 AD',
#: '476 CE', 'CE 476'. Anchored to the whole (trimmed) string rather than
#: searched for, because a rewrite inside a longer phrase would change text
#: the parser is otherwise reading correctly.
_ERA_YEAR = re.compile(r"^(?:(AD|CE)\s+(\d{1,4})|(\d{1,4})\s*(AD|CE))$", re.IGNORECASE)

#: A bare year of fewer than four digits -- the form dateutil fills a month
#: and day into.
_SHORT_YEAR = re.compile(r"^(\d{1,3})$")

#: An ordinal century, with an optional leading article and an optional AD/CE
#: suffix, both of which defeat the parser on their own.
_CENTURY = re.compile(
    r"^(?:the\s+)?(\d{1,2}(?:st|nd|rd|th))\s+century(?:\s+(?:AD|CE))?$", re.IGNORECASE
)

#: Written before the year, and preserved: the parser detects uncertainty on
#: the string it is handed, so dropping 'circa' while padding the year would
#: turn a hedged date into an exact one.
_LEADING_MARKER = re.compile(
    r"^((?:circa|around|about|approximately|before|after|c\.)\s+)", re.IGNORECASE
)

#: Any mention of an era that precedes year 1. Checked before everything else
#: and on the whole string, not anchored: 'March 15, 44 BC' and '27 BC - AD 14'
#: are both unrepresentable, and the second would otherwise look like an
#: ordinary AD expression to the rules above.
_BEFORE_CHRIST = re.compile(r"\b(BC|BCE)\b", re.IGNORECASE)


def normalize_for_parsing(raw: str) -> str | None:
    """`raw` respelled for redstring's parser, or `None` if it must not see it.

    Args:
        raw: A temporal expression as the model wrote it.

    Returns:
        The text to parse. `None` means the expression states a date that
        cannot be represented at all (BC), and the caller is expected to
        preserve `raw` rather than treat the entity as undated -- the two are
        not the same thing and only the caller can tell them apart afterwards.
        Anything this module has no measured correction for comes back
        unchanged, including text that is not a date.
    """
    if _BEFORE_CHRIST.search(raw):
        return None

    trimmed = raw.strip()
    if not trimmed:
        return raw

    marker_match = _LEADING_MARKER.match(trimmed)
    marker = marker_match.group(1) if marker_match else ""
    body = trimmed[len(marker) :]

    century = _CENTURY.match(body)
    if century is not None:
        return f"{marker}{century.group(1).lower()} century"

    era_year = _ERA_YEAR.match(body)
    if era_year is not None:
        year = era_year.group(2) or era_year.group(3)
        return f"{marker}{int(year):04d}"

    short_year = _SHORT_YEAR.match(body)
    if short_year is not None:
        return f"{marker}{int(short_year.group(1)):04d}"

    return raw
