"""What `temporal_expressions` has to get right for an ancient-history corpus.

Every expectation below was measured against redstring's parser on
2026-08-15 before being written, not reasoned about. The measurements are
recorded in `temporal_expressions.py`'s docstring; these tests are what fails
if the normalisation stops producing them.

The parser is reached here through its dotted path, which
`tests/test_architecture.py` permits in `tests/` and forbids in
`research_team/`. That asymmetry is the point: the production module must not
import it, and this test must, because the whole claim being tested is about
what that exact function does with the string we hand it.
"""

from datetime import UTC, datetime

import pytest
from redstring.domain.temporal_parsing import parse_temporal

from research_team.infrastructure.knowledge.temporal_expressions import (
    normalize_for_parsing,
)

# The publication date of the 'Edict of Milan' Wikipedia article, which is the
# vantage point the real extraction used and the source of the fabricated
# month and day this module exists to stop.
REFERENCE = datetime(2003, 8, 25, tzinfo=UTC)


def parsed(raw: str):
    """`raw` normalised and then parsed, the way extraction will do it."""
    normalized = normalize_for_parsing(raw)
    if normalized is None:
        return None
    return parse_temporal(normalized, reference_date=REFERENCE)


class TestYearsBeforeAThousand:
    """The defect that shipped: a short year borrows the article's month."""

    @pytest.mark.parametrize(
        ("raw", "year"),
        [
            ("313", 313),
            ("AD 476", 476),
            ("476 AD", 476),
            ("476 CE", 476),
            ("CE 476", 476),
            ("AD 14", 14),
            ("14 AD", 14),
        ],
    )
    def test_an_ancient_year_is_a_year_and_not_a_day(self, raw: str, year: int) -> None:
        """Fails against the unnormalised string, which is how this shipped.

        Handed to the parser raw, '313' yields 0313-08-25 at DAY precision --
        August 25 being the *article's* publication date, not anything the
        text said. That value is in the real database.
        """
        extent = parsed(raw)
        assert extent is not None
        assert extent.start_date.year == year
        assert extent.precision.name == "YEAR"
        assert extent.start_date.month == 1
        assert extent.start_date.day == 1

    def test_a_four_digit_year_is_untouched(self) -> None:
        """The case that already worked, kept working.

        Six of the eight dated entities in the real database are modern
        four-digit years; they parse correctly today and a normalisation that
        broke them would trade one silent loss for another.
        """
        extent = parsed("2002")
        assert extent is not None
        assert extent.start_date.year == 2002
        assert extent.precision.name == "YEAR"


class TestCenturies:
    """`the` in front of a century loses it entirely."""

    @pytest.mark.parametrize(
        "raw",
        ["2nd century", "the 2nd century", "2nd century AD", "the 2nd century AD"],
    )
    def test_a_century_survives_its_article_and_its_era(self, raw: str) -> None:
        """Three of these four yield `None` unnormalised.

        Only the bare '2nd century' parses. The prompt in
        `research_corpus.yaml` invites exactly the forms that do not -- it
        offers 'the latter half of the 19th century' as a model answer.
        """
        extent = parsed(raw)
        assert extent is not None
        assert extent.start_date.year == 101
        assert extent.end_date.year == 200

    def test_a_modern_century_still_parses(self) -> None:
        extent = parsed("the 19th century")
        assert extent is not None
        assert extent.start_date.year == 1801


class TestHedgedCenturies:
    """A century wrapped in a qualifier is still a century.

    Every expression here is real model output from the 2026-08-15 runs
    against qwen3.8-27b-mtp, and every one of them parses to `None`
    unnormalised -- the qualifier alone is what defeats the parser.

    **They resolve to the whole century, not to a third of it.** 'early 2nd
    century' does mean the early part, and emitting 0101-0133 for it was
    considered and rejected: the thirds are a convention this code would be
    inventing, and the repository's rule is that a guessed date is worse than
    a vague one. Widening is safe -- the band contains the truth -- where
    narrowing asserts edges the text never gave. The cost is real and worth
    stating: 'early 2nd century' and 'late 2nd century' draw identical bands.
    The entity keeps the model's wording, so the label still distinguishes
    them even when the geometry does not.
    """

    @pytest.mark.parametrize(
        ("raw", "first", "last"),
        [
            ("around the mid-2nd century AD", 101, 200),
            ("by the late 2nd century AD", 101, 200),
            ("during the 4th century", 301, 400),
            ("early 3rd century AD", 201, 300),
            ("the late 1st century", 1, 100),
            ("mid 5th century CE", 401, 500),
        ],
    )
    def test_a_qualified_century_spans_that_century(
        self, raw: str, first: int, last: int
    ) -> None:
        extent = parsed(raw)
        assert extent is not None
        assert extent.start_date.year == first
        assert extent.end_date.year == last

    def test_a_qualified_century_is_marked_uncertain(self) -> None:
        """The qualifier is a hedge and the extent has to say so.

        Drawn as an exact band, 'around the mid-2nd century' asserts a
        hundred-year certainty the text did not offer.
        """
        extent = parsed("around the mid-2nd century AD")
        assert extent.uncertainty.name in {"APPROXIMATE", "CIRCA"}


