"""Ontology layer integration tests for `ProjectGraphReader`.

Covers discovered class joining, membership decoration, and store interaction.
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
)

from research_team.infrastructure.knowledge.graph_reader import ProjectGraphReader

TENANT_ID = uuid4()


def _entity(
    entity_id,
    name: str,
    entity_type: str = "person",
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


class _FakeOntology:
    """The ontology read side, narrowed to the two calls the reader makes.

    A fake rather than a real `OntologyStore` for the reason the rest of this
    file fakes its store: what is under test is the join and the caps, not
    SQLite. The wiring test in `tests/integration/` is what proves a composed
    application actually passes one of these in.
    """

    def __init__(self, classes=(), members=None) -> None:
        self._classes = list(classes)
        self._members = members or {}

    async def classes_for(self, project_id):
        return list(self._classes)

    async def members_for(self, class_id):
        return list(self._members.get(class_id, ()))


class _Row:
    """Enough of `OntologyClassRow`/`OntologyMembershipRow` to join on."""

    def __init__(self, **fields):
        for key, value in fields.items():
            setattr(self, key, value)


def _class(class_id, name="Difficulty", *, kind="ordered_scale", source_id="songs"):
    return _Row(
        id=class_id,
        project_id=TENANT_ID,
        source_id=source_id,
        name=name,
        kind=kind,
        declared_count=6,
        member_count=2,
        parent_class_id=None,
        evidence_start=0,
        evidence_end=66,
        rejected_members="[]",
        model="m",
        generated_at="t",
        stale=False,
    )


def _member(class_id, name, ordinal=0):
    return _Row(
        id=uuid4(),
        project_id=TENANT_ID,
        class_id=class_id,
        member_name=name,
        ordinal=ordinal,
    )


@pytest.fixture
async def graph_with_a_class():
    """Two entities that a discovered class claims as its members."""
    store = InMemoryGraphStore()
    easy_id, master_id = uuid4(), uuid4()
    await store.upsert_entities(
        [
            _entity(easy_id, "EASY", entity_type="category"),
            _entity(master_id, "MASTER", entity_type="category"),
        ]
    )
    class_id = uuid4()
    ontology = _FakeOntology(
        classes=[_class(class_id)],
        members={
            class_id: [
                _member(class_id, "EASY", 0),
                _member(class_id, "MASTER", 4),
            ]
        },
    )
    reader = ProjectGraphReader(project_id=TENANT_ID, store=store, ontology=ontology)
    return reader, easy_id, master_id


async def test_a_discovered_class_arrives_as_an_inferred_node(graph_with_a_class):
    reader, _easy_id, _master_id = graph_with_a_class

    graph = await reader.whole()

    (klass,) = [entity for entity in graph.entities if entity.entity_type == "class"]
    assert klass.name == "Difficulty"
    assert klass.inferred is True


async def test_ordinary_entities_are_not_marked_inferred(graph_with_a_class):
    """`inferred` defaults False and has to stay False for everything redstring
    stored. A test asserting only that class nodes are inferred would pass
    against an implementation that marked every node."""
    reader, _easy_id, _master_id = graph_with_a_class

    graph = await reader.whole()

    assert all(
        not entity.inferred for entity in graph.entities if entity.entity_type != "class"
    )


async def test_each_member_gets_an_inferred_instance_of_edge_to_the_class(
    graph_with_a_class,
):
    reader, easy_id, master_id = graph_with_a_class

    graph = await reader.whole()

    (klass,) = [entity for entity in graph.entities if entity.entity_type == "class"]
    edges = [edge for edge in graph.relationships if edge.relationship_type == "instance_of"]
    assert {edge.source_id for edge in edges} == {str(easy_id), str(master_id)}
    assert {edge.target_id for edge in edges} == {klass.entity_id}
    assert all(edge.inferred for edge in edges)


async def test_an_instance_of_edge_says_where_the_class_came_from(graph_with_a_class):
    """An inferred edge with no visible derivation is indistinguishable from an
    asserted one -- the confusion `derivation` exists to prevent. Here the
    derivation is provenance rather than arithmetic, so it names the source and
    the offsets a reader can open."""
    reader, _easy_id, _master_id = graph_with_a_class

    graph = await reader.whole()

    edge = next(
        edge for edge in graph.relationships if edge.relationship_type == "instance_of"
    )
    assert "songs" in edge.derivation
    assert "0" in edge.derivation and "66" in edge.derivation


async def test_a_member_that_resolves_to_no_entity_draws_no_edge():
    """The staleness contract. The membership row survives with a null
    `entity_id`, and here it must produce no edge -- an edge to a node the
    caller was not given is one it cannot draw, the same dangling-reference
    rule `returned_ids` already enforces for stored edges."""
    store = InMemoryGraphStore()
    easy_id = uuid4()
    await store.upsert_entities([_entity(easy_id, "EASY", entity_type="category")])
    class_id = uuid4()
    ontology = _FakeOntology(
        classes=[_class(class_id)],
        members={
            class_id: [
                _member(class_id, "EASY", 0),
                _member(class_id, "APPEND", 5),
            ]
        },
    )
    reader = ProjectGraphReader(project_id=TENANT_ID, store=store, ontology=ontology)

    graph = await reader.whole()

    node_ids = {entity.entity_id for entity in graph.entities}
    for edge in graph.relationships:
        assert edge.source_id in node_ids
        assert edge.target_id in node_ids
    assert len([e for e in graph.relationships if e.relationship_type == "instance_of"]) == 1


async def test_a_class_none_of_whose_members_are_on_the_canvas_is_not_drawn():
    """A class node with no edges is a bare hub: a name floating unattached,
    asserting a grouping of nothing. Whether its members were cut by the node
    cap or never extracted, the class has nothing to say on this drawing."""
    store = InMemoryGraphStore()
    class_id = uuid4()
    ontology = _FakeOntology(
        classes=[_class(class_id)],
        members={class_id: [_member(class_id, "APPEND", 5)]},
    )
    reader = ProjectGraphReader(project_id=TENANT_ID, store=store, ontology=ontology)

    graph = await reader.whole()

    assert [entity for entity in graph.entities if entity.entity_type == "class"] == []


async def test_a_reader_with_no_ontology_draws_no_classes_and_does_not_fail():
    """The collaborator is optional, so every construction site that predates
    it keeps working. Stated as a test because the cost of that default is
    real: a site that forgets to pass one draws no classes and reports no
    error, which is why `tests/integration/test_ontology_graph_wiring.py`
    asks a composed application instead of trusting this."""
    store = InMemoryGraphStore()
    await store.upsert_entities([_entity(uuid4(), "EASY", entity_type="category")])
    reader = ProjectGraphReader(project_id=TENANT_ID, store=store)

    graph = await reader.whole()

    assert len(graph.entities) == 1
    assert graph.relationships == ()
