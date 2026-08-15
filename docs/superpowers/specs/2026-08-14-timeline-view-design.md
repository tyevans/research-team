# Timeline view

A fifth material tab beside the graph, drawing dated entities on a time axis.
This is the view `docs/design/temporal-edges-in-the-graph-view.md` deferred
rather than a new capability: that design excluded `BEFORE` from the drawn
relations because it is dense enough to collapse a force-directed layout, and
closed by saying "what preceded what" is a timeline question that wants its
own view. This is that view, and the reason it draws no edges at all.

## What it shows, and what it deliberately does not

Dated entities from one project's knowledge graph, on a horizontal axis, in
lanes grouped by entity type.

**No edges.** Position on the axis *is* precedence, so a `BEFORE` line would
spend the densest relation redstring can produce on information the reader
already has from where the bars sit. The graph view refuses `BEFORE` because
100 dated entities yield on the order of 4,950 such edges; a timeline refuses
it because it is redundant. `CONTAINS` and `OVERLAPS` are visible here as
geometry -- a bar inside another bar, two bars sharing a column -- which is
the whole reason a reader would open this tab rather than the graph one.

**No new charting dependency.** The bundle budget is a CI gate
(`scripts/check-size.mjs`) and `react-force-graph-2d` already spends most of
the allowance. A time axis is a linear scale and a list of rectangles; it does
not need a library, and adding one would be paid for by whichever feature next
runs into the budget.

## Why there is no read model

`ProjectGraphs.open(project_id)` already hands back a redstring `GraphStore`,
and `GraphStore` satisfies redstring's `EntityReader` protocol -- verified by
introspection, not assumed: `EntityReader` requires `close`,
`find_by_blocking_key`, `find_by_blocking_keys`, `find_entities`,
`get_entities` and `get_entity`, and `GraphStore` has all six.
`TemporalQuery.__init__` takes exactly an `EntityReader`.

So the timeline reads the same store the graph view reads, through a type
redstring already exports, and needs **no read model, no projection and no
runner**. That is worth stating plainly because the shape of the surrounding
code argues otherwise -- `CorpusStore`, `TopicRow` and `CheckOutcomeRow` are
all SQLite read models fed by projections, and the reflex on meeting a new
read is to add a fourth. The graph read path is the exception in this
repository: it computes everything per request from a store folded out of the
knowledge event log, and the timeline is a second read of that same kind.

The cost of that choice is stated under "What this costs" below rather than
hidden.

## The port

`research_team/application/timeline_read.py`, a new module rather than a
method on `GraphReadPort`.

Separate because the design doc that deferred this said so explicitly, and the
reason survives re-reading: `GraphReadPort.whole` is bounded by
`MAX_GRAPH_NODES` and answers "draw me this graph", where a timeline read is
bounded by *time* and pages the tenant looking for dated entities. Folding a
read with a different cost profile behind a method named for a different
question is how a port stops describing anything.

It follows `GraphReadPort`'s conventions: this application's own frozen
dataclasses, plain `str` ids, no redstring type named above the adapter.

```python
@dataclass(frozen=True)
class TimelineBand:
    """One dated entity as something a browser can position and size.

    `extent` and the `start`/`end` pair are both here and are not redundant.
    `extent` is `render_extent`'s text -- what the document said, read back to
    a human ("November 1923", "1990-1995"). `start`/`end` are the drawn
    interval, which is a *different* quantity: it is precision-widened, so a
    year-precision extent spans its year rather than sitting on its first
    instant. A view given only the text cannot lay anything out, and a view
    given only the interval would label a bar "1815-01-01 - 1816-01-01" when
    the document said "1815".
    """

    entity_id: str
    name: str
    entity_type: str
    extent: str
    start: str | None
    """ISO instant the band begins, or `None` for open below.

    `None` is not "unknown" -- it is an `UncertaintyMarker.BEFORE`, which is a
    positive claim that the thing happened at some unbounded time prior. A
    browser draws it as a bar running off the left edge, which is why the
    field is nullable rather than defaulted to the axis minimum: an axis
    minimum computed from the data would move as the data changed, and the
    bar would appear to have a start that shifted.
    """

    end: str | None
    """ISO instant the band ends, or `None` for open above. See `start`."""

    precision: str
    uncertainty: str
    """`DatePrecision` and `UncertaintyMarker` names, for dressing.

    Carried rather than folded into the geometry because "circa 1850" and
    "1850" produce the *same* interval by deliberate decision (see
    `temporal_interval.py`), and a reader who cannot tell them apart has been
    shown a certainty the extraction never claimed.
    """


@dataclass(frozen=True)
class Timeline:
    bands: tuple[TimelineBand, ...]
    undated_count: int
    """Entities in this project carrying no drawable extent.

    Not an optional nicety. Most entities in a real graph are not events, so
    a timeline is by nature a view of a minority of the corpus, and one that
    showed 40 bands with no denominator would read as "this project contains
    40 things". Same convention as `Graph.truncated`: a view missing data
    says so.
    """

    truncated: bool
```

