"""The fetch tool, against a stubbed transport.

No test here reaches the network, the same way the search tests do not. What
these pin is the shape of what reaches the model: a page is a citation plus
readable prose, capped, and every failure is prose rather than an exception --
a tool that raises costs the whole turn, and the model can do nothing useful
with a traceback.
"""

import itertools

import httpx
import pytest

from research_team.infrastructure.agent.fetch import (
    UNREADABLE,
    build_fetch_tool,
    extract_page,
)
from research_team.infrastructure.agent.recall import Recall, url_key
from research_team.infrastructure.agent.search import build_search_tool
from research_team.research.application.corpus_read import (
    CorpusReadError,
    SourceListing,
    StoredDocument,
    TextSourceUri,
)
from research_team.research.domain import TextRecord
from research_team.session.application.autonomy import FETCH_TOOL

SEARCH_PAYLOAD = {
    "results": [
        {
            "title": "A paper",
            "url": "https://arxiv.org/abs/2401.00001",
            "content": "Abstract.",
        }
    ]
}

ARTICLE = (
    "<html><head><title>Incident severity</title></head><body>"
    "<nav>Home About Contact</nav>"
    "<article><h1>Incident severity</h1><h2>Definitions</h2><p>"
    + (
        "A SEV-1 is a total loss of a revenue critical path, declared "
        "regardless of duration. " * 8
    )
    + "</p></article><footer>(c) 2026 Example</footer></body></html>"
)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


_call_ids = (f"t{n}" for n in itertools.count(1))


async def _invoke(fetch_tool, args: dict, *, call_id: str | None = None):
    """Call a `fetch`-shaped tool the way `ToolNode` actually does: a full
    `ToolCall`, not a bare args dict.

    Required since `fetch` grew `tool_call_id: Annotated[str,
    InjectedToolCallId]` to release its gate reservation in a `finally` --
    `langchain_core.tools.base._parse_input` raises `ValueError` for a tool
    with an injected field invoked with anything less than the full shape.
    `call_id` defaults to a fresh, never-repeated id per call so that tests
    which never reserve anything (the overwhelming majority in this file)
    are unaffected, and tests that do reserve can still pass a specific id
    to match what they reserved under.

    Invoking with a full `ToolCall` (rather than a bare args dict) also
    changes what comes back: langchain wraps the result in a `ToolMessage`
    instead of handing back the tool's plain string. `.content` is that
    string -- returning it here is what keeps every existing assertion in
    this file (`"x" in text`, `text == UNREADABLE`, ...) working unchanged.
    """
    call = {
        "name": FETCH_TOOL,
        "args": args,
        "id": call_id or next(_call_ids),
        "type": "tool_call",
    }
    result = await fetch_tool.ainvoke(call)
    return result.content


def _html_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, html=ARTICLE)


def _body_client(body: str) -> httpx.AsyncClient:
    return _client(lambda request: httpx.Response(200, html=body))


