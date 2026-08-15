# Timeline View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Timeline tab beside the Graph tab on the project page, drawing the project's dated entities as bars on a horizontal time axis, in lanes grouped by entity type.

**Architecture:** No new persistence. `ProjectGraphs.open(project_id)` already returns a redstring `GraphStore`, and `GraphStore` satisfies redstring's `EntityReader` protocol, which is exactly what `TemporalQuery` takes — so the timeline is a second read over the store the graph view already opens. A new port (`timeline_read.py`), a new adapter (`timeline_reader.py`), a local interval module (`temporal_interval.py`, because redstring's own interval helpers are behind a forbidden import path), one route, and a new material tab on the frontend mirroring `GraphPane`.

**Tech Stack:** Python 3.12 / FastAPI / redstring 0.8.0 / pytest. React 19 / TypeScript / zustand / zod / wouter (hash routing) / Tailwind v4 / vitest (jsdom + Playwright-chromium browser mode).

**Spec:** `docs/superpowers/specs/2026-08-14-timeline-view-design.md`

## Global Constraints

- **Four CI gates, all required.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `cd frontend && npm run verify`. The two ruff commands run over the **whole repository**, not the files you touched. `npm run verify` covers no Python; `pytest` covers no formatting.
- **A fifth command that is not a gate but is required by this plan:** `cd frontend && npm run test:browser`. Task 11 exists solely to run it. jsdom lays nothing out, so bar geometry cannot be asserted anywhere else.
- **Never run two `vitest` processes at once.** Concurrent runs fail spuriously with a coverage temp-file error naming nothing about the real cause. If a frontend test fails, re-run it alone before investigating.
- **Do not import anything under `redstring.domain.`** `tests/test_architecture.py:156` forbids it and will fail. This applies especially to `redstring.domain.interval` (`bounds`, `widen`), which is the obvious shortcut for Task 1 and is not available.
- **Only import redstring names present in `redstring.__all__`.** Confirmed present and usable: `TemporalQuery`, `TemporalExtent`, `TemporalRelation`, `DatePrecision`, `UncertaintyMarker`, `Bounds`, `Entity`, `EntityId`, `TenantId`, `InMemoryGraphStore`. Confirmed **absent**: `render_temporal`, `bounds`, `widen`, `infer_relations` helpers beyond `infer_relations` itself.
- **`border-solid` beside one directional width draws three unwanted sides.** This build imports no Tailwind preflight. Pair `border-solid` with `border-0` plus the directional width you actually want.
- **Overriding a `tokens.css` rule with a Tailwind utility does not work** when the rule is unlayered (e.g. the global `:focus-visible`). Use the `.lay-ring-inward` class in `layout.css` for inward focus rings, never a `focus-visible:outline-offset-[…]` utility.
- **Comments explain why, not what.** State costs and trade-offs, name what a test would fail on, and say when something was measured rather than reasoned. Commit messages carry what was considered and rejected.
- **Prove every test red before trusting it green.** If a test would pass with the change reverted, say so in its docstring rather than leaving it as reassurance.
- **Work happens in the worktree** `/home/ty/workspace/research-team/.claude/worktrees/timeline-view` on branch `timeline-view`. All paths below are relative to it.

---

## File Structure

**Python — create:**
- `research_team/application/timeline_read.py` — the port: `TimelineBand`, `Timeline`, `TimelineReadPort`, `MAX_TIMELINE_BANDS`.
- `research_team/infrastructure/knowledge/temporal_interval.py` — `extent_bounds(extent) -> tuple[datetime, datetime] | None`, precision widening and open bounds. The only module doing date arithmetic.
- `research_team/infrastructure/knowledge/timeline_reader.py` — `ProjectTimelineReader`, the adapter.
- `tests/infrastructure/test_temporal_interval.py`
- `tests/infrastructure/test_timeline_reader.py`
- `tests/interfaces/test_timeline_route.py`

**Python — modify:**
- `research_team/interfaces/web/presenters.py` — add `band_view`, `timeline_view`.
- `research_team/interfaces/web/app.py` — add `_timeline_reader` and the route.

**TypeScript — create:**
- `frontend/src/domain/knowledge/timeline.ts` — `TimelineBand`, `Timeline`, `emptyTimeline`, `laneRows` (the row-packing fold; pure, so its correctness is testable without a DOM).
- `frontend/src/infrastructure/http/timeline-repository.ts` — `HttpTimelineRepository`.
- `frontend/src/application/research/timeline-store.ts` — `createTimelineStore`.
- `frontend/src/presentation/research/TimelinePane.tsx` — container + exported `TimelineBrowser`.
- `frontend/src/presentation/research/TimelineCanvas.tsx` — lazy-loaded SVG drawing.
- `frontend/src/domain/knowledge/timeline.test.ts`
- `frontend/src/presentation/research/TimelinePane.test.tsx`
- `frontend/src/presentation/research/timeline-geometry.browser.test.tsx`

**TypeScript — modify:**
- `frontend/src/infrastructure/http/dto.ts` — `timelineBandDto`, `timelineDto`.
- `frontend/src/infrastructure/http/mappers.ts` — `toTimelineBand`, `toTimeline`.
- `frontend/src/application/ports/repositories.ts` — `TimelineRepository`; `GraphDetail`'s consumer contract is unchanged.
- `frontend/src/app/container.ts` — `timelines: new HttpTimelineRepository(http)`.
- `frontend/src/presentation/routing/routes.ts` — `FACETS` gains `'timeline'`.
- `frontend/src/presentation/project/ProjectView.tsx` — `regionOf`, `MaterialFacet`, `MATERIAL_TABS`, the new `TabPanel`.
- `frontend/src/presentation/research/GraphDetail.tsx` — optional `onRemove`.

---

## Task 1: `temporal_interval.py` — extents to drawable intervals

This is the module carrying the design's risk. It exists because `redstring.domain.interval`'s `bounds` and `widen` are behind an import path `tests/test_architecture.py` forbids outright.

**Files:**
- Create: `research_team/infrastructure/knowledge/temporal_interval.py`
- Test: `tests/infrastructure/test_temporal_interval.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `extent_bounds(extent: Any) -> tuple[datetime | None, datetime | None] | None`. Returns `None` when the extent is undated (absent, empty, or carrying only a `sequence_position`). Otherwise a `(lower, upper)` pair where either element may be `None` meaning "open in that direction".

- [ ] **Step 1: Write the failing tests**

Create `tests/infrastructure/test_temporal_interval.py`:

```python
"""`extent_bounds`: the arithmetic redstring would have done and may not.

`redstring.domain.interval.bounds` and `widen` are exactly this function, and
`tests/test_architecture.py` forbids importing anything under
`redstring.domain.`. So this is a reimplementation against `TemporalExtent`'s
public fields, and these tests are the only thing standing between it and a
timeline that draws every year-precision entity as a hairline on 1 January.
"""

from datetime import datetime

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
        start_date=datetime(1815, 1, 1),
        precision=DatePrecision.YEAR,
    )

    assert extent_bounds(extent) == (datetime(1815, 1, 1), datetime(1816, 1, 1))


def test_a_month_precision_extent_spans_its_month_across_a_year_boundary():
    """December widens into the next January, not into month 13.

    The naive widening is `month + 1`, which raises for December. Chosen as
    the fixture month for exactly that reason -- a test using June would pass
    against the broken arithmetic.
    """
    extent = TemporalExtent(
        start_date=datetime(1923, 12, 1),
        precision=DatePrecision.MONTH,
    )

    assert extent_bounds(extent) == (datetime(1923, 12, 1), datetime(1924, 1, 1))


def test_a_day_precision_extent_spans_its_day():
    extent = TemporalExtent(
        start_date=datetime(1969, 7, 20),
        precision=DatePrecision.DAY,
    )

    assert extent_bounds(extent) == (datetime(1969, 7, 20), datetime(1969, 7, 21))


def test_an_explicit_end_date_is_not_widened():
    """A range already says where it stops.

    Widening an extent that carries its own `end_date` would push every range
    a year past what the document said. The widening is for the *absent* end
    only.
    """
    extent = TemporalExtent(
        start_date=datetime(1990, 1, 1),
        end_date=datetime(1995, 1, 1),
        precision=DatePrecision.YEAR,
    )

    assert extent_bounds(extent) == (datetime(1990, 1, 1), datetime(1995, 1, 1))


def test_a_before_marker_opens_the_lower_bound_and_leaves_the_upper_closed():
    """`BEFORE` is a claim about unboundedness, not about margin.

    Asserted separately from `AFTER` below, because one test over "an open
    bound" passes against an implementation that opens whichever end it
    likes.
    """
    extent = TemporalExtent(
        start_date=datetime(1500, 1, 1),
        precision=DatePrecision.YEAR,
        uncertainty=UncertaintyMarker.BEFORE,
    )

    assert extent_bounds(extent) == (None, datetime(1500, 1, 1))


def test_an_after_marker_opens_the_upper_bound_and_leaves_the_lower_closed():
    extent = TemporalExtent(
        start_date=datetime(1500, 1, 1),
        precision=DatePrecision.YEAR,
        uncertainty=UncertaintyMarker.AFTER,
    )

    assert extent_bounds(extent) == (datetime(1500, 1, 1), None)


def test_circa_produces_exactly_the_same_interval_as_exact():
    """The intuitive choice is to widen `CIRCA`, and it is the wrong one.

    "circa 1850" is a claim about how confidently 1850 is known, not about
    which years it might have been. Widening means inventing a margin -- a
    decade? a century? -- after which every bar's width rests on a number
    nobody chose. The marker travels to the browser as a field instead, which
    `test_timeline_reader.py` pins.
    """
    dates = {"start_date": datetime(1850, 1, 1), "precision": DatePrecision.YEAR}

    circa = TemporalExtent(**dates, uncertainty=UncertaintyMarker.CIRCA)
    exact = TemporalExtent(**dates, uncertainty=UncertaintyMarker.EXACT)

    assert extent_bounds(circa) == extent_bounds(exact)


def test_approximate_and_inferred_also_widen_nothing():
    dates = {"start_date": datetime(1850, 1, 1), "precision": DatePrecision.YEAR}
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
        start_date=datetime(1969, 7, 20, 20, 17),
        precision=DatePrecision.MINUTE,
    )

    lower, upper = extent_bounds(extent)
    assert lower == datetime(1969, 7, 20, 20, 17)
    assert upper == datetime(1969, 7, 21, 20, 17)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/timeline-view
uv run pytest tests/infrastructure/test_temporal_interval.py -v
```

Expected: every test fails at collection with `ModuleNotFoundError: No module named 'research_team.infrastructure.knowledge.temporal_interval'`.

- [ ] **Step 3: Write the implementation**

Create `research_team/infrastructure/knowledge/temporal_interval.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/infrastructure/test_temporal_interval.py -v
```

Expected: 12 passed.

- [ ] **Step 5: Prove the load-bearing test red**

Temporarily change `_widen_to_precision`'s `YEAR` branch to `return start`, then:

```bash
uv run pytest tests/infrastructure/test_temporal_interval.py::test_a_year_precision_extent_spans_its_whole_year -v
```

Expected: FAIL. Restore the branch and re-run the file — 12 passed. If it stayed green, the test is evidence about the fixture rather than the code; fix the test before continuing.

- [ ] **Step 6: Run the Python gates and commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest tests/infrastructure/ -q
git add research_team/infrastructure/knowledge/temporal_interval.py tests/infrastructure/test_temporal_interval.py
git commit -m "Turn a temporal extent into an interval a browser can draw

redstring has this function twice over -- \`bounds\` and \`widen\` in
\`redstring.domain.interval\` -- and \`tests/test_architecture.py\` forbids
importing anything under \`redstring.domain.\`, because redstring's contract
is that a dotted path is internal and may change in a patch release. So it is
written here, the same way \`render_extent\` was written rather than reaching
for \`render_temporal\`.

The decision worth reviewing is that a band is the precision-widened
interval. A YEAR-precision extent is \`1815-01-01\` with no end, and drawn
literally that is a zero-width mark on New Year's Day claiming a precision the
extraction never made -- "1815" landing exactly where "1 January 1815" lands,
at the same size.

Rejected: widening CIRCA and APPROXIMATE. It is the intuitive reading and it
means inventing a margin, after which every bar's width rests on a number
nobody chose. The marker travels to the browser as a field instead.

Month arithmetic is written out rather than \`timedelta(days=30)\`, which
drifts enough that two adjacent month bars would overlap in one place and
leave a gap in another.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: The `timeline_read` port

**Files:**
- Create: `research_team/application/timeline_read.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `MAX_TIMELINE_BANDS: int`, `TimelineBand` (frozen dataclass: `entity_id: str`, `name: str`, `entity_type: str`, `extent: str`, `start: str | None`, `end: str | None`, `precision: str`, `uncertainty: str`), `Timeline` (frozen dataclass: `bands: tuple[TimelineBand, ...]`, `undated_count: int`, `truncated: bool`), `TimelineReadPort` Protocol with `async def timeline(self, *, entity_type: str | None = None, limit: int = MAX_TIMELINE_BANDS) -> Timeline`.

