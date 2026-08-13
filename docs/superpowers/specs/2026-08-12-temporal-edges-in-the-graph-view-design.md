# Temporal edges in the graph view

Extraction has been writing dates onto entities since redstring landed, and
nothing has ever drawn them. This is the wiring, and the reasoning for where
it stops.

`docs/design/temporal-edges-in-the-graph-view.md` is the redstring team's
analysis of why nothing is visible today and is not repeated here. This
document is the design, and it differs from that analysis in four places
where reading the actual redstring source changed the answer. Each is marked.

## The claim, verified

`grep -ril temporal research_team/ frontend/src/` returns nothing. Not one
reference, on either side of the wire. There is no bug to fix and no
regression to explain: the capability was never wired.

What exists underneath it:

- **`Entity.temporal`** is a `TemporalExtent` — `start_date`, `end_date`,
  `precision`, `uncertainty`, `original_text`, `sequence_position`,
  `publication_date`. A property of a node, so a view that draws nodes and
  stored relationships has nothing to draw for it.
- **`redstring.infer_relations(entities, *, relations, max_pairs)`** pairs up
  every dated member and returns `InferredRelation`s. These are deliberately
  not `Relationship`s — they carry no `id`, so they cannot reach
  `upsert_relationship` even by accident. redstring's own module docstring
  gives three reasons and they are all still true here: no invalidation event
  exists, so a stored inferred edge goes stale silently when re-extraction
  improves an extent; the interesting edges are *between* documents while
  extraction only ever sees one; and a derived fact in a durable log means a
  replay can disagree with the same arithmetic run today.

**This adds no store round trip.** `infer_relations` is pure over entities
already fetched.

Not to be confused with `docs/direction.md` §6's "temporal queries", which is
about the event log — what this system believed when. This is about what the
*corpus* says happened when. Different question, different data, no overlap.

## Where the wiring goes

`ProjectGraphReader` (`research_team/infrastructure/knowledge/graph_reader.py`).

It and `redstring_adapter.py` are the only two modules importing redstring's
domain types, and `graph_read.py`'s docstring is explicit that the port must
not name them: everything above `GraphReadPort` speaks this application's
`GraphEntity`/`GraphRelationship` so a redstring schema change stays an
implementation detail underneath the port rather than a change to its
contract. Inference is a redstring call over redstring `Entity` objects, so
it belongs on the adapter's side of that line and the port learns only a
boolean and two strings.

## 1. The port DTOs

`research_team/application/graph_read.py`:

```python
@dataclass(frozen=True)
class GraphEntity:
    ...
    temporal: str | None = None
    """When this entity happened, rendered for reading. `None` when undated.

    Here rather than left to the edge that needed it, because a node at the
    end of a temporal edge showing no date makes the edge look arbitrary --
    the reader is shown a line asserting a containment and given nothing to
    check it against. Most entities in a real graph are not events, so `None`
    is the ordinary case rather than an error.
    """


@dataclass(frozen=True)
class GraphRelationship:
    ...
    inferred: bool = False
    """Computed from two extents on this read, rather than recorded by the log.

    They are not the same claim and must not draw the same. An asserted edge
    is something a document said; an inferred one is arithmetic over two
    dates that changes the next time either entity is re-extracted under a
    new model version.
    """

    derivation: str | None = None
    """The two extents this was computed from, as text. `None` when asserted.

    An inferred edge with no visible derivation is indistinguishable from an
    asserted one, which is the confusion redstring's `InferredRelation`
    exists to prevent -- it carries `source_extent`/`target_extent` for
    exactly this and nothing else.
    """
```

Both new relationship fields and the entity field are defaulted, so every
existing construction site and every existing test keeps working unchanged.

`Graph` gains one flag:

```python
    inferred_truncated: bool = False
    """Whether the inferred-edge cap dropped any. See `MAX_INFERRED_EDGES`.

    Separate from `truncated` rather than folded into it: `truncated` says
    entities are missing, and a reader told "this graph is incomplete" when
    every entity is present and only some computed lines were dropped would
    go looking for missing nodes that are all there.
    """
```

`Neighborhood` does **not** gain it. A neighborhood is bounded by
`MAX_NEIGHBORHOOD_DEPTH` over one root's neighbours, which is a far smaller
set than 500 in every case the cap is protecting against; adding a flag that
can never be true would be a field nobody can write a test for.

