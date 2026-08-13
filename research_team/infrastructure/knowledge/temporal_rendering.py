"""`render_extent`: an extent as text a reader can check an edge against.

Not a re-export of redstring's own `render_temporal`. That function exists to
support a round-trip property -- parse, render, re-parse to an identical
`TemporalExtent` -- and returns `None` whenever it cannot promise that, which
includes ordinary extraction output: a month-precision range, or any extent
carrying a `publication_date` alongside its `start_date`. This module has no
round trip to protect and no parser to feed back into; it exists to put text
under a node on a canvas, so it renders everything the model can express a
`start_date` for and reserves `None` for the one case that actually means
"undated" -- an absent, empty, or merely-ordered extent. Getting that
boundary wrong here is silent in a way it would not be in `render_temporal`:
`None` from this function is read as "nothing to show", not "could not
format", so a wrong answer does not raise, it just erases a date from the
graph.
"""

from typing import Any

# Kept in sync with the module docstring's example, not with `DatePrecision`
# itself: `HOUR` and `MINUTE` exist on the enum but no extraction pipeline in
# this project produces them, so they fall through to the ISO branch below
# along with "no precision at all" rather than earning their own format.
_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _format_one(date: Any, precision: Any) -> str:
    precision_name = getattr(precision, "name", None)
    if precision_name == "YEAR":
        return str(date.year)
    if precision_name == "MONTH":
        return f"{_MONTH_NAMES[date.month - 1]} {date.year}"
    if precision_name == "DAY":
        return f"{date.day} {_MONTH_NAMES[date.month - 1]} {date.year}"
    return date.date().isoformat()


def render_extent(extent: Any) -> str | None:
    """`extent` as short display text, or `None` if there is nothing to show.

    `extent` types as `Any`, matching the convention `graph_reader.py`'s own
    helpers use for redstring objects: this module does not depend on
    `TemporalExtent`'s shape beyond the attributes it reads, so it does not
    import the type.

    `None` only for an extent that is itself absent, empty, or -- per
    `is_empty` -- ordered (`sequence_position` set) but undated. Everything
    else renders, even a bare `start_date` with no `precision` and no
    `original_text`: a bare date is still a date the graph is drawing an edge
    from, and hiding it because one descriptive field is missing would be
    worse than showing an ISO string.
    """
    if extent is None or extent.is_empty:
        return None

    original_text = extent.original_text
    if original_text is not None and original_text.strip():
        return original_text

    start_date = extent.start_date
    if start_date is None:
        # `is_empty` is true for a bare `sequence_position`, but not for
        # `uncertainty` alone -- redstring allows an extent that marks *how*
        # sure the (absent) date is without ever supplying one. There is
        # still nothing to render.
        return None

    precision = extent.precision
    end_date = extent.end_date
    start_text = _format_one(start_date, precision)
    if end_date is None:
        return start_text

    end_text = _format_one(end_date, precision)
    # A range whose two ends format identically -- same year at YEAR
    # precision, same day at DAY precision -- reads as "1904-1904" if joined
    # blindly. That tells a reader nothing the single value didn't already,
    # so collapse to it instead of the span.
    return start_text if start_text == end_text else f"{start_text}-{end_text}"
