"""Turning a vector store into graph edges.

The arithmetic here replaced `VectorStore.search` for a measured reason -- one
search per entity is quadratic and done in Python, 13.9s for 500 entities at
768 dimensions against redstring's in-memory store. These tests are about the
parts of doing it by hand that are easy to get wrong and impossible to see:
which pairs come back, in which order, and how many times.
"""

import math
from uuid import UUID, uuid4

import pytest
from redstring import InMemoryVectorStore

from research_team.infrastructure.knowledge.semantic_neighbours import (
    MIN_STANDOUT_POPULATION,
    VectorNeighbours,
)

DIMENSION = 4


def unit(*components: float) -> list[float]:
    return list(components)


#: Six directions in the first three components, so the fourth is free for the
#: rescale below. `a` and `b` are 0.2 rad apart and everything else is at least
#: 0.9 rad from both, which is the structure the relative cut is meant to find.
def spread() -> dict[str, list[float]]:
    return {
        "a": unit(1.0, 0.0, 0.0, 0.0),
        "b": unit(math.cos(0.2), math.sin(0.2), 0.0, 0.0),
        "c": unit(math.cos(1.1), math.sin(1.1), 0.0, 0.0),
        "d": unit(math.cos(1.9), math.sin(1.9), 0.0, 0.0),
        "e": unit(math.cos(2.6), math.sin(2.6), 0.0, 0.0),
        "f": unit(0.0, 0.0, 1.0, 0.0),
    }


#: `spread`, with every vector given the same component in the free fourth
#: slot and shrunk in the other three. For unit inputs of equal norm this maps
#: every cosine by `cos -> (s^2 cos + t^2) / (s^2 + t^2)` -- affine, so the
#: ordering is untouched and every similarity rises. Exactly the difference
#: between two embedding models with different bands, and nothing else.
def squeezed(*, s: float = 0.35, t: float = 0.9) -> dict[str, list[float]]:
    return {name: [x * s, y * s, z * s, t] for name, (x, y, z, _) in spread().items()}


async def store_with(vectors: dict[UUID, list[float]], tenant_id: UUID):
    store = InMemoryVectorStore(dimension=DIMENSION)
    for entity_id, vector in vectors.items():
        await store.upsert(entity_id, vector, tenant_id)
    return store


@pytest.mark.asyncio
async def test_each_pair_comes_back_once_with_its_ends_in_order():
    """`left < right`, once. The port's contract, and why it is the port's.

    The adjacency *adds* the weights it is given, so a pair reported from both
    endpoints' neighbour lists would be twice as attractive as one reported
    once -- and mutually-nearest pairs are exactly the ones that get reported
    twice. That is a silent thumb on the scale in favour of the pairs the
    method is most confident about, which sounds harmless and is not: it is a
    weighting nobody chose.
    """
    tenant_id = uuid4()
    ids = {name: uuid4() for name in spread()}
    store = await store_with(
        {ids[name]: vector for name, vector in spread().items()}, tenant_id
    )

    pairs = await VectorNeighbours(store, tenant_id=tenant_id).neighbours(
        [str(entity_id) for entity_id in ids.values()]
    )

    assert pairs, "a and b are 0.2 rad apart in a corpus that is otherwise spread"
    assert len(pairs) == len({(left, right) for left, right, _ in pairs})
    for left, right, _ in pairs:
        assert left < right


@pytest.mark.asyncio
async def test_a_one_sided_nearest_neighbour_still_draws_its_edge():
    """Union, not intersection, and the choice matters at the periphery.

    k-nearest-neighbour is not symmetric: a peripheral entity's nearest
    neighbour is often a hub whose own nearest neighbours are all other hubs.
    Taking the intersection would drop precisely the edges that connect a
    small cluster to a large one -- which are the edges this channel exists to
    draw, since a well-connected pair is already joined by the graph.

    Built as a tight cluster plus one outlier: the outlier's nearest is inside
    the cluster, and nothing inside the cluster is near the outlier.
    """
    tenant_id = uuid4()
    cluster = [uuid4() for _ in range(6)]
    outlier = uuid4()
    vectors = {
        entity_id: unit(1.0, 0.01 * index, 0, 0) for index, entity_id in enumerate(cluster)
    }
    vectors[outlier] = unit(0.95, 0.4, 0, 0)
    store = await store_with(vectors, tenant_id)

    pairs = await VectorNeighbours(store, tenant_id=tenant_id).neighbours(
        [str(entity_id) for entity_id in [*cluster, outlier]]
    )

    touching_outlier = [pair for pair in pairs if str(outlier) in (pair[0], pair[1])]
    assert touching_outlier, (
        "the outlier's own nearest neighbour must survive even though nothing "
        "in the cluster counts the outlier among its nearest"
    )


@pytest.mark.asyncio
async def test_an_entity_with_no_stored_vector_is_skipped_silently():
    """Three ordinary causes, none of them an error.

    Entities extracted before embeddings were durable have no vector, a
    provider whose endpoint was down leaves gaps, and a graph read includes the
    ontology pass's synthesised class nodes, which are not redstring entities
    and were never embedded.
    """
    tenant_id = uuid4()
    known, unknown = uuid4(), uuid4()
    store = await store_with({known: unit(1, 0, 0, 0)}, tenant_id)

    pairs = await VectorNeighbours(store, tenant_id=tenant_id).neighbours(
        [str(known), str(unknown)]
    )

    assert pairs == ()


