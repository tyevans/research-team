"""Turning a vector store into graph edges.

The arithmetic here replaced `VectorStore.search` for a measured reason -- one
search per entity is quadratic and done in Python, 13.9s for 500 entities at
768 dimensions against redstring's in-memory store. These tests are about the
parts of doing it by hand that are easy to get wrong and impossible to see:
which pairs come back, in which order, and how many times.
"""

from uuid import UUID, uuid4

import pytest
from redstring import InMemoryVectorStore

from research_team.infrastructure.knowledge.semantic_neighbours import VectorNeighbours

DIMENSION = 4


def unit(*components: float) -> list[float]:
    return list(components)


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
    left, right = uuid4(), uuid4()
    store = await store_with({left: unit(1, 0, 0, 0), right: unit(1, 0, 0, 0)}, tenant_id)

    pairs = await VectorNeighbours(store, tenant_id=tenant_id).neighbours(
        [str(left), str(right)]
    )

    assert len(pairs) == 1
    first, second, _ = pairs[0]
    assert first < second


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
async def test_the_floor_is_read_on_the_ports_scale_and_not_on_raw_cosine():
    """`MIN_EMBEDDING_SCORE` is 0.83 on `(1 + cosine) / 2`, so a cosine of 0.66.

    **The case that separates the two readings**, and it took a second attempt
    to find. The obvious test -- two opposite vectors are not neighbours --
    passes whichever scale is used, because -1 and 0 are both below 0.83; it
    asserted the floor exists rather than where it is.

    A cosine of 0.75 is above the floor once mapped (0.875) and below it if the
    mapping is skipped. An adapter that compared raw cosine would silently
    apply a far harsher filter than the constant names, and the only symptom
    would be a curriculum with fewer semantic edges than it should have -- a
    number nobody has an independent expectation for.
    """
    tenant_id = uuid4()
    left, right = uuid4(), uuid4()
    store = await store_with(
        {left: unit(1, 0, 0, 0), right: unit(0.75, 0.6614378277661477, 0, 0)}, tenant_id
    )

    pairs = await VectorNeighbours(store, tenant_id=tenant_id).neighbours(
        [str(left), str(right)]
    )

    assert len(pairs) == 1, "a cosine of 0.75 maps to 0.875 and clears the floor"
    assert pairs[0][2] == pytest.approx(0.875, abs=1e-6)


@pytest.mark.asyncio
async def test_an_orthogonal_pair_is_not_a_neighbour():
    """The floor doing its ordinary job: unrelated things do not pair.

    Deliberately kept alongside the test above rather than folded into it.
    This one is about the constant being high enough to mean something; that
    one is about which scale it is read on.
    """
    tenant_id = uuid4()
    left, right = uuid4(), uuid4()
    store = await store_with({left: unit(1, 0, 0, 0), right: unit(0, 1, 0, 0)}, tenant_id)

    pairs = await VectorNeighbours(store, tenant_id=tenant_id).neighbours(
        [str(left), str(right)]
    )

    assert pairs == ()


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