## 2. The adapter computes them

```python
from redstring import TemporalRelation, infer_relations

#: Which inferred relations reach a drawing. **`BEFORE` is deliberately
#: absent.** It holds between almost every pair of disjoint intervals, so it
#: is dense where the others are sparse: 100 dated entities yield on the
#: order of 4,950 `BEFORE` edges against at most 500 nodes, and a
#: force-directed layout given that resolves to a solid disc. Containment and
#: coincidence are the relations a reader learns something from. "What
#: preceded what" is a timeline question rather than a graph one and wants
#: its own view; drawing it here does not answer it, it only hides the edges
#: that would have.
#:
#: `AFTER` and `DURING` are absent because `infer_relations` never emits
#: them, not because they were excluded -- it canonicalises each pair to one
#: edge, so an `AFTER` arrives as its target's `BEFORE` and a `DURING` as its
#: target's `CONTAINS`. Listing them here would be config that cannot fire.
_DRAWN_RELATIONS = frozenset(
    {
        TemporalRelation.CONTAINS,
        TemporalRelation.OVERLAPS,
        TemporalRelation.EQUALS,
    }
)
```

`_inferred_edges(entities)` returns
`tuple[GraphRelationship, ...]` built from `infer_relations(entities,
relations=_DRAWN_RELATIONS)`, each with `inferred=True` and a `derivation` of
`f"{source_extent} {relation.value} {target_extent}"` rendered through
`_render_extent`.

It takes the same list the nodes are built from, and that is what makes the
both-ends-present filter the stored edges need unnecessary here: an inferred
edge is only ever produced between two members of the list, so there is no
edge to an entity the caller was not given.

In `whole`, after `kept` is computed, and in `neighborhood` over
`[root, *neighbors]`. `_to_graph_entity` grows
`temporal=_render_extent(entity.temporal)`.

## 3. `_render_extent` is written here, and `render_temporal` is not used

**This is the first place the analysis's recommendation changes on reading
the source.** The analysis offers two options — write it locally, or export
`render_temporal` upstream. The second is wrong, not merely slower.

`redstring.domain.temporal_parsing.render_temporal` exists for a round-trip
property: it renders only text the same module parses back to an *identical*
extent, and returns `None` for everything else. It returns `None` for a
month- or day-precision range, for any extent carrying a `sequence_position`
or a `publication_date`, for a year range whose end is not strictly after its
start, and for any `start_date` not landing exactly on the boundary its
precision names. Those are all extents extraction produces. Wiring it to the
canvas would blank the date on a large fraction of real nodes and there would
be no error to notice — the field would simply be `None`, which already means
"undated".

Display has the opposite contract: never `None` for an extent that holds
anything, because a date the reader cannot see is a date they cannot check the
edge against. So:

```python
def _render_extent(extent: Any) -> str | None:
    """`extent` as short text a reader can check an edge against.

    Deliberately not `redstring`'s `render_temporal`, which exists for a
    round-trip property and returns `None` for anything it cannot re-parse to
    the same extent -- a month range, anything with a publication date,
    anything whose start does not land on its precision's boundary. Those are
    ordinary extraction output, and blanking them would be silent: `None`
    already means undated, so there would be nothing to notice.

    `original_text` first, because it is what the document said and no
    reformatting improves on it. The fallback only runs when extraction
    stored dates without the text they came from.
    """
```

Order: `original_text` if set; else a range or point formatted by
`precision`; else the ISO date. `None` only when the extent is absent or
`is_empty`.

`redstring.__all__` carries `TemporalExtent`, `TemporalRelation`,
`DatePrecision`, `UncertaintyMarker`, `infer_relations` and
`InferredRelation` — everything this needs. Nothing reaches into
`redstring.domain.*` or `redstring.temporal.*`.

**`tests/test_architecture.py` grows the rule that keeps it that way.** Its
one helper, `_imported_roots`, reduces every import to its root package with
`.split(".")[0]` — deliberately, since the existing rule is about which
*frameworks* a layer may name. So `from redstring.domain.temporal_parsing
import render_temporal` reads as `redstring` and passes every existing case.
The new rule therefore needs its own helper that keeps the full dotted path,
rather than a new parametrisation of the existing one. redstring's contract is that
anything reached by a dotted path is internal and may change in a patch
release, and this repository already has two modules doing it —
`tests/application/test_graph_read.py` imports `redstring.domain.entity` and
`redstring.domain.relationship`. So the new rule applies to
`research_team/` only and those test imports stay legal; a test constructing
a fixture is not shipping against a private API.

