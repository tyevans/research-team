"""The corpus reading tools, against a fake port.

No database and no projection: these tools exist to turn a port into prose the
model can act on, and the interesting failures are all in the prose. What the
read model does behind the port is `test_corpus_read_model.py`'s problem.

The recurring assertion is that the offsets a response *claims* are the offsets
it actually returned. A tool that says "0-1200" and returns something else is
worse than one that reports no offsets at all, because a citation built on it
looks checkable and is not.
"""

import hashlib

import pytest

from research_team.application.autonomy import GATED_TOOLS
from research_team.application.corpus_read import (
    LIST_SOURCES_TOOL,
    READ_SOURCE_TOOL,
    REFERENCE_SYNTAX_PROMPT,
    SEARCH_SOURCES_TOOL,
    CorpusReadError,
    SourceListing,
    StoredDocument,
)
from research_team.domain import MediaRecord, TextRecord
from research_team.infrastructure.agent.corpus_tools import (
    CORPUS_PROMPT,
    MAX_PER_SOURCE,
    build_corpus_tools,
    format_listing,
)

ALPHABET = "abcdefghijklmnopqrstuvwxyz "


def _document(source_id: str, text: str, **metadata) -> StoredDocument:
    """A stored document, digest and all.

    `TextRecord` requires a `sha256` these tests do not care about, so it
    is computed rather than faked -- a stub digest here would be the one place
    in the system where a record's digest did not describe its bytes.
    """
    return StoredDocument(
        record=TextRecord(
            source_id=source_id,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            char_count=len(text),
            **metadata,
        ),
        text=text,
    )


class FakeCorpus:
    """A corpus read port over a dict. `fails` makes every call raise."""

    def __init__(self, *documents: StoredDocument, fails: bool = False) -> None:
        self._documents = {document.record.source_id: document for document in documents}
        self._fails = fails

    async def list_sources(self) -> list[SourceListing]:
        if self._fails:
            raise CorpusReadError("the read model is unavailable")
        # `extracted=False` throughout: `format_listing` deliberately does not
        # render it, and a double that varied it would suggest it should.
        return [
            SourceListing(record=document.record, extracted=False)
            for document in self._documents.values()
        ]

    async def read_document(self, source_id: str) -> StoredDocument | None:
        if self._fails:
            raise CorpusReadError("the read model is unavailable")
        return self._documents.get(source_id)


def _tools(*documents: StoredDocument, fails: bool = False, max_chars: int = 20_000):
    corpus = FakeCorpus(*documents, fails=fails)
    return {tool.name: tool for tool in build_corpus_tools(corpus, max_chars=max_chars)}


# --- autonomy ---------------------------------------------------------------


def test_the_reading_tools_are_not_gated() -> None:
    """Pinned, not merely intended. These are read-only, and `autonomy.py`'s
    rule is that gating read tools trains people to click through approvals
    without reading them. A later change that gates them should fail here."""
    assert LIST_SOURCES_TOOL not in GATED_TOOLS
    assert READ_SOURCE_TOOL not in GATED_TOOLS
    assert SEARCH_SOURCES_TOOL not in GATED_TOOLS


def test_every_tool_is_built_under_its_declared_name() -> None:
    assert set(_tools()) == {LIST_SOURCES_TOOL, SEARCH_SOURCES_TOOL, READ_SOURCE_TOOL}


# --- list_sources -----------------------------------------------------------


async def test_listing_names_each_source_with_its_size() -> None:
    tools = _tools(
        _document("s1", "alpha", title="Alpha", uri="https://a.example"),
        _document("s2", "beta beta"),
    )
    text = await tools[LIST_SOURCES_TOOL].ainvoke({})
    assert "s1" in text
    assert "Alpha" in text
    assert "https://a.example" in text
    assert "5" in text
    assert "s2" in text


