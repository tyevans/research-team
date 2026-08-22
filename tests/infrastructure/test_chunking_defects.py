"""Chunking properties this repository needs from redstring, pinned here.

This file arrived holding one `xfail(strict=True)` for a defect that was open
upstream, on the argument that strict makes the suite go red the day the fix
lands rather than leaving a plain failure everyone learns to scroll past. That
worked exactly as intended: the redstring bump in this commit turned it
`XPASS(strict)`, which is how the fix announced itself.

What is left is an ordinary regression test. Keeping it after the fix is the
point -- the defect was invisible from every direction (nothing raised, the
corpus simply held one chunk it did not need), so nothing but this assertion
would notice it coming back.
"""

from uuid import uuid4

import pytest
from redstring import InMemoryChunkStore

from research_team.application.knowledge import SourceRef

#: 2,700 characters: longer than the 1,000-character window the corpus is
#: chunked with, which is the condition the defect below needs. A document at
#: or under the window size is unaffected and would pass either way.
LONGER_THAN_THE_WINDOW = "The quick brown fox jumps over the lazy dog. " * 60


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

    **Fixed upstream by redstring PR #72**, which this repository picked up in
    the same commit that removed this test's `xfail`. That PR fixes a second
    containment case too -- a break point reached twice emitting the overlap
    region alone -- which this same assertion covers, and which was found by
    the property test written for the first one rather than by anyone looking.

    Kept as a regression test rather than deleted with the defect. Both causes
    were silent: nothing raised, coverage stayed complete, and the only symptom
    was a corpus holding a chunk whose every character another chunk already
    carried. Nothing else in either repository would notice it returning.
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
