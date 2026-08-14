"""`GraphReadPort` and `ProjectGraphReader`.

Seeded directly through `InMemoryGraphStore.upsert_entities` /
`upsert_relationships` -- no LLM, no extraction, no `ingest`. What is under
test is the read side, and the write side has its own coverage.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from redstring import (
    DatePrecision,
    Entity,
    ExtractionMethod,
    InMemoryGraphStore,
    Provenance,
    Relationship,
    TemporalExtent,
)

from research_team.application.graph_read import (
    MAX_GRAPH_NODES,
    MAX_INFERRED_EDGES,
    MAX_NEIGHBORHOOD_DEPTH,
    Graph,
    GraphEntity,
    GraphRelationship,
)
from research_team.infrastructure.knowledge.graph_reader import ProjectGraphReader

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
        # Fixed rather than `datetime.now`: nothing under test reads
        # `observed_at`, and a moving value in a fixture is a difference that
        # shows up in a failure diff without meaning anything.
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


@pytest.fixture
async def seeded_graph(graph_reader):
    """Prandtl, advised by nobody, advising von Kármán, both at Göttingen --
    plus an entity entirely outside the neighborhood, linked to von Kármán,
    to give the dangling-edge test something to drop.
    """
    _reader, store = graph_reader
    prandtl_id, karman_id, goettingen_id, outsider_id = uuid4(), uuid4(), uuid4(), uuid4()
    await store.upsert_entities(
        [
            _entity(prandtl_id, "Ludwig Prandtl"),
            _entity(karman_id, "Theodore von Kármán"),
            _entity(goettingen_id, "Göttingen", entity_type="place"),
            _entity(outsider_id, "Someone Two Hops Away"),
        ]
    )
    await store.upsert_relationships(
        [
            _relationship(uuid4(), prandtl_id, karman_id, "advised"),
            _relationship(uuid4(), prandtl_id, goettingen_id, "worked_at"),
            _relationship(uuid4(), karman_id, outsider_id, "advised"),
        ]
    )
    return {"prandtl_id": prandtl_id, "karman_id": karman_id, "outsider_id": outsider_id}


@pytest.fixture
async def deep_graph(graph_reader):
    """A chain five hops long, so depth=5 and depth=MAX_NEIGHBORHOOD_DEPTH
    provably differ unless the port clamps."""
    _reader, store = graph_reader
    ids = [uuid4() for _ in range(6)]
    await store.upsert_entities([_entity(i, f"Node {n}") for n, i in enumerate(ids)])
    await store.upsert_relationships(
        [_relationship(uuid4(), ids[n], ids[n + 1], "next") for n in range(5)]
    )
    return {"root_id": ids[0]}


def test_a_relationship_is_asserted_unless_it_says_otherwise():
    """The default is the safe one.

    Every existing construction site omits these fields, so a default of
    `True` -- or a required argument -- would relabel every stored edge in the
    application as inferred. The flag's whole job is telling those apart.
    """
    edge = GraphRelationship(source_id="a", target_id="b", relationship_type="advised")
    assert edge.inferred is False
    assert edge.derivation is None


def test_an_entity_is_undated_unless_it_says_otherwise():
    node = GraphEntity(entity_id="a", name="Prandtl", entity_type="person")
    assert node.temporal is None


def test_a_graph_reports_its_two_truncations_separately():
    """`truncated` is about entities; `inferred_truncated` is about lines.

    One flag for both would tell a reader that nodes are missing when every
    node is present, and send them looking for entities that are all there.
    """
    graph = Graph(entities=(), relationships=(), truncated=True)
    assert graph.inferred_truncated is False


async def test_a_neighborhood_carries_the_edges_among_what_it_returned(
    graph_reader, seeded_graph
):
    """One call, not N. A client that had to ask how its own result is wired
    would issue a request per node and draw a graph that flickers into shape."""
    reader, _store = graph_reader
    hood = await reader.neighborhood(str(seeded_graph["prandtl_id"]), depth=1)

    assert {entity.name for entity in hood.entities} >= {"Theodore von Kármán", "Göttingen"}
    assert any(edge.relationship_type == "advised" for edge in hood.relationships)


async def test_edges_to_entities_outside_the_neighborhood_are_dropped(
    graph_reader, seeded_graph
):
    """An edge whose other end was not returned is one the caller cannot draw."""
    reader, _store = graph_reader
    hood = await reader.neighborhood(str(seeded_graph["prandtl_id"]), depth=1)

    returned = {entity.entity_id for entity in hood.entities} | {hood.root.entity_id}
    for edge in hood.relationships:
        assert edge.source_id in returned
        assert edge.target_id in returned

    # The outsider is two hops from Prandtl -- outside a depth=1 neighborhood
    # -- so its edge to von Kármán must not appear at all.
    assert str(seeded_graph["outsider_id"]) not in returned


async def test_depth_is_clamped_by_the_port_not_only_the_route(graph_reader, deep_graph):
    """A route is not the last thing that can ask for depth 5."""
    reader, _store = graph_reader
    root_id = str(deep_graph["root_id"])

    deep = await reader.neighborhood(root_id, depth=5)
    capped = await reader.neighborhood(root_id, depth=MAX_NEIGHBORHOOD_DEPTH)
    uncapped_reach = await reader.neighborhood(root_id, depth=MAX_NEIGHBORHOOD_DEPTH + 1)

    assert {entity.entity_id for entity in deep.entities} == {
        entity.entity_id for entity in capped.entities
    }
    # Distinguish "clamped correctly" from "returned nothing": the capped
    # neighborhood must actually contain more than zero non-root entities,
    # and depth=5 must not have quietly reached further than the clamp.
    assert len(capped.entities) > 0
    assert len(capped.entities) < 5
    assert {entity.entity_id for entity in uncapped_reach.entities} == {
        entity.entity_id for entity in capped.entities
    }


async def test_an_unknown_entity_reads_as_none(graph_reader, seeded_graph):
    reader, _store = graph_reader
    assert await reader.neighborhood(str(uuid4())) is None


async def test_find_entities_pages_and_maps_to_graph_entities(graph_reader, seeded_graph):
    reader, _store = graph_reader
    page = await reader.find_entities(limit=100)

    assert {entity.name for entity in page.entities} == {
        "Ludwig Prandtl",
        "Theodore von Kármán",
        "Göttingen",
        "Someone Two Hops Away",
    }
    assert page.next_after is None


async def test_find_entities_filters_by_type(graph_reader, seeded_graph):
    reader, _store = graph_reader
    page = await reader.find_entities(entity_type="place")

    assert [entity.name for entity in page.entities] == ["Göttingen"]


async def test_find_entities_matches_name_as_a_case_insensitive_substring(
    graph_reader, seeded_graph
):
    """A search box needs the same give `RedstringKnowledge.search` gives an
    agent typing free text -- `GraphStore.find_entities(name=...)` matches
    `normalized_name` exactly, which "prandtl" alone would never satisfy."""
    reader, _store = graph_reader
    page = await reader.find_entities(name="prandtl")

    assert [entity.name for entity in page.entities] == ["Ludwig Prandtl"]


async def test_find_entities_name_filter_excludes_non_matches(graph_reader, seeded_graph):
    """The substring filter must actually filter, not degrade into
    'return everything regardless of name'."""
    reader, _store = graph_reader
    page = await reader.find_entities(name="no-such-substring")

    assert page.entities == ()


async def test_the_whole_graph_arrives_wired_in_one_call(graph_reader, seeded_graph):
    """What a browser opens with: every entity, and every edge among them.

    The outsider that `neighborhood` drops at depth=1 is here, and so is its
    edge -- nothing is outside the whole graph, which is the point of it.
    """
    reader, _store = graph_reader
    graph = await reader.whole()

    assert {entity.name for entity in graph.entities} == {
        "Ludwig Prandtl",
        "Theodore von Kármán",
        "Göttingen",
        "Someone Two Hops Away",
    }
    assert {edge.relationship_type for edge in graph.relationships} == {
        "advised",
        "worked_at",
    }
    assert len(graph.relationships) == 3
    assert graph.truncated is False


async def _merge_away(store, *, alias_id, canonical_id):
    """Record `alias_id` as having been absorbed into `canonical_id`.

    Written straight into the store rather than driven through `Consolidator`,
    for the reason at the top of this module: what is under test is the read
    side. An `Alias` row is exactly what redstring's own merge projection
    leaves behind, so seeding one reproduces the post-merge state without an
    LLM, an adjudicator or a similarity threshold in the way.
    """
    from datetime import UTC, datetime

    from redstring import Alias

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


async def test_an_entity_merged_away_is_not_drawn_as_its_own_node(graph_reader):
    """A merge is not a delete, and the canvas was drawing the difference.

    `GraphStore.find_entities` returns absorbed entities too -- redstring
    documents that deliberately, because the row is what `undo` restores. This
    reader passed the result straight to the browser, so a *correctly*
    consolidated pair still rendered as two nodes: the canonical one with all
    the edges, and the alias sitting beside it with none, since the merge
    redirected them. That is the duplicate a reader actually sees, and no
    amount of fixing consolidation removes it.

    This test would pass with the change reverted only if `find_entities` had
    stopped returning aliases, which is not something this repository controls.
    Proved red first: before the fix it found both names.
    """
    reader, store = graph_reader
    canonical_id, alias_id = uuid4(), uuid4()
    await store.upsert_entities(
        [
            _entity(canonical_id, "Nova Scotia Duck Tolling Retriever"),
            _entity(alias_id, "Nova Scotia Duck Tolling Retriever"),
        ]
    )
    await _merge_away(store, alias_id=alias_id, canonical_id=canonical_id)

    graph = await reader.whole()

    assert [entity.entity_id for entity in graph.entities] == [str(canonical_id)]

    page = await reader.find_entities(name="Nova Scotia")
    assert [entity.entity_id for entity in page.entities] == [str(canonical_id)]


async def test_an_entity_merged_away_is_not_drawn_in_a_neighborhood(graph_reader):
    """What `whole` has always done, which `neighborhood` never did.

    `GraphStore.neighbors` returns absorbed entities as well as canonical
    ones -- a merge is not a delete, because the row is what `undo_merge`
    restores. Passed through, a *correctly* consolidated pair draws as two
    nodes: the canonical one carrying every edge, and the alias beside it
    with none, because the merge redirected them. An isolated node bearing a
    name already on the canvas is precisely the duplicate a reader reports.

    Fails against the code as it was: the alias came back in `entities`.
    """
    reader, store = graph_reader
    root_id, canonical_id, alias_id = uuid4(), uuid4(), uuid4()
    await store.upsert_entities(
        [
            _entity(root_id, "Root"),
            _entity(canonical_id, "Nova Scotia Duck Tolling Retriever"),
            _entity(alias_id, "Nova Scotia Duck Tolling Retriever"),
        ]
    )
    await store.upsert_relationships(
        [
            _relationship(uuid4(), root_id, canonical_id, "related_to"),
            # The alias's own edge, unredirected in this fake store's `merge`
            # -- an `Alias` row records that it was absorbed, but does not
            # rewire relationships, so `neighbors`' BFS still reaches it
            # exactly as it would in the store this reader actually runs
            # against. Without that edge the alias is merely unconnected,
            # which proves nothing about the filter under test.
            _relationship(uuid4(), root_id, alias_id, "related_to"),
        ]
    )
    await _merge_away(store, alias_id=alias_id, canonical_id=canonical_id)

    hood = await reader.neighborhood(str(root_id), depth=1)

    assert str(alias_id) not in {entity.entity_id for entity in hood.entities}
    for edge in hood.relationships:
        assert edge.source_id != str(alias_id)
        assert edge.target_id != str(alias_id)


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


async def test_an_empty_project_reads_as_an_empty_graph(graph_reader):
    """A project with nothing extracted yet is the commonest way to reach
    this read at all, and it must answer rather than fail."""
    reader, _store = graph_reader
    graph = await reader.whole()

    assert graph.entities == ()
    assert graph.relationships == ()
    assert graph.truncated is False


async def test_a_graph_larger_than_the_cap_says_it_was_truncated(graph_reader):
    """Silence here would be a graph that looks complete and is not."""
    reader, store = graph_reader
    await store.upsert_entities([_entity(uuid4(), f"Node {n}") for n in range(5)])

    graph = await reader.whole(limit=3)

    assert len(graph.entities) == 3
    assert graph.truncated is True


async def test_a_graph_of_exactly_the_cap_is_not_truncated(graph_reader):
    """The boundary the count-versus-limit test gets wrong: a graph that
    fits exactly is complete, and reporting it as truncated would send a
    reader looking for entities that do not exist."""
    reader, store = graph_reader
    await store.upsert_entities([_entity(uuid4(), f"Node {n}") for n in range(3)])

    graph = await reader.whole(limit=3)

    assert len(graph.entities) == 3
    assert graph.truncated is False


async def test_edges_to_entities_cut_off_by_the_cap_are_dropped(graph_reader):
    """Under truncation a dangling edge is the ordinary case, not an edge
    case: half of a relationship is not drawable."""
    reader, store = graph_reader
    ids = [uuid4() for _ in range(4)]
    await store.upsert_entities([_entity(i, f"Node {n}") for n, i in enumerate(ids)])
    await store.upsert_relationships(
        [_relationship(uuid4(), ids[n], ids[n + 1], "next") for n in range(3)]
    )

    graph = await reader.whole(limit=2)

    returned = {entity.entity_id for entity in graph.entities}
    for edge in graph.relationships:
        assert edge.source_id in returned
        assert edge.target_id in returned


async def test_the_cap_is_enforced_by_the_port_not_only_the_route(graph_reader):
    """A route is not the last thing that can ask for the whole of a graph
    too big to draw -- the same reasoning `depth` gets."""
    reader, store = graph_reader
    await store.upsert_entities([_entity(uuid4(), f"Node {n}") for n in range(3)])

    graph = await reader.whole(limit=MAX_GRAPH_NODES + 1_000)

    assert len(graph.entities) == 3
    assert graph.truncated is False
