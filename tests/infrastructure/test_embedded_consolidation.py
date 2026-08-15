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
discrimination.

**Measured on 2026-08-14** against a real `nomic-embed-text`, which the
paragraph above could only estimate. The "0.011 apart" figure this docstring
used to give was wrong -- that pair is 0.31 apart -- but the claim it was
supporting is right, and more strongly than the number suggested. Over ten
same-entity and ten different-entity pairs there is **no threshold that
separates them**: the weakest true pair scores below the strongest false one
in every prefixing scheme tried (bare -0.235, `clustering:` -0.114,
`search_document:`/`search_query:` -0.192). The embedding feature ranks; it
does not gate. See BACKLOG B58 for the table and what follows from it.
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


def _score(name: float, embedding: float | None, graph: float | None) -> float:
    """Scored the way the adapter scores: redstring's own default weights."""
    return combined_score(
        SimilarityFeatures(name=name, embedding=embedding, graph=graph), FeatureWeights()
    )


def test_containment_does_not_fire_for_a_cross_document_pair():
    """0.9.0's containment fix is real and unreachable, and that is the finding.

    `string_similarity` gained token containment in 0.9.0, so `Dr. Grant`
    against `Grant` scores `CONTAINMENT_CEILING` (0.85) rather than the 0.437
    an edit distance gives it. It buys nothing here. A cross-document pair
    carries `graph = 0.0` as a *present* feature, `combined_score` keeps a
    present zero in its divisor, and the pair lands below `LOW_SIMILARITY`:

        0.5(0.85) + 0.3(1.00) + 0.2(0.00)  =  0.7250  <  0.75

    Rejected before the adjudicator is ever offered it, and **at any embedding
    value whatever** -- clearing 0.75 would need an embedding of 1.083, which
    is why the first assertion below uses a perfect 1.0: `combined_score` is
    monotonic in the embedding, so rejecting at the ceiling rejects everywhere.

    **The reweighting sweep is the assertion that matters**, because it is the
    one that rules out the fix this repository actually attempted and withdrew
    (6c2ae4a). No split of the remaining budget across name and embedding
    rescues a pair whose third feature is a present zero -- swept below against
    the *measured* 0.8516 embedding rather than the assumed 1.0, because
    assuming that number is precisely how the withdrawn reweight came to look
    like it worked. Prose here would be the same mistake in a different place.

    B58 is the fix: with the graph feature *absent* rather than zero, the same
    pair scores 0.8506 against a real `nomic-embed-text` and is adjudicated.
    """
    assert string_similarity("Dr. Grant", "Grant") == CONTAINMENT_CEILING

    score = _score(name=CONTAINMENT_CEILING, embedding=1.0, graph=0.0)

    assert score == pytest.approx(0.7250)
    assert decide(score) is MergeDecision.REJECT

    # Every reweighting of name against embedding, graph left at its default.
    # Measured embedding, not the assumed one: 0.8516 from a real
    # `nomic-embed-text` on 2026-08-14 (BACKLOG B58 carries the table).
    for tenth in range(9):
        name_weight = tenth / 10
        weights = FeatureWeights(name=name_weight, embedding=0.8 - name_weight, graph=0.2)
        swept = combined_score(
            SimilarityFeatures(name=CONTAINMENT_CEILING, embedding=0.8516, graph=0.0),
            weights,
        )
        assert decide(swept) is MergeDecision.REJECT, (
            f"name={name_weight} scored {swept:.4f}; if this ever passes, the "
            f"reweight withdrawn in 6c2ae4a would have worked after all"
        )

    # Absent rather than zero -- the whole of B58, in one line.
    assert decide(_score(CONTAINMENT_CEILING, 1.0, None)) is MergeDecision.ADJUDICATE


def test_zeroing_the_graph_weight_would_auto_merge_on_name_alone():
    """Why no `weights=` override is passed, and why the obvious one is a trap.

    `FeatureWeights(graph=0.0)` and `use_graph_signal=False` are the same
    scoring change -- a zero weight is exactly equivalent to an absent feature,
    per `combined_score`'s own docstring -- and neither can be scoped to the
    cross-document case, because weights are fixed when the `Consolidator` is
    constructed and `resolve` takes no override.

    Dropping graph from the divisor leaves a weighted mean of two features both
    near 1.0 for a duplicate, so it clears `HIGH_SIMILARITY` (0.92) for *any*
    name/embedding split: the `#84` duplicate would merge with no model call.
    Worse, with no embeddings configured it leaves name as the only feature,
    renormalized to weight 1.0, so an exact name match auto-merges on one
    feature -- which is a silent merge in the cheap configuration this project
    still supports.

    Executable so that "just zero the graph weight" is refused by the suite and
    not only by a comment. It was proposed, and these are the numbers that
    rejected it.
    """
    zeroed = FeatureWeights(name=0.6, embedding=0.4, graph=0.0)

    duplicate = combined_score(SimilarityFeatures(name=1.0, embedding=1.0, graph=0.0), zeroed)
    assert decide(duplicate) is MergeDecision.MERGE, "the adjudicator is bypassed"

    name_only = combined_score(SimilarityFeatures(name=1.0, embedding=None, graph=0.0), zeroed)
    assert decide(name_only) is MergeDecision.MERGE, "merged on a name and nothing else"

    # redstring's defaults, which is what the adapter uses: both stay in hand.
    assert decide(_score(1.0, 1.0, 0.0)) is MergeDecision.ADJUDICATE
    assert decide(_score(1.0, None, 0.0)) is MergeDecision.REJECT


def test_a_cross_document_pair_cannot_auto_merge_however_good_the_evidence():
    """The cap that keeps every duplicate costing one adjudicator call.

    A perfect name and a perfect embedding against `graph = 0.0` reach exactly
    0.8000, below `HIGH_SIMILARITY` (0.92). This is the arithmetic behind the
    claim `test_auto_merge_stays_out_of_reach_so_every_duplicate_costs_a_call`
    asserts through an ingest; kept beside it because that test proves the
    behaviour and this one says why, and the two fail for different reasons.

    The same present zero that causes B58's recall problem is what provides
    this safety, which is why B58 is a judgement call and not a pure win: with
    the feature absent, `Retriever`/`Retrievers` auto-merges at 0.968.
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
