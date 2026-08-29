"""The semantic channel, end to end: the real adapter in the real loop.

`SemanticPort` (`application/area_projection.py`) has exactly one production
adapter, `VectorNeighbours`, and until this file nothing drove both ends over
data a real ingest wrote. `tests/infrastructure/test_semantic_neighbours.py`
drives the adapter alone against an `InMemoryVectorStore` it hand-fills;
`tests/application/test_curriculum.py` and `test_semantic_edges.py` drive
`project_areas` with literal tuples. Each half was verified, and the question
"does the real writer produce what the real reader expects" was asked by
nothing.

That is byte-for-byte the shape CLAUDE.md records for `CoMentionPort`, which
shipped, produced nothing from the day it merged, and printed a 0 on screen for
a whole feature. This file is the sibling of the remedy written then --
`tests/infrastructure/test_co_mentions.py`,
`test_a_curriculum_built_over_a_real_ingest_counts_shared_passages`.

**What was measured, on 2026-08-29.** Unlike the co-mention channel, this one
is alive. A real ingest of a five-entity document, embedded by the real
`qwen3-embedding-0.6b` endpoint at 1024 dimensions, driven through the real
`ProjectGraphReader`, the real `VectorNeighbours` and the real
`CurriculumService`, produced **5 semantic pairs** with `used_embeddings=True`:

    London          -- Charles Babbage     0.8308
    London          -- Ada Lovelace        0.8319
    Charles Babbage -- Analytical Engine   0.8360
    Charles Babbage -- Ada Lovelace        0.8745
    Difference Eng. -- Analytical Engine   0.8951

Every score sits just above `MIN_EMBEDDING_SCORE` (0.83), which is the part
worth keeping in view: the channel is alive, and it is alive by two hundredths.
`test_the_live_endpoint_draws_semantic_edges_over_a_real_ingest` is that
measurement, kept runnable with `-m live`.

**Why the CI arm does not use `FakeEmbeddingProvider`.** Its vectors come from
a hash and carry no semantics by its own docstring, so every pair scores near
0.5 -- below the floor -- and a "live" arm built on it would assert zero and
prove nothing. Measured here first: with `FakeEmbeddingProvider` the whole loop
runs, the card store is filled, every id resolves, and `semantic_count` is
still 0. That is a fixture artefact and would have read as the defect.
`CardWordEmbeddings` below is the smallest provider whose distances mean
something, so the CI arm can assert on a count that is 0 exactly when the
wiring is broken.
"""

import math
import os
import re
import zlib
from collections.abc import Sequence
from uuid import UUID, uuid4

import pytest
from redstring import InMemoryChunkStore, InMemoryVectorStore

from research_team.application.curriculum import CurriculumService
from research_team.application.knowledge import SourceRef
from research_team.infrastructure.knowledge.co_mention_reader import RecordedCoMentions
from research_team.infrastructure.knowledge.co_mentions import CoMentionIndex
from research_team.infrastructure.knowledge.graph_reader import ProjectGraphReader
from research_team.infrastructure.knowledge.semantic_neighbours import VectorNeighbours
from tests.conftest import fake_provider

#: Wide enough that two different words rarely share a slot, narrow enough that
#: a hand-run test costs nothing. Collisions only ever *raise* a similarity, so
#: the contrast arm -- which asserts zero -- cannot be flattered by one.
DIMENSION = 256

#: The live endpoint's embedding model and the width it returns. Named here
#: rather than read from `AGENT_*` so the live arm measures the model this
#: file's docstring quotes numbers for, not whatever the environment holds.
LIVE_BASE_URL = "http://192.168.1.14:8080/v1"
LIVE_MODEL = "qwen3-embedding-0.6b"
LIVE_DIMENSION = 1024

#: Five entities and four relationships, from one document. Five rather than
#: two because `EMBEDDING_NEIGHBOURS` is 5 and a two-entity graph cannot tell a
#: k-nearest walk from a cross product.
FIVE_ENTITIES = {
    "entities": [
        {"name": "Ada Lovelace", "entity_type": "Person"},
        {"name": "Charles Babbage", "entity_type": "Person"},
        {"name": "Analytical Engine", "entity_type": "Machine"},
        {"name": "Difference Engine", "entity_type": "Machine"},
        {"name": "London", "entity_type": "Place"},
    ],
    "relationships": [
        {
            "source_name": "Ada Lovelace",
            "target_name": "Charles Babbage",
            "relationship_type": "WORKED_WITH",
        },
        {
            "source_name": "Charles Babbage",
            "target_name": "Analytical Engine",
            "relationship_type": "DESIGNED",
        },
        {
            "source_name": "Charles Babbage",
            "target_name": "Difference Engine",
            "relationship_type": "DESIGNED",
        },
        {
            "source_name": "Charles Babbage",
            "target_name": "London",
            "relationship_type": "LIVED_IN",
        },
    ],
}

