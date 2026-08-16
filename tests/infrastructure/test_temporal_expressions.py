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

    @pytest.mark.parametrize("raw", ["", "   ", "sometime later", "during the war"])
    def test_undated_prose_is_passed_through_for_the_parser_to_refuse(self, raw: str) -> None:
        """Not this module's job to decide these are undated.

        It normalises spelling of dates; deciding what is a date at all is the
        parser's, and duplicating that judgement here would put two
        disagreeing answers in the codebase.
        """
        assert normalize_for_parsing(raw) == raw