## The adapter

`research_team/infrastructure/knowledge/timeline_reader.py`, `ProjectTimelineReader`,
sibling to `ProjectGraphReader` and bound to one project the same way.

It calls `TemporalQuery(store).timeline(tenant_id=..., interval=..., entity_type=...)`.

Ordering is taken from the library rather than re-sorted here. redstring
promises start, then end, then id, and documents *why* the id tiebreak exists:
two entities routinely carry the same extent -- a document naming three things
that happened in 1066 -- and without it their order would depend on what the
store handed back, which the port does not promise to keep stable across
adapters. Re-sorting here would discard that and reintroduce the instability
on the next adapter change.

Aliases are filtered before banding, for the reason `neighborhood` learned the
hard way: an absorbed entity keeps its own `temporal`, so a canonical entity
and its own alias draw as two bars with identical extents -- which on a
timeline looks like corroboration from two sources rather than one thing
counted twice.

## `temporal_interval.py`, and the constraint that shapes it

`research_team/infrastructure/knowledge/temporal_interval.py`, sibling to
`temporal_rendering.py`. This is the module carrying the risk in this design,
and it exists as its own module for a reason that is not taste.

**redstring's interval helpers cannot be imported.** `bounds` and `widen` live
at `redstring.domain.interval`. They are absent from `redstring.__all__`, and
`tests/test_architecture.py` forbids any import under `redstring.domain.`
outright -- redstring's contract is that anything reached by a dotted path is
internal and may change in a patch release. So the interval arithmetic is
written here against `TemporalExtent`'s public fields.

This is not a new precedent. `temporal_rendering.py` exists for the same
reason at one remove: redstring's `render_temporal` is unexported *and*
unsuitable, so `render_extent` was written locally. The two modules are the
same shape of answer to the same shape of problem, which is why they sit
beside each other rather than one absorbing the other -- text and geometry are
different outputs with different `None` conditions, and a single function
returning both would have to pick one meaning of "nothing to show".

### The decision inside it

**A band is the precision-widened interval.** A `YEAR`-precision extent has
`start_date = 1815-01-01` and frequently no `end_date`. Drawn literally that
is a zero-width mark on the 1st of January, which asserts a precision the
extraction never claimed and puts "1815" and "1 January 1815" at the same
place at the same size. So `YEAR` spans to the next year, `MONTH` to the next
month, `DAY` to the next day. `HOUR` and `MINUTE` exist on the enum and no
pipeline in this project produces them; they fall through to a day, matching
the fall-through `temporal_rendering.py` already documents.

**Uncertainty markers widen nothing.** `BEFORE` and `AFTER` open a bound --
they are claims about unboundedness, not about margin. `CIRCA`, `APPROXIMATE`,
`INFERRED` and `EXACT` all produce the ordinary closed interval. This mirrors
redstring's own documented reasoning, which is worth repeating here because
the opposite is the intuitive choice: "circa 1850" is a claim about how
confidently 1850 is known, not about which years it might have been. Widening
it means inventing the margin -- a decade? a century? -- and then every bar's
width rests on a number nobody chose deliberately. The uncertainty is carried
to the browser as a field and dressed there instead.

**`None` means undated.** An extent that is absent, empty, or carries only a
`sequence_position` yields no interval. Sequence position orders events that
have no dates at all, and no axis position applies to it. Those entities count
towards `undated_count` and draw nowhere.

## The route

`GET /api/projects/{project_id}/timeline?entity_type=&from=&to=&limit=`

In `research_team/interfaces/web/app.py`, beside the three graph routes, using
the same `_graph_reader`-shaped helper to open the store and 503 when `graphs`
is unwired. A `timeline_view` presenter in `presenters.py` beside `graph_view`.

Project-level rather than under `/graph/` because it is not a graph shape:
nothing in the response has a source, a target or a type of edge, and nesting
it there would suggest a client could ask for one and get the other.

`limit` is clamped inside the port, not at the route, for the reason
`MAX_NEIGHBORHOOD_DEPTH` is: a route is not the last thing that can call a
port.

## Frontend

Additive along seams that already exist.

**Tab and route.** `FACETS` and `MaterialFacet` gain `'timeline'`;
`MATERIAL_TABS` gains `{ id: 'timeline', label: 'Timeline' }` after Graph;
`regionOf`'s total switch maps it to `material`. Tab state is URL state at no
cost, because it already is: `#/p/<id>/timeline`, and
`#/p/<id>/timeline/<entityId>` for a selection.

After Graph rather than before it because the ordering in `MATERIAL_TABS` is
documented as meaningful -- artifacts and workspace are one shelf at two ages,
then material that arrived from outside the course. The timeline is a second
reading of the graph's own material, so it belongs adjacent to it and last.

