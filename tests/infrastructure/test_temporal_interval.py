"""`extent_bounds`: the arithmetic redstring would have done and may not.

`redstring.domain.interval.bounds` and `widen` are exactly this function, and
`tests/test_architecture.py` forbids importing anything under
`redstring.domain.`. So this is a reimplementation against `TemporalExtent`'s
public fields, and these tests are the only thing standing between it and a
timeline that draws every year-precision entity as a hairline on 1 January.
"""

from datetime import UTC, datetime

from redstring import DatePrecision, TemporalExtent, UncertaintyMarker

from research_team.infrastructure.knowledge.temporal_interval import extent_bounds


def test_a_year_precision_extent_spans_its_whole_year():
    """The decision the whole module exists for.

    A `YEAR`-precision extent carries `start_date = 1815-01-01` and no end.
    Drawn literally that is a zero-width mark on New Year's Day, which claims
    a precision the extraction never made and puts "1815" at the same place
    and size as "1 January 1815". Delete the widening in `_widen_to_precision`
    and this test is the one that goes red.
    """
    extent = TemporalExtent(
        start_date=datetime(1815, 1, 1, tzinfo=UTC),
        precision=DatePrecision.YEAR,
    )

    assert extent_bounds(extent) == (
        datetime(1815, 1, 1, tzinfo=UTC),
        datetime(1816, 1, 1, tzinfo=UTC),
    )


def test_a_month_precision_extent_spans_its_month_across_a_year_boundary():
    """December widens into the next January, not into month 13.

    The naive widening is `month + 1`, which raises for December. Chosen as
    the fixture month for exactly that reason -- a test using June would pass
    against the broken arithmetic.
    """
    extent = TemporalExtent(
        start_date=datetime(1923, 12, 1, tzinfo=UTC),
        precision=DatePrecision.MONTH,
    )

    assert extent_bounds(extent) == (
        datetime(1923, 12, 1, tzinfo=UTC),
        datetime(1924, 1, 1, tzinfo=UTC),
    )


def test_a_day_precision_extent_spans_its_day():
    extent = TemporalExtent(
        start_date=datetime(1969, 7, 20, tzinfo=UTC),
        precision=DatePrecision.DAY,
    )

    assert extent_bounds(extent) == (
        datetime(1969, 7, 20, tzinfo=UTC),
        datetime(1969, 7, 21, tzinfo=UTC),
    )


def test_an_explicit_end_date_is_not_widened():
    """A range already says where it stops.

    Widening an extent that carries its own `end_date` would push every range
    a year past what the document said. The widening is for the *absent* end
    only.
    """
    extent = TemporalExtent(
        start_date=datetime(1990, 1, 1, tzinfo=UTC),
        end_date=datetime(1995, 1, 1, tzinfo=UTC),
        precision=DatePrecision.YEAR,
    )

    assert extent_bounds(extent) == (
        datetime(1990, 1, 1, tzinfo=UTC),
        datetime(1995, 1, 1, tzinfo=UTC),
    )


def test_a_before_marker_opens_the_lower_bound_and_leaves_the_upper_closed():
    """`BEFORE` is a claim about unboundedness, not about margin.

    Asserted separately from `AFTER` below, because one test over "an open
    bound" passes against an implementation that opens whichever end it
    likes.
    """
    extent = TemporalExtent(
        start_date=datetime(1500, 1, 1, tzinfo=UTC),
        precision=DatePrecision.YEAR,
        uncertainty=UncertaintyMarker.BEFORE,
    )

    assert extent_bounds(extent) == (None, datetime(1500, 1, 1, tzinfo=UTC))


def test_an_after_marker_opens_the_upper_bound_and_leaves_the_lower_closed():
    extent = TemporalExtent(
        start_date=datetime(1500, 1, 1, tzinfo=UTC),
        precision=DatePrecision.YEAR,
        uncertainty=UncertaintyMarker.AFTER,
    )

    assert extent_bounds(extent) == (datetime(1500, 1, 1, tzinfo=UTC), None)


def test_circa_produces_exactly_the_same_interval_as_exact():
    """The intuitive choice is to widen `CIRCA`, and it is the wrong one.

    "circa 1850" is a claim about how confidently 1850 is known, not about
    which years it might have been. Widening means inventing a margin -- a
    decade? a century? -- after which every bar's width rests on a number
    nobody chose. The marker travels to the browser as a field instead, which
    `test_timeline_reader.py` pins.
    """
    dates = {"start_date": datetime(1850, 1, 1, tzinfo=UTC), "precision": DatePrecision.YEAR}

    circa = TemporalExtent(**dates, uncertainty=UncertaintyMarker.CIRCA)
    exact = TemporalExtent(**dates, uncertainty=UncertaintyMarker.EXACT)

    assert extent_bounds(circa) == extent_bounds(exact)


def test_approximate_and_inferred_also_widen_nothing():
    dates = {"start_date": datetime(1850, 1, 1, tzinfo=UTC), "precision": DatePrecision.YEAR}
    exact = extent_bounds(TemporalExtent(**dates, uncertainty=UncertaintyMarker.EXACT))

    for marker in (UncertaintyMarker.APPROXIMATE, UncertaintyMarker.INFERRED):
        assert extent_bounds(TemporalExtent(**dates, uncertainty=marker)) == exact


def test_an_absent_extent_has_no_interval():
    assert extent_bounds(None) is None


def test_an_extent_with_no_dates_at_all_has_no_interval():
    assert extent_bounds(TemporalExtent()) is None


def test_an_extent_carrying_only_a_sequence_position_has_no_interval():
    """The case that looks dated and is not.

    `sequence_position` orders events that have no dates -- third in a
    narrative, with nothing saying when the narrative happened. No axis
    position applies to it, and an implementation checking only
    `start_date is None` would already pass; this one fails an
    implementation that treats "the extent is non-empty" as "the extent is
    dated".
    """
    assert extent_bounds(TemporalExtent(sequence_position=3)) is None


def test_hour_and_minute_precision_fall_through_to_a_day():
    """Neither is produced by any pipeline in this project.

    `temporal_rendering.py` documents the same fall-through for the same
    reason. A day is the choice rather than an hour because these arrive only
    from a model that volunteered more precision than asked for, and a
    one-hour bar is invisible on an axis spanning years.
    """
    extent = TemporalExtent(
        start_date=datetime(1969, 7, 20, 20, 17, tzinfo=UTC),
        precision=DatePrecision.MINUTE,
    )

    lower, upper = extent_bounds(extent)
    assert lower == datetime(1969, 7, 20, 20, 17, tzinfo=UTC)
    assert upper == datetime(1969, 7, 21, 20, 17, tzinfo=UTC)
