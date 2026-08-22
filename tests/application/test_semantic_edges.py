"""The embedding channel in the area projection.

These are about the thing an earlier version of this project reasoned itself
out of building. `area_projection`'s docstring used to argue that entity
vectors "encode `entity.name` rather than subject matter", as though embedding
a name were a comparison of spellings -- which is exactly backwards, and is
what these tests exist on the other side of. An embedding puts `glass` near
`cup`; a string comparison never will.

What each test pins is a choice that has a plausible alternative. A test that
only proved "semantic edges do something" would pass against three different
weightings and tell nobody which one shipped.
"""

import pytest

from research_team.application.area_projection import (
    EMBEDDING_WEIGHT,
    MIN_EMBEDDING_SCORE,
    _adjacency,
    _semantic_edges,
    project_areas,
)
from research_team.application.graph_read import Graph, GraphEntity, GraphRelationship

KNOWN = frozenset({"a", "b", "c"})


def entity(entity_id: str) -> GraphEntity:
    return GraphEntity(entity_id=entity_id, name=entity_id.upper(), entity_type="thing")


def relationship(source: str, target: str) -> GraphRelationship:
    return GraphRelationship(
        source_id=source, target_id=target, relationship_type="relates_to"
    )


def test_a_pair_at_the_floor_contributes_almost_nothing():
    """The rescale, and the reason it is not `EMBEDDING_WEIGHT * score`.

    **This is the test that separates the two candidate formulas**, and the
    naive one is genuinely tempting: `weight = EMBEDDING_WEIGHT * score` reads
    as "more similar, more weight" and is monotonic in exactly the right
    direction. It is also nearly flat over the range that matters. Cosine
    similarities among real entity cards sit near the top of the scale, so on
    redstring's `(1 + cosine) / 2` mapping a pair that scrapes past the floor
    at 0.83 would get 83% of the weight of a perfect match -- which is not a
    distinction, it is noise wearing a number.

    Under the shipped formula the floor means zero. Under the rejected one it
    means `0.83 * EMBEDDING_WEIGHT`, which is more than a whole passage's
    co-mention budget.
    """
    edges = _semantic_edges([("a", "b", MIN_EMBEDDING_SCORE)], KNOWN)

    assert edges[("a", "b")] == pytest.approx(0.0, abs=1e-9)


def test_a_perfect_match_contributes_the_whole_weight():
    edges = _semantic_edges([("a", "b", 1.0)], KNOWN)

    assert edges[("a", "b")] == pytest.approx(EMBEDDING_WEIGHT)


def test_a_pair_below_the_floor_draws_no_edge_at_all():
    """Not "a small edge" -- no edge.

    A k-nearest-neighbour graph always has a nearest neighbour for every node,
    however unrelated, so without a floor the sparsest corner of a graph gets
    the same five edges as the densest and the method invents structure there.
    """
    edges = _semantic_edges([("a", "b", MIN_EMBEDDING_SCORE - 0.01)], KNOWN)

    assert edges == {}


def test_a_pair_reported_twice_is_not_weighted_twice():
    """`max`, not `+`.

    An adapter that yields each pair once per endpoint -- the obvious shape,
    since k-nearest-neighbour is computed per node -- reports `(a, b)` from
    a's list and `(b, a)` from b's. Summing makes exactly the mutually-nearest
    pairs twice as attractive as one-sided ones, which is a silent
    thumb on the scale rather than an error anything would catch.
    """
    once = _semantic_edges([("a", "b", 1.0)], KNOWN)
    twice = _semantic_edges([("a", "b", 1.0), ("b", "a", 1.0)], KNOWN)

    assert twice == once


def test_an_edge_to_an_entity_outside_the_graph_is_dropped():
    """A vector store outlives the entity whose id it holds.

    Nothing deletes a vector when consolidation absorbs an entity, so a store
    can answer with ids the graph read no longer contains. An adjacency built
    over one of them raises a `KeyError` deep inside the merge, which is the
    worst place to find out.
    """
    assert _semantic_edges([("a", "elsewhere", 1.0)], KNOWN) == {}


def test_an_entity_the_graph_cannot_place_is_placed_by_meaning():
    """The whole point of the channel, stated as what it rescues.

    An entity with no relationship and no co-mention is invisible to the graph.
    `_absorb_small` drops a leftover that has no edge into any surviving area --
    correctly, because on the graph alone there is genuinely nothing to say
    about where it belongs -- so it does not appear in the curriculum at all.

    That is the `glass`/`cup` case put properly: two things about the same
    subject that no sentence happens to name together and no model asserted an
    edge between. A string comparison never recovers it. An embedding does,
    which is the entire reason this channel exists.

    **The first version of this test asserted something else and was wrong.**
    It gave two dense triangles one semantic edge and expected them to merge.
    They do not, and should not: modularity weighs one bridging edge against
    six internal ones and declines, which is the algorithm being right rather
    than the channel being broken. Worth recording, because "add a stronger
    edge until it passes" was the available next move and it would have tuned
    a constant to fit a test instead of the other way round.
    """
    graph = Graph(
        entities=(entity("a"), entity("b"), entity("c"), entity("d")),
        relationships=(
            relationship("a", "b"),
            relationship("b", "c"),
            relationship("c", "a"),
        ),
        truncated=False,
    )

    without = project_areas(graph, [])
    with_meaning = project_areas(graph, [], [("c", "d", 1.0)])

    placed = {member.entity_id for area in without.areas for member in area.members}
    assert "d" not in placed, "an unconnected entity has no place on the graph alone"

    rescued = {member.entity_id for area in with_meaning.areas for member in area.members}
    assert "d" in rescued, "a semantic edge must be able to place it"
    assert len(with_meaning.areas) == 1, "and place it in the area it is near"


def test_a_semantic_edge_does_not_overrule_an_asserted_relationship():
    """The ordering of the evidence, as an inequality on the weights.

    A model read a document and asserted a relationship. An embedding says two
    entities look alike and no document ever said so. The second must never
    outweigh the first, and the constants are where that is decided -- so this
    checks the constants rather than a clustering outcome, which would depend
    on the graph as much as on the weights.
    """
    adjacency, _, _, _ = _adjacency(
        [entity("a"), entity("b"), entity("c")],
        [relationship("a", "b")],
        [],
        [("a", "c", 1.0)],
    )

    assert adjacency["a"]["b"] > adjacency["a"]["c"]


def test_a_run_that_drew_no_semantic_edges_does_not_claim_it_used_embeddings():
    """`used_embeddings` follows the result, not the configuration.

    A projection handed a thousand pairs that all fell below the floor used
    embeddings in no sense a reader cares about. Reporting otherwise makes the
    flag agree with whether the feature was switched on, which every surface
    already knows, instead of with whether it changed anything.
    """
    graph = Graph(
        entities=(entity("a"), entity("b"), entity("c")),
        relationships=(relationship("a", "b"),),
        truncated=False,
    )

    offered = project_areas(graph, [], [("a", "c", MIN_EMBEDDING_SCORE - 0.2)])

    assert offered.semantic_count == 0
    assert offered.used_embeddings is False


def test_a_run_that_drew_them_says_so():
    graph = Graph(
        entities=(entity("a"), entity("b"), entity("c")),
        relationships=(relationship("a", "b"),),
        truncated=False,
    )

    used = project_areas(graph, [], [("a", "c", 1.0)])

    assert used.semantic_count == 1
    assert used.used_embeddings is True