def _failing_client() -> httpx.AsyncClient:
    """A client whose every request fails at the transport, the way an
    unreachable host does -- used where a test needs a fetch that cannot
    possibly reach a page, as opposed to one whose page is merely unreadable.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope", request=request)

    return _client(handler)


def _client_returning(*bodies: str) -> httpx.AsyncClient:
    """A client that serves each of `bodies` in order, one per request --
    for tests that need a second, different response on a second call (e.g.
    `refresh=True`)."""
    responses = iter(bodies)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=next(responses))

    return _client(handler)


def _corpus_holding(source_id: str, *, text: str, uri: str) -> "_StubCorpus":
    return _StubCorpus([_stored(source_id, uri, text)])


# ---- extraction ----
#
# These six read `format_page` until 2026-08-27, when it was deleted as
# uncalled. Every assertion below is the same one; only the seam moved, onto
# `extract_page`, which is what the fetch tool actually calls. The citation
# header and the truncation marker that `format_page` also produced are
# asserted on the tool instead -- `test_a_corpus_hit_comes_back_citable`,
# `test_retained_provenance_matches_the_header_the_model_saw` and
# `test_the_whole_page_is_retained_though_only_part_is_shown` -- which is the
# only path that composes them in production.


def test_the_page_is_returned_as_markdown_prose():
    extracted = extract_page(ARTICLE, "https://ex.example/sev")
    assert extracted is not None
    text, _title, _date = extracted
    assert "# Incident severity" in text
    assert "revenue critical path" in text


async def test_the_url_is_carried_with_the_text():
    """The citation is the point of fetching. A page whose text arrives
    without its address cannot be cited by anything downstream, and the model
    will confabulate a source rather than admit it lost one.
    """
    fetch = build_fetch_tool(client=_client(_html_response))
    text = await _invoke(fetch, {"url": "https://ex.example/sev"})
    assert "https://ex.example/sev" in text


def test_boilerplate_is_dropped():
    """Nav and footer are the bulk of a real page and none of its meaning.
    Keeping them would spend context on chrome and teach the model that
    "Home About Contact" is part of what it read.
    """
    extracted = extract_page(ARTICLE, "https://ex.example/sev")
    assert extracted is not None
    text, _title, _date = extracted
    assert "Home About Contact" not in text
    assert "(c) 2026 Example" not in text


async def test_a_long_page_is_capped_and_says_it_was():
    """Silent truncation is worse than visible truncation: the model would
    reason about a partial page believing it had the whole one.

    On the tool rather than on a formatter, because the tool is where the cap
    is now applied -- `truncate_page` went with `format_page`, its one caller.
    """
    fetch = build_fetch_tool(max_chars=200, client=_client(_html_response))
    text = await _invoke(fetch, {"url": "https://ex.example/sev"})
    assert len(text) < 500
    assert "truncated" in text.lower()


async def test_a_page_with_no_extractable_prose_says_so():
    """An app shell, a login wall, or a pure-JS page extracts to nothing.
    That is an ordinary thing for the web to be, not an exception.

    Both halves, because they were one call until `format_page` was deleted:
    extraction answers None, and the tool turns that into `UNREADABLE` rather
    than an empty string or a raise. Nothing else in this file asserted the
    second half -- `test_an_unreadable_page_is_not_retained` checks only what
    the memo did not keep.
    """
    assert extract_page("<html><body></body></html>", "https://ex.example") is None

    tool = build_fetch_tool(client=_body_client("<html><body></body></html>"))
    assert await _invoke(tool, {"url": "https://ex.example"}) == UNREADABLE


def test_input_that_is_not_html_at_all_is_handled_like_any_other_unreadable_page():
    """`extract_page` is total by construction. A server can send anything at
    all with a text/html content type, and the caller has no way to know. The
    tool turns both cases into `UNREADABLE` at `fetch.py`'s one `is None`.
    """
    assert extract_page("not html at all", "https://ex.example") is None


# ---- the tool ----


async def test_fetching_a_page_returns_its_prose():
    fetch = build_fetch_tool(client=_client(_html_response))
    text = await _invoke(fetch, {"url": "https://ex.example/sev"})
    assert "revenue critical path" in text


async def test_an_unreachable_host_is_reported_rather_than_raised():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope", request=request)

    fetch = build_fetch_tool(client=_client(handler))
    text = await _invoke(fetch, {"url": "https://ex.example"})
    assert "could not" in text.lower()


async def test_an_http_error_status_is_reported_with_its_code():
    """404 and 403 are the two the model can actually act on -- one means the
    URL is wrong, the other means this page will never be readable this way.
    """
    fetch = build_fetch_tool(client=_client(lambda r: httpx.Response(404)))
    text = await _invoke(fetch, {"url": "https://ex.example/gone"})
    assert "404" in text


async def test_a_non_html_content_type_is_refused_by_name():
    """A PDF or a tarball would extract to noise at best. Naming the type is
    what lets the model decide to look elsewhere instead of retrying.
    """
    fetch = build_fetch_tool(
        client=_client(
            lambda r: httpx.Response(
                200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"}
            )
        )
    )
    text = await _invoke(fetch, {"url": "https://ex.example/p.pdf"})
    assert "application/pdf" in text


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://ex.example", "javascript:x"])
async def test_a_non_web_scheme_is_refused_without_a_request(url: str):
    """The refusal happens before the transport, so a scheme httpx would
    handle differently -- or a future httpx that grows a file transport --
    cannot turn this tool into a local file reader that skips the file tools'
    event recording entirely.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, html=ARTICLE)

    fetch = build_fetch_tool(client=_client(handler))
    text = await _invoke(fetch, {"url": url})
    assert "http" in text.lower()
    assert seen == []


