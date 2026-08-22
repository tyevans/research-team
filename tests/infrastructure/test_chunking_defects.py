"""Defects in redstring's chunking that this repository indexes around.

Each test here names the upstream change that resolves it. They are
`xfail(strict=True)` rather than plain failures: strict means the suite goes
**red when one starts passing**, which is the signal worth having -- it says
the upstream release landed and this file needs revisiting. A plain failing
test would say the same thing by staying red, and would also make every
unrelated run red, which teaches people to ignore it.
"""

from uuid import uuid4

import pytest
from redstring import InMemoryChunkStore

from research_team.application.knowledge import SourceRef

#: 2,700 characters: longer than the 1,000-character window the corpus is
#: chunked with, which is the condition the defect below needs. A document at
#: or under the window size is unaffected and would pass either way.
LONGER_THAN_THE_WINDOW = "The quick brown fox jumps over the lazy dog. " * 60


@pytest.mark.xfail(
    strict=True,
    reason="redstring <= 0.9.2 emits a redundant tail chunk; redstring PR #72 fixes it",
)
@pytest.mark.asyncio
async def test_no_indexed_chunk_is_wholly_contained_in_another(tmp_path, build_adapter):
    """A document longer than the window gets one redundant tail chunk.

    `SlidingWindowChunker` emits a final window `(len - overlap, len)` even
    when the previous chunk already reached `len`, so the last chunk is wholly
    inside the one before it. Measured 2026-08-21 against redstring 0.9.2 at
    1000/500 across 450-4500 characters: exactly one redundant chunk, always
    the last, for every document longer than the window.

    Two consequences here, and neither is cosmetic. `UsageReader` deduplicates
    on `(source_id, start_char, end_char)` and the two spans differ, so a
    reader is shown two overlapping passages, one a suffix of the other. And
    BM25 counts the tail's terms in two chunks, giving tail passages a second
    draw that no mid-document passage gets.

    **When this starts failing as XPASS, redstring has released the fix** --
    delete the `xfail` and keep the assertion, which is then a regression
    test. redstring PR #72 also fixes a second containment case (a break point
    reached twice emitting the overlap region alone) that this same assertion
    covers.
    """
    project_id = uuid4()
    chunk_store = InMemoryChunkStore(dimension=8)
    knowledge, _, _ = build_adapter(tmp_path, project_id, chunks=chunk_store)

    await knowledge.index(SourceRef(source_id="doc-1", text=LONGER_THAN_THE_WINDOW))

    chunks = await chunk_store.get_by_source("doc-1", project_id)
    spans = [(chunk.start_char, chunk.end_char) for chunk in chunks]
    contained = [
        (inner, outer)
        for inner in spans
        for outer in spans
        if inner != outer and outer[0] <= inner[0] and inner[1] <= outer[1]
    ]

    assert contained == [], f"chunks wholly inside another: {contained}"
