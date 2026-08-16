"""`MarkdownTableChunker`: does every chunk of a table carry its header?

The assertions that matter are the two the module's docstring makes promises
about -- that a headerless table chunk gains one, and that
`text[prefix:] == original[start_char:end_char]` still holds afterwards. The
second is the one that would go quietly wrong: a prefix recorded one character
off makes every citation of a table row point at neighbouring words, and
nothing raises.
"""

from uuid import uuid4

import pytest
from redstring.extraction.chunkers import BoundaryPreferenceChunker, SlidingWindowChunker

from research_team.infrastructure.knowledge.markdown_table_chunker import (
    SYNTHETIC_PREFIX_CHARS,
    TABLE_HEADER,
    MarkdownTableChunker,
    original_text,
)

HEADER = "| Rank | Reward |\n|---|---|\n"
TENANT_ID = uuid4()


def table(rows: int, *, prefix: str = "", suffix: str = "") -> str:
    """A table of `rows` rows, each padded to a predictable width."""
    body = "".join(f"| {index} rank | {'x' * 40} reward |\n" for index in range(rows))
    return f"{prefix}{HEADER}{body}{suffix}"


@pytest.fixture(params=["boundary", "sliding"])
def chunker(request):
    """Both delegates, because they cut differently.

    `SlidingWindowChunker` searches only the last 500 characters of its window
    and so lands mid-row far more often than `BoundaryPreferenceChunker` does;
    a repair that only worked on clean line boundaries would pass under one and
    fail under the other.
    """
    if request.param == "boundary":
        delegate = BoundaryPreferenceChunker()
    else:
        delegate = SlidingWindowChunker()
    return MarkdownTableChunker(delegate)


def test_every_chunk_of_a_long_table_carries_the_header(chunker):
    text = table(200)

    result = chunker.chunk(text, max_chunk_size=1000, overlap_size=100)

    assert len(result.chunks) > 1, "fixture too small to have a headerless chunk at all"
    assert all(HEADER in chunk.text for chunk in result.chunks)


def test_the_synthetic_prefix_is_exactly_what_the_document_does_not_contain(chunker):
    text = table(200, prefix="Some prose first.\n\n", suffix="\nSome prose after.\n")

    result = chunker.chunk(text, max_chunk_size=1000, overlap_size=100)

    for chunk in result.chunks:
        assert original_text(chunk) == text[chunk.start_char : chunk.end_char]


def test_prose_only_text_is_returned_unchanged_but_annotated(chunker):
    text = "A paragraph with no table in it.\n\n" * 60

    result = chunker.chunk(text, max_chunk_size=400, overlap_size=40)

    assert [chunk.text for chunk in result.chunks] == [
        chunk.text for chunk in chunker._delegate.chunk(text, 400, 40).chunks
    ]
    assert all(chunk.metadata[SYNTHETIC_PREFIX_CHARS] == 0 for chunk in result.chunks)
    assert all(TABLE_HEADER not in chunk.metadata for chunk in result.chunks)


def test_the_chunk_that_already_holds_the_header_is_not_given_a_second_one(chunker):
    text = table(200)

    result = chunker.chunk(text, max_chunk_size=1000, overlap_size=100)

    first = result.chunks[0]
    assert first.metadata[SYNTHETIC_PREFIX_CHARS] == 0
    assert first.text.count("|---|---|") == 1


def test_a_pipe_in_prose_is_not_a_table(chunker):
    """No delimiter line, so no table -- and so no header to hallucinate.

    This fails if `_ROW` alone is treated as enough. The delimiter is what
    distinguishes a table from a line of shell.
    """
    text = "Run `ls | grep x | wc -l` and see.\n" * 200

    result = chunker.chunk(text, max_chunk_size=400, overlap_size=40)

    assert all(chunk.metadata[SYNTHETIC_PREFIX_CHARS] == 0 for chunk in result.chunks)


def test_a_chunk_after_the_table_ends_gets_no_header(chunker):
    """A row-shaped table followed by enough prose to fill whole chunks.

    Would pass with the `chunk.start_char < table.end` bound removed only if
    the trailing prose happened to be short enough to share a chunk with the
    table, which is why the suffix here is long.
    """
    text = table(20, suffix="\n" + "Prose that follows the table entirely. " * 200)

    result = chunker.chunk(text, max_chunk_size=1000, overlap_size=0)

    tail = result.chunks[-1]
    assert "|" not in original_text(tail)
    assert tail.metadata[SYNTHETIC_PREFIX_CHARS] == 0


def test_two_tables_each_repair_with_their_own_header(chunker):
    first_header = "| Rank | Reward |\n|---|---|\n"
    second_header = "| Song | Producer |\n|:--|--:|\n"
    first = first_header + "".join(f"| {i} rank | {'x' * 60} |\n" for i in range(60))
    second = second_header + "".join(f"| song {i} | {'y' * 60} |\n" for i in range(60))
    text = f"{first}\nBetween them.\n\n{second}"

    result = chunker.chunk(text, max_chunk_size=800, overlap_size=0)

    for chunk in result.chunks:
        header = chunk.metadata.get(TABLE_HEADER)
        if header is None:
            continue
        expected = first_header if chunk.start_char < len(first) else second_header
        assert header == expected


def test_chunker_type_names_the_delegate(chunker):
    result = chunker.chunk(table(50), max_chunk_size=500, overlap_size=0)

    assert result.chunking_method == chunker.chunker_type
    assert chunker._delegate.chunker_type in result.chunking_method


def test_blank_text_still_yields_no_chunks(chunker):
    """The delegate's contract, which wrapping must not change."""
    assert chunker.chunk("", max_chunk_size=500, overlap_size=0).chunks == []


async def test_redstring_drops_chunk_metadata_on_the_way_into_the_store():
    """**Upstream gap: `metadata` does not survive `index_documents`.**

    `redstring.extraction.corpus.stored_chunks` builds each `StoredChunk`
    without passing `chunk.metadata` through, even though `StoredChunk` has a
    `metadata` field. So a chunk indexed into the corpus arrives with the
    header prepended to its text and **no `synthetic_prefix_chars` to subtract
    it back off** -- `original_text` silently becomes the identity, and the
    offsets disagree with the text again.

    That is why `RedstringKnowledge.index` does NOT wrap its chunker: the
    representation this module depends on cannot survive the trip. The
    extraction path is unaffected, because those chunks go straight to the
    model and are never stored.

    This test asserts upstream's *current* behaviour, so it fails when
    redstring starts carrying metadata -- which is the signal that
    `index` can be wrapped. Fix it by wiring the chunker, not by deleting
    this.
    """
    from eventsource import InMemoryEventStore
    from redstring import InMemoryChunkStore, SourceDocument, index_documents

    text = table(200)
    store = InMemoryChunkStore(dimension=8)
    await index_documents(
        [SourceDocument(id="doc-1", text=text)],
        store=store,
        tenant_id=TENANT_ID,
        chunker=MarkdownTableChunker(BoundaryPreferenceChunker()),
        event_store=InMemoryEventStore(),
    )

    stored = await store.get_by_source("doc-1", TENANT_ID)
    carrying = [chunk for chunk in stored if HEADER in chunk.text]
    assert carrying, "fixture produced no header-carrying chunk, so this proves nothing"
    assert all(SYNTHETIC_PREFIX_CHARS not in chunk.metadata for chunk in carrying)
    assert any(chunk.text != text[chunk.start_char : chunk.end_char] for chunk in carrying), (
        "the disagreement this test exists to record"
    )
