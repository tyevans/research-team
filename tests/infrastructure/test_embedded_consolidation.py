"""What the third scoring feature does, and what it costs when it is absent.

The measurement these tests pin, taken through a real `CandidateFinder` on the
`#84` fixture shape (each side carrying its own distinct neighbour, which is
what makes `graph = 0.0` an honest finding rather than an absent feature):

| pair                       | two features   | three features |
|----------------------------|----------------|----------------|
| **exact duplicate (#84)**  | 0.7143 dropped | **0.8000 admitted** |
| `Retriever`/`Retrievers`   | 0.7102 dropped | 0.6409 dropped |
| `Robert`/`Roberta Smith`   | 0.7033 dropped | 0.6686 dropped |
| `World War I`/`II`         | 0.7024 dropped | 0.6391 dropped |
| `University of York`/`Cork`| 0.6984 dropped | 0.6543 dropped |

**The right-hand column is not evidence about a real embedding model, and
must not be read as any.** `FakeEmbeddingProvider` hashes text into a unit
vector, so it returns 1.0 for two identical strings and roughly 0.5 for every
other pair -- `World War I` against `World War II` scores 0.55, and so does
`Bicycle`. It models "the same text gives the same vector" exactly and
semantic similarity not at all. A real model returns 0.90 or better on
near-identical names, which puts every one of those four near-misses at
0.759--0.787 and therefore **above** `LOW_SIMILARITY`.

So the honest claim, and the only one these tests make: three-feature scoring
lifts the exact cross-document duplicate over `LOW_SIMILARITY` **on its own
evidence**, which is what lets the `low=` override go. It does not improve
discrimination -- under a real model the exact duplicate and
`University of York`/`University of Cork` land 0.011 apart.
"""

from uuid import uuid4

import pytest
from redstring import (
    FakeEmbeddingProvider,
    FakeLlmProvider,
    FeatureWeights,
    InMemoryVectorStore,
)
from redstring.consolidation.policy import MergeDecision, decide
from redstring.domain.similarity import (
    CONTAINMENT_CEILING,
    SimilarityFeatures,
    combined_score,
    string_similarity,
)

from research_team.application.knowledge import SourceRef
from research_team.infrastructure.knowledge.redstring_adapter import _WEIGHTS
from tests.infrastructure.test_redstring_adapter import (
    _BREED_AND_HUNTING,
    _BREED_IN_CANADA,
    _SAYS_THEY_ARE_THE_SAME,
)

EMBEDDING_DIMENSION = 64


@pytest.fixture
def breed_provider():
    """The `#84` corpus: one breed, two documents, two different neighbours."""
    return FakeLlmProvider(
        by_substring={
            "duck hunting": _BREED_AND_HUNTING,
            "Pair 1": _SAYS_THEY_ARE_THE_SAME,
        },
        default=_BREED_IN_CANADA,
    )


