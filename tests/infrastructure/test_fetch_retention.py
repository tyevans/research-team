"""Tests exercising fetch PageMemo retention and unattended keep hooks.

Covers full-page retention in PageMemo, unreadable/failed fetch exclusions,
corpus-hit isolation, recall cache stability, prompt specifications for remember_page,
refresh overwrites, and the keep hook lifecycle for unattended runs.
"""

import itertools

import httpx

from research_team.application.research.corpus_read import (
    SourceListing,
    StoredDocument,
    TextSourceUri,
)
from research_team.application.session.autonomy import FETCH_TOOL
from research_team.domain import TextRecord
from research_team.infrastructure.agent.fetch import (
    FETCH_CORPUS_PROMPT,
    build_fetch_tool,
)
from research_team.infrastructure.agent.recall import PageMemo, Recall


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


_call_ids = (f"t{n}" for n in itertools.count(1))


async def _invoke(fetch_tool, args: dict, *, call_id: str | None = None):
    call = {
        "name": FETCH_TOOL,
        "args": args,
        "id": call_id or next(_call_ids),
        "type": "tool_call",
    }
    result = await fetch_tool.ainvoke(call)
    return result.content


def _body_client(body: str) -> httpx.AsyncClient:
    return _client(lambda request: httpx.Response(200, html=body))


def _failing_client() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope", request=request)

    return _client(handler)


def _client_returning(*bodies: str) -> httpx.AsyncClient:
    responses = iter(bodies)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=next(responses))

    return _client(handler)


class _StubCorpus:
    def __init__(self, documents=(), error=None, drop_on_read=None):
        self._documents = list(documents)
        self._error = error
        self._drop_on_read = drop_on_read
        self.reads: list[str] = []
        self.listed_uris = 0
        self.listed_sources = 0

    async def list_sources(self):
        if self._error:
            raise self._error
        self.listed_sources += 1
        return [
            SourceListing(record=document.record, extracted=False)
            for document in self._documents
        ]

    async def list_text_uris(self):
        if self._error:
            raise self._error
        self.listed_uris += 1
        return [
            TextSourceUri(source_id=document.record.source_id, uri=document.record.uri)
            for document in self._documents
            if document.record.kind == "text" and document.record.uri
        ]

    async def read_document(self, source_id):
        if self._error:
            raise self._error
        self.reads.append(source_id)
        if source_id == self._drop_on_read:
            return None
        for document in self._documents:
            if document.record.source_id == source_id:
                return document
        return None


def _stored(source_id: str, uri: str, text: str = "stored prose") -> StoredDocument:
    return StoredDocument(
        record=TextRecord(
            source_id=source_id,
            sha256="0" * 64,
            char_count=len(text),
            uri=uri,
            title="Stored",
        ),
        text=text,
    )


def _corpus_holding(source_id: str, *, text: str, uri: str) -> _StubCorpus:
    return _StubCorpus([_stored(source_id, uri, text)])


async def test_the_whole_page_is_retained_though_only_part_is_shown():
    """The model's budget stops being the corpus's ceiling.

    MAX_CHARS is documented as what one page may cost the conversation. Because
    a document could only reach the corpus through the model's own output, it
    was also the most the corpus could ever hold of a fetched page -- against a
    corpus that accepts 200_000.
    """
    body = "<html><body><p>" + ("word " * 4000) + "</p></body></html>"
    pages = PageMemo(stamp=lambda: "t")
    tool = build_fetch_tool(max_chars=100, client=_body_client(body), pages=pages)

    shown = await _invoke(tool, {"url": "https://example.com/long"})

    retained = pages.get("https://example.com/long")
    assert retained is not None
    assert len(retained.text) > len(shown)
    assert "[truncated" not in retained.text


async def test_the_retained_text_carries_no_citation_header():
    """The header is for the model to read. The corpus stores it as fields, and
    a document whose first line is `url: ...` would quote back as though the
    page said it."""
    body = "<html><body><p>Real prose here, at length.</p></body></html>"
    pages = PageMemo(stamp=lambda: "t")
    tool = build_fetch_tool(client=_body_client(body), pages=pages)

    await _invoke(tool, {"url": "https://example.com/a"})

    retained = pages.get("https://example.com/a")
    assert retained is not None
    assert not retained.text.startswith("url:")


async def test_retained_provenance_matches_the_header_the_model_saw():
    """One extraction feeds both, so the fields and the header cannot disagree."""
    body = (
        "<html><head><title>A Paper</title>"
        '<meta property="article:published_time" content="2026-01-02"/>'
        "</head><body><p>Real prose here, at length.</p></body></html>"
    )
    pages = PageMemo(stamp=lambda: "t")
    tool = build_fetch_tool(client=_body_client(body), pages=pages)

    shown = await _invoke(tool, {"url": "https://example.com/a"})

    retained = pages.get("https://example.com/a")
    assert retained is not None
    assert retained.uri == "https://example.com/a"
    assert retained.title == "A Paper"
    assert retained.title is not None and retained.title in shown


