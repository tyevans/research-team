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

**Why it exists, and what it is *not* the fix for.** Measured on 2026-08-15
against the real database, project "Ancient Rome": 2,525 entities, 8 with a
temporal extent. That rate is **not** what this module fixes. Its cause was
that the model files the date in `properties` and `_build_extent` reads only
the schema field, so nothing reached the parser at all -- see `CLAUDE.md`'s
Extraction section and `redstring_adapter._DatingProvider`.

This module fixes what happens *once* an expression arrives. Every defect
below is real and every one of them was measured, but they were all downstream
of an empty field, which is why fixing them first moved the rate almost not at
all. They matter now because the lift made them reachable. All measured
against `parse_temporal` directly, with `reference_date` set to the article's
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
twice in two places is how the two answers start to disagree. The two
exceptions are the kinds the parser answers *wrongly* rather than not at all
-- BC, which it drops, and narrative-relative, which it resolves against the
publication date -- and both return `None` rather than a rewrite.

**Every rule here is a workaround for a redstring defect, and redstring is
this project's own library.** `BACKLOG.md` B87 lists the four, with the
measurements; the first two would let most of this module be deleted. It is
worth knowing that before adding a fifth rule.
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

#: A span of years, with an optional regnal 'r.' and an optional era suffix.
#:
#: The parser's range branch wants four digits on both sides: '130-170' yields
#: None where '0130-0170' parses. The corpus produced these as reigns --
#: 'r. 249-251' (Decius) and 'r. 253-268' (Gallienus) from the Edict of Milan
#: article. The 'r.' is dropped rather than interpreted; a reign is a
#: different claim from an event, but it is the only date those entities
#: carry and the years it names are exactly the extent.
#:
#: Both dash forms, because the model uses the en dash as readily as the
#: hyphen -- '91-88 BC' came back with one.
_YEAR_RANGE = re.compile(
    # U+2013 and U+2014 as escapes rather than literals: ruff's RUF001 reads a
    # literal en or em dash as a typo for a hyphen and fails the lint gate.
    # Both are genuinely needed -- the model returned a BC range punctuated
    # with an en dash, so a hyphen-only class would miss it.
    r"^(?:r\.?\s*)?(\d{1,4})\s*[-\u2013\u2014]\s*(\d{1,4})(?:\s+(?:AD|CE))?$",
    re.IGNORECASE,
)

#: An ordinal century, however it is hedged.
#:
#: The parser accepts a bare '19th century' and nothing else: a leading
#: article, a leading preposition, a position qualifier, or an era suffix each
#: defeat it alone, and real output stacks all four ('around the mid-2nd
#: century AD'). Every part outside the capture group is discarded.
#:
#: **The qualifier is dropped, not honoured.** 'early 2nd century' resolves to
#: the whole of 101-200 rather than to its first third. The thirds would be a
#: convention invented here, and a wider band contains the truth where a
#: narrower one asserts edges the text never gave -- the same reasoning that
#: makes a guessed date worse than a vague one. The cost is that 'early' and
#: 'late' draw identically; the entity keeps the model's wording, so the label
#: still separates them.
_CENTURY = re.compile(
    r"^(?:(?:in|during|by|from|around|about|circa|throughout)\s+)?"
    r"(?:the\s+)?"
    r"(?:(?:early|mid|middle|late|beginning\s+of|end\s+of|first\s+half\s+of"
    r"|second\s+half\s+of|latter\s+half\s+of)[\s-]+)?"
    r"(?:the\s+)?"
    r"(\d{1,2}(?:st|nd|rd|th))\s+centur(?:y|ies)"
    r"(?:\s+(?:AD|CE))?$",
    re.IGNORECASE,
)