@pytest.mark.asyncio
async def test_a_cross_document_duplicate_merges_with_no_floor(
    tmp_path, build_adapter, breed_provider
):
    """The `#84` pair, scored with three features and redstring's own `low`.

    This is the test the whole change exists for. PR #84 could only merge this
    pair by overriding `LOW_SIMILARITY` with `EXACT_NAME_SCORE` (0.7143), and
    PR #87 kept that override because redstring 0.5.0 does not fix this
    fixture -- its two documents describe genuinely different neighbourhoods,
    so `graph = 0.0` is a true statement about them.

    With an embedding channel the pair scores **0.8000** and clears
    redstring's unmodified 0.75 by itself. `build_adapter` no longer passes
    `low=` anywhere; the floor is gone from the source, so this test cannot
    pass because of it.

    **Proved red before it was trusted green**: with the vector store removed
    from this call and everything else identical, the pair scores 0.7143 and
    `search` finds two canonical nodes.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(
        tmp_path,
        project_id,
        provider=breed_provider,
        adjudicate=True,
        embeddings=FakeEmbeddingProvider(dimension=EMBEDDING_DIMENSION),
        vector_store=InMemoryVectorStore(dimension=EMBEDDING_DIMENSION),
    )

    await adapter.ingest(SourceRef(source_id="a", text="The breed originates in Canada."))
    await adapter.ingest(SourceRef(source_id="b", text="The breed is used for duck hunting."))

    matches = await adapter.search("Nova Scotia Duck Tolling Retriever")
    assert len(matches) == 1, f"one breed, one node; got {[match.name for match in matches]}"


@pytest.mark.asyncio
async def test_without_embeddings_the_same_pair_stays_two_nodes(
    tmp_path, build_adapter, breed_provider
):
    """The other half, and the reason the test above is not self-congratulation.

    Identical to it but for the vector store. The pair scores 0.7143, below
    redstring's 0.75, and is dropped before the adjudicator is offered it --
    no exception, no verdict, two nodes and silence. That is the shipped bug
    `#84` reported, still reproducible on 0.5.0 once the floor is removed.

    Keeping this beside the passing case is what stops the floor's deletion
    being justified by an assertion nobody re-derived.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(
        tmp_path, project_id, provider=breed_provider, adjudicate=True
    )

    await adapter.ingest(SourceRef(source_id="a", text="The breed originates in Canada."))
    await adapter.ingest(SourceRef(source_id="b", text="The breed is used for duck hunting."))

    matches = await adapter.search("Nova Scotia Duck Tolling Retriever")
    assert len(matches) == 2, "two features cannot reach 0.75; this is the #84 bug"