- [ ] **Step 1: Write the module**

There is no test in this task: it declares dataclasses and a Protocol with no behaviour, and a test asserting that a frozen dataclass has the fields it was just given fields is a test of the language. Task 3 is where these are exercised.

Create `research_team/application/timeline_read.py`:

```python
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
```

- [ ] **Step 2: Verify it imports and the gates pass**

```bash
uv run python -c "from research_team.application.timeline_read import Timeline, TimelineBand, TimelineReadPort, MAX_TIMELINE_BANDS; print(MAX_TIMELINE_BANDS)"
uv run ruff check . && uv run ruff format --check .
```

Expected: prints `1000`, then both ruff commands clean.

- [ ] **Step 3: Commit**

```bash
git add research_team/application/timeline_read.py
git commit -m "Declare the port a timeline is read through

A separate port rather than a method on \`GraphReadPort\`, which is the call
\`docs/design/temporal-edges-in-the-graph-view.md\` made when it deferred this
view: \`whole\` is bounded by node count and answers 'draw me this graph',
where a timeline is bounded by time and pages the tenant for the dated
minority. A read with a different cost profile behind a method named for a
different question is how a port stops describing anything.

\`extent\` and the \`start\`/\`end\` pair are both present and are not
redundant -- one is what the document said, the other is the widened interval
that gets drawn. A band carrying only the second would be labelled
'1815-01-01 - 1816-01-01' for a document that said '1815'.

\`MAX_TIMELINE_BANDS\` is 1,000 against \`MAX_GRAPH_NODES\`' 500, deliberately.
A timeline degrades gracefully where a force-directed graph does not: a
thousand bars on an axis is dense and still pans, a thousand nodes in a
simulation is a disc. The bound here is layout cost, not legibility.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `ProjectTimelineReader` — the adapter

**Files:**
- Create: `research_team/infrastructure/knowledge/timeline_reader.py`
- Test: `tests/infrastructure/test_timeline_reader.py`

**Interfaces:**
- Consumes: `extent_bounds` (Task 1); `Timeline`, `TimelineBand`, `MAX_TIMELINE_BANDS` (Task 2); `render_extent` from `research_team.infrastructure.knowledge.temporal_rendering`.
- Produces: `ProjectTimelineReader(*, project_id: UUID, store: Any)` with `async def timeline(self, *, entity_type=None, limit=MAX_TIMELINE_BANDS) -> Timeline`.

- [ ] **Step 1: Write the failing tests**

Create `tests/infrastructure/test_timeline_reader.py`:

```python
"""`ProjectTimelineReader` over an in-memory store.

Fixtures build entities directly rather than running extraction: the reader's
job is turning stored entities into bands, and an extraction step in the way
would mean a failure here could be a failure there.
"""

from datetime import datetime
from uuid import uuid4

import pytest
from redstring import (
    DatePrecision,
    Entity,
    InMemoryGraphStore,
    TemporalExtent,
    UncertaintyMarker,
)

from research_team.infrastructure.knowledge.timeline_reader import ProjectTimelineReader


def _entity(name: str, *, entity_type: str = "event", temporal=None) -> Entity:
    return Entity(
        id=uuid4(),
        name=name,
        entity_type=entity_type,
        temporal=temporal,
    )


def _year(year: int) -> TemporalExtent:
    return TemporalExtent(start_date=datetime(year, 1, 1), precision=DatePrecision.YEAR)


async def _reader_over(entities: list[Entity]) -> ProjectTimelineReader:
    project_id = uuid4()
    store = InMemoryGraphStore()
    if entities:
        await store.upsert_entities(entities, project_id)
    return ProjectTimelineReader(project_id=project_id, store=store)


@pytest.mark.asyncio
async def test_a_dated_entity_becomes_a_band_carrying_both_its_text_and_its_interval():
    """The two quantities `TimelineBand` keeps apart.

    `extent` is what the document said; `start`/`end` is what gets drawn.
    Asserted together because an implementation that filled one from the other
    would satisfy either assertion alone.
    """
    reader = await _reader_over([_entity("Waterloo", temporal=_year(1815))])

    timeline = await reader.timeline()

    (band,) = timeline.bands
    assert band.name == "Waterloo"
    assert band.extent == "1815"
    assert band.start == "1815-01-01T00:00:00"
    assert band.end == "1816-01-01T00:00:00"


@pytest.mark.asyncio
async def test_undated_entities_are_absent_from_the_bands_and_counted_instead():
    """The ordinary case, not the edge case.

    Most entities in a real graph are not events. A timeline showing two bands
    with no denominator reads as "this project contains two things".
    """
    reader = await _reader_over(
        [
            _entity("Waterloo", temporal=_year(1815)),
            _entity("Trafalgar", temporal=_year(1805)),
            _entity("Cavalry", temporal=None),
            _entity("Artillery", temporal=TemporalExtent()),
            _entity("Third act", temporal=TemporalExtent(sequence_position=3)),
        ]
    )

    timeline = await reader.timeline()

    assert [band.name for band in timeline.bands] == ["Trafalgar", "Waterloo"]
    assert timeline.undated_count == 3


@pytest.mark.asyncio
async def test_bands_are_ordered_by_when_they_begin():
    reader = await _reader_over(
        [
            _entity("Third", temporal=_year(1900)),
            _entity("First", temporal=_year(1700)),
            _entity("Second", temporal=_year(1800)),
        ]
    )

    timeline = await reader.timeline()

    assert [band.name for band in timeline.bands] == ["First", "Second", "Third"]


@pytest.mark.asyncio
async def test_circa_and_exact_draw_alike_and_read_differently():
    """Both halves, because either alone permits a wrong implementation.

    The intervals matching pins the decision not to invent a margin. The
    markers differing pins that the decision is still visible to a reader --
    an implementation that dropped `uncertainty` would pass the first half.
    """
    reader = await _reader_over(
        [
            _entity(
                "Circa",
                temporal=TemporalExtent(
                    start_date=datetime(1850, 1, 1),
                    precision=DatePrecision.YEAR,
                    uncertainty=UncertaintyMarker.CIRCA,
                ),
            ),
            _entity(
                "Exact",
                temporal=TemporalExtent(
                    start_date=datetime(1850, 1, 1),
                    precision=DatePrecision.YEAR,
                    uncertainty=UncertaintyMarker.EXACT,
                ),
            ),
        ]
    )

    timeline = await reader.timeline()

    by_name = {band.name: band for band in timeline.bands}
    assert (by_name["Circa"].start, by_name["Circa"].end) == (
        by_name["Exact"].start,
        by_name["Exact"].end,
    )
    assert by_name["Circa"].uncertainty == "CIRCA"
    assert by_name["Exact"].uncertainty == "EXACT"


@pytest.mark.asyncio
async def test_a_before_marker_leaves_the_start_open():
    reader = await _reader_over(
        [
            _entity(
                "Ancient",
                temporal=TemporalExtent(
                    start_date=datetime(1500, 1, 1),
                    precision=DatePrecision.YEAR,
                    uncertainty=UncertaintyMarker.BEFORE,
                ),
            )
        ]
    )

    (band,) = (await reader.timeline()).bands

    assert band.start is None
    assert band.end == "1500-01-01T00:00:00"


@pytest.mark.asyncio
async def test_entity_type_restricts_which_entities_are_banded():
    reader = await _reader_over(
        [
            _entity("A battle", entity_type="event", temporal=_year(1815)),
            _entity("A general", entity_type="person", temporal=_year(1815)),
        ]
    )

    timeline = await reader.timeline(entity_type="event")

    assert [band.name for band in timeline.bands] == ["A battle"]


@pytest.mark.asyncio
async def test_the_cap_sets_truncated_and_a_graph_at_exactly_the_cap_does_not():
    """Both directions, because the off-by-one is the whole risk.

    A drawing missing bars looks exactly like a drawing with none to miss, and
    a complete drawing wrongly flagged sends a reader looking for entities
    that are all there.
    """
    reader = await _reader_over([_entity(f"Event {n}", temporal=_year(1800 + n)) for n in range(5)])

    assert (await reader.timeline(limit=3)).truncated is True
    assert (await reader.timeline(limit=5)).truncated is False


@pytest.mark.asyncio
async def test_an_absorbed_entity_does_not_draw_beside_the_one_that_absorbed_it():
    """A merge is not a delete, and on a timeline that shows as corroboration.

    `find_entities` returns absorbed entities deliberately -- the row is what
    `undo_merge` restores. Two bars with identical extents and near-identical
    names read as two sources agreeing, which is the opposite of what one
    entity counted twice means.
    """
    canonical = _entity("Waterloo", temporal=_year(1815))
    absorbed = _entity("Battle of Waterloo", temporal=_year(1815))
    project_id = uuid4()
    store = InMemoryGraphStore()
    await store.upsert_entities([canonical, absorbed], project_id)
    await store.upsert_alias(absorbed.id, canonical.id, project_id)
    reader = ProjectTimelineReader(project_id=project_id, store=store)

    timeline = await reader.timeline()

    assert [band.name for band in timeline.bands] == ["Waterloo"]


@pytest.mark.asyncio
async def test_an_empty_project_is_an_empty_timeline_rather_than_an_error():
    reader = await _reader_over([])

    timeline = await reader.timeline()

    assert timeline.bands == ()
    assert timeline.undated_count == 0
    assert timeline.truncated is False
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/infrastructure/test_timeline_reader.py -v
```

Expected: collection error, `No module named 'research_team.infrastructure.knowledge.timeline_reader'`.

If `Entity(...)` or `upsert_alias(...)` raises a signature error instead, fix the fixture against the real redstring 0.8.0 signatures — check with `uv run python -c "import redstring, inspect; print(redstring.Entity.model_fields.keys()); print(inspect.signature(redstring.GraphStore.upsert_alias))"` — and keep the assertions as written.

- [ ] **Step 3: Write the implementation**

Create `research_team/infrastructure/knowledge/timeline_reader.py`:

```python
"""`ProjectTimelineReader`: `TimelineReadPort` over a live redstring `GraphStore`.

The third module importing redstring's own types, alongside `graph_reader.py`
and `redstring_adapter.py`, and for the same reason: everything above
`TimelineReadPort` speaks this application's `TimelineBand`, so the
translation happens here or nowhere.

**No read model, and that is worth stating because the surrounding code argues
otherwise.** `CorpusStore`, `TopicRow` and `CheckOutcomeRow` are all SQLite
read models fed by projections, so the reflex on meeting a new read is to add
a fourth. The graph read path is this repository's exception: it computes
everything per request from a store folded out of the knowledge event log, and
a timeline is a second read of that same kind. `GraphStore` satisfies
redstring's `EntityReader` protocol -- verified by introspection, all six
methods present -- and `TemporalQuery` takes exactly an `EntityReader`, so this
reads the store `ProjectGraphs` already opened for the graph view.
"""

from typing import Any
from uuid import UUID

from eventsource.domain.tenant_context import tenant_scope
from redstring import TemporalQuery

from research_team.application.timeline_read import (
    MAX_TIMELINE_BANDS,
    Timeline,
    TimelineBand,
)
from research_team.infrastructure.knowledge.temporal_interval import extent_bounds
from research_team.infrastructure.knowledge.temporal_rendering import render_extent


