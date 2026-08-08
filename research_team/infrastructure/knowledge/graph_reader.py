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

from research_team.application.graph_read import (
    MAX_NEIGHBORHOOD_DEPTH,
    EntityPage,
    GraphEntity,
    GraphRelationship,
    Neighborhood,
)


def _to_graph_entity(entity: Any) -> GraphEntity:
    return GraphEntity(
        entity_id=str(entity.id),
        name=entity.name,
        entity_type=entity.entity_type,
    )


def _to_graph_relationship(relationship: Any) -> GraphRelationship:
    return GraphRelationship(
        source_id=str(relationship.source_entity_id),
        target_id=str(relationship.target_entity_id),
        relationship_type=relationship.relationship_type,
    )


class ProjectGraphReader:
    """`GraphReadPort` for one project, over the `GraphStore` `ProjectGraphs` opened.

    Bound to a `project_id` at construction, the same shape `RedstringAdapter`
    uses it in: the project a caller can traverse is fixed by which reader it
    was handed, not by anything a caller passes per call.
    """

    def __init__(self, *, project_id: UUID, store: Any) -> None:
        self._project_id = project_id
        self._store = store

    async def find_entities(
        self,
        *,
        name: str | None = None,
        entity_type: str | None = None,
        limit: int = 100,
        after: str | None = None,
    ) -> EntityPage:
        after_id = UUID(after) if after is not None else None
        async with tenant_scope(self._project_id):
            entities = await self._store.find_entities(
                self._project_id,
                name=name,
                entity_type=entity_type,
                limit=limit,
                after=after_id,
            )
        page = tuple(_to_graph_entity(entity) for entity in entities)
        # A page that came back short of `limit` is the last one -- the same
        # signal `GraphStore.find_entities`'s own cursor contract relies on,
        # so there is nothing further to resume from.
        next_after = page[-1].entity_id if len(page) == limit else None
        return EntityPage(entities=page, next_after=next_after)

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
            neighbors = await self._store.neighbors(root_id, self._project_id, depth=capped_depth)

            # Every edge among the entities this call is about to return, in
            # one round trip -- resolved over the *result* set (root plus its
            # neighbors), which is exactly what makes it safe to keep only
            # edges whose both ends survived into that set.
            entity_ids = [root_id, *(entity.id for entity in neighbors)]
            relationships = await self._store.get_relationships_for(entity_ids, self._project_id)

        returned_ids = {root_id} | {entity.id for entity in neighbors}
        edges = tuple(
            _to_graph_relationship(relationship)
            for relationship in relationships
            if relationship.source_entity_id in returned_ids
            and relationship.target_entity_id in returned_ids
        )
        return Neighborhood(
            root=_to_graph_entity(root),
            entities=tuple(_to_graph_entity(entity) for entity in neighbors),
            relationships=edges,
        )