class TestTheHundredsForm:
    """'200s' fabricates a date rather than failing, which is the worse mode.

    Measured with `reference_date` 2005-05-31: bare '200s' parses to
    2005-05-30 at DAY precision -- the reference date, less a day. 'mid-200s',
    which is what the Roman economy article actually returned, yields `None`.
    So the safe spelling is the one the corpus produced and the dangerous one
    is a keystroke away.

    Read as the century, 200-299, on the historical convention: 'the 200s' in
    a text about Rome is the third century, not the decade 200-209. That
    reading is wrong for a sentence about the 2000s, which is why this is
    scoped to three digits -- a four-digit '1990s' is already handled
    correctly by the parser as a decade and is left alone.
    """

    def test_the_hundreds_span_their_century(self) -> None:
        extent = parsed("mid-200s")
        assert extent is not None
        assert extent.start_date.year == 200
        assert extent.end_date.year == 299

    def test_a_bare_hundreds_is_not_the_reference_date(self) -> None:
        """Fails unnormalised with 2005-05-30, DAY."""
        extent = parsed("200s")
        assert extent is not None
        assert extent.start_date.year == 200
        assert extent.precision.name == "YEAR"

    def test_a_modern_decade_is_left_alone(self) -> None:
        """'1990s' already parses as 1990-1999 and must not become a century."""
        extent = parsed("the 1990s")
        assert extent.start_date.year == 1990
        assert extent.end_date.year == 1999

    def test_a_three_digit_decade_is_left_to_the_parser(self) -> None:
        """'250s' is a decade, not a century, and this rule must not claim it.

        The trailing '00' is what separates the two readings. Left unchanged
        rather than handled, so if the parser ever learns the form it is not
        fighting a rewrite here.
        """
        assert normalize_for_parsing("250s") == "250s"

    def test_the_span_is_hedged_rather_than_exact(self) -> None:
        """A century derived from 'mid-200s' is not an exact claim about 299.

        A bare '0200-0299' parses EXACT, which would assert both edges. Fails
        without the 'around' the normaliser prepends.
        """
        assert parsed("mid-200s").uncertainty.name == "APPROXIMATE"


class TestShortYearRanges:
    """A span of ancient years needs the same padding a single one does.

    '130-170' yields `None` where '0130-0170' parses, for the same reason a
    bare '313' misparses: the parser's range branch wants four digits. The
    corpus produced these as regnal spans -- 'r. 249-251' on Decius and
    'r. 253-268' on Gallienus, from the Edict of Milan article.

    The 'r.' is dropped rather than interpreted. A reign is not the same claim
    as an event, but it is the only date those entities carry, and the extent
    it denotes is exactly the years given.
    """

    @pytest.mark.parametrize(
        ("raw", "first", "last"),
        [
            ("249-251", 249, 251),
            ("r. 249-251", 249, 251),
            ("r. 253-268", 253, 268),
            ("270-275 AD", 270, 275),
        ],
    )
    def test_a_short_range_spans_its_years(self, raw: str, first: int, last: int) -> None:
        extent = parsed(raw)
        assert extent is not None
        assert extent.start_date.year == first
        assert extent.end_date.year == last

    def test_a_modern_range_is_unchanged(self) -> None:
        """'2009-2014' already parses; padding it must be a no-op."""
        extent = parsed("2009-2014")
        assert extent.start_date.year == 2009
        assert extent.end_date.year == 2014

    def test_a_backwards_range_is_left_alone(self) -> None:
        """The normaliser does not emit a spelling it knows is incoherent.

        **This test passes with the guard reverted**, and the docstring it
        replaces claimed otherwise -- that emitting '0251-0249' would raise
        `ValueError` out of `TemporalExtent` and cost the whole chunk.
        Measured on redstring 0.9.2: the parser returns `None` for it, so the
        entity ends up undated either way and nothing is lost.

        Kept because the guard asserts something about this function rather
        than about the parser: what it returns is meant to be a better
        spelling of its input, and emitting a backwards range on the
        expectation that something downstream will refuse it is a dependency
        on behaviour no test here pins.
        """
        assert normalize_for_parsing("251-249") == "251-249"

    def test_a_bc_range_is_still_refused(self) -> None:
        """The range rule must not reach past the BC guard.

        '91-88 BC' is two years that cannot be represented; matching the digits
        and dropping the era would date it to AD 91-88 -- which is also
        backwards, and would raise rather than merely mislead.
        """
        assert normalize_for_parsing("91-88 BC") is None