def _to_band(entity: Any) -> TimelineBand | None:
    """`entity` as a band, or `None` when it has nothing to draw.

    Returns `None` rather than raising for an undated entity because undated
    is the *ordinary* case -- most entities in a real graph are not events --
    and the caller counts them rather than treating them as a failure.
    """
    bounds = extent_bounds(entity.temporal)
    if bounds is None:
        return None
    lower, upper = bounds
    return TimelineBand(
        entity_id=str(entity.id),
        name=entity.name,
        entity_type=entity.entity_type,
        # `or ""` rather than letting `None` through: `extent_bounds` already
        # said this entity is dated, so a `None` here would mean the two
        # modules disagree about what "undated" is -- and an empty label is a
        # visible defect where a `None` in a `str` field is a type error at
        # some distance from its cause.
        extent=render_extent(entity.temporal) or "",
        start=lower.isoformat() if lower is not None else None,
        end=upper.isoformat() if upper is not None else None,
        precision=getattr(getattr(entity.temporal, "precision", None), "name", ""),
        uncertainty=getattr(getattr(entity.temporal, "uncertainty", None), "name", ""),
    )


class ProjectTimelineReader:
    """`TimelineReadPort` for one project, over the store `ProjectGraphs` opened.

    Bound to a `project_id` at construction, the shape `ProjectGraphReader`
    uses: the project a caller can read is fixed by which reader it was
    handed, not by anything passed per call.
    """

    def __init__(self, *, project_id: UUID, store: Any) -> None:
        self._project_id = project_id
        self._store = store

    async def _without_aliases(self, entities: list[Any]) -> list[Any]:
        """`entities` with everything merged away removed.

        The same filter `ProjectGraphReader` applies, needed here for a
        sharper reason. On a canvas an absorbed entity draws as an isolated
        node with no edges, which reads as a duplicate. On a timeline it draws
        as a *second bar with an identical extent*, which reads as two sources
        agreeing -- corroboration rather than double-counting, and a reader
        has no way to tell.

        `==`, not `is`: `resolve_entity_ids` may hand back a rebuilt `UUID`
        for an id that is not an alias, and `is` would filter out every entity
        and draw an empty timeline. redstring's own `CandidateFinder` carries
        the same warning over the same call, having been bitten by it.
        """
        if not entities:
            return []
        canonical = await self._store.resolve_entity_ids(
            [entity.id for entity in entities], self._project_id
        )
        return [entity for entity in entities if canonical[entity.id] == entity.id]

    async def timeline(
        self,
        *,
        entity_type: str | None = None,
        limit: int = MAX_TIMELINE_BANDS,
    ) -> Timeline:
        """This project's dated entities, ascending by when they begin.

        **Two passes over the tenant, and the second is the price of
        `undated_count`.** `TemporalQuery.timeline` returns only dated
        entities, so the denominator has to come from somewhere else --
        `find_entities` over the same store. This is the same order of cost
        `ProjectGraphReader.whole` already pays on every graph open, so it is
        not a new class of expense, but it is double a single read and it is
        paid on a tab a reader may return to repeatedly.

        Deliberately uncached. A cache needs an invalidation, the knowledge
        log already emits frames that would have to drive one, and building
        that before a measurement says which half is slow would be guessing at
        which one to fix.

        Ordering comes from the library rather than being redone here.
        redstring promises start, then end, then id, and documents why the id
        tiebreak exists: two entities routinely carry the same extent -- a
        document naming three things that happened in 1066 -- and without it
        their order would depend on what the store handed back, which the port
        does not promise to keep stable across adapters. Re-sorting here would
        throw that away and reintroduce the instability at the next adapter
        change.
        """
        capped = min(limit, MAX_TIMELINE_BANDS)
        async with tenant_scope(self._project_id):
            dated = await TemporalQuery(self._store).timeline(
                self._project_id, entity_type=entity_type
            )
            dated = await self._without_aliases(list(dated))
            everything = await self._store.find_entities(
                self._project_id, entity_type=entity_type
            )
            everything = await self._without_aliases(list(everything))

        bands = [band for band in map(_to_band, dated) if band is not None]
        # Counted against the whole entity set rather than by subtracting the
        # band count from it: `TemporalQuery` and `extent_bounds` decide
        # "dated" separately, and a subtraction would silently absorb any
        # disagreement between them into the undated figure.
        undated_count = len(everything) - len(bands)
        return Timeline(
            bands=tuple(bands[:capped]),
            # Never negative, even if the two "dated" judgements above ever
            # diverge: a negative count on screen is a worse failure than a
            # zero, and this is the one place it could reach a reader.
            undated_count=max(undated_count, 0),
            truncated=len(bands) > capped,
        )
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/infrastructure/test_timeline_reader.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Prove a test red**

Temporarily delete the `dated = await self._without_aliases(list(dated))` line, then run `test_an_absorbed_entity_does_not_draw_beside_the_one_that_absorbed_it`. Expected: FAIL. Restore and re-run the file.

- [ ] **Step 6: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest tests/ -q
git add research_team/infrastructure/knowledge/timeline_reader.py tests/infrastructure/test_timeline_reader.py
git commit -m "Read a project's dated entities as an ordered set of bands

No read model, which the surrounding code argues against: CorpusStore,
TopicRow and CheckOutcomeRow are all SQLite read models fed by projections, so
the reflex on meeting a new read is to add a fourth. The graph read path is
the exception here -- it computes per request from a store folded out of the
knowledge log -- and a timeline is a second read of that same kind.
\`GraphStore\` satisfies redstring's \`EntityReader\` protocol, verified by
introspection, and \`TemporalQuery\` takes exactly that.

The alias filter is carried over from \`ProjectGraphReader\` for a sharper
reason than it has there. On a canvas an absorbed entity draws as an isolated
node, which reads as a duplicate. On a timeline it draws as a second bar with
an identical extent, which reads as two sources agreeing.

Ordering is the library's, not redone here: redstring promises start, end,
then id, and the id tiebreak exists because a document naming three things
that happened in 1066 would otherwise order by whatever the store returned.

Cost, stated rather than designed around: two linear passes over the tenant
per open, the second one buying \`undated_count\`, which
\`TemporalQuery.timeline\` cannot supply because it returns only dated
entities. Same order as \`ProjectGraphReader.whole\`, double a single read.
Deliberately uncached -- a cache needs an invalidation, and building one
before a measurement says which half is slow is guessing.

\`undated_count\` is computed against the full entity set rather than by
subtraction, so a disagreement between \`TemporalQuery\` and \`extent_bounds\`
about what counts as dated cannot be silently absorbed into it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: The presenter and the route

**Files:**
- Modify: `research_team/interfaces/web/presenters.py`
- Modify: `research_team/interfaces/web/app.py`
- Test: `tests/interfaces/test_timeline_route.py`

**Interfaces:**
- Consumes: `Timeline`, `TimelineBand` (Task 2); `ProjectTimelineReader` (Task 3).
- Produces: `band_view(band: TimelineBand) -> dict[str, Any]`, `timeline_view(timeline: Timeline) -> dict[str, Any]`, and `GET /api/projects/{project_id}/timeline` returning `{"bands": [...], "undated_count": int, "truncated": bool}` where each band is `{"entity_id", "name", "entity_type", "extent", "start", "end", "precision", "uncertainty"}`.

- [ ] **Step 1: Write the failing route test**

Look first at an existing route test for the app fixture this suite uses:

```bash
ls tests/interfaces/
grep -rn "graph" tests/interfaces/ | head -20
```

Create `tests/interfaces/test_timeline_route.py`, following whatever client fixture the neighbouring graph route tests use (the assertions below are the contract; the fixture wiring must match the file you find):

```python
"""`/api/projects/{id}/timeline`: the shape the browser's zod DTO parses.

The route is thin, so these tests are about the envelope rather than the
arithmetic -- `test_timeline_reader.py` owns that. What can only break here is
the field names, which the frontend parses by exact key.
"""

import pytest


@pytest.mark.asyncio
async def test_the_timeline_route_returns_bands_with_the_keys_the_browser_parses(
    client, project_with_dated_entities
):
    """Field names, asserted literally.

    `dto.ts` parses these by exact key and a rename here fails as a
    `ContractError` in the browser with nothing failing in Python. Written out
    rather than compared against a constant so the two spellings are
    independent.
    """
    response = await client.get(f"/api/projects/{project_with_dated_entities}/timeline")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"bands", "undated_count", "truncated"}
    assert set(body["bands"][0]) == {
        "entity_id",
        "name",
        "entity_type",
        "extent",
        "start",
        "end",
        "precision",
        "uncertainty",
    }


@pytest.mark.asyncio
async def test_an_unknown_project_is_a_404(client):
    from uuid import uuid4

    response = await client.get(f"/api/projects/{uuid4()}/timeline")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_limit_past_the_cap_is_clamped_rather_than_refused(
    client, project_with_dated_entities
):
    """The opposite of what `neighborhood` does with `depth`, deliberately.

    A depth past the bound asks for a *shape* of answer the server will not
    produce, and the caller needs to know its question was wrong. A limit past
    the bound asks for as much as possible, which is what the clamp returns --
    and `truncated` already says the timeline did not fit, so a 422 would tell
    the caller nothing the answer does not.
    """
    response = await client.get(
        f"/api/projects/{project_with_dated_entities}/timeline?limit=100000"
    )

    assert response.status_code == 200
```

Add a `project_with_dated_entities` fixture to this file (or to the suite's `conftest.py` if the graph route tests keep theirs there) that creates a project and puts at least one dated entity in its graph store, mirroring however the existing graph route tests seed theirs.

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/interfaces/test_timeline_route.py -v
```

Expected: 404 on the route (FastAPI has no such path yet), so the first and third tests fail on status code.

- [ ] **Step 3: Add the presenters**

In `research_team/interfaces/web/presenters.py`, after `neighborhood_view`, add:

```python
def band_view(band: TimelineBand) -> dict[str, Any]:
    """One bar: what to draw, where to put it, and what the document said.

    `extent` and the `start`/`end` pair both travel, which looks redundant and
    is not -- see `TimelineBand.extent`. A browser given only the interval
    would label a bar "1815-01-01T00:00:00 - 1816-01-01T00:00:00" for a
    document that said "1815".

    `precision` and `uncertainty` travel on every band rather than only on
    uncertain ones, the same choice `relationship_view` makes with `inferred`:
    a client never has to read an absent field as a default it guessed at.
    """
    return {
        "entity_id": band.entity_id,
        "name": band.name,
        "entity_type": band.entity_type,
        "extent": band.extent,
        "start": band.start,
        "end": band.end,
        "precision": band.precision,
        "uncertainty": band.uncertainty,
    }


def timeline_view(timeline: Timeline) -> dict[str, Any]:
    """A project's dated entities in time order, and what is not in the drawing.

    `undated_count` is not decoration. Most entities in a real graph are not
    events, so a timeline is a view of a minority of the corpus by nature, and
    one showing forty bars with no denominator reads as "this project contains
    forty things". Same guarantee `truncated` gives on `graph_view`: data
    missing from a drawing is invisible precisely because it is missing.
    """
    return {
        "bands": [band_view(band) for band in timeline.bands],
        "undated_count": timeline.undated_count,
        "truncated": timeline.truncated,
    }
```

Add `Timeline` and `TimelineBand` to the imports at the top of `presenters.py`, from `research_team.application.timeline_read`.

- [ ] **Step 4: Add the route**

In `research_team/interfaces/web/app.py`, immediately after the `neighborhood` route, add:

```python
    async def _timeline_reader(project_id: UUID) -> TimelineReadPort:
        """This project's `TimelineReadPort`, over the store `graphs` owns.

        503 rather than 404 when `graphs` was not wired, matching
        `_graph_reader`: a build with no graph read model is a valid thing to
        serve, and the caller needs to know the server cannot answer rather
        than that the project has no timeline.

        Opens through `graphs` rather than holding its own store, so the
        timeline and the graph read the *same* store rather than two folds of
        one log that could drift apart between tabs.
        """
        if graphs is None:
            raise HTTPException(status_code=503, detail="no graph read model is configured")
        store = await graphs.open(project_id)
        return ProjectTimelineReader(project_id=project_id, store=store)

    @app.get("/api/projects/{project_id}/timeline")
    async def read_timeline(
        project_id: UUID,
        entity_type: str | None = None,
        limit: int = MAX_TIMELINE_BANDS,
    ):
        """This project's dated entities, ordered, for drawing on an axis.

        Project-level rather than under `/graph/` because it is not a graph
        shape: nothing in the response has a source, a target or an edge type,
        and nesting it there would suggest a client could ask for one and be
        given the other.

        `limit` is clamped by the port rather than refused here, the same call
        `read_graph` makes and for the same reason -- "as much as possible" is
        precisely what the clamp returns, and `truncated` in the body already
        says it did not all fit.
        """
        await _require_project(project_id)
        reader = await _timeline_reader(project_id)
        return timeline_view(await reader.timeline(entity_type=entity_type, limit=limit))
```

