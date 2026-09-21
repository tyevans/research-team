"""Entity search and description query operations over the knowledge graph."""

from collections.abc import Sequence
from uuid import UUID

from eventsource.domain.tenant_context import tenant_scope
from redstring import (
    ChunkStore,
    GraphStore,
    RedstringError,
    RetrievalMode,
    Retriever,
    rank_chunks,
    tokenize,
)

from research_team.knowledge.application import (
    KnowledgeError,
    Match,
    SearchMode,
    SearchOutcome,
)


async def count_relationships(
    store: GraphStore,
    project_id: UUID,
    entity_ids: Sequence[UUID],
) -> dict[UUID, int]:
    """Count relationships for a sequence of entities in one round-trip."""
    edges = await store.get_relationships_for(entity_ids, project_id) if entity_ids else []
    counts: dict[UUID, int] = dict.fromkeys(entity_ids, 0)
    for edge in edges:
        for endpoint in (edge.source_entity_id, edge.target_entity_id):
            if endpoint in counts:
                counts[endpoint] += 1
    return counts


async def search_entities(
    store: GraphStore,
    project_id: UUID,
    query: str,
    *,
    limit: int = 10,
) -> SearchOutcome:
    """Entities matching `query`, best first.

    Two channels, unioned: a substring test over the tenant's names, and
    `redstring.Retriever`'s **lexical** channel -- blocking keys over the
    name, scored by Jaro-Winkler.

    **The substring channel is neither redundant nor legacy.** Measured
    2026-08-21 against this adapter: `Retriever` finds `Adah Lovelace` for
    `Ada Lovelace`, which no substring test can reach, and misses both an
    interior fragment (`ovelace`) and a short prefix (`Ada`), which the
    substring test finds -- its lexical channel blocks on a five-character
    prefix of the normalized name plus a soundex of the whole name, and a
    fragment shares neither. Neither channel dominates, so both run.
    `test_search_finds_an_entity_by_an_interior_fragment` and its
    short-prefix sibling are what fail if this one is ever dropped for the
    library's class; the original reasoning still holds too --
    `find_entities(name=...)` matches `normalized_name` exactly, and a
    tool the agent drives with free text needs more give than that.

    Reordered names (`lovelace ada`) match in neither and are not a
    regression from this change: they returned nothing before it.
    See `BACKLOG.md` B-SEARCH-REORDER-1.

    `Retriever` ranks; the substring pass does not. So fused hits come
    first in `Retriever`'s order and substring-only hits follow in store
    order, and an entity found by both appears once, at its ranked
    position.

    **`RetrievalMode.LEXICAL`, not `HYBRID`, and that is a decision.**
    Turning the semantic channel on makes this tool answer with entities
    that match the query nowhere in their text: measured here, searching
    `Nova Scotia Duck Tolling Retriever` also returned `Duck hunting` and
    `Canada`. Three reasons not to:

    * The tool this backs is documented to the model as finding entities
      **by name**, and an agent counting what it found is misled -- which
      is not hypothetical, it is how this was noticed
      (`test_embedded_consolidation.py` uses `search` to assert that a
      duplicate merged into one node).
    * stark-bench I.2 measured a model shown entities unrelated to its
      query scoring **below** one shown none. Unrelated names are not
      free context; they are attention spent.
    * Retrieving an entity by *describing* it is a real capability and it
      is deliberately the next stage's, over a corpus built for it. A weak
      version here would move the baseline that stage has to be measured
      against.

    So the entity vectors `build_graph` writes are still read by exactly
    one consumer -- consolidation scoring. This stage does not change that.

    **`Retriever` is skipped entirely when embeddings are unavailable, and
    that is a wart rather than a design.** Its lexical channel needs no
    embedding at all, but `Retriever.__init__` takes an
    `EmbeddingProvider` and dimension-checks it against the vector store,
    so there is no way to ask for the lexical half alone. Calling
    `find_by_blocking_keys` and `lexical_score` directly -- the way
    `UsageReader` calls redstring's chunk-ranking internals, for this
    exact reason -- is not available either: neither name is exported, and
    `tests/test_architecture.py` refuses `redstring.domain.*`. So a
    deployment with `AGENT_VECTOR_STORE=none`, or one whose embedding
    probe failed, gets substring matching only. See `BACKLOG.md`
    B-LEXICAL-NEEDS-EMBEDDINGS-1.

    The page of entities per call is unchanged and is still the first
    thing to revisit behind Neo4j.
    """
    if limit < 1:
        raise KnowledgeError("limit must be at least 1")
    needle = query.strip().lower()
    if not needle:
        # `Retriever.retrieve` raises on a blank query and this returns
        # nothing, which is the older contract and the one the agent tool
        # depends on.
        return SearchOutcome(matches=(), mode=SearchMode.FUSED)

    try:
        async with tenant_scope(project_id):
            entities = await store.find_entities(project_id)
            # `find_entities` returns absorbed entities too -- a merge is
            # not a delete, because the row is what `undo_merge` restores.
            # Without this the agent's own search reports a consolidated
            # pair as two hits, one of which has had all its edges
            # redirected away and so answers `relationship_count=0`. The
            # same filter guards the browser's read in `graph_reader.py`;
            # both call sites exist because both read the store directly.
            canonical = await store.resolve_entity_ids(
                [entity.id for entity in entities], project_id
            )
            # `==`, not `is`: an adapter may rebuild the UUID for an id
            # that is not an alias, and `is` would filter out everything
            # and answer that the project is empty.
            by_id = {
                entity.id: entity for entity in entities if canonical[entity.id] == entity.id
            }

            # `lexical_only`, so this no longer waits on `_embedding_pair`.
            # The blocking-key channel reaches no vector, and requiring a
            # provider to construct a retriever that never calls one is
            # what used to make a mistyped embedding model silently cost
            # misspelling-tolerant search. See redstring B163 / ADR 0045.
            retrieved = await Retriever.lexical_only(graph=store).retrieve(
                query, project_id, k=limit, mode=RetrievalMode.LEXICAL
            )
            # A ranked id may name an absorbed entity, which `by_id` has
            # already dropped; skipping here rather than resolving keeps one
            # rule about what a match is.
            ordered: list[UUID] = [
                scored.entity.id for scored in retrieved.matches if scored.entity.id in by_id
            ]

            seen = set(ordered)
            ordered.extend(
                entity_id
                for entity_id, entity in by_id.items()
                if entity_id not in seen and needle in entity.name.lower()
            )
            ordered = ordered[:limit]

            # One read, not one per match. The previous shape issued a
            # `get_relationships_for` inside the match loop, which is N
            # round trips to answer one question and was invisible to
            # every test because the answers were identical either way.
            counts = await count_relationships(store, project_id, ordered)

            matches = [
                Match(
                    entity_id=entity_id,
                    name=by_id[entity_id].name,
                    entity_type=by_id[entity_id].entity_type,
                    relationship_count=counts[entity_id],
                )
                for entity_id in ordered
            ]
    except RedstringError as error:
        raise KnowledgeError(str(error)) from error
    return SearchOutcome(matches=tuple(matches), mode=SearchMode.FUSED)


