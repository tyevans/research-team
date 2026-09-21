"""Temporal edge inference and inferred edge cap tests for `ProjectGraphReader`.

Extracted from `test_graph_read.py`. Covers Allen-interval temporal edge
generation, suppression of non-drawn relations (like `BEFORE`), handling of
undated entities, merge/alias loop suppression, and inferred edge truncation
bounds.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from redstring import (
    Alias,
    DatePrecision,
    Entity,
    ExtractionMethod,
    InMemoryGraphStore,
    Provenance,
    Relationship,
    TemporalExtent,
)

from research_team.infrastructure.knowledge.graph_reader import ProjectGraphReader
from research_team.knowledge.application.graph_read import MAX_INFERRED_EDGES

TENANT_ID = uuid4()


def _entity(
    entity_id,
    name: str,
    entity_type: str = "person",
    *,
    temporal: TemporalExtent | None = None,
) -> Entity:
    return Entity(
        id=entity_id,
        tenant_id=TENANT_ID,
        name=name,
        normalized_name=name.lower(),
        entity_type=entity_type,
        provenance=Provenance(
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            extraction_method=ExtractionMethod.MANUAL,
            confidence=1.0,
        ),
        temporal=temporal,
    )


def _relationship(
    relationship_id, source_id, target_id, relationship_type: str
) -> Relationship:
    return Relationship(
        id=relationship_id,
        tenant_id=TENANT_ID,
        source_entity_id=source_id,
        target_entity_id=target_id,
        relationship_type=relationship_type,
        confidence=1.0,
    )


@pytest.fixture
def graph_reader():
    store = InMemoryGraphStore()
    return ProjectGraphReader(project_id=TENANT_ID, store=store), store


def _year(year: int) -> TemporalExtent:
    return TemporalExtent(
        start_date=datetime(year, 1, 1, tzinfo=UTC),
        end_date=datetime(year, 12, 31, tzinfo=UTC),
        precision=DatePrecision.YEAR,
    )


def _month(year: int, month: int) -> TemporalExtent:
    return TemporalExtent(
        start_date=datetime(year, month, 1, tzinfo=UTC),
        precision=DatePrecision.MONTH,
    )


async def _merge_away(store, *, alias_id, canonical_id):
    await store.upsert_alias(
        Alias(
            id=uuid4(),
            tenant_id=TENANT_ID,
            canonical_entity_id=canonical_id,
            alias_entity_id=alias_id,
            merged_at=datetime.now(UTC),
            merge_reason="the same thing under two names",
        )
    )


async def test_a_temporal_edge_appears_between_entities_the_store_never_related(graph_reader):
    """Inference ran, as opposed to a stored edge acquiring a flag.

    The pair here has *no* stored relationship, which is what makes that
    distinction checkable: an implementation that only labelled stored edges
    produces nothing at all for this pair.

    The extents are a year and a month inside it, so the relation is
    `CONTAINS`. Two identical extents would give `EQUALS`, which would also
    appear under an implementation that never compared anything and simply
    paired every dated entity up.
    """
    reader, store = graph_reader
    era_id, event_id = uuid4(), uuid4()
    await store.upsert_entities(
        [
            _entity(era_id, "The Weimar Republic", temporal=_year(1923)),
            _entity(event_id, "Hyperinflation Peaks", temporal=_month(1923, 11)),
        ]
    )

    graph = await reader.whole()

    inferred = [edge for edge in graph.relationships if edge.inferred]
    assert len(inferred) == 1
    edge = inferred[0]
    assert {edge.source_id, edge.target_id} == {str(era_id), str(event_id)}
    assert edge.relationship_type == "contains"
    assert edge.derivation is not None


async def test_a_stored_edge_between_the_same_pair_is_still_asserted(graph_reader):
    """The other half of the pair above. Same two entities, related in the
    store as well -- the stored edge must come back with `inferred=False` and
    no derivation, alongside the computed one rather than instead of it."""
    reader, store = graph_reader
    era_id, event_id = uuid4(), uuid4()
    await store.upsert_entities(
        [
            _entity(era_id, "The Weimar Republic", temporal=_year(1923)),
            _entity(event_id, "Hyperinflation Peaks", temporal=_month(1923, 11)),
        ]
    )
    await store.upsert_relationships([_relationship(uuid4(), era_id, event_id, "encompassed")])

    graph = await reader.whole()

    asserted = [edge for edge in graph.relationships if not edge.inferred]
    inferred = [edge for edge in graph.relationships if edge.inferred]
    assert len(asserted) == 1
    assert asserted[0].relationship_type == "encompassed"
    assert asserted[0].derivation is None
    assert len(inferred) == 1
    assert inferred[0].relationship_type == "contains"


async def test_before_is_not_drawn(graph_reader):
    """Two disjoint dated entities produce no edge at all.

    `_DRAWN_RELATIONS` is the only thing keeping the drawing legible -- 100
    dated entities is on the order of 4,950 `BEFORE` edges against at most 500
    nodes, and a force-directed layout given that resolves to a solid disc. An
    exemption nobody checks stops holding silently.
    """
    reader, store = graph_reader
    earlier_id, later_id = uuid4(), uuid4()
    await store.upsert_entities(
        [
            _entity(earlier_id, "Treaty Signed", temporal=_year(1918)),
            _entity(later_id, "Armistice Anniversary", temporal=_year(1938)),
        ]
    )

    graph = await reader.whole()

    assert [edge for edge in graph.relationships if edge.inferred] == []


async def test_undated_entities_are_drawn_and_take_no_part(graph_reader):
    """One entity with no extent and one with an empty one, alongside a dated
    pair that *does* infer an edge: both undated entities present as nodes,
    both absent from every inferred edge, and the dated pair proves the
    assertion actually ran. Most entities in a real graph are not events, so
    the undated pair is the ordinary case rather than the edge case -- but a
    fixture with only one dated entity can infer nothing at all, which would
    let this pass with `_inferred_edges` deleted outright."""
    reader, store = graph_reader
    undated_id, empty_id, era_id, event_id = uuid4(), uuid4(), uuid4(), uuid4()
    await store.upsert_entities(
        [
            _entity(undated_id, "No Extent At All"),
            _entity(empty_id, "Empty Extent", temporal=TemporalExtent()),
            _entity(era_id, "The Weimar Republic", temporal=_year(1923)),
            _entity(event_id, "Hyperinflation Peaks", temporal=_month(1923, 11)),
        ]
    )

    graph = await reader.whole()

    assert {entity.entity_id for entity in graph.entities} == {
        str(undated_id),
        str(empty_id),
        str(era_id),
        str(event_id),
    }
    inferred = [edge for edge in graph.relationships if edge.inferred]
    assert inferred, "the dated pair should have produced an inferred edge"
    for edge in inferred:
        assert str(undated_id) not in (edge.source_id, edge.target_id)
        assert str(empty_id) not in (edge.source_id, edge.target_id)


async def test_a_merged_pair_infers_no_edge_to_itself(graph_reader):
    """The alias fix and inference, together, in `neighborhood`.

    Inference knows nothing about merges and an absorbed entity keeps its own
    `temporal`, so without Task 4 a canonical entity and its own alias produce
    an `EQUALS` between what is really one thing -- a duplicate node wired to
    itself. Reverting Task 4 turns this red.
    """
    reader, store = graph_reader
    root_id, canonical_id, alias_id = uuid4(), uuid4(), uuid4()
    same_date = _year(1923)
    await store.upsert_entities(
        [
            _entity(root_id, "Root", temporal=_year(1920)),
            _entity(canonical_id, "Weimar Republic", temporal=same_date),
            _entity(alias_id, "Weimar Republic", temporal=same_date),
        ]
    )
    await store.upsert_relationships(
        [
            _relationship(uuid4(), root_id, canonical_id, "related_to"),
            _relationship(uuid4(), root_id, alias_id, "related_to"),
        ]
    )
    await _merge_away(store, alias_id=alias_id, canonical_id=canonical_id)

    hood = await reader.neighborhood(str(root_id), depth=1)

    for edge in hood.relationships:
        assert str(alias_id) not in (edge.source_id, edge.target_id)


async def test_the_inferred_edge_cap_drops_lines_but_never_asserted_edges(graph_reader):
    """`inferred_truncated` actually reflects the slice, not just the flag's
    default.

    65 entities sharing one identical extent produce `65 * 64 / 2 = 2,080`
    `EQUALS` pairs -- over `MAX_INFERRED_EDGES` (2,000) and comfortably under
    `MAX_GRAPH_NODES` (500), so the node cap never gets in the way of
    reaching the edge cap. A stored relationship among the same entities is
    seeded alongside them, so "asserted edges are never sacrificed to make
    room for inferred ones" is asserted here rather than merely implied by
    the slice being taken from the inferred list alone.
    """
    reader, store = graph_reader
    same_date = _year(1923)
    ids = [uuid4() for _ in range(65)]
    await store.upsert_entities(
        [_entity(i, f"Node {n}", temporal=same_date) for n, i in enumerate(ids)]
    )
    await store.upsert_relationships([_relationship(uuid4(), ids[0], ids[1], "next")])

    graph = await reader.whole()

    inferred = [edge for edge in graph.relationships if edge.inferred]
    asserted = [edge for edge in graph.relationships if not edge.inferred]
    assert len(inferred) == MAX_INFERRED_EDGES
    assert len(asserted) == 1
    assert graph.inferred_truncated is True


async def test_a_graph_under_the_inferred_edge_cap_is_not_reported_truncated(graph_reader):
    """The other half of the boundary: nothing dropped means the flag stays
    false, the same "complete unless it says otherwise" contract `truncated`
    already gives entities."""
    reader, store = graph_reader
    same_date = _year(1923)
    ids = [uuid4() for _ in range(5)]
    await store.upsert_entities(
        [_entity(i, f"Node {n}", temporal=same_date) for n, i in enumerate(ids)]
    )

    graph = await reader.whole()

    inferred = [edge for edge in graph.relationships if edge.inferred]
    assert len(inferred) == 5 * 4 // 2
    assert graph.inferred_truncated is False