Add the imports at the top of `app.py`: `MAX_TIMELINE_BANDS` and `TimelineReadPort` from `research_team.application.timeline_read`, `ProjectTimelineReader` from `research_team.infrastructure.knowledge.timeline_reader`, and `timeline_view` alongside the existing presenter imports.

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/interfaces/test_timeline_route.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Full Python gates and commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
git add research_team/interfaces/web/presenters.py research_team/interfaces/web/app.py tests/interfaces/test_timeline_route.py
git commit -m "Serve the timeline at a project-level route

Project-level rather than under /graph/ because the response is not a graph
shape: nothing in it has a source, a target or an edge type, and nesting it
there would suggest a client could ask for one and be handed the other.

\`limit\` is clamped by the port rather than refused, matching \`read_graph\`
and deliberately unlike \`neighborhood\`'s treatment of \`depth\`. A depth past
the bound asks for a shape of answer the server will not produce; a limit past
it asks for as much as possible, which is what the clamp returns.

\`_timeline_reader\` opens through \`graphs\` rather than holding a store of its
own, so the two tabs read one store rather than two folds of the same log that
could drift apart.

The route test asserts field names literally rather than against a shared
constant: \`dto.ts\` parses these by exact key, so a rename fails as a
ContractError in the browser with nothing failing in Python, and two
independent spellings are what catch it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Frontend domain — types and the row-packing fold

Row packing is pure and has a correctness property (two bars overlapping in time must never share a row), so it lives in `domain/` and is tested without a DOM — the same split `domain/knowledge/graph.ts` uses for its merge semantics.

**Files:**
- Create: `frontend/src/domain/knowledge/timeline.ts`
- Test: `frontend/src/domain/knowledge/timeline.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `TimelineBand` (interface: `id: string`, `name: string`, `entityType: string`, `extent: string`, `start: string | null`, `end: string | null`, `precision: string`, `uncertainty: string`), `Timeline` (`bands: readonly TimelineBand[]`, `undatedCount: number`, `truncated: boolean`), `emptyTimeline: Timeline`, `PositionedBand` (`band: TimelineBand`, `row: number`), `Lane` (`entityType: string`, `rows: number`, `bands: readonly PositionedBand[]`), `laneRows(bands: readonly TimelineBand[]): readonly Lane[]`, `spanOf(bands: readonly TimelineBand[]): { from: number; to: number } | null`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/domain/knowledge/timeline.test.ts`:

```ts
import { describe, expect, it } from 'vitest'

import { emptyTimeline, laneRows, spanOf, type TimelineBand } from './timeline.ts'

const band = (over: Partial<TimelineBand> & { id: string }): TimelineBand => ({
  name: over.id,
  entityType: 'event',
  extent: '',
  start: null,
  end: null,
  precision: 'YEAR',
  uncertainty: 'EXACT',
  ...over,
})

const year = (id: string, from: number, to: number, entityType = 'event'): TimelineBand =>
  band({
    id,
    entityType,
    start: `${from}-01-01T00:00:00`,
    end: `${to}-01-01T00:00:00`,
    extent: `${from}`,
  })

describe('laneRows', () => {
  it('gives each entity type its own lane, in first-appearance order', () => {
    const lanes = laneRows([year('a', 1800, 1801, 'person'), year('b', 1900, 1901, 'event')])

    expect(lanes.map((lane) => lane.entityType)).toEqual(['person', 'event'])
  })

  it('puts two bands that overlap in time on different rows', () => {
    // The correctness property the whole function exists for: two bars on one
    // row would draw on top of each other, and the one underneath is not
    // merely hard to read, it is invisible.
    const lanes = laneRows([year('a', 1800, 1850), year('b', 1820, 1870)])

    const [lane] = lanes
    expect(lane.rows).toBe(2)
    expect(lane.bands.map((positioned) => positioned.row)).toEqual([0, 1])
  })

  it('reuses a row once the previous band on it has ended', () => {
    // Packing rather than one row per band. A hundred sequential events each
    // on its own row is a diagonal line, not a timeline.
    const lanes = laneRows([year('a', 1800, 1810), year('b', 1820, 1830)])

    const [lane] = lanes
    expect(lane.rows).toBe(1)
    expect(lane.bands.map((positioned) => positioned.row)).toEqual([0, 0])
  })

  it('treats bands that merely touch as non-overlapping', () => {
    // A half-open interval: 1810 ends where 1810-1820 begins, and they share
    // no instant. Widening this to "touching counts as overlapping" would put
    // every consecutive year-precision pair on its own row -- which is the
    // diagonal-line failure above, reached by a different route.
    const lanes = laneRows([year('a', 1800, 1810), year('b', 1810, 1820)])

    expect(lanes[0].rows).toBe(1)
  })

  it('rows a band open at both ends against everything in its lane', () => {
    // An open bound is unbounded, not missing: a band running off both edges
    // overlaps every other band there is, so it cannot share a row with any.
    const lanes = laneRows([band({ id: 'open' }), year('a', 1800, 1810)])

    expect(lanes[0].rows).toBe(2)
  })

  it('has no lanes for no bands', () => {
    expect(laneRows([])).toEqual([])
  })
})

describe('spanOf', () => {
  it('spans from the earliest start to the latest end', () => {
    const span = spanOf([year('a', 1800, 1810), year('b', 1900, 1910)])

    expect(span).toEqual({
      from: Date.parse('1800-01-01T00:00:00'),
      to: Date.parse('1910-01-01T00:00:00'),
    })
  })

  it('ignores open bounds when computing the span', () => {
    // An axis cannot start at negative infinity. A band open below is drawn
    // running off the edge of whatever span the *bounded* bands establish,
    // which is why the open bound contributes nothing to it.
    const span = spanOf([band({ id: 'open' }), year('a', 1800, 1810)])

    expect(span).toEqual({
      from: Date.parse('1800-01-01T00:00:00'),
      to: Date.parse('1810-01-01T00:00:00'),
    })
  })

  it('is null when nothing has a bounded date', () => {
    expect(spanOf([band({ id: 'open' })])).toBeNull()
    expect(spanOf([])).toBeNull()
  })
})

describe('emptyTimeline', () => {
  it('is empty rather than absent, so a pane can render before its first fetch', () => {
    expect(emptyTimeline.bands).toEqual([])
    expect(emptyTimeline.undatedCount).toBe(0)
    expect(emptyTimeline.truncated).toBe(false)
  })
})
```

- [ ] **Step 2: Run to verify failure**

```bash
cd frontend && npx vitest run src/domain/knowledge/timeline.test.ts
```

Expected: fails to resolve `./timeline.ts`.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/domain/knowledge/timeline.ts`:

```ts
/** A project's dated entities, and how they pack onto rows.
 *
 * A pure fold: no fetching, no React, no store. Here rather than inside the
 * canvas because row packing has a correctness property that is easy to break
 * under refactoring pressure and impossible to see in a screenshot -- two
 * bands overlapping in time must never share a row, because the one drawn
 * second covers the first entirely.
 */

export interface TimelineBand {
  readonly id: string
  readonly name: string
  readonly entityType: string
  /** What the document said, already formatted: "1815", "November 1923".
   *  Distinct from `start`/`end`, which are the widened interval that gets
   *  drawn -- see the port's `TimelineBand.extent`. */
  readonly extent: string
  /** ISO instant, or `null` for open below -- an `UncertaintyMarker.BEFORE`,
   *  which is a claim about unboundedness rather than a missing value. */
  readonly start: string | null
  readonly end: string | null
  readonly precision: string
  readonly uncertainty: string
}

export interface Timeline {
  readonly bands: readonly TimelineBand[]
  /** Entities in this project with no drawable extent. Rendered, not dropped:
   *  a timeline is a view of a minority of any real corpus, and one with no
   *  denominator reads as the whole of it. */
  readonly undatedCount: number
  readonly truncated: boolean
}

export const emptyTimeline: Timeline = { bands: [], undatedCount: 0, truncated: false }

export interface PositionedBand {
  readonly band: TimelineBand
  readonly row: number
}

export interface Lane {
  readonly entityType: string
  readonly rows: number
  readonly bands: readonly PositionedBand[]
}

/** `-Infinity`/`Infinity` for an open bound, so comparisons need no special
 *  case. An open bound is unbounded, and that is exactly what these mean --
 *  the alternative, substituting the axis extremes, would make a band's
 *  overlap depend on what else happened to be on the timeline. */
const startOf = (band: TimelineBand): number =>
  band.start === null ? -Infinity : Date.parse(band.start)

const endOf = (band: TimelineBand): number => (band.end === null ? Infinity : Date.parse(band.end))

/** `bands` grouped by entity type, each group packed onto as few rows as it can
 *  take without two bands overlapping on one.
 *
 * Lanes are in first-appearance order rather than alphabetical: the bands
 * arrive sorted by time, so first-appearance means the lane whose earliest
 * event is earliest comes first, and the reader's eye travels down the page in
 * the same direction it travels across it.
 *
 * Greedy first-fit, which is not optimal and does not need to be: the optimal
 * packing is interval-graph colouring, the greedy pass over time-sorted
 * intervals already achieves the minimum row count for that case, and the
 * bands are time-sorted when they arrive here.
 */
export const laneRows = (bands: readonly TimelineBand[]): readonly Lane[] => {
  const byType = new Map<string, TimelineBand[]>()
  for (const band of bands) {
    const existing = byType.get(band.entityType)
    if (existing === undefined) byType.set(band.entityType, [band])
    else existing.push(band)
  }

  return [...byType].map(([entityType, laneBands]) => {
    // The instant each row is free from. A band goes on the first row whose
    // last occupant has already ended.
    const rowEnds: number[] = []
    const positioned = laneBands.map((band) => {
      const start = startOf(band)
      // `<=`, not `<`: the intervals are half-open, so a band beginning
      // exactly where the previous one ended shares no instant with it.
      // Treating touching as overlapping would put every consecutive
      // year-precision pair on its own row, drawing a diagonal line.
      const row = rowEnds.findIndex((freeFrom) => freeFrom <= start)
      if (row === -1) {
        rowEnds.push(endOf(band))
        return { band, row: rowEnds.length - 1 }
      }
      rowEnds[row] = endOf(band)
      return { band, row }
    })
    return { entityType, rows: Math.max(rowEnds.length, 1), bands: positioned }
  })
}

/** The axis extent: earliest bounded start to latest bounded end, or `null`
 *  when nothing is bounded.
 *
 * Open bounds contribute nothing, because an axis cannot begin at negative
 * infinity. A band open below is drawn running off the edge of the span the
 * bounded bands establish, which is the only rendering of "unbounded" that
 * does not require inventing a date.
 */
export const spanOf = (bands: readonly TimelineBand[]): { from: number; to: number } | null => {
  const starts = bands.map(startOf).filter(Number.isFinite)
  const ends = bands.map(endOf).filter(Number.isFinite)
  if (starts.length === 0 && ends.length === 0) return null
  return { from: Math.min(...starts, ...ends), to: Math.max(...starts, ...ends) }
}
```

- [ ] **Step 4: Run the tests**

```bash
npx vitest run src/domain/knowledge/timeline.test.ts
```

Expected: all pass.

- [ ] **Step 5: Prove a test red**

Change the `findIndex` predicate from `freeFrom <= start` to `freeFrom <= Infinity`, run again. Expected: "puts two bands that overlap in time on different rows" fails. Restore.

- [ ] **Step 6: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/timeline-view
git add frontend/src/domain/knowledge/timeline.ts frontend/src/domain/knowledge/timeline.test.ts
git commit -m "Fold timeline bands onto the rows they will be drawn on

