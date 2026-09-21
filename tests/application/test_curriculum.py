"""The join, and the one thing it can get wrong that arithmetic cannot.

`area_projection` and `learning_paths` are pure and tested as such. What is
left here is reading: how many times the graph is read, whether two views of
one curriculum can disagree, and whether the cache serves a projection built
from a graph that has since changed.
"""

from uuid import uuid4

import pytest

from research_team.curriculum.application import CurriculumService
from research_team.curriculum.application.curriculum import graph_fingerprint
from research_team.knowledge.application.graph_read import (
    Graph,
    GraphEntity,
    GraphRelationship,
)


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


@pytest.mark.asyncio
async def test_modified_graph_with_same_count_is_projected_again():
    """B127: Modifying graph without changing counts invalidates cache via fingerprint."""
    entities, relationships = two_cliques()
    reader = StubGraphReader(entities, relationships)
    co = StubCoMentions()
    service = CurriculumService()
    project = uuid4()
    await service.build(project, reader, co)
    assert co.calls == 1

    # Replace one entity with a different entity_id, keeping counts identical
    modified_entities = [entity("x9") if e.entity_id == "a1" else e for e in entities]
    modified_relationships = [
        rel("x9", r.target_id) if r.source_id == "a1" else r for r in relationships
    ]
    modified_reader = StubGraphReader(modified_entities, modified_relationships)
    await service.build(project, modified_reader, co)

    assert co.calls == 2, (
        "cache must be invalidated when graph content changes even if counts match"
    )


@pytest.mark.asyncio
async def test_force_refresh_bypasses_cache():
    """force_refresh=True reprojects even when graph has not changed."""
    reader = StubGraphReader(*two_cliques())
    co = StubCoMentions()
    service = CurriculumService()
    project = uuid4()

    await service.build(project, reader, co)
    assert co.calls == 1

    await service.build(project, reader, co, force_refresh=True)
    assert co.calls == 2


def test_graph_fingerprint_changes_on_entity_or_relationship_mutation():
    entities, relationships = two_cliques()
    g1 = Graph(entities=tuple(entities), relationships=tuple(relationships), truncated=False)
    fp1 = graph_fingerprint(g1)
    assert fp1 == graph_fingerprint(g1)

    modified_entities = [entity("x9") if e.entity_id == "a1" else e for e in entities]
    g2 = Graph(
        entities=tuple(modified_entities), relationships=tuple(relationships), truncated=False
    )
    fp2 = graph_fingerprint(g2)
    assert fp1 != fp2


@pytest.mark.asyncio
async def test_cache_eviction_respects_max_cache_size_and_preserves_lru():
    """Cache bounds to max_cache_size and preserves most recently accessed entries."""
    reader = StubGraphReader(*two_cliques())
    co = StubCoMentions()
    service = CurriculumService(max_cache_size=3)

    p1, p2, p3, p4 = uuid4(), uuid4(), uuid4(), uuid4()

    # Fill cache to capacity (3)
    await service.build(p1, reader, co)
    await service.build(p2, reader, co)
    await service.build(p3, reader, co)
    assert len(service._cache) == 3
    assert co.calls == 3

    # Access p1, making p2 the least recently used
    await service.build(p1, reader, co)
    assert co.calls == 3  # Cache hit

    # Add p4: capacity exceeded, p2 should be evicted
    await service.build(p4, reader, co)
    assert len(service._cache) == 3
    assert co.calls == 4
    assert p1 in service._cache
    assert p2 not in service._cache
    assert p3 in service._cache
    assert p4 in service._cache

    # Building p1 is still a cache hit
    await service.build(p1, reader, co)
    assert co.calls == 4

    # Building evicted p2 requires recomputation
    await service.build(p2, reader, co)
    assert co.calls == 5
    assert len(service._cache) == 3


def test_default_max_cache_size_is_32():
    service = CurriculumService()
    assert service.max_cache_size == 32


def test_forget_safely_handles_nonexistent_or_evicted_project():
    service = CurriculumService(max_cache_size=2)
    # Never-cached project
    service.forget(uuid4())

    p1 = uuid4()
    service._cache[p1] = (("key",), None, None, None)  # type: ignore[assignment]
    assert p1 in service._cache

    service.forget(p1)
    assert p1 not in service._cache

    # Forgetting again does not raise
    service.forget(p1)


@pytest.mark.asyncio
async def test_path_toward_survives_eviction_between_build_and_lookup():
    """Defensively rebuilds if entry is evicted between build and lookup
    without bare KeyError.
    """
    reader = StubGraphReader(*two_cliques())
    co = StubCoMentions()
    service = CurriculumService(max_cache_size=2)
    project = uuid4()

    original_build = service.build
    evicted_once = False

    async def build_and_evict(*args, **kwargs):
        res = await original_build(*args, **kwargs)
        nonlocal evicted_once
        if not evicted_once:
            service.forget(project)
            evicted_once = True
        return res

    service.build = build_and_evict  # type: ignore[method-assign]
    complete = await original_build(project, reader, co)
    target_slug = complete.path.area_slugs[0]

    # path_toward will see cache miss after initial build, fall back to rebuild, and succeed
    path = await service.path_toward(project, target_slug, reader, co)
    assert path is not None
    assert path.area_slugs[0] == target_slug
    assert evicted_once


@pytest.mark.asyncio
async def test_path_toward_handles_persistent_cache_miss_gracefully():
    """If cache remains empty (e.g. max_cache_size=0), path_toward returns None
    without KeyError.
    """
    reader = StubGraphReader(*two_cliques())
    co = StubCoMentions()
    service = CurriculumService(max_cache_size=0)
    project = uuid4()

    path = await service.path_toward(project, "any-area", reader, co)
    assert path is None
