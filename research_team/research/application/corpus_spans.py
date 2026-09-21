"""Turning retained source text into citable offsets.

A claim is only checkable if it can point at the words it came from. The graph
cannot do that: extraction computes character offsets while chunking and then
throws them away, leaving an entity that names its document but not its
sentence. Rather than chase that upstream, we keep the source text and derive
offsets here, on demand.

That is affordable *because chunking is deterministic*. The same text and the
same parameters always yield the same spans, so no event has to record them and
no migration is needed when the parameters change -- a citation is just
`source_id` plus two integers, resolved against text the corpus already holds.
The whole design leans on that, which is why the tests are mostly properties:
the guarantee that matters is not "chunks look sensible" but "with no overlap,
concatenating the chunks reproduces the input exactly". Lose one character and
every offset after it silently points at the wrong words.

Two consequences of taking that seriously. Chunk text is never stripped --
separators stay attached to the chunk they end, because trimming them would
make the partition lossy. And boundary detection may only ever *choose among*
split points; it may never rewrite the text, so CRLF stays CRLF.

Boundary preference is paragraph, then sentence, then word, then a hard cut.
"Sentence" here is a heuristic and not a claim to sentence segmentation: it is
a full stop, question or exclamation mark, optional closing quotes or brackets,
then whitespace. It splits "et al. 1999" and "Fig. 4", and it does not split at
"3.5" or an unpunctuated line ending. That is an acceptable trade for a
dependency-free application layer, because a misplaced boundary costs a chunk
that reads slightly oddly, while a lost character costs correctness.
"""

import re
from bisect import bisect_right
from dataclasses import dataclass

__all__ = ["Span", "chunk", "quote"]


@dataclass(frozen=True)
class Span:
    """A half-open range of a source document, carried with its own text.

    The text is redundant with the offsets and kept anyway: a span is usually
    handed to a model or a reader who needs the words, and re-slicing at every
    such point is where an off-by-one gets introduced.
    """

    start: int
    end: int
    text: str


#: Runs of whitespace, the only places a split can avoid landing mid-word.
_WHITESPACE = re.compile(r"\s+")

#: A sentence-ish terminator: see the module docstring for what this misses.
_SENTENCE = re.compile("[.!?][\"')\\]\u2019\u201d]*(?:\\s+|$)")


def _boundaries(text: str) -> tuple[list[int], list[int], list[int]]:
    """Every candidate split point in `text`, as three ascending lists.

    Computed once for the whole document rather than per chunk: the scan is
    linear either way, but doing it per chunk makes chunking quadratic on the
    long documents this exists to serve.
    """
    paragraphs: list[int] = []
    words: list[int] = []
    for run in _WHITESPACE.finditer(text):
        words.append(run.end())
        if run.group().count("\n") >= 2:
            paragraphs.append(run.end())
    sentences = [match.end() for match in _SENTENCE.finditer(text)]
    return paragraphs, sentences, words


def _last_within(candidates: list[int], after: int, limit: int) -> int | None:
    """The greatest candidate in `(after, limit]`, or `None`."""
    index = bisect_right(candidates, limit) - 1
    if index >= 0 and candidates[index] > after:
        return candidates[index]
    return None


def chunk(text: str, *, target_chars: int = 1200, overlap: int = 0) -> list[Span]:
    """Split `text` into spans of roughly `target_chars`, preferring clean breaks.

    `target_chars` is a ceiling, not an average: a chunk is cut at the last
    acceptable boundary at or before it, so a document with sparse punctuation
    yields shorter chunks rather than longer ones. Only a token longer than
    `target_chars` is ever cut mid-word, because refusing to cut it would let
    one pathological run defeat the bound entirely.

    With `overlap=0` the result is a partition: ordered, contiguous, and
    concatenating to exactly the input. A positive `overlap` repeats that many
    trailing characters at the start of the next chunk, for retrieval where a
    match straddling a boundary would otherwise be missed; the spans then still
    cover every character, but no longer partition.
    """
    if target_chars < 1:
        raise ValueError("target_chars must be at least 1")
    if overlap < 0:
        raise ValueError("overlap must not be negative")
    if overlap >= target_chars:
        # Otherwise a chunk could rewind at least as far as it advanced.
        raise ValueError("overlap must be smaller than target_chars")
    if not text:
        return []

    paragraphs, sentences, words = _boundaries(text)
    spans: list[Span] = []
    start = 0
    while start < len(text):
        limit = start + target_chars
        if limit >= len(text):
            end = len(text)
        else:
            end = (
                _last_within(paragraphs, start, limit)
                or _last_within(sentences, start, limit)
                or _last_within(words, start, limit)
                # No boundary in reach: cut at the ceiling. Inside a long run
                # of whitespace this is also the right answer, not a fallback.
                or limit
            )
        spans.append(Span(start, end, text[start:end]))
        # `start + 1` guarantees progress even when a boundary lands close
        # enough behind `end` that the overlap would otherwise rewind past it.
        start = end if overlap == 0 else max(start + 1, end - overlap)
    return spans


def quote(text: str, start: int, end: int, *, context: int = 0) -> Span:
    """The span of `text` at `[start, end)`, widened by `context` either side.

    Offsets reach this from a model's output, where they are a guess, so every
    out-of-range case clamps rather than raising: a clamped quote is something
    a reader can still judge, whereas an exception aborts a turn over what is
    usually an off-by-a-few. Reversed offsets collapse to an empty span at
    `start` -- an empty quote reads as "it pointed nowhere", which is the
    honest rendering of a nonsensical range.
    """
    if context < 0:
        raise ValueError("context must not be negative")
    start = max(0, min(start, len(text)))
    end = max(start, min(end, len(text)))
    start = max(0, start - context)
    end = min(len(text), end + context)
    return Span(start, end, text[start:end])
