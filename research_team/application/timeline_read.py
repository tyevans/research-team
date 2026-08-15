"""One project's dated entities, in time order, for drawing on an axis.

**A separate port rather than a method on `GraphReadPort`**, and the reason
outlives the file it came from: `GraphReadPort.whole` is bounded by
`MAX_GRAPH_NODES` and answers "draw me this graph", where this read is bounded
by *time* and pages the tenant looking for the dated minority.
`docs/design/temporal-edges-in-the-graph-view.md` made the same call when it
deferred this view, on the grounds that a read with a different cost profile
behind a method named for a different question is how a port stops describing
anything.

It follows `graph_read.py`'s conventions exactly: this application's own
frozen dataclasses, plain `str` ids, and no redstring type named above the
adapter -- so a redstring schema change stays an implementation detail
underneath this contract rather than a change to it.
"""

from dataclasses import dataclass
from typing import Protocol

#: How many bands one timeline hands back. A cap for the same reason
#: `MAX_GRAPH_NODES` is one: the response crosses a wire and is then laid out
#: as individual SVG rectangles, and both stop being free some way before a
#: mature project's dated-entity count does.
#:
#: Higher than `MAX_GRAPH_NODES` deliberately. A timeline degrades far more
#: gracefully than a force-directed graph -- 1,000 bars on an axis is dense
#: but still readable and still pans, where 1,000 nodes in a simulation is a
#: disc. The bound here is the browser's layout cost, not legibility.
MAX_TIMELINE_BANDS = 1_000


@dataclass(frozen=True)
class TimelineBand:
    """One dated entity, as something a browser can position and size."""

    entity_id: str
    name: str
    entity_type: str

    extent: str
    """What the document said, rendered for reading: "1815", "November 1923".

    Not redundant against `start`/`end` below, which are a *different*
    quantity. Those are the drawn interval, precision-widened, so a
    year-precision extent spans its year instead of sitting on its first
    instant. A view given only this text cannot lay anything out; a view given
    only the interval would label a bar "1815-01-01 - 1816-01-01" when the
    document said "1815".
    """

    start: str | None
    """ISO instant the band begins, or `None` for open below.

    `None` is not "unknown". It is an `UncertaintyMarker.BEFORE` -- a positive
    claim that the thing happened at some unbounded earlier time -- and a
    browser draws it running off the left edge. Nullable rather than defaulted
    to the axis minimum because an axis minimum computed from the data moves
    as the data changes, and the bar would appear to have a start that
    shifted.
    """

    end: str | None
    """ISO instant the band ends, or `None` for open above. See `start`."""

    precision: str
    """`DatePrecision`'s name -- YEAR, MONTH, DAY, HOUR, MINUTE."""

    uncertainty: str
    """`UncertaintyMarker`'s name -- EXACT, CIRCA, APPROXIMATE, INFERRED,
    BEFORE, AFTER.

    Carried rather than folded into the geometry because "circa 1850" and
    "1850" produce the *same* interval, by the deliberate decision recorded in
    `temporal_interval.py`. A reader who cannot tell those apart has been
    shown a certainty the extraction never claimed, so this is the field the
    dressing depends on rather than decoration.
    """


@dataclass(frozen=True)
class Timeline:
    """A project's dated entities in time order, and what is missing from it."""

    bands: tuple[TimelineBand, ...]

    undated_count: int
    """Entities in this project carrying no drawable extent.

    Not an optional nicety. Most entities in a real graph are not events, so a
    timeline is by nature a view of a minority of the corpus -- and one
    showing 40 bands with no denominator reads as "this project contains 40
    things". Same convention as `Graph.truncated`: a view missing data says
    so, because absent data is invisible precisely because it is absent.
    """

    truncated: bool
    """Whether the band cap cut this short. See `MAX_TIMELINE_BANDS`.

    Separate from `undated_count` rather than added into it: an undated entity
    was never going to be drawn, and a capped one was. Folding them would tell
    a reader to look for bars that are missing for two unrelated reasons.
    """


class TimelineReadPort(Protocol):
    """One project's dated entities, ordered by when they happened.

    Bound to a project at construction, the same way `GraphReadPort`'s
    implementation is and for the same reason: the project a caller can read
    is fixed by which reader it was handed, never by a parameter a caller
    passes.
    """

    async def timeline(
        self,
        *,
        entity_type: str | None = None,
        limit: int = MAX_TIMELINE_BANDS,
    ) -> Timeline:
        """This project's dated entities, ascending by when they begin.

        `limit` is clamped inside the implementation rather than trusted, for
        the reason `MAX_NEIGHBORHOOD_DEPTH` is clamped inside `neighborhood`:
        a route is not the last thing that can call a port.
        """
        ...
