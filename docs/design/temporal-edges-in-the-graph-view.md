# Temporal edges in the graph view

Extraction populates dates on entities and nothing draws them. This is the
wiring that puts them on the canvas, and the reasoning for where it stops.

## Why nothing is visible today

redstring's temporal support is two separate things, and only one of them is
ever an edge.

**Extents live on entities.** `Entity.temporal` is a `TemporalExtent` — a
start, an end, a `DatePrecision` and an `UncertaintyMarker` — parsed by
extraction from whatever the model said. The Neo4j adapter stores it as a
JSON blob on the node (`temporal_json`). It is a *property of a node*, so a
view that draws nodes and stored relationships has nothing to draw for it.

**Temporal relations are computed on read and never persisted.**
`redstring.infer_relations(entities)` pairs up every dated entity and returns
`InferredRelation`s — `BEFORE`, `CONTAINS`, `OVERLAPS`, `EQUALS`. These are
deliberately not redstring `Relationship`s: they carry no `id`, so they cannot
be handed to `GraphStore.upsert_relationship` even by accident. redstring's
ADR 0005 gives the reasons — they go stale silently when re-extraction
improves an extent (there is no invalidation event), they are quadratic across
the tenant rather than per-document, and they are derived facts that do not
belong in a durable log.

**Nothing in this repository calls it.** `grep` across `research_team/`,
`web.py` and `main.py` finds no reference to `infer_relations`,
`InferredRelation` or `TemporalQuery`. `ProjectGraphReader` reads stored
entities and stored relationships only, so inferred edges are computed nowhere
in the path that feeds the drawing and therefore cannot appear in it.

There is no bug to fix. The capability was never wired.

## Where the wiring goes

`ProjectGraphReader` (`research_team/infrastructure/knowledge/graph_reader.py`).

It and `redstring_adapter.py` are the only two modules that import redstring's
domain types, and `graph_read.py`'s own docstring is explicit that the port
must not name them: everything above `GraphReadPort` speaks this application's
`GraphEntity`/`GraphRelationship` so that a redstring schema change stays an
implementation detail underneath the port rather than a change to its
contract. Inference is a redstring call over redstring `Entity` objects, so it
belongs on the adapter's side of that line, and the port learns only a
boolean.

`infer_relations` is pure over entities already fetched. **This adds no store
round trip** to either read.

## 1. The port DTOs

`research_team/application/graph_read.py`:

```python
@dataclass(frozen=True)
class GraphRelationship:
    """One edge, stripped to what a browser draws: two ends and a label.

    `inferred` separates edges redstring's log recorded from edges computed
    from two entities' dates on this read. They are not the same claim and
    must not draw the same: an asserted edge is something a document said, an
    inferred one is arithmetic over two extents that changes the next time
    either entity is re-extracted under a new model version. `derivation`
    carries the two extents as rendered text so a reader can see the working
    -- an inferred edge with no visible derivation is indistinguishable from
    an asserted one, which is the confusion redstring's `InferredRelation`
    exists to prevent.
    """

    source_id: str
    target_id: str
    relationship_type: str
    inferred: bool = False
    derivation: str | None = None
```

Both new fields are defaulted, so every existing construction site and every
existing test keeps working unchanged.

`GraphEntity` gains the extent as well, or the nodes at the ends of a temporal
edge show no date and the edge looks arbitrary:

```python
    temporal: str | None = None   # rendered extent, e.g. "2023", "1990-1995"
```

## 2. The adapter computes them

```python
from redstring import TemporalRelation, infer_relations

#: Which inferred relations reach a drawing. **`BEFORE` is deliberately
#: absent.** It holds between almost every pair of disjoint intervals, so it
#: is dense where the others are sparse: 100 dated entities yield on the order
#: of 4,950 `BEFORE` edges against at most 500 nodes, and a force-directed
#: layout given that resolves to a solid disc. Containment and coincidence are
#: the relations a reader learns something from. "What preceded what" is a
#: timeline question rather than a graph one and wants its own view; drawing
#: it here does not answer it, it only hides the edges that would have.
_DRAWN_RELATIONS = frozenset(
    {
        TemporalRelation.CONTAINS,
        TemporalRelation.OVERLAPS,
        TemporalRelation.EQUALS,
    }
)


def _inferred_edges(entities: list[Any]) -> tuple[GraphRelationship, ...]:
    """Temporal edges among `entities`, computed rather than stored.

    Takes the same list the nodes are built from, which is what makes the
    both-ends-present filter the stored edges need unnecessary here: an
    inferred edge is only ever produced between two members of the list, so
    there is no edge to an entity the caller was not given.
    """
    return tuple(
        GraphRelationship(
            source_id=str(relation.source_entity_id),
            target_id=str(relation.target_entity_id),
            relationship_type=relation.relation.value,
            inferred=True,
            derivation=(
                f"{_render_extent(relation.source_extent)} "
                f"{relation.relation.value} "
                f"{_render_extent(relation.target_extent)}"
            ),
        )
        for relation in infer_relations(entities, relations=_DRAWN_RELATIONS)
    )
```