In domain/ rather than inside the canvas because row packing has a
correctness property that is easy to break under refactoring pressure and
invisible in a screenshot: two bands overlapping in time on one row draw on
top of each other, and the one underneath is not hard to read, it is absent.

Greedy first-fit, which is not optimal and does not need to be -- optimal
packing here is interval-graph colouring, and a greedy pass over time-sorted
intervals already achieves the minimum row count for that case. The bands
arrive time-sorted from the server.

Touching counts as not overlapping, because the intervals are half-open. The
opposite reading puts every consecutive year-precision pair on its own row and
draws a diagonal line instead of a timeline, which is the same failure as no
packing at all reached by a different route.

Open bounds are +/-Infinity for comparison and contribute nothing to the axis
span. Substituting the axis extremes instead would make one band's overlap
depend on what else happened to be on the timeline.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Frontend data layer — DTO, mapper, repository, container

**Files:**
- Modify: `frontend/src/infrastructure/http/dto.ts`
- Modify: `frontend/src/infrastructure/http/mappers.ts`
- Modify: `frontend/src/application/ports/repositories.ts`
- Create: `frontend/src/infrastructure/http/timeline-repository.ts`
- Modify: `frontend/src/app/container.ts`

**Interfaces:**
- Consumes: `Timeline`, `TimelineBand` (Task 5); the route contract from Task 4.
- Produces: `dto.timelineDto`, `dto.timelineBandDto`, `toTimeline`, `toTimelineBand`, `TimelineRepository` interface with `timeline(projectId: ProjectId, entityType?: string): Promise<Timeline>`, `HttpTimelineRepository`, and `timelines` on the container.

- [ ] **Step 1: Add the DTOs**

In `frontend/src/infrastructure/http/dto.ts`, after `graphNeighborhoodDto`, add:

```ts
/** One bar of `/api/projects/{id}/timeline`.
 *
 * `start` and `end` are nullable rather than optional: `null` is an open
 * bound, a positive claim that the entity extends unboundedly in that
 * direction, and a client reading it as "absent" would draw nothing where it
 * should draw a bar running off the edge.
 */
export const timelineBandDto = z.object({
  entity_id: z.string(),
  name: z.string(),
  entity_type: z.string(),
  extent: z.string().default(''),
  start: z.string().nullable(),
  end: z.string().nullable(),
  precision: z.string().default(''),
  uncertainty: z.string().default(''),
})

export const timelineDto = z.object({
  bands: z.array(timelineBandDto).default([]),
  undated_count: z.number().default(0),
  truncated: z.boolean().default(false),
})
```

- [ ] **Step 2: Add the mappers**

In `frontend/src/infrastructure/http/mappers.ts`, after `toNeighborhood`, add:

```ts
export const toTimelineBand = (raw: Dto<typeof dto.timelineBandDto>): TimelineBand => ({
  id: raw.entity_id,
  name: raw.name,
  entityType: raw.entity_type,
  extent: raw.extent,
  start: raw.start,
  end: raw.end,
  precision: raw.precision,
  uncertainty: raw.uncertainty,
})

export const toTimeline = (raw: Dto<typeof dto.timelineDto>): Timeline => ({
  bands: raw.bands.map(toTimelineBand),
  undatedCount: raw.undated_count,
  truncated: raw.truncated,
})
```

Add `import type { Timeline, TimelineBand } from '@domain/knowledge/timeline.ts'` to the file's imports.

- [ ] **Step 3: Add the port**

In `frontend/src/application/ports/repositories.ts`, after `GraphRepository`, add:

```ts
export interface TimelineRepository {
  /** The project's dated entities in time order, up to the server's cap.
   *
   * `undatedCount` on the result is not optional dressing -- most entities in
   * a real graph carry no dates, so a timeline is a view of a minority of the
   * corpus and the caller must show the denominator. `truncated` says the cap
   * bit, the same way `WholeGraph.truncated` does. */
  timeline(projectId: ProjectId, entityType?: string): Promise<Timeline>
}
```

Add `Timeline` to the type imports from `@domain/knowledge/timeline.ts`.

- [ ] **Step 4: Add the repository**

Create `frontend/src/infrastructure/http/timeline-repository.ts`:

```ts
import type { TimelineRepository } from '@application/ports/repositories.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, query, seg } from './http-client.ts'
import { toTimeline } from './mappers.ts'

export class HttpTimelineRepository implements TimelineRepository {
  constructor(private readonly http: HttpClient) {}

  async timeline(projectId: ProjectId, entityType?: string) {
    // No `limit`, matching `HttpGraphRepository.whole`: the server's own cap
    // is the right one, and a number picked here would be a second bound to
    // keep in step with it.
    const body = await this.http.get(
      `/api/projects/${seg(projectId)}/timeline${query({ entity_type: entityType })}`,
      dto.timelineDto,
    )
    return toTimeline(body)
  }
}
```

- [ ] **Step 5: Wire the container**

In `frontend/src/app/container.ts`, add `timelines: new HttpTimelineRepository(http),` directly after the `graphs:` line, and import `HttpTimelineRepository` from `'../infrastructure/http/timeline-repository.ts'` (match the import style of the neighbouring repository imports in that file). Add `timelines: TimelineRepository` to the container's type declaration — find it with:

```bash
cd frontend && grep -rn "graphs: GraphRepository" src/
```

and add the field alongside, importing `TimelineRepository` from the ports module.

- [ ] **Step 6: Typecheck and commit**

```bash
cd frontend && npx tsc --noEmit
```

Expected: clean. Then:

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/timeline-view
git add frontend/src/infrastructure/http/dto.ts frontend/src/infrastructure/http/mappers.ts frontend/src/infrastructure/http/timeline-repository.ts frontend/src/application/ports/repositories.ts frontend/src/app/container.ts
git commit -m "Fetch the timeline through a port of its own

Mirrors HttpGraphRepository exactly, including the decision not to send a
limit: the server's cap is the right one and a number picked in the browser
would be a second bound to keep in step with it.

start and end are nullable rather than optional in the DTO, and the
distinction matters. null is an open bound -- a positive claim that the entity
extends unboundedly in that direction -- so a client treating it as 'absent'
would draw nothing where it should draw a bar running off the edge.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: The timeline store

**Files:**
- Create: `frontend/src/application/research/timeline-store.ts`

**Interfaces:**
- Consumes: `TimelineRepository` (Task 6); `Timeline`, `emptyTimeline` (Task 5).
- Produces: `createTimelineStore({ timelines, projectId })` returning a zustand store with state `{ timeline: Timeline, entityType: string | null, loading: boolean, error: string | null, selected: string | null }` and actions `load(): Promise<void>`, `setEntityType(entityType: string | null): Promise<void>`, `select(id: string | null): void`.

- [ ] **Step 1: Write the store**

No dedicated unit test in this task: the store's behaviour is exercised through `TimelinePane.test.tsx` in Task 9 against a fake repository, which is the level `graph-store.ts` is tested at too — a separate test here would assert the same transitions twice.

Create `frontend/src/application/research/timeline-store.ts`:

```ts
import { create } from 'zustand'

import { errorMessage } from '@application/ports/errors.ts'
import { emptyTimeline, type Timeline } from '@domain/knowledge/timeline.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import type { TimelineRepository } from '../ports/repositories.ts'

/** One project's timeline: the bands, and which type of entity is on show.
 *
 * Project-keyed for the same reason `graph-store` is: the graph is
 * tenant-scoped by project, and a store shared across projects would draw one
 * project's events on another's page the moment two tabs were open.
 */
export interface TimelineState {
  readonly timeline: Timeline
  /** The entity type filter, or `null` for every type.
   *
   * Held here rather than in the pane because changing it refetches -- the
   * filter is pushed to the server, not applied to bands already in hand, so
   * it is part of what the store last asked for rather than a view setting.
   */
  readonly entityType: string | null
  readonly loading: boolean
  readonly error: string | null
  /** The band whose detail is open, or `null`.
   *
   * Here rather than in the pane for the reason `graph-store.selected` is:
   * one gesture both highlights a bar and says what it is, and two pieces of
   * state for one gesture is two places for them to disagree.
   */
  readonly selected: string | null

  load(): Promise<void>
  setEntityType(entityType: string | null): Promise<void>
  select(id: string | null): void
}

export const createTimelineStore = ({
  timelines,
  projectId,
}: {
  timelines: TimelineRepository
  projectId: ProjectId
}) =>
  create<TimelineState>((set, get) => ({
    timeline: emptyTimeline,
    entityType: null,
    loading: false,
    error: null,
    selected: null,

    async load() {
      set({ loading: true, error: null })
      try {
        const timeline = await timelines.timeline(projectId, get().entityType ?? undefined)
        // The selection survives a reload when its band is still present, so
        // a live extraction arriving does not close a detail panel the reader
        // is in the middle of. It is dropped when the band is gone, because a
        // panel describing an entity no longer on the timeline is a panel
        // about nothing.
        const selected = get().selected
        set({
          timeline,
          loading: false,
          selected: timeline.bands.some((band) => band.id === selected) ? selected : null,
        })
      } catch (error) {
        // The timeline is replaced with an empty one rather than left stale:
        // a failed refresh showing the previous bands beside an error message
        // invites the reader to trust bands that may be arbitrarily old.
        set({ timeline: emptyTimeline, loading: false, error: errorMessage(error) })
      }
    },

    async setEntityType(entityType: string | null) {
      set({ entityType })
      await get().load()
    },

    select(id: string | null) {
      set({ selected: id })
    },
  }))
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/timeline-view
git add frontend/src/application/research/timeline-store.ts
git commit -m "Hold one project's timeline in a store keyed to it

Project-keyed like graph-store, and for the same reason: the graph is
tenant-scoped, and a shared store would draw one project's events on another's
page the moment two tabs were open.

A failed load empties the timeline rather than leaving the previous bands
beside an error, which would invite the reader to trust bands of unknown age.
A selection survives a reload when its band is still there, so a live
extraction arriving does not close a detail panel mid-read.

The entity-type filter lives in the store rather than the pane because it is
pushed to the server -- it is part of what was last asked for, not a view
setting applied to bands already in hand.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: `TimelineCanvas` — the SVG drawing

**Files:**
- Create: `frontend/src/presentation/research/TimelineCanvas.tsx`
- Modify: `frontend/src/presentation/research/GraphDetail.tsx`

**Interfaces:**
- Consumes: `laneRows`, `spanOf`, `TimelineBand` (Task 5); `colorForType`, `KIND_TOKENS` from `./entity-colors.ts`.
- Produces: `TimelineCanvas` (named export) taking `{ bands: readonly TimelineBand[]; selected: string | null; onSelect: (id: string) => void }`. `GraphDetail`'s `onRemove` becomes optional.

- [ ] **Step 1: Read the neighbouring conventions first**

```bash
cd frontend
sed -n '1,45p' src/presentation/research/entity-colors.ts
sed -n '1,30p' src/presentation/research/GraphCanvas.tsx
```

Match whatever `colorForType`'s palette argument expects and however `GraphCanvas` sizes itself to its container.

- [ ] **Step 2: Write the canvas**

Create `frontend/src/presentation/research/TimelineCanvas.tsx`:

```tsx
import { useMemo, useState } from 'react'

import { laneRows, spanOf, type TimelineBand } from '@domain/knowledge/timeline.ts'

import { colorForType, KIND_TOKENS } from './entity-colors.ts'

/** Height of one packed row, and the gap above a lane's label. Constants
 *  rather than measured: the drawing is an SVG with its own coordinate space,
 *  so these are units in that space and not CSS pixels to be reconciled with
 *  anything. */
const ROW_HEIGHT = 22
const ROW_GAP = 4
const LANE_LABEL_HEIGHT = 18
const LANE_GAP = 12

/** How far outside the data's own span the axis reaches, as a fraction.
 *
 * Without it a band at the earliest date begins exactly on the left edge and
 * reads as clipped rather than as first. */
const AXIS_PADDING = 0.02

/** A band with an open bound runs this far past the axis before being clipped.
 *
 * A fraction of the span rather than "to the edge": drawn to the exact edge it
 * is indistinguishable from a band that merely starts early, and the whole
 * point of an open bound is that the reader can see it does not stop. */
const OPEN_OVERHANG = 0.06

