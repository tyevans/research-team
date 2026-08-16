"""A chunker that carries a markdown table's header into every chunk of it.

The motivating document is `sekaipedia-list-of-songs` in the Project SEKAI
corpus: 131,701 characters, of which almost all is one markdown table of 705
rows. Split by character count, the first chunk gets

    | Song title | Producer | ... | Date added | Description |
    |---|---|---|---|---|---|---|---|
    | [Tell Your World](...) | kz (livetune) | ... | 2020/09/30 |  |

and every chunk after it gets rows with no header at all -- so neither a model
extracting from the chunk nor a reader shown it as a citation can tell that the
seventh cell is a release date rather than, say, a chart date.

Measured against that document on 2026-08-15, not reasoned. At the extraction
chunk size of 2000, `SlidingWindowChunker` makes 79 chunks of it; 76 contain
table rows and only 4 of those carried a header. Wrapped, 75 chunks gain one
and all 76 have one. In the chunk corpus, `BoundaryPreferenceChunker` at its
own defaults makes 855 chunks, 3 of which had a header; 627 gain one. (627 is
larger than the 359 that hold a recognisable row, because at 154 characters a
chunk on average many hold only a fragment of one row -- those are inside the
table too, and are exactly the passages retrieval is worst at.)

The consumer that makes this more than tidiness is taxonomy discovery. Reading
`| Rank | Reward |` together with rows `D rank ... S rank` is what lets a pass
infer that those five entities form one ordered scale; the same rows without
the header are five unrelated strings, which is why the graph currently holds
`S-rank`, `A-rank` and `B-rank` as disconnected nodes.

## What this does not do: re-implement splitting

This wraps a delegate `Chunker` rather than cutting text itself. Every
boundary decision -- paragraph over sentence over word, how far back to look,
what overlap means -- stays with `BoundaryPreferenceChunker` or
`SlidingWindowChunker`, which have both had that reasoning argued out already.
This pass only looks at where the delegate's boundaries landed and prepends a
header where one is missing.

The cost of that choice, stated plainly: **a chunk carrying a header is longer
than `max_chunk_size`**, by the header's length. Keeping the ceiling would mean
telling the delegate to cut short by an amount that is not known until after it
has cut, which is either a fixed point iteration or a re-implementation of the
splitting the delegate exists to own. For the motivating document the header is
153 characters, so the longest chunk measured at a budget of 2000 was 2153 --
under 8% over, against a budget that is itself a heuristic standing in for a
token limit. A caller for whom the ceiling is hard should not use this chunker.

## The invariant this breaks, and what replaces it

`Chunk`'s docstring is explicit that `start_char`/`end_char` index the
*original* text, "which is what keeps an entity traceable back to the passage
that produced it once merging has discarded which chunk reported it". A
repeated header means `chunk.text` is no longer `original[start_char:end_char]`
-- the header is text the document does not contain at that offset.

The offsets are left alone and the *text* is annotated instead. Every chunk
this produces satisfies

    chunk.text[prefix:] == original[chunk.start_char:chunk.end_char]

where `prefix` is `chunk.metadata[SYNTHETIC_PREFIX_CHARS]`, and the helper
`original_text(chunk)` is the one-liner that applies it. When no header was
added, `prefix` is 0 and the original invariant holds unchanged, so a consumer
that subtracts the prefix is correct for every chunk of every chunker, and a
consumer that does not is wrong only on the chunks that needed a header.

The key `SYNTHETIC_PREFIX_CHARS` is set on **every** chunk, including the ones
with nothing synthetic in them, and that is deliberate. A key present only when
non-zero makes `metadata.get(key, 0)` the correct read and `metadata[key]` a
`KeyError` that appears on some documents and not others; a key always present
makes a consumer that forgot to look fail on the first chunk rather than the
first table.

Rejected: carrying the header only in metadata and asking the extraction prompt
to assemble it. That keeps the slice invariant exactly, and was turned down
because it puts the fix in one consumer. The chunk corpus is read by retrieval
and quoted back to a person through `UsageReader`; a header living only in
metadata is invisible to both, and the retrieval half of the problem is the
half the user asked about first.

Also rejected: a distinct `synthetic_prefix` field on `Chunk`. It cannot be
done here -- `Chunk` is redstring's, redstring is pre-1.0 with a no-shim policy
and is not editable from this repository. `metadata` is the extension point it
provides. If this chunker earns its place upstream, as
`BoundaryPreferenceChunker` did after living here first, a real field is the
better home and the metadata key is what should be replaced.

## What counts as a table

A GitHub-flavoured markdown table: a row line, then a delimiter line whose
cells are runs of `-` with optional `:` alignment markers, then rows until a
line that is not a row. The header is those first two lines together -- the
delimiter is not decoration, it is what tells a markdown reader (and a model
that has seen a million of them) that the line above was headings.

Not handled, on purpose: tables without leading and trailing pipes, HTML
tables, and reStructuredText grid tables. Each would widen the detector's false
positive surface -- a line of prose with a pipe in it, a code block drawing a
box -- for corpora this project does not have. The failure mode of missing one
is the behaviour before this module existed, which is the right way round.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, replace

from redstring.extraction.chunking import Chunk, ChunkingResult
from redstring.extraction.protocols import Chunker

__all__ = [
    "SYNTHETIC_PREFIX_CHARS",
    "TABLE_HEADER",
    "MarkdownTableChunker",
    "original_text",
]

#: Characters at the front of `Chunk.text` that the document does not contain
#: at `start_char`. Always set by this chunker; see the module docstring.
SYNTHETIC_PREFIX_CHARS = "synthetic_prefix_chars"

#: The header this chunk was given, absent when it needed none. Carried
#: separately from the text so a consumer can show it as a header rather than
#: as the first two lines of a passage.
TABLE_HEADER = "table_header"

#: A table row: starts and ends with a pipe. Leading whitespace is allowed
#: because markdown tables are routinely indented inside list items.
_ROW = re.compile(r"^[ \t]*\|.*\|[ \t]*$")

#: The line under a header: cells of dashes, with optional alignment colons.
#: `|---|---|` and `| :--- | ---: |` both match; `|--|` does too, since one
#: dash is legal GFM and refusing it would drop real tables.
_DELIMITER = re.compile(r"^[ \t]*\|(?:[ \t]*:?-+:?[ \t]*\|)+[ \t]*$")


@dataclass(frozen=True)
class _Table:
    """One table found in a document, in original-text offsets.

    `body_start` is where the rows begin, i.e. just past the delimiter line's
    newline. A chunk starting at or before `header_start` already contains the
    header and needs nothing; a chunk starting in `[body_start, end)` does.
    """

    header_start: int
    body_start: int
    end: int
    header: str


def _tables(text: str) -> list[_Table]:
    """Every markdown table in `text`, in ascending order of offset.

    One linear pass over the lines, for the reason `BoundaryPreferenceChunker`
    gives for scanning boundaries once: the documents this exists to serve are
    long, and re-scanning per chunk is what makes chunking quadratic on them.
    """
    starts: list[int] = []
    lines: list[str] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        starts.append(offset)
        lines.append(line)
        offset += len(line)

    tables: list[_Table] = []
    index = 0
    while index + 1 < len(lines):
        if not _ROW.match(lines[index].rstrip("\r\n")) or not _DELIMITER.match(
            lines[index + 1].rstrip("\r\n")
        ):
            index += 1
            continue
        header_start = starts[index]
        body_start = starts[index + 1] + len(lines[index + 1])
        end = index + 2
        while end < len(lines) and _ROW.match(lines[end].rstrip("\r\n")):
            end += 1
        tables.append(
            _Table(
                header_start=header_start,
                body_start=body_start,
                end=starts[end - 1] + len(lines[end - 1]),
                # Exactly as written, including the delimiter line and its
                # newline: a header re-indented or re-spaced here would not be
                # the document's header, and the point is that a reader can
                # match it against the document.
                header=text[header_start:body_start],
            )
        )
        index = end
    return tables


def original_text(chunk: Chunk) -> str:
    """The part of `chunk.text` the document actually contains at its offsets.

    Equal to `document[chunk.start_char:chunk.end_char]` for any chunk this
    module produced, and to `chunk.text` for a chunk produced by any chunker
    that sets no prefix -- so this is safe to apply to chunks of unknown
    origin, which is what makes it usable in code that does not know which
    chunker ran.
    """
    return chunk.text[chunk.metadata.get(SYNTHETIC_PREFIX_CHARS, 0) :]


class MarkdownTableChunker:
    """A `Chunker` that gives every chunk of a table its header.

    Wraps another `Chunker` and does not split text itself; see the module
    docstring for why, and for what it costs.
    """

    def __init__(self, delegate: Chunker) -> None:
        self._delegate = delegate

    @property
    def chunker_type(self) -> str:
        """Names the delegate too.

        `ChunkingResult.chunking_method` is recorded on stored chunks and is
        what someone reads when a corpus looks wrong. "markdown_table" alone
        would hide the half of the behaviour that actually decided the
        boundaries.
        """
        return f"markdown_table({self._delegate.chunker_type})"

    def chunk(
        self,
        text: str,
        max_chunk_size: int | None = None,
        overlap_size: int | None = None,
    ) -> ChunkingResult:
        """Split `text` with the delegate, then repair headerless table chunks.

        Every chunk comes back with `SYNTHETIC_PREFIX_CHARS` in its metadata,
        including the untouched ones, so a consumer reading it never has to
        distinguish "no prefix" from "a chunker that does not set this".

        `original_length` and the offsets are the delegate's, unchanged: they
        describe the document, and this pass did not change the document.
        """
        result = self._delegate.chunk(text, max_chunk_size, overlap_size)
        tables = _tables(text)
        body_starts = [table.body_start for table in tables]

        chunks: list[Chunk] = []
        for chunk in result.chunks:
            metadata = dict(chunk.metadata)
            header = _header_for(chunk, tables, body_starts)
            if header is None:
                metadata[SYNTHETIC_PREFIX_CHARS] = 0
                chunks.append(replace(chunk, metadata=metadata))
                continue
            metadata[SYNTHETIC_PREFIX_CHARS] = len(header)
            metadata[TABLE_HEADER] = header
            chunks.append(replace(chunk, text=header + chunk.text, metadata=metadata))

        return replace(result, chunks=chunks, chunking_method=self.chunker_type)


def _header_for(chunk: Chunk, tables: list[_Table], body_starts: list[int]) -> str | None:
    """The header this chunk is missing, or None if it needs none.

    Located by bisection rather than a scan: a document with 705 rows in one
    table has few tables, but a document that is a hundred small ones would
    make a linear search per chunk quadratic, and the bisection costs nothing
    on the easy case.

    A chunk starting at or before a table's `header_start` is not given one --
    it contains the header already. A chunk starting *inside* the header, which
    a hard cut through the delimiter line can do, is given one: half a
    delimiter line is not a header. That case is why the table after the
    bisection point is examined too -- its `body_start` is past the chunk's
    start, so the bisection alone would miss it.
    """
    index = bisect_right(body_starts, chunk.start_char) - 1
    for candidate in (index, index + 1):
        if not 0 <= candidate < len(tables):
            continue
        table = tables[candidate]
        if table.header_start < chunk.start_char < table.end:
            return table.header
    return None
