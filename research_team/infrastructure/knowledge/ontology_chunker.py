"""`DocumentChunkPort` over the chunkers extraction already uses.

The application layer states its need as `chunk(text) -> list[DocumentChunk]`
and nothing more, so that `tests/test_architecture.py` can keep redstring's
vocabulary -- `Chunk`, `ChunkingResult`, overlap, metadata keys -- out of the
layer above. These few lines are the only place the two meet.

**`MarkdownTableChunker` is the whole reason discovery can chunk at all**, and
this is the seam that makes its guarantee usable. It repeats a table's header
into every chunk of that table, which is what stops `| S rank |` arriving with
no name for what it belongs to -- the objection
`application/ontology_discovery.py` used to give for never chunking. The cost
it charges is that `chunk.text` is no longer a contiguous slice of the
document, and paying that cost correctly is what
`DocumentChunk.prefix_start_char` is for: it is where the repeated header
really lives, so a class whose name is stated only in the header can still be
cited into the document.

**`SlidingWindowChunker`, not `BoundaryPreferenceChunker`**, matching
`redstring_adapter`'s choice for the extraction corpus. At the sizes discovery
uses -- 40,000 characters against extraction's 1,000 -- a boundary-preferring
splitter's search for a paragraph break buys almost nothing: a cut is already
one break in ~40,000 characters rather than one in ~1,000, and the overlap is
what covers a sentence the cut lands inside. Cheaper and with one fewer
heuristic to explain.
"""

from redstring.extraction.chunkers import SlidingWindowChunker

from research_team.application.ontology_discovery import DocumentChunk
from research_team.infrastructure.knowledge.markdown_table_chunker import (
    SYNTHETIC_PREFIX_CHARS,
    TABLE_HEADER,
    MarkdownTableChunker,
)

__all__ = ["MarkdownAwareDocumentChunker"]


class MarkdownAwareDocumentChunker:
    """`DocumentChunkPort`: cuts a document, carrying table headers and their offsets.

    Structural rather than nominal -- it does not inherit the `Protocol`, the
    house pattern `ChatModelOntologyText` follows. Nothing enforces the match
    but the type checker at the composition site, which is where the two are
    handed to each other.
    """

    def __init__(self, *, chunk_chars: int, overlap_chars: int) -> None:
        self._chunk_chars = chunk_chars
        self._overlap_chars = overlap_chars
        self._chunker = MarkdownTableChunker(
            SlidingWindowChunker(default_chunk_size=chunk_chars, default_overlap=overlap_chars)
        )

    def chunk(self, text: str) -> list[DocumentChunk]:
        result = self._chunker.chunk(text, self._chunk_chars, self._overlap_chars)
        return [
            DocumentChunk(
                text=chunk.text,
                start_char=chunk.start_char,
                prefix=chunk.text[: chunk.metadata.get(SYNTHETIC_PREFIX_CHARS, 0)],
                prefix_start_char=_header_start(
                    text, chunk.metadata.get(TABLE_HEADER), chunk.start_char
                ),
            )
            for chunk in result.chunks
        ]


def _header_start(text: str, header: str | None, chunk_start: int) -> int:
    """Where in the document the header prepended to this chunk really begins.

    `MarkdownTableChunker` records the header's text but not its offset, and
    the offset is what a citation needs. Found by searching backwards from the
    chunk's start: the header this chunk was given belongs to the table the
    chunk sits inside, so the last occurrence at or before `chunk_start` is
    that table's own header and not some other table's identical one. A
    forwards search would find the *next* table's header on any document with
    two tables sharing a column layout, which wikis have constantly.

    `rfind` failing is not expected -- the header was cut from this document --
    but returning 0 silently would cite the top of the document, so it returns
    `chunk_start` instead: a span that then lands in ordinary text is wrong in
    a way a reader can see, where a span at offset 0 looks like a plausible
    lead paragraph.
    """
    if not header:
        return 0
    found = text.rfind(header, 0, chunk_start + len(header))
    return found if found != -1 else chunk_start
