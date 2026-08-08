"""`GraphReadPort` and `ProjectGraphReader`.

Seeded directly through `InMemoryGraphStore.upsert_entities` /
`upsert_relationships` -- no LLM, no extraction, no `ingest`. What is under
test is the read side, and the write side has its own coverage.
"""

from uuid import uuid4

import pytest
from redstring import InMemoryGraphStore
from redstring.domain.entity import Entity, ExtractionMethod
from redstring.domain.relationship import Relationship

from research_team.application.graph_read import MAX_NEIGHBORHOOD_DEPTH
from research_team.infrastructure.knowledge.graph_reader import ProjectGraphReader

TENANT_ID = uuid4()


def _entity(entity_id, name: str, entity_type: str = "person") -> Entity:
    return Entity(
        id=entity_id,
        tenant_id=TENANT_ID,
        name=name,
        normalized_name=name.lower(),
        entity_type=entity_type,
        extraction_method=ExtractionMethod.MANUAL,
        confidence=1.0,
    )


def _relationship(relationship_id, source_id, target_id, relationship_type: str) -> Relationship:
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


async def test_a_neighborhood_carries_the_edges_among_what_it_returned(graph_reader, seeded_graph):
    """One call, not N. A client that had to ask how its own result is wired
    would issue a request per node and draw a graph that flickers into shape."""
    reader, _store = graph_reader
    hood = await reader.neighborhood(str(seeded_graph["prandtl_id"]), depth=1)

    assert {entity.name for entity in hood.entities} >= {"Theodore von Kármán", "Göttingen"}
    assert any(edge.relationship_type == "advised" for edge in hood.relationships)


async def test_edges_to_entities_outside_the_neighborhood_are_dropped(graph_reader, seeded_graph):
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


async def test_find_entities_matches_name_as_a_case_insensitive_substring(graph_reader, seeded_graph):
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