@pytest.mark.asyncio
async def test_an_id_that_is_not_a_uuid_does_not_raise():
    """Ontology class nodes carry derived ids that are not entity ids.

    `UUID(...)` on one raises `ValueError`, and the whole projection would fail
    on a project that had ever run the ontology pass -- a crash in a feature
    nobody connected to the one they turned on.
    """
    tenant_id = uuid4()
    known = uuid4()
    store = await store_with({known: unit(1, 0, 0, 0)}, tenant_id)

    pairs = await VectorNeighbours(store, tenant_id=tenant_id).neighbours(
        [str(known), "class:person"]
    )

    assert pairs == ()


@pytest.mark.asyncio
async def test_the_same_structure_at_a_different_similarity_level_draws_the_same_edges():
    """The whole reason the cut is relative, in one assertion.

    Two corpora with **identical geometry** and different absolute similarity:
    the second is the first squeezed towards a common direction, so every
    cosine rises and the ordering is untouched. An absolute floor answers
    differently on the two -- that is what an absolute floor *is* -- and the
    difference is indistinguishable from a change in the data.

    This is not a hypothetical. Measured on 2026-08-29 against
    `qwen3-embedding-0.6b` over real entity cards, the old 0.83 floor kept
    1 of 10 pairs on a five-entity baroque-music corpus and 10 of 10 on a
    five-entity monetary-policy one -- a complete graph, which is precisely
    the invent-structure failure the floor was written to prevent. It was
    reading how high in the scale a corpus's vocabulary happens to sit.

    It is also the model-swap test. `embedding_model` is a setting
    (`AGENT_EMBEDDING_MODEL`), every model has its own band, and a per-model
    constant that nothing recomputes is what a user changing providers would
    silently retune. *Fails against* any reintroduction of an absolute floor.
    """
    tenant_id = uuid4()
    ids = {name: uuid4() for name in spread()}

    def reader_of(vectors):
        return VectorNeighbours(vectors, tenant_id=tenant_id)

    loose = await store_with({ids[n]: v for n, v in spread().items()}, tenant_id)
    # Every vector rotated a fixed amount towards `(0, 0, 0, 1)` raises every
    # pairwise cosine without reordering any of them.
    tight = await store_with(
        {ids[name]: vector for name, vector in squeezed().items()}, tenant_id
    )
    argument = [str(entity_id) for entity_id in ids.values()]

    loose_pairs = await reader_of(loose).neighbours(argument)
    tight_pairs = await reader_of(tight).neighbours(argument)

    assert loose_pairs, "the spread corpus has structure to find"
    assert {(left, right) for left, right, _ in loose_pairs} == {
        (left, right) for left, right, _ in tight_pairs
    }, (
        "the same geometry at a higher similarity level drew different edges, "
        "which is an absolute threshold reading the corpus's overall level "
        "rather than its structure"
    )


@pytest.mark.asyncio
async def test_a_corpus_with_no_structure_in_it_draws_nothing():
    """Every entity equidistant from every other: no pair stands out.

    The failure this replaces the old orthogonality test for is the same one
    and stated better. A k-nearest-neighbour walk always finds a nearest
    neighbour, however unrelated, so the sparsest corner of a graph gets the
    same five edges as the densest -- and under a relative cut the corner that
    has no structure gets none, without anyone having to name a number that
    happens to sit above it.
    """
    tenant_id = uuid4()
    # Four mutually orthogonal vectors: every off-diagonal similarity is
    # exactly 0.5, so every row's deviation is zero.
    vectors = {
        uuid4(): unit(*(1.0 if i == axis else 0.0 for i in range(DIMENSION)))
        for axis in range(DIMENSION)
    }
    store = await store_with(vectors, tenant_id)

    pairs = await VectorNeighbours(store, tenant_id=tenant_id).neighbours(
        [str(entity_id) for entity_id in vectors]
    )

    assert pairs == ()


@pytest.mark.asyncio
async def test_a_corpus_too_small_to_have_a_distribution_draws_nothing():
    """`MIN_STANDOUT_POPULATION`, and why it is not 2.

    With three entities a row holds two similarities, its standard deviation
    is half the gap between them, and the larger is therefore *always* exactly
    1.0 above the mean -- so at `MIN_NEIGHBOUR_STANDOUT = 1.0` every
    three-entity project would draw its top pair by arithmetic rather than by
    evidence, whatever its vectors were. The old absolute floor had no such
    case and this is the cost of the change, stated rather than discovered.

    *Fails against* someone lowering the population guard to restore the
    two-entity behaviour the cosine floor had.
    """
    tenant_id = uuid4()
    vectors = {
        uuid4(): unit(1.0, 0.0, 0, 0),
        uuid4(): unit(0.99, 0.14106735979665883, 0, 0),
        uuid4(): unit(0, 1.0, 0, 0),
    }
    assert len(vectors) < MIN_STANDOUT_POPULATION
    store = await store_with(vectors, tenant_id)

    pairs = await VectorNeighbours(store, tenant_id=tenant_id).neighbours(
        [str(entity_id) for entity_id in vectors]
    )

    assert pairs == (), (
        "two near-identical vectors and one stranger is a pair that any "
        "threshold would draw, and there is no distribution behind it"
    )


@pytest.mark.asyncio
async def test_nothing_to_compare_yields_nothing():
    tenant_id = uuid4()
    store = await store_with({}, tenant_id)

    reader = VectorNeighbours(store, tenant_id=tenant_id)

    assert await reader.neighbours([]) == ()
    assert await reader.neighbours([str(uuid4())]) == ()


@pytest.mark.asyncio
async def test_an_absent_store_is_not_an_error():
    """Embeddings off is a configuration, not a fault.

    The route hands `None` straight through rather than branching, so this is
    the branch that keeps `AGENT_VECTOR_STORE=none` serving a curriculum.
    """
    assert await VectorNeighbours(None, tenant_id=uuid4()).neighbours(["a"]) == ()
