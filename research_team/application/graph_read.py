"""Browsing the knowledge graph, in this application's own terms.

`GraphStore` has exactly one read method reachable from the agent side:
`search`, and it is documented there as "entry points, not traversal" -- a
model asks it for a place to start, never for a place to wander. Nothing
today can browse the graph outward from an entry point. This port is that
browse.

**Why a new port, not more methods on `KnowledgePort`.** `KnowledgePort` is
the agent's graph vocabulary: `ingest`, `search`, `undo_merge`, nothing else,
because every method on it is something a tool can invoke and a prompt can
be written against. Traversal is a reader's operation -- a human or a UI
walking the graph a project's tools already built, not the agent building
it -- and it needs a `tenant_id` besides. `KnowledgePort` gets its tenant
implicitly, the same way `CorpusReadPort` does: an instance is bound to one
project at construction, so the *only* project a caller can ever traverse is
the one it was handed. Threading a `tenant_id` parameter through the
agent-facing port to get there would expose a knob no tool should ever be
allowed to turn -- a model that could set it could read another project's
graph, which is exactly the failure `KnowledgePort`'s implicit binding
exists to make impossible. Keeping it in a separate port with its own
implicit binding gets the same guarantee for a second caller without
touching the first.

**Depth is clamped here, not only at whatever route calls this.** `neighbors`
on a well-connected entity can return most of the graph at `depth=2`, all of
it well past that -- and a route is not the last thing that can ask for
`depth=5`. `MAX_NEIGHBORHOOD_DEPTH` is enforced inside `neighborhood` itself
so no caller of this port, present or future, can bypass it by skipping a
layer above.

**One call, not one per node.** `neighborhood` resolves every edge among the
entities it is about to return in a single `get_relationships_for` call over
that entity set, then keeps only the edges whose *both* ends survived into
the result. An edge to a node the caller was not given is an edge it cannot
draw -- a client forced to discover its own wiring one request at a time
would issue a call per node and render a graph that flickers into shape
instead of arriving whole.
"""

from dataclasses import dataclass
from typing import Protocol

#: `neighbors` on a hub entity can pull in most of a well-populated graph
#: well before this bound; enforced inside the port itself, not left for a
#: route to remember to check.
MAX_NEIGHBORHOOD_DEPTH = 2


@dataclass(frozen=True)
class GraphEntity:
    """One entity, in the shape a browser needs and nothing more.

    This port's own type rather than the domain `Entity` `CorpusReadPort`
    reuses: `Entity` is a pydantic model carrying extraction provenance,
    confidence, blocking keys -- write-side detail a browser has no use for
    and that would make this port's surface grow every time redstring's
    entity shape does. `entity_id` is a plain `str` for the same reason
    `neighborhood` takes one: nothing above this layer should have to import
    `redstring.domain.ids.EntityId` to call it.
    """

    entity_id: str
    name: str
    entity_type: str


@dataclass(frozen=True)
class GraphRelationship:
    """One edge, stripped to what a browser draws: two ends and a label."""

    source_id: str
    target_id: str
    relationship_type: str


@dataclass(frozen=True)
class EntityPage:
    """One page of `find_entities`, with the cursor for the next one.

    `next_after` is `None` when this page reached the end -- the same
    "absent means finished" shape `GraphStore.find_entities`'s own `after`
    cursor uses, so a caller does not need a separate has-more flag.
    """

    entities: tuple[GraphEntity, ...]
    next_after: str | None


@dataclass(frozen=True)
class Neighborhood:
    """A root entity, what is reachable from it, and how they connect.

    `root` is not repeated inside `entities` -- `GraphStore.neighbors` never
    returns the origin either, and duplicating it here would just be a second
    place for a caller to wonder whether the root counts towards a size
    limit it does not actually count towards.
    """

    root: GraphEntity
    entities: tuple[GraphEntity, ...]
    relationships: tuple[GraphRelationship, ...]


class GraphReadPort(Protocol):
    """One project's knowledge graph, browsed rather than searched.

    Both methods speak in this module's own `GraphEntity`/`GraphRelationship`
    rather than redstring's `Entity`/`Relationship`, unlike `CorpusReadPort`,
    which reuses the domain's own `DocumentRecord`. The two cases differ:
    `DocumentRecord` is *this application's* domain type, defined for the
    corpus aggregate and safe to depend on everywhere. `Entity` and
    `Relationship` belong to redstring, an infrastructure dependency: naming
    them here would make every route and every future consumer of this port
    import a third-party package to describe a browser result, and would
    make a redstring schema change a change to this port's contract instead
    of an implementation detail underneath it.
    """

    async def find_entities(
        self,
        *,
        name: str | None = None,
        entity_type: str | None = None,
        limit: int = 100,
        after: str | None = None,
    ) -> EntityPage:
        """Entry points into the graph: entities matching every filter given.

        Mirrors `GraphStore.find_entities`'s own filtering and cursor
        contract -- `name` and `entity_type` combine with AND, `after`
        resumes strictly after that id in the store's total order. This is
        where a browser starts before it has anything to traverse from.
        """
        ...

    async def neighborhood(self, entity_id: str, *, depth: int = 1) -> Neighborhood | None:
        """`entity_id` and what lies within `depth` hops of it, fully wired.

        `None` when this project has no such entity -- a model or a client
        guessing at an id is the ordinary case here, the same reasoning
        `CorpusReadPort.read_document` gives for its own `None`, not a
        failure worth an exception.

        `depth` is clamped to `MAX_NEIGHBORHOOD_DEPTH` before it reaches
        storage, silently rather than by raising: a caller asking for more
        than the cap is asking a reasonable question with an unreasonable
        radius, and the useful answer is the largest neighborhood this port
        is willing to hand back, not an error that discards the id.
        """
        ...