def test_listing_a_media_source_says_media_and_never_a_character_count() -> None:
    """`format_listing` directly, because `FakeCorpus` holds `StoredDocument`s
    and a media source has no text to store one under.

    Fails if the media branch is dropped and every record is rendered through
    `char_count`: a `MediaRecord` has none, so the honest failure is an
    `AttributeError` -- but a branch that reached for a default would print
    `0 chars` for a video, which reads as an empty document. A model told a
    source is empty stops trying to use it; a plausible-looking wrong answer
    is worse here than a crash.
    """
    line = format_listing(
        [
            SourceListing(
                record=MediaRecord(
                    source_id="v1",
                    sha256="0" * 64,
                    media_type="video/mp4",
                    byte_count=2048,
                    title="A talk",
                ),
                extracted=False,
            )
        ]
    )
    assert "v1" in line
    assert "video/mp4" in line
    assert "2048" in line
    assert "A talk" in line
    assert "chars" not in line


async def test_listing_never_includes_document_text() -> None:
    """The listing is metadata by contract. A corpus of fifty documents whose
    listing inlined them would crowd out the conversation that asked."""
    tools = _tools(_document("s1", "the secret contents of the document"))
    assert "secret contents" not in await tools[LIST_SOURCES_TOOL].ainvoke({})


async def test_an_empty_corpus_says_so() -> None:
    """Distinct from a failure, and worth saying: "nothing here yet" is an
    instruction to go and gather, and a traceback is not."""
    text = await _tools()[LIST_SOURCES_TOOL].ainvoke({})
    assert "empty" in text.lower()


async def test_a_storage_failure_comes_back_as_prose() -> None:
    tools = _tools(_document("s1", "alpha"), fails=True)
    text = await tools[LIST_SOURCES_TOOL].ainvoke({})
    assert "unavailable" in text
    assert "Could not" in text


# --- read_source ------------------------------------------------------------


async def test_reading_a_small_document_returns_all_of_it() -> None:
    tools = _tools(_document("s1", "Alpha beta gamma."))
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "s1"})
    assert "Alpha beta gamma." in text
    assert "s1@0-17" in text


async def test_a_range_returns_exactly_that_span_and_says_which() -> None:
    tools = _tools(_document("s1", "Alpha beta gamma."))
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "s1", "start": 6, "end": 10})
    assert "s1@6-10" in text
    _, _, body = text.partition("\n\n")
    assert body.split("\n\n[")[0] == "beta"
    # An explicitly requested range that stops short still says the document
    # continues. Redundant to the caller who chose the range, and not to the
    # model reading the transcript three turns later.
    assert "continues to 17" in text


async def test_an_out_of_range_end_is_clamped_and_the_header_says_the_truth() -> None:
    """The offsets are a model's guess. Clamping keeps the turn alive; naming
    the clamped values keeps the citation honest."""
    tools = _tools(_document("s1", "Alpha beta gamma."))
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "s1", "start": 6, "end": 9999})
    assert "s1@6-17" in text
    assert "9999" not in text


async def test_a_start_beyond_the_end_of_the_document_reads_as_empty_not_as_content() -> None:
    tools = _tools(_document("s1", "Alpha."))
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "s1", "start": 500})
    assert "s1@6-6" in text
    assert "empty" in text.lower()


async def test_a_start_with_no_end_reads_to_the_end_of_the_document() -> None:
    tools = _tools(_document("s1", "Alpha beta gamma."))
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "s1", "start": 6})
    assert "s1@6-17" in text
    assert "beta gamma." in text


async def test_the_header_carries_the_citation_metadata() -> None:
    tools = _tools(
        _document(
            "s1",
            "Alpha.",
            title="A Paper",
            uri="https://a.example",
            published_at="2024-03-01",
        )
    )
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "s1"})
    assert "A Paper" in text
    assert "https://a.example" in text
    assert "2024-03-01" in text


# --- the size ceiling -------------------------------------------------------


async def test_an_oversized_document_returns_a_prefix_and_says_it_is_a_prefix() -> None:
    """The model must not be left believing it read a whole document it only
    partly received -- that is how a confident claim about an unread section
    gets written down."""
    tools = _tools(_document("s1", "word " * 200), max_chars=100)
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "s1"})
    assert "1000" in text  # the true length, stated
    assert "read_source" in text  # how to get the rest
    assert "s1@0-100" in text


