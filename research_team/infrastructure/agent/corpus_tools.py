"""The project's own sources, as two read-only tools.

A retained corpus nothing can read is not worth retaining. `remember` puts
documents in; without these the agent can only reach them through the graph,
which is to say through an extraction of them -- and an extraction is exactly
what a claim needs to be checked *against*, not the thing to quote.

Every response leads with `source_id@start-end`, and those numbers always bound
the text underneath them. That is the whole contract: an offset that drifts
from what was actually returned is worse than no offset, because a citation
built on it looks verifiable and is not. So the ranges are computed by
`corpus_spans.quote` and then *reported back from the result*, never from what
the caller asked for -- the request is a guess and the response is a fact.

Neither tool is gated. They read text this project already stored, cost
nothing, and escape nothing; `autonomy.py` explains why putting them behind an
approval would make every other approval mean less.
"""

from langchain_core.tools import BaseTool, tool

from research_team.application.corpus_read import (
    LIST_SOURCES_TOOL,
    READ_SOURCE_TOOL,
    REFERENCE_SYNTAX_PROMPT,
    CorpusReadError,
    CorpusReadPort,
    SourceListing,
    StoredDocument,
)
from research_team.application.corpus_spans import Span, chunk, quote

MAX_CHARS = 20_000
"""How much of a document reaches the model in one call.

The same ceiling `fetch` uses, for the same reason and now with a better
remedy: there, truncation loses the rest of the page until it is fetched again;
here the rest is still in the corpus and one `read_source` call away."""

MAX_LISTED = 30
"""How many source ids an error message names before it defers to
`list_sources`. A corpus can hold hundreds, and an error that recites all of
them buries the sentence that says what went wrong."""


def format_listing(listings: list[SourceListing]) -> str:
    """One line per source: what it is, how big, and where it came from.

    Metadata only, by contract. Inlining even a snippet of each document would
    make listing a large corpus cost more context than reading the one document
    the agent actually wanted.

    A media source reports its mimetype and byte size rather than a character
    count it does not have. Printing `0 characters` for one would read as an
    empty document rather than as a video -- a plausible-looking wrong answer,
    worse than a line that plainly says "media".

    `extracted` is deliberately *not* shown. It is a fact about the graph, and
    a model reading this list is choosing what to read, not what to requeue --
    the one caller that can act on it is the Documents page. Adding it here
    would put a word on every line of a large listing to no end.
    """
    if not listings:
        return (
            "This project's corpus is empty -- nothing has been stored yet. "
            "Use `remember` to store a document before trying to read one."
        )
    lines = [f"{len(listings)} source(s) in this project's corpus:"]
    for listing in listings:
        summary = listing.record
        if summary.kind == "media":
            parts = [
                f"{summary.source_id} -- media, {summary.media_type}, "
                f"{summary.byte_count} bytes"
            ]
        else:
            parts = [f"{summary.source_id} -- {summary.char_count} chars"]
        if summary.title:
            parts.append(summary.title)
        if summary.uri:
            parts.append(summary.uri)
        if summary.published_at:
            parts.append(f"published {summary.published_at}")
        if summary.note:
            parts.append(summary.note)
        lines.append("  " + " | ".join(parts))
    return "\n".join(lines)


def format_document(document: StoredDocument, span: Span) -> str:
    """`span` of `document`, headed by the citation that makes it quotable.

    The header is built from `span`, not from anything requested, so the two
    cannot disagree. When the span stops short of the end, the response says so
    in a sentence naming the next offset -- a model that is told only "1000
    chars" and handed 100 will reason about the document as though it read it.
    """
    summary = document.record
    header = [f"{summary.source_id}@{span.start}-{span.end} of {summary.char_count} chars"]
    if summary.title:
        header.append(f"title: {summary.title}")
    if summary.uri:
        header.append(f"uri: {summary.uri}")
    if summary.published_at:
        header.append(f"published: {summary.published_at}")

    body = span.text
    if not body:
        body = "(empty -- that range is past the end of the document, or has nothing in it)"
    parts = ["\n".join(header), body]
    if span.end < summary.char_count:
        parts.append(
            f"[this is characters {span.start}-{span.end}; the document continues to "
            f"{summary.char_count}. Call `read_source` with start={span.end} for more.]"
        )
    return "\n\n".join(parts)


