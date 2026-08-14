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
    CorpusReadError,
    DocumentListing,
    StoredDocument,
)
from research_team.domain import DocumentRecord
from research_team.infrastructure.agent.corpus_tools import build_corpus_tools

ALPHABET = "abcdefghijklmnopqrstuvwxyz "


def _document(source_id: str, text: str, **metadata) -> StoredDocument:
    """A stored document, digest and all.

    `DocumentRecord` requires a `sha256` these tests do not care about, so it
    is computed rather than faked -- a stub digest here would be the one place
    in the system where a record's digest did not describe its bytes.
    """
    return StoredDocument(
        record=DocumentRecord(
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

    async def list_documents(self) -> list[DocumentListing]:
        if self._fails:
            raise CorpusReadError("the read model is unavailable")
        # `extracted=False` throughout: `format_listing` deliberately does not
        # render it, and a double that varied it would suggest it should.
        return [
            DocumentListing(record=document.record, extracted=False)
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


def test_both_tools_are_built_under_their_declared_names() -> None:
    assert set(_tools()) == {LIST_SOURCES_TOOL, READ_SOURCE_TOOL}


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