async def test_the_returned_offsets_bound_the_returned_text_exactly() -> None:
    """The invariant behind every citation this tool makes possible."""
    body = "word " * 200
    tools = _tools(_document("s1", body), max_chars=100)
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "s1"})
    header, _, returned = text.partition("\n\n")
    start, end = _offsets(header)
    assert returned.split("\n\n[")[0] == body[start:end]


async def test_a_truncated_read_cuts_on_a_word_boundary() -> None:
    tools = _tools(_document("s1", "word " * 200), max_chars=100)
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "s1"})
    _, _, returned = text.partition("\n\n")
    assert not returned.split("\n\n[")[0].rstrip().endswith("wor")


async def test_a_document_exactly_at_the_ceiling_is_not_called_truncated() -> None:
    tools = _tools(_document("s1", "x" * 100), max_chars=100)
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "s1"})
    assert "continues" not in text


async def test_an_oversized_range_is_truncated_from_the_requested_start() -> None:
    """Continuing from an offset must work, or a long document is unreadable
    past its first chunk."""
    body = ALPHABET * 40
    tools = _tools(_document("s1", body), max_chars=50)
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "s1", "start": 200})
    header, _, returned = text.partition("\n\n")
    start, end = _offsets(header)
    assert start == 200
    assert returned.split("\n\n[")[0] == body[start:end]


# --- an unknown source ------------------------------------------------------


async def test_an_unknown_source_names_what_is_available() -> None:
    tools = _tools(_document("s1", "alpha"), _document("s2", "beta"))
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "nope"})
    assert "nope" in text
    assert "s1" in text
    assert "s2" in text


async def test_an_unknown_source_in_an_empty_corpus_says_the_corpus_is_empty() -> None:
    tools = _tools()
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "nope"})
    assert "empty" in text.lower()


async def test_an_unknown_source_does_not_raise() -> None:
    """A tool that raises costs the whole turn; the model can act on prose."""
    tools = _tools(_document("s1", "alpha"))
    assert isinstance(await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "nope"}), str)


async def test_the_available_list_is_capped_rather_than_dumping_the_corpus() -> None:
    tools = _tools(*[_document(f"s{index}", "x") for index in range(60)])
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "nope"})
    assert text.count("\n") < 60
    assert LIST_SOURCES_TOOL in text


async def test_a_storage_failure_while_reading_comes_back_as_prose() -> None:
    tools = _tools(_document("s1", "alpha"), fails=True)
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "s1"})
    assert "Could not" in text
    assert "unavailable" in text


def _offsets(header: str) -> tuple[int, int]:
    marker = header.split("@")[1].split()[0]
    start, _, end = marker.partition("-")
    return int(start), int(end)


@pytest.mark.parametrize("bad", [-5, -1])
async def test_a_negative_start_is_clamped_to_the_beginning(bad: int) -> None:
    tools = _tools(_document("s1", "Alpha."))
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "s1", "start": bad})
    assert "s1@0-6" in text


def test_the_reference_syntax_is_taught_beside_reading_it():
    """`CORPUS_PROMPT` is what `composition.py` actually appends to every
    project session's prompt; the grammar has to live inside it, not beside
    it, or a session never hears the syntax the reading tools just taught it
    to read a source with."""
    assert REFERENCE_SYNTAX_PROMPT in CORPUS_PROMPT


def test_the_prompt_states_the_id_charset():
    """Found in review: without this, a model could write an id containing a
    disqualifying character and produce a silently dead reference -- no
    error, just a `[[src:...]]` that never becomes a link. `:` is named
    explicitly because `fetch_media.py` mints ids containing one
    (`f"fetch:{digest}"`), and the frontend charset was widened to admit it."""
    assert "`:`" in REFERENCE_SYNTAX_PROMPT


# --- search_sources ---------------------------------------------------------
#
# The assertion that matters throughout is the module's own: an offset a
# response reports has to bound the text it reported beside it. It is sharper
# here than for `read_source`, because a search result's offsets are what the
# *next* call is made from -- a snippet whose span is a few characters off
# sends every subsequent read to the wrong place, and the read succeeds.