TEXT = (
    "Ada Lovelace worked with Charles Babbage on the Analytical Engine, a "
    "mechanical general-purpose computer designed in London. Babbage had "
    "earlier designed the Difference Engine, an automatic mechanical "
    "calculator. " * 6
)


class CardWordEmbeddings:
    """A deterministic `EmbeddingProvider` whose distances mean something.

    Bag of words, hashed into `DIMENSION` slots and normalised. Two entity
    cards that share vocabulary land close together; two that share none land
    orthogonal. That is not a model, and nothing here claims it ranks as well
    as one -- it is the minimum property `MIN_EMBEDDING_SCORE` needs in order
    to be a threshold rather than a wall.

    Deterministic per text, like `FakeEmbeddingProvider`, so nothing here
    depends on a seed or on the order cards are assembled in.
    """

    def __init__(self, *, dimension: int = DIMENSION) -> None:
        self._dimension = dimension

    @property
    def model(self) -> str:
        return "card-words-v1"

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    async def embed_query(self, texts: Sequence[str]) -> list[list[float]]:
        # Symmetric on purpose: an asymmetric fake would make the two sides of
        # a comparison incomparable, and this channel only ever compares
        # documents with documents.
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        counts = [0.0] * self._dimension
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            # `zlib.crc32` rather than `hash`: CPython salts string hashing
            # per process, so `hash` would give this provider a different
            # vector for the same card on every run -- deterministic within
            # a run and not across one, which is the worst of both.
            counts[zlib.crc32(word.encode()) % self._dimension] += 1.0
        norm = math.sqrt(sum(c * c for c in counts))
        if norm == 0.0:
            # A zero-norm vector is refused by the store on the way in, so an
            # empty card would fail the write rather than the assertion. One
            # arbitrary component keeps the failure legible.
            counts[0] = 1.0
            return counts
        return [c / norm for c in counts]


async def _ingest(build_adapter, tmp_path, *, embeddings, dimension):
    """One real ingest with every store the semantic channel touches.

    Returns the pieces the loop is assembled from, not a curriculum: each test
    below wires them differently, and the difference between the arms is the
    assertion.
    """
    project_id = uuid4()
    card_vectors = InMemoryVectorStore(dimension=dimension)
    co_mentions = CoMentionIndex()
    adapter, _, _ = build_adapter(
        tmp_path,
        project_id,
        provider=fake_provider(FIVE_ENTITIES),
        embeddings=embeddings,
        vector_store=InMemoryVectorStore(dimension=dimension),
        card_vector_store=card_vectors,
        cards=InMemoryChunkStore(dimension=dimension),
        chunks=InMemoryChunkStore(dimension=dimension),
        co_mentions=co_mentions,
    )
    await adapter.ingest(SourceRef(source_id="notes", text=TEXT))
    reader = ProjectGraphReader(project_id=project_id, store=adapter._store)
    return project_id, adapter, reader, card_vectors, co_mentions


@pytest.mark.asyncio
async def test_a_curriculum_built_over_a_real_ingest_draws_semantic_edges(
    build_adapter, tmp_path
):
    """The port and its adapter, meeting for the first time.

    The live arm is the real `CurriculumService` over the real
    `VectorNeighbours` over the card vector store a real ingest filled. The
    contrast arm is the same service over an **empty** store of the same width
    -- which is what every project ingested before embeddings were durable has,
    and what a build with `AGENT_VECTOR_STORE=none` has always had.

    Two arms rather than one absolute number for the reason the co-mention
    sibling gives: the count depends on `EMBEDDING_NEIGHBOURS` and on the
    fixture's cards, and asserting a specific integer would be a test of those.

    *Fails against* the whole class of defect this file exists for: a card
    store keyed by anything but the entity id, a graph read whose
    `entity_id` strings do not parse as the UUIDs the store was written under,
    a `CurriculumService` that stops passing `semantic` to `project_areas`, or
    an ingest that stops writing card vectors at all. Each of those leaves
    `semantic_count` at 0 with nothing raised and nothing logged.

    **Proved red on 2026-08-29**, twice, one break per end of the seam. The
    writer: deleting `await self._card_vectors.upsert_many(event.embeddings)`
    from `RedstringKnowledge._record_embeddings` -- 2 failed, 0 passed over this
    file, and the sibling test below names which end broke. The consumer:
    `project_areas(graph, passages, [])` in `CurriculumService.build` -- 1
    failed, 1 passed, which is the split that makes the pair worth having. The
    tree was restored from a copy rather than with `git checkout`, which would
    have taken the rest of this change with it.
    """
    project_id, adapter, reader, card_vectors, co_mentions = await _ingest(
        build_adapter, tmp_path, embeddings=CardWordEmbeddings(), dimension=DIMENSION
    )
    co_mention_reader = RecordedCoMentions(co_mentions, project_id, adapter._store)

    live = await CurriculumService().build(
        project_id,
        reader,
        co_mention_reader,
        VectorNeighbours(card_vectors, tenant_id=project_id),
    )
    dead = await CurriculumService().build(
        project_id,
        reader,
        co_mention_reader,
        VectorNeighbours(InMemoryVectorStore(dimension=DIMENSION), tenant_id=project_id),
    )

    assert live.projection.semantic_count > 0, (
        "an ingest that embedded five entity cards has neighbours among them; "
        "zero here is the channel not running, which is what the co-mention "
        "channel did for a whole feature"
    )
    assert live.projection.used_embeddings, (
        "a run that drew edges must record that it did, or 'configured' and "
        "'used' stop being distinguishable on the projection"
    )
    assert dead.projection.semantic_count == 0, (
        "a store nothing wrote to reports zero, which is what a project "
        "ingested before embeddings were durable has"
    )
    assert not dead.projection.used_embeddings