## 4. Aliases in `neighborhood`

`whole` runs `_without_aliases` before `kept`. `neighborhood` calls
`GraphStore.neighbors` and passes the result straight through.

Inference knows nothing about merges and an absorbed entity keeps its own
`temporal`, so a canonical entity and its own alias produce an `EQUALS` edge
between what is really one thing — a duplicate node wired to itself, in the
first consolidated project anyone opens a neighborhood view on.

**The fix drops aliases from the neighborhood entirely, not just before
inference.** This is the second departure from the analysis, which proposes
filtering only for the inference step. Filtering twice over would leave the
alias drawn as an isolated node with no edges — `_without_aliases`'s own
docstring calls that "precisely the duplicate a reader reports" — so the
neighborhood would still show the bug, just without the self-edge. The
inconsistency with `whole` was pre-existing; the temporal edge is what makes
it loud enough to fix.

Costs one `resolve_entity_ids` round trip per neighborhood read, which is
what `whole` already pays and what that method's docstring already accounts
for.

## 5. The inferred-edge cap

**Third departure.** The analysis says an edge cap is "worth measuring
before deciding". It is worth adding, and the measurement is the wrong
instrument: what a measurement of today's corpora can establish is that the
common case is sparse, which nobody doubts. The cap is not for the common
case. `MAX_GRAPH_NODES` is 500, admitting 124,750 pairs, and a corpus about a
single decade can put every entity inside the same containing era — every
`OVERLAPS`, every pair. Nothing between `infer_relations` and the canvas
bounds edges at all, and the failure mode is a browser tab that stops
responding, not a slow one.

```python
#: How many inferred edges reach one drawing. Not a legibility bound -- a
#: graph is unreadable long before this -- but the point past which a
#: force-directed simulation in a browser stops responding at all. The
#: relations drawn are sparse in every corpus measured, and "in practice" is
#: not a bound: 500 entities inside one containing era is 124,750 pairs, and
#: nothing between `infer_relations` and the canvas bounds edges otherwise.
MAX_INFERRED_EDGES = 2_000
```

It falls on inferred edges only. Asserted edges are what the log recorded and
are never dropped to make room for arithmetic. `infer_relations` returns a
sorted, deterministic list, so the kept prefix is the same on every read of an
unchanged graph rather than varying between two identical requests.

`inferred_truncated` reports it for the same reason `truncated` exists: a
drawing missing lines looks exactly like a drawing with none to miss.

## 6. `DEFAULT_MAX_PAIRS` cannot fire, and a comment says why

`infer_relations` refuses above 500,000 pairs. `whole` is capped at 500
entities, so at most 124,750. The refusal is unreachable on this path today
and becomes reachable if `MAX_GRAPH_NODES` is ever raised past ~1,000. That
belongs as a note at the cap, where someone raising it will read it, rather
than as a runtime surprise a year later.

## 7. The wire and the browser

**Presenter** (`interfaces/web/presenters.py`): `entity_view` gains
`temporal`, `relationship_view` gains `inferred` and `derivation`,
`graph_view` gains `inferred_truncated`. All pass-through.

**DTO** (`frontend/src/infrastructure/http/dto.ts`): the three new fields on
`graphEntityDto`/`graphRelationshipDto` as nullable, `inferred_truncated` on
`graphWholeDto` with a `false` default — matching how `truncated` is already
declared. Mappers map them onto `GraphNode.temporal`, `GraphLink.inferred`,
`GraphLink.derivation`.

**`linkKey` gains `inferred`.** This is the fourth departure, and it is a bug
the analysis does not reach because it stops at the port. `domain/knowledge/
graph.ts` keys links on `source|target|relationshipType`. An asserted
`contains` and an inferred `CONTAINS` between the same pair produce the same
key, so `expand` collapses them into one line and which survives depends on
arrival order. They are different claims — that is the whole premise of
`inferred` — and the merge must keep both. The docstring already explains why
the key is directed rather than unordered; this extends the same argument by
one field.

