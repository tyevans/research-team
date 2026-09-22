"""Interaction log metrics, constants, and summary models.

Extracted from `interaction_reader.py` to isolate statistical models, Levenshtein
distance logic, and Pydantic page/summary schemas from database query operations.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel

if TYPE_CHECKING:
    from research_team.infrastructure.persistence.interaction_log import InteractionEventRow

REPEAT_SEARCH_MAX_DISTANCE_RATIO = 0.3
"""How different two consecutive searches may be and still count as a repeat.

Levenshtein distance over the normalised text, divided by the longer of the
two lengths -- so 0.3 means "up to a third of the characters changed". A
reformulation like `roman senate` -> `the roman senate` scores 0.25 and counts;
`roman senate` -> `carthage` scores 1.0 and does not.

**A heuristic, and never a measurement.** There is no corpus of real searches
to tune this against -- the log is what would produce one -- so the number it
produces is a pointer to a stream worth reading by eye, not a friction rate.
Reasoned, not measured. Revisit once the log holds real searches: if a
plausible reformulation scores above this, the count is missing the signal it
exists for.
"""

VIEW_DWELL_PERCENTILE = 0.9
"""The `p90` in `by_view`, by nearest-rank rather than by interpolation.

Nearest-rank returns a dwell that some view exit actually had, which is what
makes the number checkable against the feed below it; an interpolated
percentile returns a duration nobody experienced.
"""

__all__ = [
    "REPEAT_SEARCH_MAX_DISTANCE_RATIO",
    "VIEW_DWELL_PERCENTILE",
    "ApprovalSummary",
    "BrowserSessionPage",
    "BrowserSessionRow",
    "EmptyResultPlace",
    "FrictionSummary",
    "InteractionEventPage",
    "InteractionLogHealth",
    "InteractionSummary",
    "ViewDwell",
    "_edit_distance",
    "_is_repeat_search",
    "_median",
    "_normalised_query",
    "_parse_timestamp",
    "_percentile",
    "_timestamp_sql",
]


def _normalised_query(text: str) -> str:
    """Lowercased, whitespace collapsed. The spec's definition, in one place."""
    return " ".join(text.lower().split())


def _edit_distance(left: str, right: str) -> int:
    """Levenshtein, two rows rather than a full matrix.

    Written out rather than taken from a dependency: it is used on one pair of
    bounded strings (`QUERY_TEXT_MAX_LENGTH`) per search, and a library for it
    would be a dependency added for eleven lines.
    """
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _is_repeat_search(previous: str, current: str) -> bool:
    """Whether `current` is a near-repeat of `previous`, both already
    normalised."""
    longest = max(len(previous), len(current))
    if longest == 0:
        return True
    return _edit_distance(previous, current) / longest <= REPEAT_SEARCH_MAX_DISTANCE_RATIO


def _median(values: Sequence[int]) -> int | None:
    """The middle value, or None over nothing.

    None rather than 0: a view nobody exited and a view exited instantly are
    different facts, and 0 makes them one.
    """
    if not values:
        return None
    return int(statistics.median(values))


def _percentile(values: Sequence[int], fraction: float) -> int | None:
    """Nearest-rank percentile -- see `VIEW_DWELL_PERCENTILE`."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


class InteractionLogHealth(BaseModel):
    """Whether the instrument is working, and how much it has seen.

    Carries neither `collecting` nor `failures`: the first is a fact about the
    recorder's environment variable and belongs to the route, the second comes
    from the runner's DLQ. A reader that reported either would be guessing at
    something it cannot see.
    """

    total: int
    first_at: datetime | None
    last_at: datetime | None
    kinds: dict[str, int]
    """Every kind in `INTERACTION_EVENTS`, zeros included, plus any kind found
    in the table that the vocabulary no longer names. A dict built from what
    the table happens to hold makes "never emitted" and "does not exist" look
    identical, which is the defect this shape exists to prevent."""
    install_count: int
    session_count: int


class BrowserSessionRow(BaseModel):
    """One browser session, summarised."""

    browser_session_id: UUID
    install_id: UUID
    started_at: datetime | None
    ended_at: datetime | None
    event_count: int
    """What arrived. Beside `max_seq` on purpose: `seq` is the browser's own
    counter, so the two disagree exactly when delivery lost something."""
    max_seq: int
    views: list[str]
    project_ids: list[UUID]
    kinds: dict[str, int]


class BrowserSessionPage(BaseModel):
    sessions: list[BrowserSessionRow]
    total: int


class InteractionEventPage(BaseModel):
    events: list[InteractionEventRow]
    total: int
    """The count under the same filters, never the page length. A reader who
    cannot tell 200-of-200 from 200-of-9000 cannot tell a filter that found
    everything from one that hit the cap."""
    limit: int
    offset: int


class ViewDwell(BaseModel):
    """One view's traffic and how long people stayed."""

    view: str
    entries: int
    """`ViewEntered` for this view."""
    exits: int
    """`ViewExited` for this view. Reported apart from `entries` because the
    difference is the count of views left by a route the page-hide flush did
    not catch."""
    dwell_ms_median: int | None
    dwell_ms_p90: int | None
    hidden_ms_median: int | None
    """Reported beside dwell and never subtracted from it -- `ViewExited`'s own
    docstring gives the reason, and it holds here: the consumer chooses."""


class EmptyResultPlace(BaseModel):
    where: str
    count: int


class FrictionSummary(BaseModel):
    """The signals the vocabulary was built to carry."""

    undone: int
    retried: int
    empty_results: int
    empty_by_where: list[EmptyResultPlace]
    repeat_searches: int
    """Searches within `REPEAT_SEARCH_MAX_DISTANCE_RATIO` of the immediately
    previous search in the same browser session. A heuristic pointer to a
    stream worth reading, never a measurement -- see the constant."""


class ApprovalSummary(BaseModel):
    """The deliberation split `docs/direction.md` §3 turns on."""

    total: int
    expanded: int
    """`expanded_details == true`. **The name overstates it**, exactly as that
    field's own docstring says: it counts readers who opened Edit or Respond,
    so a careful reader who deliberates and then presses plain Approve records
    `false`. Read it as a floor on deliberation, never as a count of who read
    carefully. The caveat is repeated here rather than renamed away, because
    every plausible rename carries the same ambiguity one word further out."""
    median_latency_ms: int | None
    median_latency_ms_expanded: int | None
    median_latency_ms_plain: int | None
    by_decision: dict[str, int]


class InteractionSummary(BaseModel):
    by_kind: dict[str, int]
    by_view: list[ViewDwell]
    friction: FrictionSummary
    approvals: ApprovalSummary


def _timestamp_sql(column: str) -> str:
    """`column`, normalised to a comparable UTC string.

    Both sides of every time comparison go through this, because the stored
    text is not one format: pydantic writes `occurred_at` with a `Z` and the
    envelope columns with `+00:00`, and a raw `>=` between the two orders
    `...39.9Z` before `...39Z` -- `.` sorts below `Z`, so a bound on a whole
    second silently drops the rows within it.

    The cost is that `idx_interaction_events_kind`'s `occurred_at` half cannot
    serve a range scan. Accepted: the spec's own retention note puts this table
    years away from a million rows, and every read here already scans for a
    filter no index covers.
    """
    return f"strftime('%Y-%m-%dT%H:%M:%f', {column})"


def _parse_timestamp(value: str | None) -> datetime | None:
    """Back from `_timestamp_sql`'s form, which carries no offset of its own."""
    if value is None:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=UTC)