@pytest.mark.asyncio
async def test_the_adapter_reads_the_store_under_the_ids_the_graph_read_hands_it(
    build_adapter, tmp_path
):
    """The seam itself, named, because the count above cannot say where it broke.

    `VectorNeighbours.neighbours` is given `entity_id` *strings* off a graph
    read and looks the store up by `UUID(entity_id)` under the project as
    tenant. Three independent things have to agree for that to find anything,
    and none of them is checked by either end's own tests: the writer keys by
    entity id, the graph read's strings parse as those UUIDs, and both use the
    project id as the tenant.

    Asserted on every entity rather than on one, because a partial hit -- the
    ontology pass's synthesised class nodes, say -- is the failure this
    channel degrades through silently.
    """
    project_id, _, reader, card_vectors, _ = await _ingest(
        build_adapter, tmp_path, embeddings=CardWordEmbeddings(), dimension=DIMENSION
    )
    graph = await reader.whole()
    assert len(graph.entities) == 5, "the fake extraction should give five entities"

    for entity in graph.entities:
        record = await card_vectors.get(UUID(entity.entity_id), project_id)
        assert record is not None, (
            f"no card vector under {entity.name}'s graph-read id; the writer "
            "and the reader disagree about the key, which is invisible from "
            "either side alone"
        )


@pytest.mark.live
@pytest.mark.asyncio
async def test_the_live_endpoint_draws_semantic_edges_over_a_real_ingest(
    build_adapter, tmp_path
):
    """The number this file's docstring quotes, kept runnable.

    Deselected by default, so this is not a gate. It exists because the CI arm
    above uses a bag-of-words provider, which proves the wiring and says
    nothing about whether real card embeddings clear `MIN_EMBEDDING_SCORE` --
    and that is the question the co-mention incident was really about. The
    answer on 2026-08-29 was five pairs, every one within 0.07 of the floor.

    Prints the pairs and their scores rather than only asserting, because the
    margin is the finding and an assertion on `> 0` hides it.
    """
    from research_team.infrastructure.agent.deep_agent import build_embedding_provider

    os.environ["AGENT_EMBEDDING_BASE_URL"] = LIVE_BASE_URL
    os.environ["AGENT_EMBEDDING_MODEL"] = LIVE_MODEL
    os.environ["AGENT_EMBEDDING_DIMENSION"] = str(LIVE_DIMENSION)
    os.environ.setdefault("AGENT_EMBEDDING_API_KEY", "not-checked-locally")

    project_id, adapter, reader, card_vectors, co_mentions = await _ingest(
        build_adapter,
        tmp_path,
        embeddings=build_embedding_provider(),
        dimension=LIVE_DIMENSION,
    )
    graph = await reader.whole()
    names = {e.entity_id: e.name for e in graph.entities}
    pairs = await VectorNeighbours(card_vectors, tenant_id=project_id).neighbours(
        sorted(names)
    )
    for left, right, score in pairs:
        print(f"{names[left]} -- {names[right]}  {score:.4f}")

    curriculum = await CurriculumService().build(
        project_id,
        reader,
        RecordedCoMentions(co_mentions, project_id, adapter._store),
        VectorNeighbours(card_vectors, tenant_id=project_id),
    )
    assert curriculum.projection.semantic_count > 0, (
        "real card embeddings over a real ingest drew nothing above "
        "MIN_EMBEDDING_SCORE; the channel is configured and contributes "
        "nothing, which is the co-mention defect with a different cause"
    )