**The canvas** (`presentation/research/GraphCanvas.tsx`): inferred edges draw
dashed and dimmer than asserted ones — `linkLineDash` and a `linkColor`
reading `link.inferred`, both of which the library takes as accessors.
`linkLabel` returns `derivation` for an inferred edge and `relationshipType`
for an asserted one, so hovering a temporal line shows the arithmetic rather
than restating the word already implied by the dashes.

Dashed rather than a different colour: colour on this canvas already means
entity type, and the node painter's own comment gives the rule — overriding a
channel that carries a fact would trade one fact for another instead of
adding one. The same argument applies to lines. The dimming is a change of
alpha within the existing edge colour, not a new hue, for that reason.

`linkColor` is today `() => 'rgba(138, 149, 163, 0.35)'` — the one colour on
this canvas inlined rather than read from `tokens.css`. Making it an accessor
that branches on `inferred` means two literals where there was one, so both
move to tokens in the same change rather than doubling the thing that was
already the exception.

**The legend** (`presentation/research/GraphLegend.tsx`) grows one line, on
the same terms as the hollow-node note: prose rather than a swatch, and
withheld when the drawing contains no inferred edge, because a key explaining
a mark that is not on the canvas sends the reader hunting for one.

## 8. Tests

Per `CLAUDE.md`, each assertion has to distinguish this implementation from
the plausible wrong ones.

**`tests/application/test_graph_read.py`** — seeded through
`InMemoryGraphStore.upsert_entities` as the existing fixtures are:

- **An inferred edge between two entities with no stored relationship
  between them**, and separately an asserted edge between the *same* pair
  coming back with `inferred=False`. A test where the pair is also related in
  the store cannot tell "inference ran" from "the stored edge got a flag".
- **A pair whose extents genuinely produce `CONTAINS`** — a year and a month
  inside it. Two identical extents produce `EQUALS`, which would also appear
  under an implementation that never called `relate` and simply paired
  everything up.
- **`BEFORE` absent** from a graph of two disjoint dated entities.
  `_DRAWN_RELATIONS` is the only thing keeping the drawing legible, and an
  exemption nobody checks stops holding silently.
- **One entity with no extent and one with an empty one**, both present as
  nodes and absent from every inferred edge. Most entities in a real graph
  are not events; undated members taking no part is the ordinary case.
- **A merged pair in `neighborhood`**: the alias absent from `entities`, and
  no self-`EQUALS`. The one no other test in the suite would catch.
- **`_render_extent` on an extent `render_temporal` returns `None` for** — a
  month-precision range — asserting a non-empty string. This is what stops
  someone "simplifying" §3 back to the upstream call, and it fails if they
  do.
- **`inferred_truncated`** true past `MAX_INFERRED_EDGES` with every asserted
  edge still present, and false on a graph under it.

**`tests/test_architecture.py`** — a dotted-path case: no module under
`research_team/` may import `redstring.<anything>`, only `redstring` itself.

**`tests/interfaces/test_web.py`** — the new fields present on the graph
route's body. The presenters get no direct test: `tests/interfaces/
test_presenters.py` has no graph cases today and the route tests are where
the wire shape is already asserted, so adding a second place for it would be
adding a second place for it to drift.

**`frontend/src/domain/knowledge/graph.test.ts`** — an asserted and an
inferred link between the same pair with the same type both surviving
`expand`. Reverting the `linkKey` change turns it red.

**`GraphCanvas`/`GraphLegend`** — the legend line present with an inferred
edge in the view and absent without one, in jsdom. The dash pattern itself is
a canvas drawing operation and is not asserted: jsdom paints nothing, and a
browser-mode test that screenshots a `<canvas>` would be asserting on pixels.
Stated here so the gap is a decision rather than an oversight.

Before trusting any of it: delete the `_inferred_edges` call from `whole` and
watch the suite go red. A test that stays green under a deliberate break is
evidence about the fixture, not about the code.

## Out of scope

**A timeline view.** `TemporalQuery` (`redstring.temporal.query`) answers
"what did this graph hold over this interval" — a time-sliced read that pages
the whole tenant and filters in Python, linear in entity count regardless of
how few entities are dated. That is where `BEFORE` belongs. Separate read,
separate cost profile, and it does not go behind `GraphReadPort.whole`.

**Filtering the canvas to temporal edges only**, or a toggle hiding them.
Worth wanting once there is something to look at; specifying it before anyone
has seen an inferred edge drawn would be guessing at which control the
drawing turns out to need.

**Persisting anything.** Covered above, and by redstring's ADR 0005.