def _match_lines(text: str) -> list[tuple[str, int, int, str]]:
    """Every `source_id@start-end | snippet` line, parsed back apart."""
    parsed = []
    for line in text.splitlines():
        stripped = line.strip()
        if "@" not in stripped or " | " not in stripped:
            continue
        locator, _, snippet = stripped.partition(" | ")
        source_id, _, span = locator.partition("@")
        start, _, end = span.partition("-")
        parsed.append((source_id, int(start), int(end), snippet))
    return parsed


async def test_a_search_reports_offsets_that_bound_the_snippet_beside_them() -> None:
    """The whole reason this tool exists. Fails if the snippet is ever sliced
    from anything but the span whose numbers are printed with it."""
    body = "Alpha beta. " * 40 + "The aqueduct carried water. " + "Gamma delta. " * 40
    tools = _tools(_document("s1", body))
    text = await tools[SEARCH_SOURCES_TOOL].ainvoke({"pattern": "aqueduct"})
    (source_id, start, end, snippet) = _match_lines(text)[0]
    assert source_id == "s1"
    assert " ".join(body[start:end].split()) == snippet
    assert "aqueduct" in snippet


async def test_a_search_spans_every_source_and_names_each_one() -> None:
    """The failure this replaces: opening documents one at a time to find
    which of them discusses something."""
    tools = _tools(
        _document("s1", "nothing of interest here"),
        _document("s2", "the aqueduct at Segovia"),
        _document("s3", "another aqueduct entirely"),
    )
    text = await tools[SEARCH_SOURCES_TOOL].ainvoke({"pattern": "aqueduct"})
    assert {source for source, _, _, _ in _match_lines(text)} == {"s2", "s3"}
    assert "s1" not in text


async def test_a_search_offset_reads_back_as_the_same_text_through_read_source() -> None:
    """The loop this change exists to close, end to end: search, then read at
    the offsets the search returned, with no conversion in between. Fails if
    either tool's offsets are relative to anything but the whole document."""
    body = "x" * 3000 + "the aqueduct" + "y" * 3000
    tools = _tools(_document("s1", body))
    found = await tools[SEARCH_SOURCES_TOOL].ainvoke({"pattern": "aqueduct"})
    _, start, end, _ = _match_lines(found)[0]
    read = await tools[READ_SOURCE_TOOL].ainvoke(
        {"source_id": "s1", "start": start, "end": end}
    )
    assert f"s1@{start}-{end}" in read
    assert "aqueduct" in read


async def test_a_search_can_be_scoped_to_one_source() -> None:
    tools = _tools(_document("s1", "aqueduct"), _document("s2", "aqueduct"))
    text = await tools[SEARCH_SOURCES_TOOL].ainvoke({"pattern": "aqueduct", "source_id": "s2"})
    assert {source for source, _, _, _ in _match_lines(text)} == {"s2"}


async def test_scoping_to_an_unknown_source_says_so_rather_than_searching_all() -> None:
    """Silently searching the whole corpus would answer a question nobody
    asked, and the answer would look right."""
    tools = _tools(_document("s1", "aqueduct"))
    text = await tools[SEARCH_SOURCES_TOOL].ainvoke(
        {"pattern": "aqueduct", "source_id": "nope"}
    )
    assert "No source 'nope'" in text
    assert not _match_lines(text)


async def test_a_search_is_case_insensitive() -> None:
    tools = _tools(_document("s1", "The Aqueduct"))
    text = await tools[SEARCH_SOURCES_TOOL].ainvoke({"pattern": "aqueduct"})
    assert _match_lines(text)


async def test_no_match_says_so_and_names_the_pattern() -> None:
    tools = _tools(_document("s1", "alpha"))
    text = await tools[SEARCH_SOURCES_TOOL].ainvoke({"pattern": "aqueduct"})
    assert "No match" in text
    assert "aqueduct" in text


async def test_an_invalid_pattern_explains_itself_instead_of_raising() -> None:
    """A model writing a literal `(` is the common case, and a traceback
    ends the turn where a sentence lets it try again."""
    tools = _tools(_document("s1", "alpha (beta"))
    text = await tools[SEARCH_SOURCES_TOOL].ainvoke({"pattern": "("})
    assert "not a valid regular expression" in text