@pytest.mark.asyncio
async def test_auto_merge_stays_out_of_reach_so_every_duplicate_costs_a_call(
    tmp_path, build_adapter, breed_provider
):
    """0.8000 is below `HIGH_SIMILARITY` (0.92), and that is the running cost.

    A perfect name and a perfect embedding cap at 0.8 against `graph = 0.0`,
    so no cross-document duplicate can reach the merge-without-asking band
    whatever the evidence. Every one of them is adjudicated -- one model call
    per duplicate, per ingest, for as long as this fixture's shape is the
    common one.

    Asserted by removing the adjudicator: with nothing to ask, the band is
    rejected and the pair stays two nodes. If a future change made auto-merge
    reachable this test would go red, which is the point -- that would be a
    real behaviour change and it should not land silently.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(
        tmp_path,
        project_id,
        provider=breed_provider,
        adjudicate=False,
        embeddings=FakeEmbeddingProvider(dimension=EMBEDDING_DIMENSION),
        vector_store=InMemoryVectorStore(dimension=EMBEDDING_DIMENSION),
    )

    await adapter.ingest(SourceRef(source_id="a", text="The breed originates in Canada."))
    await adapter.ingest(SourceRef(source_id="b", text="The breed is used for duck hunting."))

    matches = await adapter.search("Nova Scotia Duck Tolling Retriever")
    assert len(matches) == 2, "0.8 is in the adjudication band, not the auto-merge one"


def _score(name: float, embedding: float, graph: float | None) -> float:
    return combined_score(
        SimilarityFeatures(name=name, embedding=embedding, graph=graph), _WEIGHTS
    )


def test_a_title_qualified_name_reaches_the_adjudicator():
    """The reweight's whole purpose, and it cannot be tested through an ingest.

    redstring 0.9.0 gave `string_similarity` token containment, so
    `Dr. Grant`/`Grant` scores `CONTAINMENT_CEILING` (0.85) rather than 0.437.
    Under redstring's default weights that fix does not fire for a
    cross-document pair -- `graph = 0.0` is *present*, so it stays in
    `combined_score`'s divisor and the pair lands at 0.7250, below
    `LOW_SIMILARITY`, at any embedding value whatever.

    Asserted on the scoring functions rather than through `adapter.ingest`
    because `FakeEmbeddingProvider` hashes text into a unit vector and returns
    roughly 0.5 for any two non-identical strings -- see this module's
    docstring. It cannot produce the ~1.0 a real model gives two spellings of
    one name, so an end-to-end version of this test would pin the fake's
    hashing, not the weights. The embedding value here is therefore an
    **assumption about a real model**, stated in the call rather than hidden.

    Proved red before it was trusted green: with `_WEIGHTS` at redstring's
    defaults this scores 0.7250 and `decide` says `reject`.
    """
    assert string_similarity("Dr. Grant", "Grant") == CONTAINMENT_CEILING

    score = _score(name=CONTAINMENT_CEILING, embedding=1.0, graph=0.0)

    assert score == pytest.approx(0.7550)
    assert decide(score) is MergeDecision.ADJUDICATE


def test_zeroing_the_graph_weight_would_auto_merge_on_name_alone():
    """Why `_WEIGHTS` keeps graph at 0.2 instead of dropping it to 0.0.

    A zero weight is exactly equivalent to an absent feature, so
    `FeatureWeights(graph=0.0)` and `use_graph_signal=False` are the same
    scoring change -- and neither can be scoped to the cross-document case,
    because weights are fixed when the `Consolidator` is constructed.

    Dropping graph from the divisor leaves a weighted mean of features that are
    both near 1.0 for a duplicate, which clears `HIGH_SIMILARITY` (0.92) for
    *any* name/embedding split. The `#84` exact duplicate would merge with no
    model call at all. Worse, in a deployment without embeddings it leaves name
    as the only feature, renormalized to weight 1.0, so an exact name match
    auto-merges on one feature.

    This test is the argument in `_WEIGHTS`'s note made executable, so that
    "just zero the graph weight" is refused by the suite and not only by a
    comment somebody may not read.
    """
    zeroed = FeatureWeights(name=0.6, embedding=0.4, graph=0.0)

    duplicate = combined_score(SimilarityFeatures(name=1.0, embedding=1.0, graph=0.0), zeroed)
    assert decide(duplicate) is MergeDecision.MERGE, "the adjudicator is bypassed"

    name_only = combined_score(SimilarityFeatures(name=1.0, embedding=None, graph=0.0), zeroed)
    assert decide(name_only) is MergeDecision.MERGE, "merged on a name and nothing else"

    # What `_WEIGHTS` does with the same two pairs: both stay in the band.
    assert decide(_score(1.0, 1.0, 0.0)) is MergeDecision.ADJUDICATE
    assert decide(_score(1.0, None, 0.0)) is MergeDecision.REJECT


def test_a_cross_document_pair_cannot_auto_merge_however_good_the_evidence():
    """The cap that keeps every duplicate costing one adjudicator call.

    A perfect name and a perfect embedding against `graph = 0.0` reach exactly
    0.8000, below `HIGH_SIMILARITY` (0.92). This is the arithmetic behind the
    claim `test_auto_merge_stays_out_of_reach_so_every_duplicate_costs_a_call`
    asserts through an ingest; kept beside it because that test proves the
    behaviour and this one says why, and the two fail for different reasons.

    A pair whose neighbourhoods *do* overlap is not capped -- that is the value
    the graph weight still carries, and the reason it is 0.2 rather than 0.
    """
    assert _score(1.0, 1.0, 0.0) == pytest.approx(0.8000)
    assert decide(_score(1.0, 1.0, 0.0)) is MergeDecision.ADJUDICATE

    assert decide(_score(1.0, 1.0, 1.0)) is MergeDecision.MERGE


class _DeadEmbeddings:
    """An `EmbeddingProvider` whose endpoint is not there.

    Stands in for the common misconfiguration now that the feature defaults on:
    `AGENT_EMBEDDING_BASE_URL` falls back to the chat endpoint, and llama.cpp
    serves one model per process, so "the server is up and does not do
    embeddings" is the case to survive rather than an exotic one.
    """

    model = "not-served-here"
    dimension = EMBEDDING_DIMENSION

    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, texts):
        self.calls += 1
        raise ConnectionError("404 page not found")


class _WrongWidthEmbeddings:
    """A provider whose server disagrees with it about the vector width.

    The failure that does not raise, and the more dangerous of the two: it
    reaches `VectorProjection` as a `DimensionMismatchError`, which is a
    poison event -- unrecoverable rather than retryable -- in the middle of an
    ingest that has already been paid for.
    """

    model = "wrong-width"
    dimension = EMBEDDING_DIMENSION

    async def embed(self, texts):
        return [[0.0] * (EMBEDDING_DIMENSION * 2) for _ in texts]


@pytest.mark.asyncio
async def test_a_dead_embedding_endpoint_costs_no_document(
    tmp_path, build_adapter, breed_provider, caplog
):
    """The ingest completes, the graph is built, and the log says what was lost.

    This is what makes the default safe to turn on. `build_graph` embeds
    *after* it extracts, so letting the error out would discard a document that
    had already been fetched and every model call its extraction cost -- to
    lose an optional third scoring feature. `_store_document` makes the same
    trade in the other direction: the cheap failure is the one left possible.

    Would pass with the change reverted only in the sense that a two-feature
    deployment also ingests fine. What it actually pins is that a *configured*
    embedding provider which fails does not become an ingest failure, and the
    assertion on `caplog` is what stops the degradation being silent.
    """
    project_id = uuid4()
    dead = _DeadEmbeddings()
    adapter, _, _ = build_adapter(
        tmp_path,
        project_id,
        provider=breed_provider,
        embeddings=dead,
        vector_store=InMemoryVectorStore(dimension=EMBEDDING_DIMENSION),
    )

    report = await adapter.ingest(
        SourceRef(source_id="a", text="The breed originates in Canada.")
    )

    assert report.entity_count == 2, "the document was extracted despite no embeddings"
    assert "did not answer a probe" in caplog.text
    assert dead.calls == 1, "probed once and latched, not retried per document"


@pytest.mark.asyncio
async def test_a_width_disagreement_is_caught_by_the_probe(
    tmp_path, build_adapter, breed_provider, caplog
):
    """Checked before it can become a poison event.

    A provider declaring 64 against a server returning 128 raises nothing at
    the call; it raises `DimensionMismatchError` at the projection, which is
    unrecoverable. Catching it in the probe turns an unrecoverable mid-ingest
    failure into a logged degradation, and the message names both numbers
    because "set both or neither" is the fix and neither number alone says so.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(
        tmp_path,
        project_id,
        provider=breed_provider,
        embeddings=_WrongWidthEmbeddings(),
        vector_store=InMemoryVectorStore(dimension=EMBEDDING_DIMENSION),
    )

    report = await adapter.ingest(
        SourceRef(source_id="a", text="The breed originates in Canada.")
    )

    assert report.entity_count == 2
    assert "components and the vector store holds" in caplog.text


@pytest.mark.asyncio
async def test_half_a_configuration_is_no_configuration(
    tmp_path, build_adapter, breed_provider
):
    """A provider with no store, or a store with no provider, is switched off.

    Either half alone looks enabled and behaves disabled: a store nothing
    writes to scores every pair with the embedding feature absent while costing
    a lookup per candidate, and a provider with nowhere to put its vectors pays
    for them and discards them. Collapsed to one fact in `__init__` rather than
    left for `build_graph` to half-honour.

    Pinned on the `#84` pair, which is the observable difference: with only
    half a configuration it scores 0.7143 and stays two nodes.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(
        tmp_path,
        project_id,
        provider=breed_provider,
        adjudicate=True,
        embeddings=FakeEmbeddingProvider(dimension=EMBEDDING_DIMENSION),
        vector_store=None,
    )

    await adapter.ingest(SourceRef(source_id="a", text="The breed originates in Canada."))
    await adapter.ingest(SourceRef(source_id="b", text="The breed is used for duck hunting."))

    matches = await adapter.search("Nova Scotia Duck Tolling Retriever")
    assert len(matches) == 2, "a provider with no store must not score as three features"
