"""`ProjectGraphReader`: `GraphReadPort` over a live redstring `GraphStore`.

The one module besides `redstring_adapter.py` that imports redstring's
domain types directly, for the same reason that one is the sole importer on
the write side: everything above `GraphReadPort` speaks this application's
own `GraphEntity`/`GraphRelationship`, and the translation from redstring's
`Entity`/`Relationship` has to happen somewhere.
"""

from typing import Any
from uuid import UUID

from eventsource.domain.tenant_context import tenant_scope
from redstring import TemporalRelation, infer_relations

from research_team.application.graph_read import (
    MAX_GRAPH_NODES,
    MAX_INFERRED_EDGES,
    MAX_NEIGHBORHOOD_DEPTH,
    EntityPage,
    Graph,
    GraphEntity,
    GraphRelationship,
    Neighborhood,
)
from research_team.infrastructure.knowledge.temporal_rendering import render_extent

#: The only relations `infer_relations` produces that are worth a line on the
#: canvas. It emits four -- `BEFORE`, `CONTAINS`, `OVERLAPS`, `EQUALS` -- of
#: `TemporalRelation`'s six, canonicalising each dated pair to one edge:
#: `AFTER` arrives here as its target's `BEFORE`, and `DURING` as its
#: target's `CONTAINS`. So this set is complete against what can ever be
#: emitted, not a subset that still needs `AFTER`/`DURING` added -- those two
#: would be config that can never fire.
#:
#: `BEFORE` is excluded on purpose, not by omission. It is the relation
#: nearly every pair of dated entities in a real corpus satisfies: a hundred
#: dated entities is on the order of 4,950 `BEFORE` pairs against at most 500
#: nodes, and a force-directed layout given that many edges resolves to a
#: solid disc rather than a graph. `CONTAINS`, `OVERLAPS` and `EQUALS` are the
#: relations that are still sparse at that scale, because they require the
#: two extents to actually coincide rather than merely be ordered.
_DRAWN_RELATIONS = frozenset(
    {TemporalRelation.CONTAINS, TemporalRelation.OVERLAPS, TemporalRelation.EQUALS}
)


def _to_graph_entity(entity: Any) -> GraphEntity:
    return GraphEntity(
        entity_id=str(entity.id),
        name=entity.name,
        entity_type=entity.entity_type,
        temporal=render_extent(entity.temporal),
    )


def _to_graph_relationship(relationship: Any) -> GraphRelationship:
    return GraphRelationship(
        source_id=str(relationship.source_entity_id),
        target_id=str(relationship.target_entity_id),
        relationship_type=relationship.relationship_type,
    )


def _inferred_edges(entities: list[Any]) -> tuple[tuple[GraphRelationship, ...], bool]:
    """Temporal edges among `entities`, plus whether the cap dropped any.

    No store round trip: `infer_relations` is pure arithmetic over the
    extents already carried on `entities`, the same set `whole`/`neighborhood`
    already fetched. Returning the cap's verdict alongside the edges rather
    than leaving a caller to compare `len(edges)` to `MAX_INFERRED_EDGES`
    avoids the same off-by-one `whole`'s own truncation test guards against --
    a result that lands exactly at the cap is complete, not truncated, and a
    length comparison alone cannot tell those apart.
    """
    relations = infer_relations(entities, relations=_DRAWN_RELATIONS)
    capped = relations[:MAX_INFERRED_EDGES]
    edges = tuple(
        GraphRelationship(
            source_id=str(relation.source_entity_id),
            target_id=str(relation.target_entity_id),
            relationship_type=relation.relation.value,
            inferred=True,
            # The verb between the two extents, not a separator standing in
            # for it: "1923 contains November 1923" tells a reader which of
            # the three drawn relations the line asserts, where "1923 /
            # November 1923" would not. `render_extent` can in principle
            # return `None` for an extent with no `start_date` -- none of
            # `_DRAWN_RELATIONS` is expected to pair a dated entity with one
            # of those, so this falls back to the empty string rather than
            # add a branch for a case `infer_relations` is not believed to
            # produce.
            derivation=f"{render_extent(relation.source_extent) or ''} "
            f"{relation.relation.value} "
            f"{render_extent(relation.target_extent) or ''}",
        )
        for relation in capped
    )
    return edges, len(relations) > len(capped)