async def test_one_prolific_source_cannot_consume_the_whole_budget() -> None:
    """Without the per-source cap a document holding the phrase everywhere
    answers for the corpus, and the other sources holding it go unnamed --
    the same miss-in-silence the mount was built to remove."""
    tools = _tools(
        _document("noisy", "aqueduct " * 200),
        _document("quiet", "one aqueduct here"),
    )
    text = await tools[SEARCH_SOURCES_TOOL].ainvoke({"pattern": "aqueduct"})
    lines = _match_lines(text)
    assert sum(1 for source, _, _, _ in lines if source == "noisy") == MAX_PER_SOURCE
    assert any(source == "quiet" for source, _, _, _ in lines)
    assert "further match" in text


async def test_a_storage_failure_while_searching_comes_back_as_prose() -> None:
    tools = _tools(_document("s1", "aqueduct"), fails=True)
    text = await tools[SEARCH_SOURCES_TOOL].ainvoke({"pattern": "aqueduct"})
    assert "Could not" in text
    assert "unavailable" in text


# --- read_source(find=) -----------------------------------------------------


async def test_find_opens_the_window_at_the_match() -> None:
    """The call the agent in the report actually wanted: it knew the phrase
    and not the offset, and had nothing to convert one into the other."""
    body = "x" * 5000 + " the aqueduct carried water " + "y" * 5000
    tools = _tools(_document("s1", body), max_chars=500)
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "s1", "find": "aqueduct"})
    assert "aqueduct carried water" in text
    start, end = _offsets(text.splitlines()[0])
    assert body[start:end] in text
    assert start <= body.index("aqueduct")


async def test_find_reports_a_span_that_is_still_the_documents_own_offsets() -> None:
    """A window opened at a match is a citation like any other. Fails if the
    header is ever built from the match rather than from the returned span."""
    body = "x" * 4000 + "aqueduct" + "y" * 4000
    tools = _tools(_document("s1", body), max_chars=400)
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "s1", "find": "aqueduct"})
    start, end = _offsets(text.splitlines()[0])
    _, _, rest = text.partition("\n\n")
    assert rest.split("\n\n[")[0] == body[start:end]


async def test_find_searches_forward_from_start_so_a_second_match_is_reachable() -> None:
    """Reading on from a match is otherwise impossible: `find` alone always
    returns the first one, so a document with two would loop."""
    body = "aqueduct" + "x" * 2000 + "aqueduct" + "y" * 100
    tools = _tools(_document("s1", body), max_chars=300)
    first = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "s1", "find": "aqueduct"})
    assert _offsets(first.splitlines()[0])[0] == 0
    second = await tools[READ_SOURCE_TOOL].ainvoke(
        {"source_id": "s1", "find": "aqueduct", "start": 500}
    )
    assert _offsets(second.splitlines()[0])[0] >= 2008 - 200


async def test_find_with_no_match_names_the_search_tool_rather_than_the_top() -> None:
    """Returning character 0 would be a document the model did not ask for,
    read as though it were the answer."""
    tools = _tools(_document("s1", "alpha beta gamma"))
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "s1", "find": "aqueduct"})
    assert "No match" in text
    assert SEARCH_SOURCES_TOOL in text
    assert "alpha beta gamma" not in text


async def test_an_invalid_find_explains_itself_instead_of_raising() -> None:
    tools = _tools(_document("s1", "alpha"))
    text = await tools[READ_SOURCE_TOOL].ainvoke({"source_id": "s1", "find": "("})
    assert "not a valid regular expression" in text


def test_the_prompt_names_the_search_tool_and_its_offsets():
    """The trap this change removes is a prompt that sends the model to
    `grep`, whose line numbers address nothing `read_source` accepts. Fails if
    a later edit reinstates grep-first without a way to convert."""
    assert SEARCH_SOURCES_TOOL in CORPUS_PROMPT
    assert "find=" in CORPUS_PROMPT
    assert "line number" in CORPUS_PROMPT
    assert "does not raise an error" in REFERENCE_SYNTAX_PROMPT
