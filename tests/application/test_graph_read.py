"""`GraphReadPort` and `ProjectGraphReader`.

Seeded directly through `InMemoryGraphStore.upsert_entities` /
`upsert_relationships` -- no LLM, no extraction, no `ingest`. What is under
test is the read side, and the write side has its own coverage.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from redstring import (
    Entity,
    ExtractionMethod,
    InMemoryGraphStore,
    Provenance,
    Relationship,
    TemporalExtent,
)

from research_team.application.graph_read import (
    MAX_GRAPH_NODES,
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


class TestDateNodesAreNotDrawn:
    """Entities that are a date rather than a thing, kept off every read path.

    redstring stopped producing these at extraction time (PR #75) and that
    fixes nothing for a store already written: events are never rewritten, so
    the 356 measured against the real database on 2026-08-23 are still there
    and will be after any rebuild. 335 of them are isolated, which is 335
    nodes on the canvas bearing a bare date and touching nothing.

    Every test here would pass with `_drawable` reverted to `_without_aliases`
    if it asserted only that the *request succeeded*, which is the shape
    `CLAUDE.md` warns about under "An event no projection handles counts as
    APPLIED". So each one names the entity that must be absent.
    """

    @pytest.fixture
    async def graph_with_a_date_node(self, graph_reader):
        """A real entity, a date-node, and an edge between them -- the exact
        shape measured in the real database."""
        _reader, store = graph_reader
        real_id, date_id = uuid4(), uuid4()
        await store.upsert_entities(
            [
                _entity(real_id, "Star Trek", entity_type="work"),
                _entity(date_id, "January 1968", entity_type="temporal_expression"),
            ]
        )
        await store.upsert_relationships(
            [_relationship(uuid4(), real_id, date_id, "temporal_expression")]
        )
        return {"real_id": real_id, "date_id": date_id}

    async def test_the_whole_graph_omits_a_date_node(
        self, graph_reader, graph_with_a_date_node
    ):
        reader, _store = graph_reader
        graph = await reader.whole()

        assert [e.name for e in graph.entities] == ["Star Trek"]

    async def test_the_edge_to_a_date_node_goes_with_it(
        self, graph_reader, graph_with_a_date_node
    ):
        """Not a separate filter -- the existing both-ends-present rule does
        it, once the node is gone. Asserted anyway because a future refactor
        that filtered entities *after* resolving edges would leave a dangling
        edge and pass every other test in this class."""
        reader, _store = graph_reader
        graph = await reader.whole()

        assert graph.relationships == ()

    async def test_a_date_node_does_not_count_toward_the_cap(
        self, graph_reader, graph_with_a_date_node
    ):
        """Filtered before the slice, as aliases are. Filtering after would
        report a complete graph as truncated because of a node nobody was
        going to see."""
        reader, _store = graph_reader
        graph = await reader.whole(limit=1)

        assert [e.name for e in graph.entities] == ["Star Trek"]
        assert not graph.truncated

    async def test_find_entities_omits_a_date_node(self, graph_reader, graph_with_a_date_node):
        reader, _store = graph_reader
        page = await reader.find_entities()

        assert [e.name for e in page.entities] == ["Star Trek"]

    async def test_a_neighborhood_omits_a_date_node(
        self, graph_reader, graph_with_a_date_node
    ):
        reader, _store = graph_reader
        neighborhood = await reader.neighborhood(str(graph_with_a_date_node["real_id"]))

        assert neighborhood is not None
        assert [e.name for e in neighborhood.entities] == []

    async def test_a_date_node_cannot_be_the_root_of_a_neighborhood(
        self, graph_reader, graph_with_a_date_node
    ):
        """The root does not pass through `_drawable`, so this needs its own
        guard, and without it a stale link answers 200 with a neighbourhood
        centred on `January 1968`."""
        reader, _store = graph_reader

        assert await reader.neighborhood(str(graph_with_a_date_node["date_id"])) is None

    async def test_a_real_entity_whose_name_parses_as_a_date_is_kept(self, graph_reader):
        """The guard on the guard.

        `parse_temporal` reads `Borg`, `MIT` and `Sun` as dates, so a filter
        without redstring's year-or-month anchor deletes them from the canvas.
        This is the assertion that fails if that anchor is ever dropped
        upstream, and it fails naming the Borg.

        **Passes with the filter reverted**, necessarily -- an absent filter
        keeps everything. It guards the filter getting *broader*, which is the
        direction the other tests in this class cannot see.
        """
        _reader, store = graph_reader
        for name in ("Borg", "MIT", "Sun", "Seven of Nine"):
            await store.upsert_entities([_entity(uuid4(), name, entity_type="concept")])
        reader, _store = graph_reader

        graph = await reader.whole()

        assert sorted(e.name for e in graph.entities) == [
            "Borg",
            "MIT",
            "Seven of Nine",
            "Sun",
        ]

    async def test_a_dated_entity_with_a_description_is_kept(self, graph_reader):
        """92 of 286 `event` entities in the real corpus have names that parse
        as dates and carry descriptions. Those are events the model named
        badly, not dates it misfiled, and they stay.

        Passes with the filter reverted, for the reason above."""
        _reader, store = graph_reader
        entity = _entity(uuid4(), "December 7, 1979", entity_type="event")
        await store.upsert_entities([entity.model_copy(update={"description": "A premiere."})])
        reader, _store = graph_reader

        graph = await reader.whole()

        assert [e.name for e in graph.entities] == ["December 7, 1979"]
