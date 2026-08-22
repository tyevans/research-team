"""The join, and the one thing it can get wrong that arithmetic cannot.

`area_projection` and `learning_paths` are pure and tested as such. What is
left here is reading: how many times the graph is read, whether two views of
one curriculum can disagree, and whether the cache serves a projection built
from a graph that has since changed.
"""

from uuid import uuid4

import pytest

from research_team.application.curriculum import CurriculumService
from research_team.application.graph_read import Graph, GraphEntity, GraphRelationship


def entity(eid: str) -> GraphEntity:
    return GraphEntity(entity_id=eid, name=eid.upper(), entity_type="concept")


def rel(a: str, b: str) -> GraphRelationship:
    return GraphRelationship(source_id=a, target_id=b, relationship_type="r")


def two_cliques() -> tuple[list[GraphEntity], list[GraphRelationship]]:
    left = ["a1", "a2", "a3", "a4"]
    right = ["b1", "b2", "b3", "b4"]
    edges = []
    for group in (left, right):
        for i, x in enumerate(group):
            for y in group[i + 1 :]:
                edges.append(rel(x, y))
    edges.append(rel("b1", "a1"))
    return [entity(e) for e in left + right], edges


class StubGraphReader:
    def __init__(self, entities, relationships) -> None:
        self._graph = Graph(
            entities=tuple(entities), relationships=tuple(relationships), truncated=False
        )
        self.reads = 0

    async def whole(self, *, limit: int = 5000) -> Graph:
        self.reads += 1
        return self._graph

    async def find_entities(self, **kwargs):  # pragma: no cover - unused here
        raise NotImplementedError

    async def neighborhood(self, entity_id, *, depth=1):  # pragma: no cover
        raise NotImplementedError


class StubCoMentions:
    def __init__(self, passages=None) -> None:
        self._passages = passages or []
        self.calls = 0

    async def passages(self, entity_ids):
        self.calls += 1
        return list(self._passages)


@pytest.mark.asyncio
async def test_a_curriculum_carries_both_the_areas_and_their_order():
    reader = StubGraphReader(*two_cliques())

    curriculum = await CurriculumService().build(uuid4(), reader, StubCoMentions())

    assert len(curriculum.projection.areas) == 2
    assert sorted(curriculum.path.area_slugs) == sorted(
        a.slug for a in curriculum.projection.areas
    )


@pytest.mark.asyncio
async def test_an_unchanged_graph_is_projected_once():
    """The clustering pass is superlinear; a view that reprojects per render
    is a view that gets slower the more interesting the project gets."""
    reader = StubGraphReader(*two_cliques())
    co = StubCoMentions()
    service = CurriculumService()
    project = uuid4()

    await service.build(project, reader, co)
    await service.build(project, reader, co)

    assert co.calls == 1
    # The graph is still read every time -- that is what detects the change.
    assert reader.reads == 2


@pytest.mark.asyncio
async def test_a_grown_graph_is_projected_again():
    entities, relationships = two_cliques()
    reader = StubGraphReader(entities, relationships)
    co = StubCoMentions()
    service = CurriculumService()
    project = uuid4()
    await service.build(project, reader, co)

    grown = StubGraphReader([*entities, entity("c1")], relationships)
    await service.build(project, grown, co)

    assert co.calls == 2


@pytest.mark.asyncio
async def test_forgetting_a_project_forces_a_reprojection():
    reader = StubGraphReader(*two_cliques())
    co = StubCoMentions()
    service = CurriculumService()
    project = uuid4()

    await service.build(project, reader, co)
    service.forget(project)
    await service.build(project, reader, co)

    assert co.calls == 2


@pytest.mark.asyncio
async def test_a_destination_path_agrees_with_the_complete_path():
    """Two cuts taken from two graph reads could order the same pair
    differently, and a learner switching views would be told two incompatible
    things with no way to choose."""
    reader = StubGraphReader(*two_cliques())
    co = StubCoMentions()
    service = CurriculumService()
    project = uuid4()
    complete = await service.build(project, reader, co)

    for slug in complete.path.area_slugs:
        cut = await service.path_toward(project, slug, reader, co)
        assert cut is not None
        positions = [complete.path.area_slugs.index(s) for s in cut.area_slugs]
        assert positions == sorted(positions)


@pytest.mark.asyncio
async def test_a_path_toward_an_unknown_area_is_not_an_error():
    reader = StubGraphReader(*two_cliques())
    service = CurriculumService()

    assert await service.path_toward(uuid4(), "nope", reader, StubCoMentions()) is None


@pytest.mark.asyncio
async def test_an_empty_graph_yields_no_areas_rather_than_failing():
    """A project that has extracted nothing is the ordinary first state, not
    an error. The counts are what tell a reader which of the two empty maps
    they are looking at."""
    curriculum = await CurriculumService().build(
        uuid4(), StubGraphReader([], []), StubCoMentions()
    )

    assert curriculum.projection.areas == ()
    assert curriculum.projection.entity_count == 0
    assert curriculum.path.area_slugs == ()
