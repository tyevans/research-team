"""Every name an entity may appear under in the corpus.

`find_aliases` returns *direct* absorptions only -- it answers "which entities
did this merge absorb", the question `ConsolidationLog` undo asks, and a
transitive answer would make that unanswerable. `known_names` asks a different
question: "under what spellings might a document call this entity", which
needs the whole chain, not one hop of it. This module is the first caller of
`find_aliases` for that second question, so there is no local precedent to
follow -- the recursion below is new, not copied.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from redstring.ports.graph_store import GraphStore


async def known_names(graph: GraphStore, entity_id: UUID, tenant_id: UUID) -> list[str]:
    """Every name this entity may appear under in the corpus, canonical first.

    Order is not cosmetic: Task 5 queries the corpus once per name and fuses
    the results by score, and ties broken toward the canonical spelling read
    better than ties broken arbitrarily.

    Walks the alias graph breadth-first from `entity_id`, because
    `find_aliases` only returns direct absorptions -- an entity that absorbed
    an entity that had itself absorbed another loses the deepest name unless
    this recurses, and that deepest name is exactly the obsolete spelling an
    old document is most likely to use.

    A `seen` set bounds the walk. Nothing in `AliasStore`'s contract promises
    the alias graph is acyclic (only `resolve_entity_ids`, a different method,
    is guaranteed terminating) -- a cycle here would otherwise hang a request
    rather than return a wrong answer, and a hang is the worse failure of the
    two: it reads as infrastructure trouble and gets retried instead of
    investigated.

    Ids are compared with `==`, never `is`. Both existing alias call sites in
    this repo (`graph_reader.py`, `redstring_adapter.py`) carry the same
    warning: an adapter may hand back a rebuilt `UUID` for an id it already
    holds, and `is` would then be false against an equal id -- the walk would
    silently terminate early, which looks like a correct answer and is not.
    """
    seen: set[UUID] = {entity_id}
    names: list[str] = []

    entity = await graph.get_entity(entity_id, tenant_id)
    if entity is not None:
        names.append(entity.name)

    frontier = [entity_id]
    while frontier:
        current = frontier.pop()
        for alias in await graph.find_aliases(current, tenant_id):
            if any(alias.alias_entity_id == known for known in seen):
                continue
            seen.add(alias.alias_entity_id)
            frontier.append(alias.alias_entity_id)
            if alias.alias_name is not None:
                names.append(alias.alias_name)

    # `dict.fromkeys` dedupes while preserving first-seen order, which is
    # what keeps the canonical name first even if it also shows up as some
    # alias's recorded name (e.g. a merge undone and redone under the same
    # spelling).
    return list(dict.fromkeys(names))


async def absorbed_ids(graph: GraphStore, entity_id: UUID, tenant_id: UUID) -> list[UUID]:
    """Every id this entity now stands for, including its own, canonical first.

    The mirror of `known_names`, over ids rather than spellings, and it exists
    for a defect that spelling could not reach: a `StoredChunk`'s `entity_ids`
    are **pre-consolidation**. redstring's extraction pipeline reads them off
    `map_extraction`'s return, before `merge_extractions` and long before
    `Consolidator.resolve`, and nothing ever rewrites a stored chunk. So a
    passage that produced an entity later absorbed into another records the
    *absorbed* id, while every graph read returns canonical entities only.

    Two consequences follow, and a caller needs both halves:

    - `get_by_entity(canonical)` misses that passage entirely, because the
      chunk is keyed by the absorbed id.
    - Intersecting a chunk's ids against a set of canonical ids drops the
      absorbed one, so a passage naming two entities that were merged into
      one and one other reads as naming one -- below any co-mention threshold.

    Walks breadth-first for `known_names`' reason: `find_aliases` answers
    directly-absorbed only, so `C` absorbing `A` which had absorbed `B` loses
    `B` unless this recurses -- and `B` is exactly the oldest spelling, so the
    oldest passages are the ones that go missing.

    `seen` bounds the walk. `AliasStore.resolve_entity_ids` is the method whose
    contract promises termination; `find_aliases` makes no such promise, and a
    hang here reads as infrastructure trouble and gets retried rather than
    investigated.

    Ids are compared with `==`, never `is`: an adapter may hand back a rebuilt
    `UUID` for an id it already holds, and `is` would terminate the walk early
    -- which looks like a correct answer and is not.
    """
    seen: list[UUID] = [entity_id]
    frontier = [entity_id]
    while frontier:
        current = frontier.pop()
        for alias in await graph.find_aliases(current, tenant_id):
            if any(alias.alias_entity_id == known for known in seen):
                continue
            seen.append(alias.alias_entity_id)
            frontier.append(alias.alias_entity_id)
    return seen