In `whole`, after `kept` is computed:

```python
        return Graph(
            entities=tuple(_to_graph_entity(entity) for entity in kept),
            relationships=edges + _inferred_edges(kept),
            truncated=len(entities) > capped,
        )
```

The same two-line addition in `neighborhood`, over `[root, *neighbors]`.

`_to_graph_entity` grows one field: `temporal=_render_extent(entity.temporal)`.

## 3. Four things that will bite

**`render_temporal` is not exported.** `redstring.__all__` carries
`TemporalExtent`, `TemporalRelation`, `DatePrecision`, `infer_relations` and
`InferredRelation` — but not `render_temporal` and not `INFERRED_RELATIONS`.
redstring's contract is that anything reached by a dotted path is internal and
may change in a patch release, so `_render_extent` is either written here
against `TemporalExtent`'s public fields, or `render_temporal` is exported
upstream first. Do not reach into `redstring.domain.temporal_parsing`.
`tests/test_architecture.py` should grow a case for that if it does not
already cover the dotted-path rule.

**`neighborhood` does not filter aliases.** Inference knows nothing about
merges, and an absorbed entity keeps its own `temporal`, so a canonical entity
and its own alias will produce an `EQUALS` edge between what is really one
thing. `whole` is already safe — `_without_aliases` runs before `kept` — but
`neighborhood` calls `GraphStore.neighbors` and passes the result straight
through. Filter there before inferring, or the first consolidated project to
open a neighborhood view sees a duplicate wired to itself.

**The cap interacts with density.** `MAX_GRAPH_NODES` bounds nodes, not edges,
and nothing downstream bounds edges at all. With `BEFORE` excluded the
remaining three relations are sparse in practice, but "in practice" is not a
bound — a corpus about a single decade can put every entity inside the same
containing era. Worth measuring against a real project graph before deciding
whether an edge cap is needed; if one is added it needs a `truncated`-style
flag for the same reason the node cap does, since a drawing missing lines
looks exactly like a drawing with none to miss.

**`DEFAULT_MAX_PAIRS` is not reachable from here.** `infer_relations` refuses
above 500,000 pairs; `whole` is capped at 500 entities, so at most 124,750
pairs. The refusal cannot fire on this path today. It becomes reachable if
`MAX_GRAPH_NODES` is ever raised past ~1,000, which is worth a comment at the
cap rather than a runtime surprise.

## 4. Tests

Per `CLAUDE.md`'s failure-shape table, the assertion has to distinguish this
implementation from the plausible wrong ones:

- **Assert an inferred edge between two entities with no stored relationship
  between them**, and separately assert that an asserted edge between the
  *same* pair still comes back with `inferred=False`. A test where the pair is
  also related in the store cannot tell "inference ran" from "the stored edge
  got a flag."
- **Give the pair extents that genuinely produce `CONTAINS`** — a year and a
  month inside it. Two identical extents produce `EQUALS`, which would also
  appear under an implementation that never called `relate` and simply paired
  everything up.
- **Assert `BEFORE` is absent** from a graph containing two disjoint dated
  entities. `_DRAWN_RELATIONS` is the only thing keeping the drawing legible,
  and an exemption that is never checked stops holding silently.
- **One entity with no extent and one with an empty one**, both present as
  nodes and absent from every inferred edge. Most entities in a real graph are
  not events; undated members taking no part is the ordinary case, not the
  edge case.
- **A merged pair in `neighborhood`**, asserting no self-`EQUALS`. This is the
  third bullet in §3 and is the one no other test in the suite would catch.

Before trusting any of it: delete the `_inferred_edges` call from `whole` and
watch the suite go red. A test that stays green under a deliberate break is
evidence about the fixture, not about the code.

## Out of scope

`TemporalQuery` (`redstring.temporal.query`) answers "what did this graph hold
over this interval" — a time-sliced read that pages the whole tenant and
filters in Python, which redstring's own B48 records as linear in entity count
regardless of how few entities are dated. That is the timeline view `BEFORE`
belongs in. It is a separate read with a separate cost profile and does not
belong behind `GraphReadPort.whole`.
