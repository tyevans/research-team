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

import re

from langchain_core.tools import BaseTool, tool

from research_team.application.corpus_read import (
    LIST_SOURCES_TOOL,
    READ_SOURCE_TOOL,
    REFERENCE_SYNTAX_PROMPT,
    SEARCH_SOURCES_TOOL,
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

MAX_MATCHES = 40
"""How many matches one `search_sources` call reports before it stops.

A search is for deciding what to open, so the ceiling is on usefulness rather
than on bytes: past a few dozen hits the answer is "narrow the pattern", and
a response that scrolls for pages costs the context the reading was for."""

MAX_PER_SOURCE = 10
"""How many matches one source contributes before the rest are counted.

Without it a single long document holding the phrase everywhere consumes the
whole budget, and `search_sources` answers "it is in s1" for a corpus where it
is in eleven sources -- which is the same miss-in-silence the mounted `grep`
was built to remove, arrived at by exhaustion instead of by absence."""

SNIPPET_CONTEXT = 80
"""Characters either side of a match in a search result.

Enough to judge whether the hit is the sense you meant, not enough to quote:
the snippet's own span is reported with it, so anything worth citing is one
`read_source` call away at offsets the search already handed over."""

LEAD_CONTEXT = 200
"""How far before a `find` match `read_source` starts its window.

A match at character 9000 read from 9000 opens mid-sentence with the argument
it belongs to behind it. Starting a little earlier costs nothing against a
20,000-character ceiling and makes the first line legible."""


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


def format_matches(pattern: str, hits: list[tuple[str, Span]], suppressed: int) -> str:
    """One line per match: where it is, and enough text to judge it.

    Every line leads with `source_id@start-end` for the same reason
    `format_document` does, and the offsets are the *snippet's*, taken from the
    span that produced the text beside them. That is the whole point of this
    tool: a hit is already addressed in the only scheme `read_source` accepts,
    so choosing what to open never involves converting between two of them.

    Newlines are collapsed so one match is one line. A snippet that wraps makes
    the count in the header disagree with what the reader counts.
    """
    if not hits:
        return (
            f"No match for {pattern!r} in this project's corpus. "
            "The pattern is a regular expression, matched case-insensitively; "
            "try a shorter or less punctuated one."
        )
    sources = len({source_id for source_id, _ in hits})
    header = f"{len(hits)} match(es) for {pattern!r} in {sources} source(s):"
    lines = [header]
    for source_id, span in hits:
        snippet = " ".join(span.text.split())
        lines.append(f"  {source_id}@{span.start}-{span.end} | {snippet}")
    if suppressed:
        lines.append(
            f"[{suppressed} further match(es) not shown. Narrow the pattern, or pass "
            f"source_id= to search one source.]"
        )
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
    """`list_sources`, `search_sources` and `read_source` over one project's corpus."""

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

    @tool(SEARCH_SOURCES_TOOL)
    async def search_sources(pattern: str, source_id: str | None = None) -> str:
        """Search stored sources for a regular expression, reporting
        `source_id@start-end` for every match."""
        try:
            expression = re.compile(pattern, re.IGNORECASE)
        except re.error as error:
            return (
                f"{pattern!r} is not a valid regular expression: {error}. "
                "Escape any regex punctuation you meant literally."
            )
        try:
            listings = await corpus.list_sources()
        except CorpusReadError as error:
            return f"Could not read the corpus: {error}"
        if source_id is not None:
            listings = [
                listing for listing in listings if listing.record.source_id == source_id
            ]
            if not listings:
                return (
                    f"No source {source_id!r} in this project's corpus. {await _available()}"
                )

        hits: list[tuple[str, Span]] = []
        suppressed = 0
        for listing in listings:
            found = listing.record.source_id
            try:
                document = await corpus.read_document(found)
            except CorpusReadError as error:
                return f"Could not read the corpus: {error}"
            if document is None:
                # Media, or a row whose text is gone. Skipped rather than
                # reported: a search says where a phrase is, and "this source
                # has no text to search" is a fact about the corpus that
                # belongs to `list_sources`.
                continue
            for index, match in enumerate(expression.finditer(document.text)):
                if index >= MAX_PER_SOURCE or len(hits) >= MAX_MATCHES:
                    suppressed += 1
                    continue
                hits.append(
                    (
                        found,
                        quote(
                            document.text, match.start(), match.end(), context=SNIPPET_CONTEXT
                        ),
                    )
                )
        return format_matches(pattern, hits, suppressed)

    @tool(READ_SOURCE_TOOL)
    async def read_source(
        source_id: str,
        start: int | None = None,
        end: int | None = None,
        find: str | None = None,
    ) -> str:
        """Read a stored source document -- a character range of one, or the window around a
        regular expression -- with its offsets."""
        try:
            document = await corpus.read_document(source_id)
        except CorpusReadError as error:
            return f"Could not read the corpus: {error}"
        if document is None:
            return f"No source {source_id!r} in this project's corpus. {await _available()}"
        if find is not None:
            try:
                expression = re.compile(find, re.IGNORECASE)
            except re.error as error:
                return (
                    f"{find!r} is not a valid regular expression: {error}. "
                    "Escape any regex punctuation you meant literally."
                )
            match = expression.search(document.text, start or 0)
            if match is None:
                where = "" if start is None else f" at or after character {start}"
                return (
                    f"No match for {find!r} in {source_id!r}{where}. "
                    f"Use `{SEARCH_SOURCES_TOOL}` to find which source holds it."
                )
            # The match decides where the window opens and `max_chars` decides
            # where it ends, so `end` is deliberately ignored here: a caller
            # that supplied both was addressing the same read two ways, and
            # honouring the range could return a window with no match in it.
            start = max(0, match.start() - LEAD_CONTEXT)
            end = None
        return format_document(document, bounded(document.text, start, end, max_chars))

    return (list_sources, search_sources, read_source)


CORPUS_PROMPT = (
    "\n\nThis project keeps the full text of every source it has stored. "
    "`list_sources` shows what is there; `read_source` returns a document, or "
    "a character range of one, headed by `source_id@start-end`.\n\n"
    "`search_sources` searches every stored source at once -- use it to find "
    "which source discusses something rather than opening documents one by "
    "one. It takes a regular expression, matched case-insensitively, and "
    "answers with one line per match: `source_id@start-end` and the text "
    "around it. Those offsets are the ones `read_source` takes, so reading a "
    "hit in full is `read_source(source_id, start=..., end=...)` with the "
    "numbers the search gave you -- never a guess. When you know the phrase "
    "but not the source, search; when you know the source but not where in "
    'it, `read_source(source_id, find="...")` opens at the match.\n\n'
    "Every stored source is also mounted read-only at `/sources/<source_id>` "
    "for `ls` and `glob`. Prefer `search_sources` over `grep` there: grep "
    "reports line numbers, and nothing turns a line number into the character "
    "offsets a citation needs. `read_file` on a mounted path is refused, "
    "because only `read_source` returns the `source_id@start-end` span that "
    "makes a quote checkable.\n\n"
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
