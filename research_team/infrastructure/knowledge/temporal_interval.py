"""`extent_bounds`: a `TemporalExtent` as the interval a browser draws.

Not a re-export of redstring's own `bounds` and `widen`. They live at
`redstring.domain.interval`, are absent from `redstring.__all__`, and
`tests/test_architecture.py` forbids importing anything under
`redstring.domain.` at all -- redstring's contract is that a dotted path is
internal and may change in a patch release. So the arithmetic is written here
against `TemporalExtent`'s public fields.

The precedent is `temporal_rendering.py`, which exists for the same reason at
one remove: `render_temporal` is both unexported and unsuitable, so
`render_extent` was written locally. The two sit beside each other rather than
one absorbing the other because text and geometry are different outputs with
different `None` conditions -- a single function returning both would have to
pick one meaning of "nothing to show".
"""

from datetime import datetime, timedelta
from typing import Any


def _widen_to_precision(start: datetime, precision: Any) -> datetime:
    """Where a band ends when the extent gave no end date.

    **This is the decision the module exists for.** A `YEAR`-precision extent
    carries `start_date = 1815-01-01` and usually no end; drawn literally that
    is a zero-width mark on New Year's Day, asserting a precision the
    extraction never claimed and placing "1815" exactly where "1 January 1815"
    goes, at the same size. So the band spans what the precision actually
    denotes.

    `HOUR` and `MINUTE` exist on `DatePrecision` and no pipeline in this
    project produces them, so they fall through to a day -- the same
    fall-through `temporal_rendering.py` documents. A day rather than an hour
    because they can only arrive from a model volunteering more precision than
    it was asked for, and an hour-wide bar is invisible on an axis spanning
    years.
    """
    name = getattr(precision, "name", None)
    if name == "YEAR":
        # Not `start.replace(year=start.year + 1)`: correct here, and it
        # raises on 29 February. `start_date` for a YEAR extent is 1 January
        # in every case extraction produces, so the bug would be unreachable
        # until the day something constructed one differently.
        return _add_years(start, 1)
    if name == "MONTH":
        return _add_months(start, 1)
    return start + timedelta(days=1)


def _add_years(date: datetime, years: int) -> datetime:
    try:
        return date.replace(year=date.year + years)
    except ValueError:
        # 29 February in a year whose successor has no 29th. Falls back to the
        # 28th rather than 1 March, so the band still ends inside the month
        # the reader is looking at.
        return date.replace(year=date.year + years, day=28)


def _add_months(date: datetime, months: int) -> datetime:
    """`date` advanced by whole months, clamped to the target month's length.

    Written out rather than `timedelta(days=30)`, which drifts: a MONTH-
    precision February would end on 2 March and a MONTH-precision July on
    31 July, so two bars that should tile the calendar would overlap in one
    place and leave a gap in another.
    """
    zero_based = date.month - 1 + months
    year = date.year + zero_based // 12
    month = zero_based % 12 + 1
    day = min(date.day, _days_in_month(year, month))
    return date.replace(year=year, month=month, day=day)


def _days_in_month(year: int, month: int) -> int:
    from calendar import monthrange

    return monthrange(year, month)[1]


def extent_bounds(extent: Any) -> tuple[datetime | None, datetime | None] | None:
    """`extent` as `(lower, upper)`, or `None` if it denotes no interval.

    `extent` types as `Any`, matching the convention `graph_reader.py` and
    `temporal_rendering.py` both use for redstring objects: this module reads
    a handful of attributes and does not depend on `TemporalExtent`'s shape
    beyond them, so it does not import the type.

    Either element of the pair may be `None`, meaning open in that direction.
    That is a positive claim rather than a gap: an `UncertaintyMarker.BEFORE`
    says the thing happened at some unbounded time prior, and a browser draws
    it running off the edge. The outer `None` -- no interval at all -- is the
    different case, and is reserved for an extent that is absent, carries no
    dates, or carries only a `sequence_position`.

    **Uncertainty markers other than `BEFORE`/`AFTER` widen nothing**, which
    is the counter-intuitive half and mirrors redstring's own documented
    reasoning: "circa 1850" is a claim about how confidently 1850 is known,
    not about which years it might have been. Widening it means inventing a
    margin nobody chose, after which every bar's width rests on that invented
    number. The marker is carried to the browser as a field and dressed there.
    """
    if extent is None:
        return None

    start = getattr(extent, "start_date", None)
    end = getattr(extent, "end_date", None)
    if start is None and end is None:
        # Covers the empty extent and the sequence-position-only one together:
        # ordering without dates is not a position on an axis.
        return None

    precision = getattr(extent, "precision", None)
    marker = getattr(getattr(extent, "uncertainty", None), "name", None)

    if marker == "BEFORE":
        # "before 1500" -- the upper bound is the date given, and there is no
        # lower one. Deliberately not widened: the date is the boundary of the
        # claim, not a value with a precision around it.
        return (None, start or end)
    if marker == "AFTER":
        return (start or end, None)

    lower = start if start is not None else end
    upper = end if end is not None else _widen_to_precision(lower, precision)
    return (lower, upper)