def bounded(text: str, start: int | None, end: int | None, max_chars: int) -> Span:
    """The requested range, clamped to the document and capped at `max_chars`.

    The cap is applied by chunking the requested range and taking its first
    chunk rather than slicing at `max_chars`, so the cut lands on a paragraph,
    sentence or word boundary. A response that stops mid-word invites the model
    to complete it from memory, which is the specific failure this whole layer
    exists to prevent.

    Public because `fetch` returns corpus hits through `format_document` too,
    and two implementations of the offset contract would eventually disagree
    -- which is the exact failure this module's docstring says is worse than
    having no offsets at all.
    """
    span = quote(text, start or 0, len(text) if end is None else end)
    if len(span.text) <= max_chars:
        return span
    first = chunk(span.text, target_chars=max_chars)[0]
    return Span(span.start, span.start + first.end, first.text)


def build_corpus_tools(
    corpus: CorpusReadPort, *, max_chars: int = MAX_CHARS
) -> tuple[BaseTool, ...]:
    """`list_sources` and `read_source` over one project's corpus."""

    async def _available() -> str:
        """What does exist, for an error message about what does not.

        Best-effort: this runs on a path that has already gone wrong, and a
        second failure here should not replace "no such source" with a
        traceback about the attempt to be helpful.
        """
        try:
            summaries = await corpus.list_sources()
        except CorpusReadError:
            return f"Use `{LIST_SOURCES_TOOL}` to see what is available."
        if not summaries:
            return "This project's corpus is empty; nothing has been stored yet."
        ids = [listing.record.source_id for listing in summaries[:MAX_LISTED]]
        listed = ", ".join(ids)
        if len(summaries) > MAX_LISTED:
            listed += f", and {len(summaries) - MAX_LISTED} more"
        return f"Available: {listed}. Use `{LIST_SOURCES_TOOL}` for details."

    @tool(LIST_SOURCES_TOOL)
    async def list_sources() -> str:
        """List the source documents stored in this project's corpus."""
        try:
            summaries = await corpus.list_sources()
        except CorpusReadError as error:
            return f"Could not read the corpus: {error}"
        return format_listing(summaries)

    @tool(READ_SOURCE_TOOL)
    async def read_source(
        source_id: str, start: int | None = None, end: int | None = None
    ) -> str:
        """Read a stored source document, or a character range of one, with its offsets."""
        try:
            document = await corpus.read_document(source_id)
        except CorpusReadError as error:
            return f"Could not read the corpus: {error}"
        if document is None:
            return f"No source {source_id!r} in this project's corpus. {await _available()}"
        return format_document(document, bounded(document.text, start, end, max_chars))

    return (list_sources, read_source)


CORPUS_PROMPT = (
    "\n\nThis project keeps the full text of every source it has stored. "
    "`list_sources` shows what is there; `read_source` returns a document, or "
    "a character range of one, headed by `source_id@start-end`.\n\n"
    "Read the source before you write about it. The knowledge graph holds an "
    "extraction of a document, which is the thing a claim should be checked "
    "against rather than the thing to quote -- if you are about to state what "
    "a source says, open it and look. A long document comes back a range at a "
    "time; the response tells you where it stopped, and reading on is another "
    "call, not a reason to fill the gap from memory.\n\n"
    "The rule for anything you write into a course artifact: a claim carries "
    "the `source_id` and the offsets it came from, or it is marked plainly as "
    "inferred. Both are legitimate -- an inference you have labelled is honest "
    "work, and a reviewer can weigh it. An inference wearing a citation is "
    "not, and the offsets are what makes the difference checkable.\n\n"
    + REFERENCE_SYNTAX_PROMPT
)