class ProjectGraphReader:
    """`GraphReadPort` for one project, over the `GraphStore` `ProjectGraphs` opened.

    Bound to a `project_id` at construction, the same shape `RedstringAdapter`
    uses it in: the project a caller can traverse is fixed by which reader it
    was handed, not by anything a caller passes per call.
    """

    def __init__(self, *, project_id: UUID, store: Any) -> None:
        self._project_id = project_id
        self._store = store

    async def _without_aliases(self, entities: list[Any]) -> list[Any]:
        """`entities` with everything merged away removed.

        **A merge is not a delete.** `GraphStore.find_entities` returns
        absorbed entities as well as canonical ones, deliberately -- the row is
        what `undo_merge` restores, so deleting it would make the undo
        impossible. That contract is right for a store and wrong for a browser:
        without this filter a *correctly* consolidated pair still draws as two
        nodes, the canonical one carrying every edge and the alias sitting
        beside it with none, because the merge redirected them. An isolated
        node bearing a name that is already on the canvas is precisely the
        duplicate a reader reports.

        Filtered here rather than pushed into the store because no `GraphStore`
        method takes "canonical only" -- `resolve_entity_ids` is the whole
        mechanism redstring offers, and it is one call for the batch. Costs one
        extra round trip per read, against an adapter that already returns the
        tenant's entire entity set; it is the same thing to revisit behind
        Neo4j as the note on `find_entities` describes.

        `==`, not `is`: `resolve_entity_ids` may hand back a rebuilt `UUID` for
        an id that is not an alias, and `is` would then filter out *every*
        entity and draw an empty graph. redstring's own `CandidateFinder`
        carries the same warning over the same call, having been bitten by it.
        """
        if not entities:
            return []
        canonical = await self._store.resolve_entity_ids(
            [entity.id for entity in entities], self._project_id
        )
        return [entity for entity in entities if canonical[entity.id] == entity.id]

    async def find_entities(
        self,
        *,
        name: str | None = None,
        entity_type: str | None = None,
        limit: int = 100,
        after: str | None = None,
    ) -> EntityPage:
        """Entry points into the graph, `name` given the same give a human
        typing into a search box needs.

        `GraphStore.find_entities(name=...)` matches `normalized_name` by
        exact equality -- no substring, no case-insensitivity -- which is a
        contract nobody typing a partial name into a browser could satisfy.
        `RedstringKnowledge.search` hit the identical problem for the agent's
        own free-text tool and filters in Python for exactly this reason;
        there is no reason a human's search box should be held to a stricter
        contract than the agent's. `entity_type` stays pushed to the store,
        because it is an exact match by nature -- a caller picks a type from
        a fixed vocabulary, never types a fragment of one.

        The cost is worse than `search`'s: `limit` is deliberately not passed
        to the store call below (the cursor invariant depends on filtering
        happening after the store returns, not before), so both adapters
        return the tenant's *entire* entity set on every call, not a page of
        it. Acceptable against an in-memory store; the first thing to revisit
        behind Neo4j, where fetching the whole tenant stops being free.
        """
        after_id = UUID(after) if after is not None else None
        async with tenant_scope(self._project_id):
            entities = await self._store.find_entities(
                self._project_id,
                entity_type=entity_type,
                after=after_id,
            )
            # Before the `name` filter and before the page slice, so the cursor
            # counts only entities a caller can actually be handed. An alias
            # left in and dropped later would make a full page look short.
            entities = await self._without_aliases(list(entities))
        if name is not None:
            needle = name.strip().lower()
            entities = [entity for entity in entities if needle in entity.name.lower()]
        page = tuple(_to_graph_entity(entity) for entity in entities[:limit])
        # A page that came back short of `limit` is the last one -- the same
        # signal `GraphStore.find_entities`'s own cursor contract relies on,
        # so there is nothing further to resume from.
        next_after = page[-1].entity_id if len(page) == limit else None
        return EntityPage(entities=page, next_after=next_after)

    async def whole(self, *, limit: int = MAX_GRAPH_NODES) -> Graph:
        """The project's whole graph, capped at `limit` entities.

        The truncation test reads one entity past the cap rather than
        comparing the kept count to `limit`: those two are only the same when
        the store holds strictly more than `limit`, and a graph of exactly
        `limit` entities would be reported as truncated by the comparison
        despite being complete. `find_entities` already returns the tenant's
        entire entity set (see the note on `find_entities` above), so the
        extra entity costs nothing to look at.
        """
        capped = min(limit, MAX_GRAPH_NODES)
        async with tenant_scope(self._project_id):
            entities = await self._store.find_entities(self._project_id)
            # Aliases go before the cap, not after: they are not nodes, so
            # counting them toward `limit` would report a graph as truncated
            # because of entities that were never going to be drawn.
            entities = await self._without_aliases(list(entities))
            kept = entities[:capped]
            entity_ids = [entity.id for entity in kept]
            # Skipped entirely for an empty graph: an adapter asked for the
            # relationships of no entities has no useful answer to give, and
            # a new project with nothing extracted yet is the commonest way
            # to reach this route at all.
            relationships = (
                await self._store.get_relationships_for(entity_ids, self._project_id)
                if entity_ids
                else []
            )

        returned_ids = set(entity_ids)
        edges = tuple(
            _to_graph_relationship(relationship)
            for relationship in relationships
            if relationship.source_entity_id in returned_ids
            and relationship.target_entity_id in returned_ids
        )
        # Over `kept`, not `entities`: an entity the cap already excluded is
        # not on the canvas, so a temporal edge to it would be exactly the
        # dangling reference `returned_ids` above exists to prevent.
        inferred, inferred_truncated = _inferred_edges(kept)
        return Graph(
            entities=tuple(_to_graph_entity(entity) for entity in kept),
            relationships=edges + inferred,
            truncated=len(entities) > capped,
            inferred_truncated=inferred_truncated,
        )

    async def neighborhood(self, entity_id: str, *, depth: int = 1) -> Neighborhood | None:
        try:
            root_id = UUID(entity_id)
        except ValueError:
            return None

        capped_depth = min(depth, MAX_NEIGHBORHOOD_DEPTH)
        async with tenant_scope(self._project_id):
            root = await self._store.get_entity(root_id, self._project_id)
            if root is None:
                return None
            neighbors = await self._store.neighbors(
                root_id, self._project_id, depth=capped_depth
            )
            # Absorbed entities dropped here, as `whole` already drops them --
            # see `_without_aliases`. Costs one `resolve_entity_ids` round trip
            # per read, which is what `whole` already pays.
            neighbors = await self._without_aliases(list(neighbors))

            # Every edge among the entities this call is about to return, in
            # one round trip -- resolved over the *result* set (root plus its
            # neighbors), which is exactly what makes it safe to keep only
            # edges whose both ends survived into that set.
            entity_ids = [root_id, *(entity.id for entity in neighbors)]
            relationships = await self._store.get_relationships_for(
                entity_ids, self._project_id
            )

        returned_ids = {root_id} | {entity.id for entity in neighbors}
        edges = tuple(
            _to_graph_relationship(relationship)
            for relationship in relationships
            if relationship.source_entity_id in returned_ids
            and relationship.target_entity_id in returned_ids
        )
        # Over root plus neighbors, same as the stored edges above. The cap
        # flag is discarded, not threaded through: `Neighborhood` has no
        # `inferred_truncated` field. That is not because a neighborhood is
        # bounded to something far smaller than `MAX_INFERRED_EDGES` -- it
        # isn't: `self._store.neighbors` applies no `MAX_GRAPH_NODES` and no
        # cap of its own, so a depth-2 traversal from a hub can return
        # thousands of entities, and this branch's own test trips the cap at
        # 65 entities sharing one era. The omission stands because, unlike
        # `whole`, a neighborhood is never the caller's only view of the
        # graph -- a reader can always widen the search -- so an unmeasured
        # risk of a silently short list here is judged acceptable rather
        # than proven safe.
        inferred, _inferred_truncated = _inferred_edges([root, *neighbors])
        return Neighborhood(
            root=_to_graph_entity(root),
            entities=tuple(_to_graph_entity(entity) for entity in neighbors),
            relationships=edges + inferred,
        )