/** The project's dated entities as bars on a shared axis.
 *
 * Hand-rolled SVG rather than a charting library, and the reason is the bundle
 * budget rather than taste: `scripts/check-size.mjs` is a CI gate,
 * `react-force-graph-2d` already spends most of the allowance on the tab
 * beside this one, and a time axis is a linear scale plus a list of
 * rectangles. A library here would be paid for by whichever feature next runs
 * into the budget.
 *
 * Lazily imported by `TimelinePane` for the same reason `GraphCanvas` is: a
 * reader on a session transcript should not pay for a drawing they are not
 * looking at.
 */
export const TimelineCanvas = ({
  bands,
  selected,
  onSelect,
}: {
  bands: readonly TimelineBand[]
  selected: string | null
  onSelect: (id: string) => void
}) => {
  // Zoom and pan in axis units, not pixels: the SVG has its own coordinate
  // space, so keeping the transform there means a resize does not move the
  // view. `zoom` is a multiplier on the span, `pan` a fraction of it.
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState(0)

  const lanes = useMemo(() => laneRows(bands), [bands])
  const span = useMemo(() => spanOf(bands), [bands])

  if (span === null) return null

  const rawWidth = span.to - span.from
  // A single-instant timeline -- one entity, or several sharing one date --
  // has a zero-width span, and every position in it would divide by zero. A
  // day either side is arbitrary and is the smallest window that still draws
  // the bar somewhere other than a vertical line at x=0.
  const width = rawWidth === 0 ? 86_400_000 : rawWidth
  const padded = width * (1 + AXIS_PADDING * 2)
  const origin = span.from - width * AXIS_PADDING

  /** An instant as a 0-1 position across the drawing, after zoom and pan. */
  const positionOf = (instant: number) => ((instant - origin) / padded) * zoom + pan

  const xOf = (iso: string | null, fallback: number) =>
    iso === null ? fallback : positionOf(Date.parse(iso))

  let y = 0
  const laneLayout = lanes.map((lane) => {
    const top = y
    y += LANE_LABEL_HEIGHT + lane.rows * (ROW_HEIGHT + ROW_GAP) + LANE_GAP
    return { lane, top }
  })

  return (
    <svg
      role="img"
      aria-label="Timeline of dated entities"
      viewBox={`0 0 1000 ${Math.max(y, 1)}`}
      preserveAspectRatio="none"
      className="h-full w-full"
      onWheel={(event) => {
        event.preventDefault()
        // Multiplicative, so a step out undoes a step in exactly. Additive
        // zoom drifts: ten steps in and ten out does not return to 1.
        setZoom((current) => Math.min(Math.max(current * (event.deltaY < 0 ? 1.1 : 1 / 1.1), 1), 50))
      }}
    >
      {laneLayout.map(({ lane, top }) => (
        <g key={lane.entityType} data-lane={lane.entityType}>
          <text
            x={4}
            y={top + 12}
            className="fill-fg-dim text-xs"
            // Not `pointer-events-none` via a utility: this is inside an SVG,
            // where Tailwind's pointer utilities apply but the label is also
            // the only affordance naming the lane, so it stays selectable.
          >
            {lane.entityType}
          </text>
          {lane.bands.map(({ band, row }) => {
            const left = xOf(band.start, positionOf(origin) - OPEN_OVERHANG)
            const right = xOf(band.end, positionOf(origin + padded) + OPEN_OVERHANG)
            const rowTop = top + LANE_LABEL_HEIGHT + row * (ROW_HEIGHT + ROW_GAP)
            return (
              <g key={band.id}>
                <rect
                  data-band={band.id}
                  data-selected={band.id === selected ? 'true' : undefined}
                  data-uncertainty={band.uncertainty}
                  x={left * 1000}
                  y={rowTop}
                  // Floored at 2 so an instant-precision band is still a
                  // visible mark and still clickable. A zero-width rect is
                  // neither, and an entity that vanishes at some zoom levels
                  // reads as missing data.
                  width={Math.max((right - left) * 1000, 2)}
                  height={ROW_HEIGHT}
                  rx={3}
                  fill={colorForType(band.entityType, KIND_TOKENS)}
                  // Dashed for anything the extraction was not certain of, so
                  // "circa 1850" and "1850" are distinguishable. They draw at
                  // identical widths by deliberate decision -- see
                  // `temporal_interval.py` -- so the stroke is the only thing
                  // carrying the difference.
                  strokeDasharray={
                    band.uncertainty === 'EXACT' || band.uncertainty === '' ? undefined : '4 3'
                  }
                  stroke={band.id === selected ? 'var(--accent)' : 'transparent'}
                  strokeWidth={band.id === selected ? 2 : 1}
                  className="cursor-pointer"
                  onClick={() => onSelect(band.id)}
                >
                  <title>{`${band.name} — ${band.extent}`}</title>
                </rect>
                <text
                  x={left * 1000 + 5}
                  y={rowTop + 15}
                  className="pointer-events-none fill-fg text-xs"
                >
                  {band.name}
                </text>
              </g>
            )
          })}
        </g>
      ))}
    </svg>
  )
}
```

- [ ] **Step 3: Make `GraphDetail.onRemove` optional**

In `frontend/src/presentation/research/GraphDetail.tsx`, change the prop type from `onRemove: (id: string) => void` to:

```ts
  /** Take the entity off the drawing, or `undefined` where there is no drawing
   *  to take it off. The timeline reuses this panel and has no canvas to
   *  prune -- offering the control there would be a button that either does
   *  nothing or silently changes a different tab. */
  onRemove?: (id: string) => void
```

Then guard the control that calls it so it renders only when `onRemove` is provided. Find it:

```bash
cd frontend && grep -n "onRemove" src/presentation/research/GraphDetail.tsx
```

- [ ] **Step 4: Typecheck and lint**

```bash
cd frontend && npx tsc --noEmit && npx eslint src/presentation/research/TimelineCanvas.tsx src/presentation/research/GraphDetail.tsx --max-warnings 0
```

Expected: clean. Existing `GraphDetail` call sites still pass `onRemove`, so nothing else changes.

- [ ] **Step 5: Run the existing GraphDetail tests**

```bash
npx vitest run src/presentation/research/
```

Expected: all pass — the prop became optional, which is backwards-compatible for every current caller.

- [ ] **Step 6: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/timeline-view
git add frontend/src/presentation/research/TimelineCanvas.tsx frontend/src/presentation/research/GraphDetail.tsx
git commit -m "Draw the bands, and let GraphDetail serve a view with no canvas

Hand-rolled SVG rather than a charting library, for the bundle budget rather
than taste: check-size.mjs is a CI gate, react-force-graph-2d already spends
most of the allowance on the tab beside this one, and a time axis is a linear
scale plus a list of rectangles. A library here gets paid for by whichever
feature next runs into the budget.

Uncertainty draws as a dashed stroke because 'circa 1850' and '1850' produce
identical intervals by deliberate decision, so width cannot carry the
difference and something has to.

Zoom is multiplicative so a step out undoes a step in exactly; additive zoom
drifts and ten steps each way does not return to 1. Bar width is floored at
2 units so an instant-precision band stays visible and clickable -- an entity
that disappears at some zoom levels reads as missing data.

GraphDetail's onRemove becomes optional. The timeline reuses the panel and has
no canvas to prune, so the control would be a button that either does nothing
or silently changes the tab next door. Every existing caller still passes it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: `TimelinePane` — container, states, and its jsdom tests

**Files:**
- Create: `frontend/src/presentation/research/TimelinePane.tsx`
- Test: `frontend/src/presentation/research/TimelinePane.test.tsx`

**Interfaces:**
- Consumes: `createTimelineStore` (Task 7); `TimelineCanvas` (Task 8); `GraphDetail`; `useContainer`, `useFrameRefresh`, `EmptyState`, `Loading`.
- Produces: `TimelinePane` and `TimelineBrowser` (both named exports). `TimelinePane` takes `{ projectId: ProjectId; entity: string | null; onEntity: (id: string | null) => void }` — the same prop shape `GraphPane` takes, so `ProjectView` wires them identically.

- [ ] **Step 1: Write the failing tests**

Read `GraphPane.test.tsx` first for the fake-repository and container-provider conventions:

```bash
cd frontend && sed -n '1,70p' src/presentation/research/GraphPane.test.tsx
```

Create `frontend/src/presentation/research/TimelinePane.test.tsx`, using the same `ContainerProvider` wrapper and `vi.mock` shape that file uses:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { TimelineRepository } from '@application/ports/repositories.ts'
import type { Timeline, TimelineBand } from '@domain/knowledge/timeline.ts'

import { TimelinePane } from './TimelinePane.tsx'

// The canvas is an SVG of computed positions, which jsdom lays out as
// nothing. Stubbed to a list of buttons so this file can assert *behaviour*
// -- which bands arrive, what a click does -- and leave geometry to
// `timeline-geometry.browser.test.tsx`, where it can actually be measured.
vi.mock('./TimelineCanvas.tsx', () => ({
  TimelineCanvas: ({
    bands,
    onSelect,
  }: {
    bands: readonly TimelineBand[]
    onSelect: (id: string) => void
  }) => (
    <div data-testid="canvas">
      {bands.map((band) => (
        <button key={band.id} onClick={() => onSelect(band.id)}>
          {band.name}
        </button>
      ))}
    </div>
  ),
}))

const band = (id: string, name: string): TimelineBand => ({
  id,
  name,
  entityType: 'event',
  extent: '1815',
  start: '1815-01-01T00:00:00',
  end: '1816-01-01T00:00:00',
  precision: 'YEAR',
  uncertainty: 'EXACT',
})

const timeline = (over: Partial<Timeline> = {}): Timeline => ({
  bands: [band('e1', 'Waterloo')],
  undatedCount: 0,
  truncated: false,
  ...over,
})

const fakeTimelines = (over: Partial<TimelineRepository> = {}): TimelineRepository => ({
  timeline: vi.fn().mockResolvedValue(timeline()),
  ...over,
})

describe('TimelinePane', () => {
  it('draws the bands the repository returned', async () => {
    renderPane({ timelines: fakeTimelines() })

    expect(await screen.findByText('Waterloo')).toBeInTheDocument()
  })

  it('says how many entities are undated rather than showing bands alone', async () => {
    // The failure this prevents is silent: a timeline showing one bar out of
    // four hundred entities looks exactly like a project containing one thing.
    renderPane({
      timelines: fakeTimelines({
        timeline: vi.fn().mockResolvedValue(timeline({ undatedCount: 312 })),
      }),
    })

    expect(await screen.findByText(/312/)).toBeInTheDocument()
  })

  it('says so when the server capped the timeline', async () => {
    renderPane({
      timelines: fakeTimelines({
        timeline: vi.fn().mockResolvedValue(timeline({ truncated: true })),
      }),
    })

    await waitFor(() => expect(screen.getByText(/more/i)).toBeInTheDocument())
  })

  it('shows an empty state when the project has no dated entities at all', async () => {
    renderPane({
      timelines: fakeTimelines({
        timeline: vi.fn().mockResolvedValue(timeline({ bands: [], undatedCount: 40 })),
      }),
    })

    // Distinguishes "nothing is dated" from "nothing was extracted": the
    // undated count is the only thing that tells those apart, and a reader
    // shown a bare empty state would go looking for an extraction failure.
    expect(await screen.findByText(/no dated entities/i)).toBeInTheDocument()
    expect(screen.getByText(/40/)).toBeInTheDocument()
  })

  it('surfaces a failed load rather than showing an empty timeline', async () => {
    renderPane({
      timelines: fakeTimelines({
        timeline: vi.fn().mockRejectedValue(new Error('the server said no')),
      }),
    })

    expect(await screen.findByText(/the server said no/)).toBeInTheDocument()
  })

  it('asks the route for one entity type when the filter is set', async () => {
    const timelines = fakeTimelines()
    renderPane({ timelines })

    await screen.findByText('Waterloo')
    await userEvent.selectOptions(screen.getByLabelText(/type/i), 'event')

    await waitFor(() =>
      expect(timelines.timeline).toHaveBeenLastCalledWith(expect.anything(), 'event'),
    )
  })

  it('opens the detail panel for a clicked band, with no remove control', async () => {
    // The remove control belongs to the graph canvas. Offering it here would
    // be a button that either does nothing or silently prunes the tab next
    // door -- see `GraphDetail.onRemove`.
    const graphs = fakeGraphsWithNeighborhood()
    renderPane({ timelines: fakeTimelines(), graphs })

    await userEvent.click(await screen.findByText('Waterloo'))

    await waitFor(() => expect(graphs.neighborhood).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: /remove/i })).not.toBeInTheDocument()
  })
})
```

