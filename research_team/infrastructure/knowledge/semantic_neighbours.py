"""Each entity's nearest neighbours in embedding space, as graph edges.

The adapter behind `application.area_projection.SemanticPort`. It answers the
question the graph cannot: which two entities are about the same thing when no
document put them in a sentence together and no model asserted an edge between
them.

**Why this does the arithmetic rather than calling `VectorStore.search`.** The
port has a perfectly good `search`, and using it costs one call per entity --
which is exact, and quadratic, and done in Python. Measured on 2026-08-22
against redstring's `InMemoryVectorStore` at 768 dimensions: 100 entities in
0.52s, 250 in 3.26s, 500 in 13.88s. The projection advertises a cap of 2,000,
which extrapolates to about four minutes for a route budgeted in seconds. The
same work as one float32 matrix multiply is 0.056s.

So the vectors are fetched once by id -- `get` per entity, which is a dict
lookup on the in-memory store -- and the neighbourhood is computed here. The
cost of that choice is a dense `n x n` similarity matrix held briefly: 16MB at
the 2,000 cap, and quadratic in memory as well as time, which is why
`MAX_SEMANTIC_ENTITIES` exists below rather than being left to the caller.

**A missing vector is not an error.** Entities extracted before embeddings
were durable have none, a provider whose endpoint was down leaves gaps, and a
graph read may include the ontology pass's synthesised class nodes, which are
not redstring entities and were never embedded. All three arrive as "no
record" and the entity simply contributes no semantic edge.
"""

import logging
from collections.abc import Sequence
from uuid import UUID

import numpy as np

from research_team.application.area_projection import (
    EMBEDDING_NEIGHBOURS,
    MIN_EMBEDDING_SCORE,
)

logger = logging.getLogger(__name__)

#: Above this many *embedded* entities the semantic channel is skipped.
#:
#: Chosen for memory rather than time: the similarity matrix is `n^2` float32,
#: so 4,000 is 64MB held while a request is in flight and 8,000 would be
#: 256MB. The projection's own `MAX_CLUSTERED_ENTITIES` is 2,000 and refuses
#: above it, so this is deliberately set beyond that -- it is a backstop for a
#: caller that raised the other cap, not a second limit a normal run can meet.
#: Skipping is silent in the areas and visible in `semantic_count`, which is 0.
MAX_SEMANTIC_ENTITIES = 4_000


class VectorNeighbours:
    """`SemanticPort` over a project's entity-card vector store.

    Holds the store and the tenant, and nothing else. Constructed per request
    rather than cached: the store it reads is the one `ProjectGraphs` folded
    at open, so this object is a view of it and caching a view buys nothing.
    """

    def __init__(self, vectors: object, *, tenant_id: UUID) -> None:
        self._vectors = vectors
        self._tenant_id = tenant_id

    async def neighbours(self, entity_ids: Sequence[str]) -> Sequence[tuple[str, str, float]]:
        """Close pairs among `entity_ids`, as `(left, right, score)`.

        `left < right` and each pair appears once, which is the port's
        contract: a pair reported twice would be weighted twice by an
        adjacency that adds rather than replaces.

        Symmetry is deliberate and is why the pairs are collected into a set.
        `A`'s five nearest may include `B` while `B`'s five nearest do not
        include `A` -- k-nearest-neighbour is not a symmetric relation -- and
        taking the union rather than the intersection is the choice that keeps
        a hub reachable from the periphery. The intersection would drop
        exactly the edges that bridge a small cluster to a large one, which
        are the edges this channel exists to draw.
        """
        if self._vectors is None or not entity_ids:
            return ()

        # Preserve the caller's order and drop duplicates, so the matrix rows
        # line up with `usable` by position and nothing is compared to itself
        # under two names.
        unique = list(dict.fromkeys(entity_ids))

        usable: list[str] = []
        rows: list[Sequence[float]] = []
        for entity_id in unique:
            try:
                record = await self._vectors.get(UUID(entity_id), self._tenant_id)
            except ValueError:
                # Not a UUID at all. The ontology pass derives class-node ids
                # from its own table, and they reach a graph read alongside
                # real entities; `GraphEntity.inferred` marks them but this
                # port is given ids rather than entities.
                continue
            if record is not None:
                usable.append(entity_id)
                rows.append(record.vector)

        if len(usable) < 2:
            return ()
        if len(usable) > MAX_SEMANTIC_ENTITIES:
            logger.info(
                "skipping semantic edges for %d embedded entities; above the "
                "%d this pass will hold a similarity matrix for",
                len(usable),
                MAX_SEMANTIC_ENTITIES,
            )
            return ()

        matrix = np.asarray(rows, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        # A zero-norm vector cannot be stored through the port -- it raises on
        # the way in -- so this guards against a store that was written by
        # something else rather than against an expected case. Dividing by it
        # would put `nan` through the whole row and `argpartition` would rank
        # on it.
        if not np.all(norms > 0):
            logger.warning("dropping semantic edges: a stored vector has zero norm")
            return ()
        matrix /= norms

        similarity = matrix @ matrix.T
        # redstring's scale, stated once in `ports/vector_store.py`: cosine
        # mapped onto 0..1 by `(1 + cosine) / 2`, so 0.5 is orthogonal. The
        # port's own `search` returns this scale and `MIN_EMBEDDING_SCORE` is
        # read on it, so the conversion belongs here rather than at either end.
        similarity = (1.0 + similarity) / 2.0
        # After the rescale, not before: -1 is a valid cosine and would survive
        # into the top-k of a row whose real neighbours all fell below the
        # floor. Below the 0..1 scale's floor it cannot.
        np.fill_diagonal(similarity, -1.0)

        k = min(EMBEDDING_NEIGHBOURS, len(usable) - 1)
        # `argpartition` rather than `argsort`: the k nearest are wanted, their
        # order among themselves is not, and partition is linear per row where
        # a full sort is `n log n`.
        top = np.argpartition(-similarity, k - 1, axis=1)[:, :k]

        pairs: dict[tuple[str, str], float] = {}
        for row, columns in enumerate(top):
            for column in columns:
                score = float(similarity[row, column])
                if score < MIN_EMBEDDING_SCORE:
                    continue
                left, right = usable[row], usable[int(column)]
                if left == right:
                    continue
                key = (left, right) if left < right else (right, left)
                # Both directions compute the same score, so this is a
                # deduplication rather than a choice between two values.
                pairs[key] = score

        # Sorted so the projection is handed the same sequence on every run.
        # The clustering is order-independent by construction, but a port that
        # returns a differently-ordered sequence each time makes that a claim
        # nobody can check rather than one a test can pin.
        return tuple((left, right, score) for (left, right), score in sorted(pairs.items()))