async def test_a_malformed_url_approved_by_a_human_is_refused_safely():
    """B42: urlsplit raises ValueError on malformed URLs like invalid IPv6 brackets.
    The tool must return a refusal prose rather than crashing the turn.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, html=ARTICLE)

    fetch = build_fetch_tool(client=_client(handler))
    text = await _invoke(fetch, {"url": "https://[::1/x"})
    assert "Only http and https URLs can be fetched" in text
    assert seen == []


async def test_the_response_body_is_capped_before_extraction():
    """A hostile or merely enormous page should not be parsed in full just to
    throw most of it away -- `lxml` on a 500MB body is a way to lose the turn.
    """
    huge = "<html><body>" + ("<p>filler filler filler</p>" * 200_000) + "</body></html>"
    fetch = build_fetch_tool(
        client=_client(lambda r: httpx.Response(200, html=huge)), max_bytes=50_000
    )
    text = await _invoke(fetch, {"url": "https://ex.example/huge"})
    assert "truncated" in text.lower()


# ---------------- recall ----------------


class _StubCorpus:
    """A `CorpusReadPort` over a fixed set of documents.

    `drop_on_read` names a source id that is listed but comes back `None`
    from `read_document` -- the state a real corpus is in for one instant
    between a delete landing and a listing that predates it.
    """

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
        # `extracted=False` throughout: nothing on the `fetch` path reads it,
        # and a double that varied it would imply this port's caller cares
        # which documents have graphs. It does not -- it is matching URLs.
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


def _counting(counter: list[int]):
    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(1)
        return httpx.Response(200, html=ARTICLE)

    return handler


@pytest.mark.asyncio
async def test_a_page_already_in_the_corpus_is_not_fetched_again():
    calls: list[int] = []
    corpus = _StubCorpus([_stored("s1", "https://ex.example/sev")])
    fetch = build_fetch_tool(client=_client(_counting(calls)), corpus=corpus, recall=Recall())

    text = await _invoke(fetch, {"url": "https://ex.example/sev"})

    assert calls == []
    assert "stored prose" in text


@pytest.mark.asyncio
async def test_a_corpus_hit_comes_back_citable():
    """The reason the corpus is consulted before the memo: a stored hit
    carries `source_id@start-end`, and a page read off the wire carries no
    identifier anything downstream can point at.
    """
    corpus = _StubCorpus([_stored("s1", "https://ex.example/sev")])
    fetch = build_fetch_tool(client=_client(_html_response), corpus=corpus)

    text = await _invoke(fetch, {"url": "https://ex.example/sev"})

    assert "s1@0-12 of 12 chars" in text
    body = text.split("\n\n")[-1]
    assert len(body) == 12 - 0


@pytest.mark.asyncio
async def test_a_corpus_hit_matches_an_equivalent_url():
    corpus = _StubCorpus([_stored("s1", "https://ex.example/sev")])
    calls: list[int] = []
    fetch = build_fetch_tool(client=_client(_counting(calls)), corpus=corpus)

    await _invoke(fetch, {"url": "HTTPS://Ex.Example:443/sev#top"})

    assert calls == []


@pytest.mark.asyncio
async def test_the_same_page_twice_is_fetched_once():
    calls: list[int] = []
    fetch = build_fetch_tool(client=_client(_counting(calls)), recall=Recall())
    await _invoke(fetch, {"url": "https://ex.example/sev"})
    await _invoke(fetch, {"url": "https://ex.example/sev"})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_recalled_page_says_it_is_recalled_and_how_old():
    calls: list[int] = []
    fetch = build_fetch_tool(client=_client(_counting(calls)), recall=Recall())
    await _invoke(fetch, {"url": "https://ex.example/sev"})
    again = await _invoke(fetch, {"url": "https://ex.example/sev"})
    assert "recalled" in again.lower()
    assert "ago" in again or "just now" in again


@pytest.mark.asyncio
async def test_refresh_reaches_the_network_past_both():
    """A tool that cannot be asked for a fresh read does not stop the request
    -- it makes the agent reach for a cache-busting query parameter, which
    arrives at the same server in a form nothing can recognise or count.
    """
    calls: list[int] = []
    corpus = _StubCorpus([_stored("s1", "https://ex.example/sev")])
    fetch = build_fetch_tool(client=_client(_counting(calls)), corpus=corpus, recall=Recall())

    await _invoke(fetch, {"url": "https://ex.example/sev"})
    await _invoke(fetch, {"url": "https://ex.example/sev", "refresh": True})

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_refresh_also_bypasses_a_memo_hit_and_repopulates_it():
    """The corpus case above is satisfied even if `refresh` only bypassed the
    corpus: with no `corpus=`, the first call warms the memo from the
    network, so a `refresh` that skipped just the corpus check but still
    honoured the memo would still show one network call. This isolates the
    memo: two plain-network reads are expected, and the second (refreshed)
    read must still land in the memo -- `recall.put` sits outside the `if not
    refresh:` guard, so a later refactor that moved it inside would go
    unnoticed without this assertion.
    """
    calls: list[int] = []
    recall = Recall()
    fetch = build_fetch_tool(client=_client(_counting(calls)), recall=recall)

    await _invoke(fetch, {"url": "https://ex.example/sev"})
    await _invoke(fetch, {"url": "https://ex.example/sev", "refresh": True})

    assert len(calls) == 2
    assert recall.get("https://ex.example/sev", key=url_key("https://ex.example/sev"))


@pytest.mark.asyncio
async def test_a_page_not_in_the_corpus_still_reaches_the_network():
    """Covers the `match is None` branch of `stored_page`: nothing in the
    corpus has this URI at all.
    """
    calls: list[int] = []
    corpus = _StubCorpus([_stored("s1", "https://ex.example/other")])
    fetch = build_fetch_tool(client=_client(_counting(calls)), corpus=corpus)

    await _invoke(fetch, {"url": "https://ex.example/sev"})

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_matching_the_corpus_never_asks_for_a_full_listing():
    """`stored_page` runs on every `fetch` call and needs two strings.

    `list_sources` loads every live document's body to answer -- measured on
    2026-08-16 at 48.1 ms and 22.5 MB peak per call over 500 documents of
    40,000 characters, against 5.7 ms and 0.16 MB for the column-projected
    `list_text_uris`. Nothing about the returned records is read here, so the
    bytes are pure cost, and the cost recurs per `fetch` rather than per page
    someone opens.

    This fails against the previous implementation, which called
    `list_sources` -- proved by writing it before the change. Nothing else in
    the suite would: both calls find the same page, so every existing
    assertion about the *answer* passes either way.
    """
    calls: list[int] = []
    corpus = _StubCorpus([_stored("s1", "https://ex.example/sev")])
    fetch = build_fetch_tool(client=_client(_counting(calls)), corpus=corpus)

    text = await _invoke(fetch, {"url": "https://ex.example/sev"})

    assert "stored prose" in text
    assert calls == []
    assert corpus.listed_uris == 1
    assert corpus.listed_sources == 0


@pytest.mark.asyncio
async def test_a_page_dropped_between_listing_and_reading_still_reaches_the_network():
    """Covers the `document is None` branch of `stored_page`: the record is
    listed, matches by URI, and then a delete lands before `read_document`
    runs -- the one window `_StubCorpus.drop_on_read` exists to reproduce.
    """
    calls: list[int] = []
    corpus = _StubCorpus([_stored("s1", "https://ex.example/sev")], drop_on_read="s1")
    fetch = build_fetch_tool(client=_client(_counting(calls)), corpus=corpus)

    await _invoke(fetch, {"url": "https://ex.example/sev"})

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_document_stored_without_a_uri_never_matches():
    """Most of the corpus looks like this today. It must be a miss, not a
    match on the empty string.
    """
    calls: list[int] = []
    document = _stored("s1", "https://ex.example/sev")
    document = StoredDocument(
        record=document.record.model_copy(update={"uri": None}), text=document.text
    )
    fetch = build_fetch_tool(client=_client(_counting(calls)), corpus=_StubCorpus([document]))

    await _invoke(fetch, {"url": "https://ex.example/sev"})

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_an_unreadable_corpus_falls_through_to_the_network():
    """A storage failure must not cost the fetch. The corpus is an
    optimisation here, and an optimisation that can break the operation is
    not one.
    """
    calls: list[int] = []
    fetch = build_fetch_tool(
        client=_client(_counting(calls)),
        corpus=_StubCorpus(error=CorpusReadError("neo4j down")),
    )

    text = await _invoke(fetch, {"url": "https://ex.example/sev"})

    assert len(calls) == 1
    assert "revenue critical path" in text


@pytest.mark.asyncio
async def test_a_failed_fetch_is_not_remembered():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, html=ARTICLE)

    fetch = build_fetch_tool(client=_client(handler), recall=Recall())
    await _invoke(fetch, {"url": "https://ex.example/sev"})
    second = await _invoke(fetch, {"url": "https://ex.example/sev"})

    assert len(calls) == 2
    assert "revenue critical path" in second


@pytest.mark.asyncio
async def test_a_project_less_fetch_still_works():
    calls: list[int] = []
    fetch = build_fetch_tool(client=_client(_counting(calls)))
    text = await _invoke(fetch, {"url": "https://ex.example/sev"})
    assert len(calls) == 1
    assert "revenue critical path" in text


@pytest.mark.asyncio
async def test_one_document_with_a_malformed_uri_does_not_break_every_fetch():
    """`uri` is free text the model supplies through `remember`, and
    `stored_page` normalizes every one of them on every call. A port that is
    not a number used to raise out of `urlsplit`, so a single stored document
    poisoned `fetch` for that project permanently.
    """
    calls: list[int] = []
    corpus = _StubCorpus([_stored("s1", "http://host:port/x")])
    fetch = build_fetch_tool(client=_client(_counting(calls)), corpus=corpus)

    text = await _invoke(fetch, {"url": "https://ex.example/sev"})

    assert len(calls) == 1
    assert "revenue critical path" in text


@pytest.mark.asyncio
async def test_a_search_for_a_url_and_a_fetch_of_it_do_not_share_an_entry():
    """`normalize_query` and `normalize_url` agree on a bare URL, so one
    keyspace would let `web_search`'s snippet list come back from `fetch`
    labelled as the page -- no `url:` header, no body -- and the reverse.
    """
    url = "https://arxiv.org/abs/2401.00001"
    recall = Recall()
    search = build_search_tool(
        "https://searx.example",
        client=_client(lambda request: httpx.Response(200, json=SEARCH_PAYLOAD)),
        recall=recall,
    )
    fetch = build_fetch_tool(client=_client(_html_response), recall=recall)

    searched = await search.ainvoke({"query": url})
    fetched = await _invoke(fetch, {"url": url})

    assert "A paper" in searched
    assert "A paper" not in fetched
    assert f"url: {url}" in fetched

    searched_again = await search.ainvoke({"query": url})
    assert "A paper" in searched_again
    assert "revenue critical path" not in searched_again