async def test_an_unreadable_page_is_not_retained():
    """For UNREADABLE's existing reason: retaining it would pin "this renders in
    the browser" for an hour after a deploy fixed it."""
    pages = PageMemo(stamp=lambda: "t")
    tool = build_fetch_tool(client=_body_client("<html><body></body></html>"), pages=pages)

    await _invoke(tool, {"url": "https://example.com/shell"})

    assert pages.get("https://example.com/shell") is None


async def test_a_failed_fetch_is_not_retained():
    pages = PageMemo(stamp=lambda: "t")
    tool = build_fetch_tool(client=_failing_client(), pages=pages)

    await _invoke(tool, {"url": "https://example.com/gone"})

    assert pages.get("https://example.com/gone") is None


async def test_a_corpus_hit_is_not_retained():
    """Nothing project-scoped may enter a process-wide store. A corpus hit is
    one project's stored text; retaining it would serve it to another project's
    `remember_page`."""
    pages = PageMemo(stamp=lambda: "t")
    corpus = _corpus_holding("s1", text="stored body", uri="https://example.com/a")
    tool = build_fetch_tool(client=_body_client("<html/>"), corpus=corpus, pages=pages)

    await _invoke(tool, {"url": "https://example.com/a"})

    assert pages.get("https://example.com/a") is None


async def test_a_recall_hit_does_not_disturb_what_was_retained():
    """The memo answers the second fetch without a request, so nothing is
    re-retained and the first retention stands."""
    body = "<html><body><p>Real prose here, at length.</p></body></html>"
    pages = PageMemo(stamp=lambda: "t")
    recall = Recall()
    tool = build_fetch_tool(client=_body_client(body), recall=recall, pages=pages)

    await _invoke(tool, {"url": "https://example.com/a"})
    await _invoke(tool, {"url": "https://example.com/a"})

    retained = pages.get("https://example.com/a")
    assert retained is not None
    assert "Real prose" in retained.text


def test_fetch_corpus_prompt_names_remember_page():
    """The prompt is the only place the model learns which tool commits a
    fetched page. If it stopped naming `remember_page`, nothing else fails --
    the tool would just go undiscovered."""
    assert "call `remember_page` with its URL" in FETCH_CORPUS_PROMPT


def test_fetch_corpus_prompt_no_longer_asks_to_pass_page_text():
    """This is the transcription instruction the by-reference feature
    replaced: passing the fetched text and its citation lines to `remember`
    by hand. A future edit reinstating it would undo the feature while
    leaving every other test here, which checks what the prompt says rather
    than what it omits, green."""
    assert "pass it to `remember`" not in FETCH_CORPUS_PROMPT


async def test_refresh_replaces_what_was_retained():
    tool_pages = PageMemo(stamp=lambda: "t")
    client = _client_returning(
        "<html><body><p>First body, long enough.</p></body></html>",
        "<html><body><p>Second body, long enough.</p></body></html>",
    )
    tool = build_fetch_tool(client=client, recall=Recall(), pages=tool_pages)

    await _invoke(tool, {"url": "https://example.com/a"})
    await _invoke(tool, {"url": "https://example.com/a", "refresh": True})

    retained = tool_pages.get("https://example.com/a")
    assert retained is not None
    assert "Second body" in retained.text


async def test_a_read_page_is_handed_to_keep():
    """The hook an unattended run stops depending on the model with.

    Asserts the url rather than the page: `keep` is given a key into `pages`,
    not the page itself, so that `fetch` stays ignorant of `SourceRef` and the
    corpus. Fails with the `keep` call removed from the success path.
    """
    kept: list[str] = []

    async def keep(url: str) -> None:
        kept.append(url)

    body = "<html><body><p>Real prose here, at length.</p></body></html>"
    pages = PageMemo(stamp=lambda: "t")
    tool = build_fetch_tool(client=_body_client(body), pages=pages, keep=keep)

    await _invoke(tool, {"url": "https://example.com/a"})

    assert kept == ["https://example.com/a"]


async def test_keep_sees_a_page_the_memo_already_holds():
    """Ordering, which is the whole of what could be wrong here.

    `keep` reads the page back out of `PageMemo` by url, so a `keep` call
    placed before `pages.put` would find nothing and save nothing -- while
    every assertion about `keep` *being called* still passed. This is the test
    that fails if the two are ever reordered.
    """
    seen: list[object] = []
    body = "<html><body><p>Real prose here, at length.</p></body></html>"
    pages = PageMemo(stamp=lambda: "t")

    async def keep(url: str) -> None:
        seen.append(pages.get(url))

    tool = build_fetch_tool(client=_body_client(body), pages=pages, keep=keep)

    await _invoke(tool, {"url": "https://example.com/a"})

    assert seen and seen[0] is not None


async def test_a_page_that_did_not_read_is_not_kept():
    """An unreadable page has nothing worth saving, and saving the failure
    would put a document in the corpus that no citation could survive."""
    kept: list[str] = []

    async def keep(url: str) -> None:
        kept.append(url)

    tool = build_fetch_tool(
        client=_body_client("<html><body></body></html>"),
        pages=PageMemo(stamp=lambda: "t"),
        keep=keep,
    )

    await _invoke(tool, {"url": "https://example.com/empty"})

    assert kept == []