#: 'the 200s', 'mid-200s' -- a three-digit century written as a span.
#:
#: Refused rather than passed through, because the bare form is the dangerous
#: one. Measured with `reference_date` 2005-05-31: '200s' parses to
#: **2005-05-30 at DAY precision** -- the reference date less a day -- while
#: 'mid-200s', which is what the corpus actually produced, yields None. The
#: safe spelling is the one that happened to appear and the fabricating one is
#: a keystroke away.
#:
#: Read as 200-299, the historical convention: 'the 200s' in a text about Rome
#: is the third century, not the decade 200-209.
#:
#: Anchored on a trailing '00s' rather than on digit count, which is what
#: separates the two readings: '200s' ends in two zeros and means the century,
#: '250s' does not and means the decade 250-259. Only the century form is
#: claimed here; a three-digit decade is left to the parser. A four-digit
#: '1990s' cannot match either, and is already read correctly as a decade.
_HUNDREDS = re.compile(
    r"^(?:(?:in|during|by|around|about|circa)\s+)?"
    r"(?:the\s+)?"
    r"(?:(?:early|mid|middle|late)[\s-]+)?"
    r"(?:the\s+)?"
    r"(\d{1,2})00s$",
    re.IGNORECASE,
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


#: Expressions anchored to the narrative rather than to a calendar.
#:
#: These have to be refused, and the reason is specific to this corpus. A
#: relative expression resolves against `reference_date`, which extraction
#: takes from `SourceDocument.published_at`. For a news article that is right.
#: For an encyclopedia entry written in 2003 and narrating the fourth century
#: it is nonsense, and it is nonsense that parses cleanly:
#: `AmbiguousReferenceDateError` fires only when there is *no* reference date,
#: and these documents always have one, so there is no error to notice.
#: Measured against redstring 0.9.2 with `reference_date` 2003-08-25:
#:
#:     '40 years ago'     -> 1963-08-25, DAY
#:     'three days later' -> 2003-08-28, DAY
#:     'last year'        -> 2002-08-25, DAY
#:
#: **The expressions the real article returned are not those.** It gave 'two
#: years earlier', 'nearly 40 years' and "After Galerius's death", and the
#: parser refuses all three on its own -- an earlier version of this comment
#: claimed 'two years earlier' became 2001, which was reasoned rather than
#: measured and is wrong. The rule stays because the distinction is a spelling
#: accident: 'two years earlier' is dropped and 'two years ago' fabricates,
#: and nothing stops the next document using the second one.
#:
#: Matched as whole words anywhere in the string rather than anchored: the
#: qualifier is what makes the expression relative, wherever it sits.
_NARRATIVE_RELATIVE = re.compile(
    r"\b(earlier|later|ago|afterwards?|thereafter|previous(?:ly)?|subsequent(?:ly)?"
    r"|following|preceding|after|before|since|during|within|next|last|recent(?:ly)?"
    r"|then|now|today|yesterday|tomorrow|current(?:ly)?)\b",
    re.IGNORECASE,
)

#: A bare span of time, which is a duration and not a date at all.
#:
#: 'nearly 40 years' came back from the real article on "the little peace of
#: the Church". It names how long something lasted, not when it happened, and
#: it carries no relative *word* for the pattern above to catch.
#:
#: The parser happens to refuse that exact spelling, so this rule changes
#: nothing for it -- '40 years ago' is the one that resolves, to 1963-08-25.
#: The rule is here because a duration and a date are different kinds of
#: answer, and letting durations through to be refused by luck means the
#: first spelling the parser *does* accept becomes a wrong date silently.
#:
#: Ordinals are excluded by construction: '19th century' does not match,
#: because `\d{1,3}\s+` cannot span the 'th'.
_BARE_DURATION = re.compile(
    r"\b\d{1,3}\s+(?:years?|months?|weeks?|days?|decades?|centuries|century)\b",
    re.IGNORECASE,
)

#: The exception to the rule above: 'before'/'after' also open an *absolute*
#: expression -- 'before 1900' is a date this project already renders with a
#: 'before ' prefix (`temporal_rendering._RENDER_PREFIX`). So a string that
#: still contains a four-digit year, or an era, is left to the parser even
#: when a relative word appears in it.
_HAS_ANCHOR = re.compile(r"\d{3,4}|\b(?:AD|CE|BC|BCE)\b|\bcentury\b", re.IGNORECASE)


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
    relative = _NARRATIVE_RELATIVE.search(raw) or _BARE_DURATION.search(raw)
    if relative and not _HAS_ANCHOR.search(raw):
        return None

    trimmed = raw.strip()
    if not trimmed:
        return raw

    marker_match = _LEADING_MARKER.match(trimmed)
    marker = marker_match.group(1) if marker_match else ""
    body = trimmed[len(marker) :]

    century = _CENTURY.match(body)
    if century is not None:
        # Not `f"{marker}..."`: the parser marks a century APPROXIMATE by
        # itself, and any leading marker here is part of the hedge the century
        # rule already discarded. Re-attaching 'around' would only replace
        # APPROXIMATE with the near-identical CIRCA.
        return f"{century.group(1).lower()} century"

    hundreds = _HUNDREDS.match(body)
    if hundreds is not None:
        first = int(hundreds.group(1)) * 100
        # A zero-padded range, because that is the only span form the parser
        # accepts: '130-170' yields None where '0130-0170' parses. The end is
        # the last year of the century rather than the next century's first,
        # so '200s' cannot be read as reaching into the 300s.
        #
        # 'around' rather than a bare range: a range parses EXACT, and a
        # hundred-year span derived from 'mid-200s' is a hedge, not an exact
        # claim about 200 and 299. The century rule above gets APPROXIMATE
        # from the parser for free; this form has to ask for it.
        return f"around {first:04d}-{first + 99:04d}"

    year_range = _YEAR_RANGE.match(body)
    if year_range is not None:
        first, last = int(year_range.group(1)), int(year_range.group(2))
        # A backwards range is left alone rather than emitted. **This changes
        # no outcome today** -- measured on redstring 0.9.2, '0251-0249'
        # returns None from the parser rather than raising, so emitting it and
        # refusing it leave the entity equally undated. An earlier version of
        # this comment claimed the emitted form would raise `ValueError` out
        # of `TemporalExtent` and cost the whole chunk; that was reasoned from
        # the model's validator and never run, and it is wrong -- the range
        # branch rejects it before an extent is built.
        #
        # Kept anyway, for one honest reason: this function's contract is that
        # what it returns is a better spelling of the input, and '0251-0249'
        # is not a better spelling of anything. Emitting a form we know to be
        # incoherent and relying on the parser to refuse it makes this code
        # depend on a behaviour nothing here tests.
        if first <= last:
            return f"{marker}{first:04d}-{last:04d}"
        return raw

    era_year = _ERA_YEAR.match(body)
    if era_year is not None:
        year = era_year.group(2) or era_year.group(3)
        return f"{marker}{int(year):04d}"

    short_year = _SHORT_YEAR.match(body)
    if short_year is not None:
        return f"{marker}{int(short_year.group(1)):04d}"

    return raw