async def describe_entities(
    *,
    cards: ChunkStore | None,
    store: GraphStore,
    project_id: UUID,
    query: str,
    limit: int = 10,
) -> SearchOutcome:
    """Entities whose *card* matches `query`, best first.

    BM25 over the entity-card corpus -- name, type, properties and the
    names of every neighbour -- which is what lets a query describe an
    entity instead of spelling it.

    The chunk's `entity_ids` is what maps a hit back, rather than reading
    the name off the card's first line: parsing would tie this to
    `card_text`'s formatting and break on the first name containing a
    newline. A chunk carrying no entity id is skipped rather than guessed
    at.

    Deduplicated by entity, keeping the best-scoring chunk. A long card is
    several chunks and a query naming two neighbours can match more than
    one of them; without this, one entity would fill the answer.
    """
    if limit < 1:
        raise KnowledgeError("limit must be at least 1")
    if cards is None:
        return SearchOutcome(matches=(), mode=SearchMode.UNAVAILABLE)
    terms = tokenize(query)
    if not terms:
        return SearchOutcome(matches=(), mode=SearchMode.CARDS)

    try:
        async with tenant_scope(project_id):
            found = await cards.lexical_candidates(terms, project_id, limit)
            best: dict[UUID, float] = {}
            for ranked in rank_chunks(terms, found, limit):
                for entity_id in ranked.chunk.entity_ids or ():
                    if best.get(entity_id, float("-inf")) < ranked.score:
                        best[entity_id] = ranked.score

            ordered = sorted(best, key=lambda key: -best[key])[:limit]
            entities = {
                entity.id: entity for entity in await store.get_entities(ordered, project_id)
            }
            counts = await count_relationships(store, project_id, ordered)

            matches = tuple(
                Match(
                    entity_id=entity_id,
                    name=entities[entity_id].name,
                    entity_type=entities[entity_id].entity_type,
                    relationship_count=counts[entity_id],
                )
                for entity_id in ordered
                if entity_id in entities
            )
    except RedstringError as error:
        raise KnowledgeError(str(error)) from error

    return SearchOutcome(matches=matches, mode=SearchMode.CARDS)
