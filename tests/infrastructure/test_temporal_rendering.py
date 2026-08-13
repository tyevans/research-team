"""`render_extent`: an extent as text a reader can check an edge against.

Deliberately not `redstring`'s `render_temporal`. That function exists for a
round-trip property and returns `None` for anything it cannot re-parse to an
identical extent -- which includes ordinary extraction output. The tests here
are mostly about the cases where the two disagree, because agreeing on the
easy ones is not what this function is for.
"""

from datetime import UTC, datetime

import pytest
from redstring import DatePrecision, TemporalExtent

from research_team.infrastructure.knowledge.temporal_rendering import render_extent


def test_the_original_text_is_preferred_to_any_reformatting():
    """What the document said, unimproved.

    Fails if the fallback formatter runs whenever it *can* rather than only
    when there is no source text -- which is the shape this most plausibly
    gets written as.
    """
    extent = TemporalExtent(
        start_date=datetime(1904, 1, 1, tzinfo=UTC),
        precision=DatePrecision.YEAR,
        original_text="the summer of 1904",
    )
    assert render_extent(extent) == "the summer of 1904"


def test_a_month_range_renders_though_redstring_declines_to():
    """The case that makes this a separate function rather than a re-export.

    `render_temporal` returns `None` here -- a month-precision *range* is not
    a form its parser accepts back -- and `None` from this function would mean
    "undated", so the date would vanish from the canvas with no error anywhere.
    """
    extent = TemporalExtent(
        start_date=datetime(1918, 3, 1, tzinfo=UTC),
        end_date=datetime(1918, 11, 1, tzinfo=UTC),
        precision=DatePrecision.MONTH,
    )
    rendered = render_extent(extent)
    assert rendered is not None
    assert "1918" in rendered


def test_a_publication_date_does_not_suppress_the_rendering():
    """Second case `render_temporal` declines. Same failure, same reason."""
    extent = TemporalExtent(
        start_date=datetime(1904, 1, 1, tzinfo=UTC),
        precision=DatePrecision.YEAR,
        publication_date=datetime(1990, 1, 1, tzinfo=UTC),
    )
    assert render_extent(extent) == "1904"


def test_a_year_renders_as_the_year_alone():
    extent = TemporalExtent(
        start_date=datetime(1904, 1, 1, tzinfo=UTC), precision=DatePrecision.YEAR
    )
    assert render_extent(extent) == "1904"


def test_a_year_range_renders_as_a_span():
    extent = TemporalExtent(
        start_date=datetime(1990, 1, 1, tzinfo=UTC),
        end_date=datetime(1995, 1, 1, tzinfo=UTC),
        precision=DatePrecision.YEAR,
    )
    assert render_extent(extent) == "1990-1995"


def test_dates_with_no_precision_still_render():
    """Precision is optional on the model, so it is optional here.

    Returning `None` for a dated extent because one *descriptive* field is
    absent would hide a date the graph is drawing an edge from.
    """
    extent = TemporalExtent(start_date=datetime(1904, 6, 15, tzinfo=UTC))
    rendered = render_extent(extent)
    assert rendered is not None
    assert "1904" in rendered


def test_a_range_with_identical_ends_collapses_to_one_value():
    """A reader gets "1904", not "1904-1904" -- the doubled form tells them
    nothing the single year didn't already.

    Fails against an implementation that joins `start_text` and `end_text`
    with `-` unconditionally: at YEAR precision, a range confined to one
    calendar year formats both ends to the same string, and blind joining
    would still produce "1904-1904".
    """
    extent = TemporalExtent(
        start_date=datetime(1904, 1, 1, tzinfo=UTC),
        end_date=datetime(1904, 6, 1, tzinfo=UTC),
        precision=DatePrecision.YEAR,
    )
    assert render_extent(extent) == "1904"


@pytest.mark.parametrize(
    ("extent", "case"),
    [
        (None, "absent"),
        (TemporalExtent(), "empty"),
        (TemporalExtent(sequence_position=3), "ordered but undated"),
    ],
)
def test_only_an_undated_extent_renders_as_none(extent, case):
    """`None` means undated and nothing else.

    `sequence_position` alone is what `infer_relations` itself treats as
    undated, so the two agree about which entities take no part.
    """
    assert render_extent(extent) is None, case