class TestUncertaintyIsNotLost:
    def test_circa_survives_normalising_the_year(self) -> None:
        """Normalising must not eat the marker that qualifies the date.

        'circa 476 AD' has to reach the parser still saying 'circa', or the
        graph asserts an exact date the text hedged.
        """
        extent = parsed("circa 476 AD")
        assert extent is not None
        assert extent.start_date.year == 476
        assert extent.uncertainty.name == "CIRCA"


class TestBeforeChrist:
    """BC is refused rather than mangled, and the refusal is the contract.

    `datetime.MINYEAR` is 1, and `TemporalExtent.start_date` is a `datetime`,
    so no year before 1 AD can be represented at all. `normalize_for_parsing`
    returns `None` to say so. That is not the same as "this text has no date",
    and the caller is required to keep the raw expression rather than drop it
    -- see `test_redstring_adapter.py`.
    """

    @pytest.mark.parametrize(
        "raw",
        [
            "44 BC",
            "509 BC",
            "27 BCE",
            "the 1st century BC",
            "March 15, 44 BC",
            "27 BC - AD 14",
        ],
    )
    def test_a_bc_expression_is_refused_not_silently_parsed(self, raw: str) -> None:
        assert normalize_for_parsing(raw) is None


class TestThingsItMustNotTouch:
    """A normaliser that rewrites too much is the same bug facing the other way."""

    @pytest.mark.parametrize(
        "raw",
        ["October 2009", "the 1990s", "March 15, 1920", "1974", "2009-2014"],
    )
    def test_an_expression_already_handled_is_passed_through(self, raw: str) -> None:
        assert normalize_for_parsing(raw) == raw

    @pytest.mark.parametrize("raw", ["", "   ", "an unspecified time", "in antiquity"])
    def test_undated_prose_is_passed_through_for_the_parser_to_refuse(self, raw: str) -> None:
        """Not this module's job to decide these are undated.

        It normalises the spelling of dates, and refuses the two kinds it
        knows the parser answers *wrongly* -- BC and narrative-relative.
        Everything else is the parser's judgement, and duplicating it here
        would put two disagreeing answers in the codebase.

        This case list used to include 'sometime later' and 'during the war'.
        Both are now refused by `TestNarrativeRelativeIsRefused` below, which
        is a deliberate narrowing of what "passed through" means: they contain
        a relative qualifier and no anchor, and against a `reference_date`
        they resolve to a date derived from when the article was published.
        """
        assert normalize_for_parsing(raw) == raw


class TestNarrativeRelativeIsRefused:
    """A date relative to the story, not to the calendar, must not be parsed.

    Resolved against `published_at` these yield a date derived from when the
    article was written, cleanly and with no exception -- redstring raises
    `AmbiguousReferenceDateError` only when a reference date is missing
    entirely, and these documents always have one. Measured against redstring
    0.9.2 with `reference_date` 2003-08-25:

        '40 years ago'     -> 1963-08-25, DAY
        'three days later' -> 2003-08-28, DAY
        'last year'        -> 2002-08-25, DAY

    The parametrised list below is wider than that, and most of it is
    belt-and-braces: 'two years earlier', 'nearly 40 years' and "After
    Galerius's death" -- the three the real article actually returned -- are
    refused by the parser unaided, so for those the rule changes the
    *normaliser's* answer without changing the extracted graph at all. (This
    class asserts the normaliser's answer, so those cases do go red without
    the rule; the end-to-end behaviour they stand for does not.) They are kept
    because the difference is a spelling accident.
    'two years earlier' is dropped and 'two years ago' fabricates; they mean
    the same thing, and which one a document uses is not something this
    project controls.

    The first three are the cases that fail without the rule.
    """

    @pytest.mark.parametrize(
        "raw",
        [
            # These fabricate a date without the rule.
            "40 years ago",
            "three days later",
            "last year",
            # These the parser already refuses; kept for the reason above.
            "two years earlier",
            "nearly 40 years",
            "After Galerius's death",
            "during the time of the kings",
            "sometime later",
            "during the war",
            "shortly afterwards",
        ],
    )
    def test_a_narrative_relative_expression_is_refused(self, raw: str) -> None:
        assert normalize_for_parsing(raw) is None

    @pytest.mark.parametrize(
        "raw",
        ["before 1900", "after 1918", "during the 4th century", "since AD 235"],
    )
    def test_a_relative_word_with_a_real_anchor_still_parses(self, raw: str) -> None:
        """'before'/'after' also open absolute expressions, and those are dates.

        `temporal_rendering._RENDER_PREFIX` renders a `BEFORE` marker, so
        'before 1900' is an extent this project already knows how to show.
        Refusing every string containing 'before' would throw those away to
        catch 'two years earlier'.
        """
        assert normalize_for_parsing(raw) is not None