Write `renderPane` and `fakeGraphsWithNeighborhood` following `GraphPane.test.tsx`'s own container-provider helper — `renderPane` mounts `TimelinePane` inside `ContainerProvider` with the given partial container, and `fakeGraphsWithNeighborhood` returns a `GraphRepository` whose `neighborhood` resolves to a root plus no neighbours.

- [ ] **Step 2: Run to verify failure**

```bash
cd frontend && npx vitest run src/presentation/research/TimelinePane.test.tsx
```

Expected: cannot resolve `./TimelinePane.tsx`.

- [ ] **Step 3: Write the pane**

Create `frontend/src/presentation/research/TimelinePane.tsx`:

```tsx
import { lazy, Suspense, useEffect, useMemo, useState } from 'react'

import { createTimelineStore } from '@application/research/timeline-store.ts'
import { useContainer } from '@app/container-context.tsx'
import type { Neighborhood } from '@domain/knowledge/graph.ts'
import type { Timeline } from '@domain/knowledge/timeline.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { EmptyState, Loading } from '../common/primitives.tsx'
import { useFrameRefresh } from '../shell/use-frame-refresh.ts'
import { GraphDetail } from './GraphDetail.tsx'

// `React.lazy` for the same reason `GraphPane` does it: a reader on a session
// transcript should not download a drawing they are not looking at.
const TimelineCanvas = lazy(() =>
  import('./TimelineCanvas.tsx').then((module) => ({ default: module.TimelineCanvas })),
)

/** The two capped/undated notices, matching `GraphPane`'s `NOTICE` rule for
 *  rule. `border-0` before the directional width is not optional: this build
 *  imports no preflight, so `border-solid` with only `border-b` set would draw
 *  the browser's ~3px default on the other three sides. */
const NOTICE =
  'm-0 border-0 border-b border-solid border-b-line-soft px-[6px] pb-[6px] pt-[4px] text-xs text-fg-dim'

/** The project's dated entities on a shared axis: what happened, and when.
 *
 * The peer of `GraphPane` rather than a route out of it. The graph answers
 * "what is connected to what" and deliberately refuses to draw `BEFORE`,
 * because it holds between nearly every pair of dated entities and collapses a
 * force-directed layout into a disc. This view answers the question that
 * refusal left open, and draws no edges at all -- on an axis, precedence is
 * where the bars sit, so a line asserting it would spend the densest relation
 * redstring can produce on information the reader already has.
 */
export const TimelinePane = ({
  projectId,
  entity,
  onEntity,
}: {
  projectId: ProjectId
  /** The selected entity, and how to change it. Owned by the route, the same
   *  arrangement `GraphPane` uses: this pane asks for a new selection and
   *  reacts to the one that comes back rather than keeping a copy beside the
   *  URL's. */
  entity: string | null
  onEntity: (id: string | null) => void
}) => {
  const { timelines, graphs } = useContainer()
  const store = useMemo(
    () => createTimelineStore({ timelines, projectId }),
    [timelines, projectId],
  )
  const { timeline, loading, error, entityType } = store()

  const [detail, setDetail] = useState<Neighborhood | null>(null)

  useEffect(() => {
    void store.getState().load()
  }, [store])

  /** Redraw when extraction lands, rather than making the reader reload.
   *
   * The same `graph` frame `GraphPane` listens for: the events that add an
   * entity to the graph are the events that add a band to this, and a second
   * frame kind would be a second thing to remember to emit. Corpus frames are
   * ignored -- they ride the same ingest, and storing a document dates
   * nothing.
   */
  useFrameRefresh(
    true,
    (frame) => frame.kind === 'graph' && frame.projectId === projectId,
    () => void store.getState().load(),
  )

  /** Fetch what the selected entity connects to, so the panel can say more
   *  than the bar already did.
   *
   * Through `graphs.neighborhood` rather than a timeline-specific route: the
   * question "what is this entity" has one answer, and a second endpoint
   * returning a subset of it would be a second thing to keep true.
   */
  useEffect(() => {
    if (entity === null) {
      setDetail(null)
      return
    }
    let cancelled = false
    void graphs
      .neighborhood(projectId, entity)
      .then((neighborhood) => {
        if (!cancelled) setDetail(neighborhood)
      })
      // Swallowed deliberately: the bar is still drawn and still correct, and
      // a failed detail fetch should not replace a working timeline with an
      // error. The panel simply does not open.
      .catch(() => {
        if (!cancelled) setDetail(null)
      })
    return () => {
      cancelled = true
    }
  }, [entity, graphs, projectId])

  const types = useMemo(
    () => [...new Set(timeline.bands.map((band) => band.entityType))].sort(),
    [timeline.bands],
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 px-2 py-1">
        <label className="text-xs text-fg-dim" htmlFor="timeline-type">
          Type
        </label>
        <select
          id="timeline-type"
          className="lay-ring-inward rounded-md border border-solid border-line bg-bg-panel px-1 text-xs"
          value={entityType ?? ''}
          onChange={(event) => void store.getState().setEntityType(event.target.value || null)}
        >
          <option value="">All</option>
          {types.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
      </div>

      <TimelineBrowser
        timeline={timeline}
        loading={loading}
        error={error}
        selected={entity}
        onSelect={onEntity}
        detail={detail}
      />
    </div>
  )
}

/** Everything the pane draws, as a function of what it was given.
 *
 * Split out and exported for the reason `GraphBrowser` is: every state --
 * loading, error, empty, capped, populated -- is then reachable in a test
 * without standing up a fake repository and waiting for a promise.
 */
export const TimelineBrowser = ({
  timeline,
  loading,
  error,
  selected,
  onSelect,
  detail,
}: {
  timeline: Timeline
  loading: boolean
  error: string | null
  selected: string | null
  onSelect: (id: string | null) => void
  detail: Neighborhood | null
}) => {
  if (loading && timeline.bands.length === 0) return <Loading />
  if (error !== null) return <EmptyState>{error}</EmptyState>

  if (timeline.bands.length === 0) {
    return (
      <EmptyState>
        {/* The count is what separates "nothing is dated" from "nothing was
            extracted". Without it a reader meeting this goes looking for an
            extraction failure that did not happen. */}
        No dated entities yet
        {timeline.undatedCount > 0 ? ` — ${timeline.undatedCount} entities carry no dates` : ''}
      </EmptyState>
    )
  }

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-h-0 flex-1 flex-col">
        {timeline.undatedCount > 0 ? (
          <p className={NOTICE}>
            {timeline.undatedCount} of {timeline.undatedCount + timeline.bands.length} entities are
            undated and are not drawn
          </p>
        ) : null}
        {timeline.truncated ? (
          <p className={NOTICE}>Showing the first {timeline.bands.length}; there are more</p>
        ) : null}
        <div className="min-h-0 flex-1 overflow-auto">
          <Suspense fallback={<Loading />}>
            <TimelineCanvas bands={timeline.bands} selected={selected} onSelect={onSelect} />
          </Suspense>
        </div>
      </div>
      {detail !== null && selected !== null ? (
        <GraphDetail
          view={{ entities: [detail.root, ...detail.entities], relationships: detail.relationships }}
          selected={selected}
          onSelect={onSelect}
          onClose={() => onSelect(null)}
        />
      ) : null}
    </div>
  )
}
```

If `GraphDetail`'s `view` prop expects a `GraphView` shaped differently from the object literal above, adapt it — check with `grep -n "interface GraphView" -A 10 src/domain/knowledge/graph.ts` and build the value with whatever helper that module exports (`loadWhole` or `emptyGraph` plus `expand`) rather than hand-shaping it.

- [ ] **Step 4: Run the tests**

```bash
cd frontend && npx vitest run src/presentation/research/TimelinePane.test.tsx
```

Expected: all pass. Fix the pane, not the assertions, if any fail.

- [ ] **Step 5: Prove a test red**

Temporarily delete the `{timeline.undatedCount > 0 ? (<p className={NOTICE}>…</p>) : null}` block and run `says how many entities are undated rather than showing bands alone`. Expected: FAIL. Restore.

- [ ] **Step 6: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/timeline-view
git add frontend/src/presentation/research/TimelinePane.tsx frontend/src/presentation/research/TimelinePane.test.tsx
git commit -m "Assemble the timeline pane, and say what it is not showing

Container plus an exported presentational half, the split GraphPane uses: every
state -- loading, error, empty, capped, populated -- is then reachable in a test
without standing up a fake repository and waiting on a promise.

The undated notice is the load-bearing part. Most entities in a real graph are
not events, so a timeline is a view of a minority of the corpus by nature, and
one showing a bar with no denominator reads as a project containing one thing.
The empty state carries the same count for a sharper reason: it is the only
thing separating 'nothing is dated' from 'nothing was extracted', and a reader
without it goes looking for an extraction failure that did not happen.

Selection detail comes from graphs.neighborhood rather than a timeline-specific
route: 'what is this entity' has one answer, and a second endpoint returning a
subset of it would be a second thing to keep true. A failed detail fetch is
swallowed -- the bar is still drawn and still correct, and the panel simply
does not open.

Listens for the same `graph` frame GraphPane does. The events that add an
entity are the events that add a band, and a second frame kind would be a
second thing to remember to emit.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: The tab

**Files:**
- Modify: `frontend/src/presentation/routing/routes.ts`
- Modify: `frontend/src/presentation/project/ProjectView.tsx`

**Interfaces:**
- Consumes: `TimelinePane` (Task 9).
- Produces: the `'timeline'` facet, reachable at `#/p/<id>/timeline` and `#/p/<id>/timeline/<entityId>`.

- [ ] **Step 1: Add the facet**

In `frontend/src/presentation/routing/routes.ts`, add `'timeline',` to the `FACETS` array, directly after `'entity'`:

```ts
  'entity',
  // The graph's peer rather than a mode of it: same material, ordered by time
  // instead of wired by relationship. A facet of its own because it is a place
  // on the project with its own selection, which is exactly what the grammar
  // is for.
  'timeline',
```

There is a test asserting `FACETS` coverage — find and run it:

```bash
cd frontend && grep -rln "FACETS" src/presentation/routing/
npx vitest run src/presentation/routing/
```

If it fails because a switch is no longer total or a fixture enumerates facets, that is the test doing its job. Fix the code it points at.

- [ ] **Step 2: Wire the tab**

In `frontend/src/presentation/project/ProjectView.tsx`:

Add `'timeline'` to the `regionOf` switch beside `'entity'`:

```ts
    case 'entity':
    case 'timeline':
    case 'doc':
```

Extend the type and the tab list:

```ts
type MaterialFacet = 'artifact' | 'file' | 'finding' | 'doc' | 'entity' | 'timeline'
```

```ts
  { id: 'entity', label: 'Graph' },
  // After Graph, not before: this list is ordered by what the reader is asking,
  // and the timeline is a second reading of the graph's own material. Last also
  // keeps it out of the default position, which matters for the same bundle
  // reason `artifact` is default -- `TimelineCanvas` is lazy, and a default of
  // `timeline` would pull it on every project page anybody opened.
  { id: 'timeline', label: 'Timeline' },
```

Add the panel beside the graph's:

```tsx
<TabPanel value="timeline" className="flex min-h-0 flex-1 flex-col">
  <TimelinePane
    projectId={projectId}
    entity={selection?.facet === 'timeline' ? (selection.id ?? null) : null}
    onEntity={(entity) => select({ facet: 'timeline', id: entity })}
  />
</TabPanel>
```

Import `TimelinePane` from `'../research/TimelinePane.tsx'`.

- [ ] **Step 3: Run the project view tests**

```bash
cd frontend && npx vitest run src/presentation/project/ src/presentation/routing/
```

Expected: all pass. If a test enumerates `MATERIAL_TABS` and asserts a count or an order, update it to include Timeline — that assertion existing is why the order is not an accident.

- [ ] **Step 4: Full frontend gate**

