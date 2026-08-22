"""What a consolidation pass costs the endpoint, counted rather than reasoned.

The number this module pins is **adjudicator calls per ingest**, which
`config.extraction_chunk_size`'s docstring already names as the one to watch:
auto-merge is unreachable across documents, so every cross-document duplicate
is adjudicated, and smaller chunks make more of them.

`Adjudicator.adjudicate` batches within one subject. The band is a small
fraction of a block by design, so a per-subject batch is nearly always one or
two pairs -- which made the per-entity `resolve` loop spend one round trip per
duplicate. `resolve_many` batches *across* subjects, so a whole chunk's band
fills one prompt.

The counting is done at the `LlmProvider` seam because that is where a round
trip actually happens; counting `Adjudicator` calls instead would count
batches, which is the thing under test and would therefore assert itself.
"""

import re
from uuid import uuid4

import pytest
from redstring import FakeEmbeddingProvider, FakeLlmProvider, InMemoryVectorStore

from research_team.application.knowledge import SourceRef

EMBEDDING_DIMENSION = 64

#: Three entities, each with a neighbour that is this document's alone. The
#: disjoint neighbourhoods are what hold the graph feature at 0.0 and keep the
#: duplicate pairs at 0.8 -- in the adjudication band, below `HIGH_SIMILARITY`
#: 0.92, which is the case this module is about. Shared neighbours would score
#: higher and could auto-merge, costing no call and proving nothing.
_THREE_IN_CANADA = {
    "entities": [
        {"name": "Alpha Retriever", "entity_type": "concept"},
        {"name": "Beta Terrier", "entity_type": "concept"},
        {"name": "Gamma Spaniel", "entity_type": "concept"},
        {"name": "Canada", "entity_type": "concept"},
    ],
    "relationships": [
        {"source_name": name, "target_name": "Canada", "relationship_type": "ORIGINATES_IN"}
        for name in ("Alpha Retriever", "Beta Terrier", "Gamma Spaniel")
    ],
}

_THREE_AND_HUNTING = {
    "entities": [
        {"name": "Alpha Retriever", "entity_type": "concept"},
        {"name": "Beta Terrier", "entity_type": "concept"},
        {"name": "Gamma Spaniel", "entity_type": "concept"},
        {"name": "Duck hunting", "entity_type": "concept"},
    ],
    "relationships": [
        {"source_name": name, "target_name": "Duck hunting", "relationship_type": "USED_FOR"}
        for name in ("Alpha Retriever", "Beta Terrier", "Gamma Spaniel")
    ],
}

_PAIR = re.compile(r"^Pair \d+", re.MULTILINE)


class _CountingAdjudicationProvider:
    """Extraction delegated; adjudication answered here and counted.

    Answers with **one verdict per pair the prompt actually asks about**,
    read off the rendered text rather than assumed. A fixed-length verdict
    list would fail `zip(strict=True)` upstream the moment batching widened
    the prompt, and upstream turns that mismatch into `None` for every pair --
    which reads as "the model declined", not as a broken fake. The bug would
    look like the feature not working.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        #: Pairs asked about, per call. `len` is round trips; `sum` is pairs.
        self.adjudications: list[int] = []

    def __getattr__(self, name):
        # `LlmProvider` carries more than `extract` -- `model` at least,
        # which redstring reads when it records provenance. Delegating
        # rather than declaring keeps this fake from having to track the
        # protocol's surface.
        return getattr(self._inner, name)

    async def extract(self, text, schema, *, system_prompt=None, **kwargs):
        pairs = len(_PAIR.findall(text))
        if pairs:
            self.adjudications.append(pairs)
            return schema(
                verdicts=[
                    {"same": True, "confidence": 0.99, "reason": "identically named"}
                    for _ in range(pairs)
                ]
            )
        return await self._inner.extract(text, schema, system_prompt=system_prompt, **kwargs)


@pytest.fixture
def three_duplicates_provider():
    return _CountingAdjudicationProvider(
        FakeLlmProvider(
            by_substring={"duck hunting": _THREE_AND_HUNTING},
            default=_THREE_IN_CANADA,
        )
    )


@pytest.mark.asyncio
async def test_a_document_of_duplicates_costs_one_adjudicator_call(
    tmp_path, build_adapter, three_duplicates_provider
):
    """Three cross-document duplicates, one round trip -- not three.

    **Proved red before it was trusted green.** Against the per-entity
    `resolve` loop this branch replaces, the same corpus records
    `[1, 1, 1]` -- one call per duplicate, each asking about a single pair.
    The merges are asserted alongside the count so that "fewer calls" cannot
    be satisfied by asking about nothing.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(
        tmp_path,
        project_id,
        provider=three_duplicates_provider,
        adjudicate=True,
        embeddings=FakeEmbeddingProvider(dimension=EMBEDDING_DIMENSION),
        vector_store=InMemoryVectorStore(dimension=EMBEDDING_DIMENSION),
    )

    await adapter.ingest(SourceRef(source_id="a", text="The breeds originate in Canada."))
    report = await adapter.ingest(
        SourceRef(source_id="b", text="The breeds are used for duck hunting.")
    )

    assert len(report.merges) == 3, f"three duplicates should merge; got {report.merges}"
    assert report.consolidation_failures == 0
    assert three_duplicates_provider.adjudications == [3], (
        "one prompt covering all three bands, not one prompt each: "
        f"{three_duplicates_provider.adjudications}"
    )