**Data.** `TimelineRepository` port, `HttpTimelineRepository`, a zod DTO and a
mapper, wired in the container -- mirroring `HttpGraphRepository` exactly.
A `timeline-store.ts` zustand store mirroring `graph-store.ts`, refreshed by
`useFrameRefresh` on `frame.kind === 'graph'`: the same knowledge events that
change the graph change the timeline, and a second frame kind would be a
second thing to remember to emit.

**Components.** `TimelinePane.tsx` (container, holds the store and the
subscription) exporting a prop-driven `TimelineBrowser` -- the split
`GraphPane` uses, and for the same reason: every state is then reachable in a
test without a fake repository. `TimelineCanvas.tsx` is lazy-loaded like
`GraphCanvas`, keeping it off the main chunk.

The canvas is hand-rolled SVG: a linear scale from the union of all band
intervals, bars packed into rows within per-type lanes so two entities that
overlap in time never share a row, colours from the existing
`entity-colors.ts`. Zoom and pan on wheel and drag.

**Undated.** A persistent note -- "312 of 400 entities are undated". Not a
tooltip and not hidden behind an empty state, because the common case is a
timeline that is both non-empty and deeply unrepresentative.

**Selection.** Clicking a band fetches that entity's neighborhood through the
*existing* `GraphRepository.neighborhood` method and renders the existing
`GraphDetail`. No new backend and no second detail component. `GraphDetail`
takes a `GraphView` and offers a "remove from canvas" action that means
nothing on a timeline, so it gains an optional prop suppressing that control
-- a targeted change to a component being worked in, not a refactor of it.
A "Show in graph" action navigates to `#/p/<id>/entity/<entityId>`, making the
two views peers rather than making the timeline a launcher.

## What this costs

**Two linear passes over the tenant per open.** One `TemporalQuery.timeline`
for the ordered dated entities, one count for the `undated_count` denominator.
redstring's own notes record `TemporalQuery` as linear in entity count
regardless of how few entities are dated, because it pages the tenant and
filters in Python.

This is the same order as `ProjectGraphReader.whole`, which already pages the
store on every graph open, so it is not a new class of cost -- but it is
double what a single read would be, and it is paid on a tab a user may switch
to repeatedly. Deliberately not cached: a cache needs an invalidation, the
knowledge log already emits frames that would have to drive one, and building
that before there is a measurement showing the pass hurts would be guessing at
which half is slow. If it does hurt, it is a BACKLOG entry with a number in
it.

**An entity cap, with a flag.** `truncated` for the same reason `Graph` has
one: a drawing missing bars looks exactly like a drawing with none to miss.

## Testing

The four gates in `CLAUDE.md`, plus `npm run test:browser`, which this change
*requires* rather than merely permits -- bar geometry is computed position and
width, and jsdom lays nothing out, so those assertions written in the jsdom
suite would have to be comments.

**Python.** Against `InMemoryGraphStore` with hand-built extents:

- A `YEAR`-precision extent spans its year, not an instant. **Delete the
  widening and this must go red** -- it is the one piece of arithmetic here
  that redstring would have done and is not allowed to.
- `BEFORE` opens the lower bound and leaves the upper closed; `AFTER` the
  reverse. Asserted separately, because a single test over "an open bound"
  passes against an implementation that opens whichever one it likes.
- `CIRCA` produces the same interval as `EXACT` over the same dates, and a
  *different* `uncertainty` value. Both halves: the first pins the decision
  not to widen, the second pins that the decision is still visible to a
  reader.
- An entity with no extent, one with an empty extent, and one carrying only a
  `sequence_position`: all absent from `bands`, all counted in
  `undated_count`. The third is the case that looks dated and is not.
- A canonical entity and its alias produce one band.
- Over the cap sets `truncated`.
- Ordering matches the library's for entities sharing an extent.

**Architecture.** Confirm the existing `redstring.domain.` rule actually fires
on an import from the new module. The whole design is shaped around that rule;
an exemption nobody checks stops holding silently.

**jsdom.** The tab appears in `MATERIAL_TABS` order and routes to
`#/p/<id>/timeline`; loading, empty, error and populated states; the undated
note renders its counts; selecting a band calls `neighborhood` and shows
`GraphDetail` without a remove control.

**Browser.** `timeline-geometry.browser.test.tsx`: a year band's width against
the axis scale, and two entities overlapping in time occupying different rows.
Both are measurements; neither is expressible in jsdom.

Per the repository convention: prove each test red before trusting it green.

## Out of scope

Brush and minimap navigation, a date-range filter UI (the port takes an
interval from the first commit; the browser ships with zoom and pan only),
drawn temporal edges, and clustering of dense regions. Each is a real feature
and none of them is needed to answer "what happened when" for a corpus this
project can currently extract.