```bash
cd frontend && npm run verify
```

Expected: all steps pass. If `size` fails, the lazy import in Task 9 is not taking effect — check that `TimelineCanvas` is reached only through `lazy()` and never statically imported anywhere, including from a test file that is part of the build graph.

- [ ] **Step 5: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/timeline-view
git add frontend/src/presentation/routing/routes.ts frontend/src/presentation/project/ProjectView.tsx
git commit -m "Offer the timeline as a tab beside the graph

A facet rather than a mode of the graph tab, so it is a place on the project
with its own selection and its own URL -- which is what the route grammar is
for, and it comes free once the facet exists.

After Graph in MATERIAL_TABS rather than before. The list is ordered by what
the reader is asking, and the timeline is a second reading of the graph's own
material. Last also keeps it out of the default slot, which matters for the
same bundle reason artifact is the default: TimelineCanvas is lazy, and a
default of timeline would pull that chunk on every project page anybody opened.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: The browser test — geometry, measured

This task exists because jsdom lays nothing out. `CLAUDE.md` records four findings in a row whose real assertion was written as a comment for that reason, and a fifth that shipped past a fully green suite.

**Files:**
- Create: `frontend/src/presentation/research/timeline-geometry.browser.test.tsx`

**Interfaces:**
- Consumes: `TimelineCanvas` (Task 8).

- [ ] **Step 1: Read an existing browser test for its conventions**

```bash
cd frontend && ls src/**/*.browser.test.tsx && sed -n '1,40p' src/presentation/research/graph-dressing.browser.test.tsx
```

Note that the viewport is set in `vite.config.ts` and a media query reads *that*, not the width of the wrapper a test renders into.

- [ ] **Step 2: Write the test**

Create `frontend/src/presentation/research/timeline-geometry.browser.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { TimelineBand } from '@domain/knowledge/timeline.ts'

import { TimelineCanvas } from './TimelineCanvas.tsx'

/** Geometry, in a browser, because jsdom has none.
 *
 * Every assertion here is a measurement: `getBoundingClientRect` on a laid-out
 * SVG. In jsdom each one returns 0 and would have to be written as a comment,
 * which `CLAUDE.md` records happening four times in a row before this suite
 * existed.
 */

const band = (over: Partial<TimelineBand> & { id: string }): TimelineBand => ({
  name: over.id,
  entityType: 'event',
  extent: '',
  start: null,
  end: null,
  precision: 'YEAR',
  uncertainty: 'EXACT',
  ...over,
})

const year = (id: string, from: number, to: number, entityType = 'event'): TimelineBand =>
  band({
    id,
    entityType,
    start: `${from}-01-01T00:00:00`,
    end: `${to}-01-01T00:00:00`,
    extent: `${from}`,
  })

const rectFor = (id: string) =>
  document.querySelector(`[data-band="${id}"]`)!.getBoundingClientRect()

describe('timeline geometry', () => {
  it('draws a band twice as wide as one covering half its span', () => {
    // The proportionality the axis is for. Asserted as a ratio rather than an
    // absolute width because the viewport is fixed in `vite.config.ts` and an
    // absolute would break the day anybody changed it -- for a reason having
    // nothing to do with this drawing.
    render(
      <TimelineCanvas
        bands={[year('wide', 1800, 1900), year('narrow', 1900, 1950)]}
        selected={null}
        onSelect={() => {}}
      />,
    )

    expect(rectFor('wide').width / rectFor('narrow').width).toBeCloseTo(2, 1)
  })

  it('puts two bands that overlap in time at different heights', () => {
    // `timeline.test.ts` already asserts they get different row *numbers*.
    // This asserts the row number reaches the drawing -- the two are different
    // claims, and the fold being right while the rendering ignores it is
    // exactly the failure a green jsdom suite would not catch.
    render(
      <TimelineCanvas
        bands={[year('early', 1800, 1850), year('late', 1820, 1870)]}
        selected={null}
        onSelect={() => {}}
      />,
    )

    expect(rectFor('early').top).not.toBeCloseTo(rectFor('late').top, 0)
  })

  it('gives every band a non-zero width, including an instant', () => {
    // A zero-width rect is invisible and unclickable, and an entity that
    // vanishes at some zoom levels reads as data that is missing.
    render(
      <TimelineCanvas
        bands={[year('instant', 1815, 1815), year('span', 1800, 1900)]}
        selected={null}
        onSelect={() => {}}
      />,
    )

    expect(rectFor('instant').width).toBeGreaterThan(0)
  })

  it('separates lanes vertically by entity type', () => {
    render(
      <TimelineCanvas
        bands={[year('a', 1800, 1810, 'person'), year('b', 1800, 1810, 'event')]}
        selected={null}
        onSelect={() => {}}
      />,
    )

    // Same interval, different types: any vertical separation between them is
    // the lane grouping, since the packing would have put them on one row.
    expect(rectFor('a').top).not.toBeCloseTo(rectFor('b').top, 0)
  })

  it('strokes a selected band in the accent colour and an unselected one not at all', () => {
    // The defect this is shaped after: a chosen control drawing in the
    // unchosen colour shipped past a fully green suite and was caught by eye.
    // Both halves asserted, because a canvas that stroked everything would
    // satisfy the first.
    render(
      <TimelineCanvas
        bands={[year('chosen', 1800, 1810), year('other', 1820, 1830)]}
        selected="chosen"
        onSelect={() => {}}
      />,
    )

    const strokeOf = (id: string) =>
      getComputedStyle(document.querySelector(`[data-band="${id}"]`)!).stroke

    expect(strokeOf('chosen')).not.toBe(strokeOf('other'))
    expect(strokeOf('chosen')).not.toBe('none')
  })
})
```

- [ ] **Step 3: Run it**

```bash
cd frontend && npm run test:browser
```

Expected: all pass. Nothing else may be running vitest at the same time.

- [ ] **Step 4: Prove one red**

Temporarily change `TimelineCanvas`'s row offset from `row * (ROW_HEIGHT + ROW_GAP)` to `0`, re-run. Expected: "puts two bands that overlap in time at different heights" fails. Restore and re-run — all pass.

- [ ] **Step 5: Commit**

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/timeline-view
git add frontend/src/presentation/research/timeline-geometry.browser.test.tsx
git commit -m "Measure the drawing, in a browser, because jsdom cannot

Every assertion here is a getBoundingClientRect or a getComputedStyle on a
laid-out SVG. In jsdom each returns 0 or only what an inline style said, and
would have to be written as a comment -- which CLAUDE.md records happening
four times in a row before this suite existed.

Widths are asserted as a ratio rather than an absolute, because the viewport
is fixed in vite.config.ts and an absolute would break the day somebody
changed it for reasons having nothing to do with this drawing.

The row-height test is not a duplicate of timeline.test.ts. That one asserts
the fold assigns different row numbers; this asserts the row number reaches the
drawing. The fold being right while the rendering ignores it is precisely the
failure a green jsdom suite does not catch.

The selection test asserts both halves -- chosen differs from unchosen, and
chosen is not 'none' -- because a canvas that stroked everything identically
would satisfy either alone. It is shaped after the defect where a chosen
control drew in the unchosen colour and shipped past a fully green suite.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: All four gates, and the documentation

**Files:**
- Modify: `BACKLOG.md`

- [ ] **Step 1: Run all four gates, in a quiet environment**

Nothing else may be running vitest or pytest.

```bash
cd /home/ty/workspace/research-team/.claude/worktrees/timeline-view
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd frontend && npm run verify
```

All four must pass. Per `CLAUDE.md`, a failure under load is not evidence until it reproduces alone — re-run any failure in isolation first, then re-run the whole suite, and treat two consecutive identical results as the bar.

- [ ] **Step 2: Run the browser suite**

```bash
cd frontend && npm run test:browser
```

- [ ] **Step 3: File what was deferred**

Add to `BACKLOG.md`, in the same voice as its neighbours:

```markdown
### B56. The timeline reads the tenant twice per open

`ProjectTimelineReader.timeline` makes two linear passes over the tenant: one
`TemporalQuery.timeline` for the ordered dated entities, and one
`find_entities` for the `undated_count` denominator. The second exists only
because `TemporalQuery.timeline` returns dated entities and therefore cannot
supply the count of the ones it left out.

This is the same *order* as `ProjectGraphReader.whole`, which already pages the
store on every graph open, so it is not a new class of cost. It is double a
single read, and it is paid on a tab a reader may return to repeatedly.

Deliberately uncached, and this entry is the record of that being a decision
rather than an oversight. A cache needs an invalidation; the knowledge log
already emits `graph` frames that would have to drive one; and building that
before a measurement says which of the two passes actually hurts would be
guessing at which half to fix. **Not measured against a real corpus** -- the
figure to get first is the wall time of each pass on the largest project
available, because if the `find_entities` pass is the cheap one there is
nothing here worth doing.
```

- [ ] **Step 4: Commit and push**

```bash
git add BACKLOG.md
git commit -m "File the timeline's double read rather than cache it blind

Two linear passes per open, the second buying undated_count because
TemporalQuery.timeline returns only dated entities and cannot report the ones
it skipped. Same order as ProjectGraphReader.whole, double a single read, paid
on a tab a reader returns to.

Filed rather than fixed because a cache needs an invalidation and the numbers
to justify one do not exist yet. The entry names the measurement to take
first: if the find_entities pass is the cheap one, there is nothing here worth
doing.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push -u origin timeline-view
```

- [ ] **Step 5: Report**

State plainly which gates were run and what they returned. If any step of the plan was skipped or altered, say which and why. Do not report completion for anything not actually verified.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| No edges drawn | Task 8 (canvas draws bars only); noted in Task 9's pane docstring |
| No new charting dependency | Task 8 |
| No read model / `GraphStore` is an `EntityReader` | Task 3 |
| The port, separate from `GraphReadPort` | Task 2 |
| `ProjectTimelineReader`, library ordering, alias filter | Task 3 |
| `temporal_interval.py`, forbidden import, precision widening, markers | Task 1 |
| The route, project-level, clamped limit | Task 4 |
| Tab, facet, URL state, ordering after Graph | Task 10 |
| Repository, DTO, mapper, container | Task 6 |
| Store, `useFrameRefresh` on `graph` frames | Tasks 7, 9 |
| Lazy canvas, lanes by type, row packing, zoom/pan | Tasks 5, 8 |
| Undated note | Tasks 3, 4, 9 |
| Selection via `GraphDetail`, optional `onRemove` | Tasks 8, 9 |
| Two-pass cost, uncached, BACKLOG | Tasks 3, 12 |
| Python tests, architecture rule, jsdom, browser | Tasks 1, 3, 4, 9, 11 |
| Out of scope (brush, minimap, filter UI, edges, clustering) | Not implemented anywhere — correct |

One spec item is not its own task: the architecture test confirming the `redstring.domain.` rule fires on the new module. The existing rule at `tests/test_architecture.py:156` scans every module in the package, so `temporal_interval.py` and `timeline_reader.py` are covered the moment they exist, and Task 1 Step 6 and Task 3 Step 6 both run the full `pytest`, which includes it. Adding a bespoke case would test the existing rule rather than the new code.

**Placeholder scan:** none. Every code step carries the actual content. Three steps direct the implementer to read a neighbouring file first (Task 4 Step 1, Task 8 Step 1, Task 9 Step 1, Task 11 Step 1) — these are for fixture and palette conventions that must match the file they sit beside, and each names the exact command and what to match.

**Type consistency:** `TimelineBand` is `entity_id`/`name`/`entity_type`/`extent`/`start`/`end`/`precision`/`uncertainty` in Python (Tasks 2, 3, 4) and `id`/`name`/`entityType`/`extent`/`start`/`end`/`precision`/`uncertainty` in TypeScript (Tasks 5, 6, 8, 9, 11), with `toTimelineBand` (Task 6) as the single translation. `Timeline` is `bands`/`undated_count`/`truncated` server-side and `bands`/`undatedCount`/`truncated` client-side, translated in the same place. `extent_bounds` returns `tuple[datetime | None, datetime | None] | None` in Task 1 and is consumed with exactly that shape in Task 3. `TimelinePane` takes the same `{ projectId, entity, onEntity }` props `GraphPane` does (Tasks 9, 10).
