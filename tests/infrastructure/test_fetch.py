"""The fetch tool, against a stubbed transport.

No test here reaches the network, the same way the search tests do not. What
these pin is the shape of what reaches the model: a page is a citation plus
readable prose, capped, and every failure is prose rather than an exception --
a tool that raises costs the whole turn, and the model can do nothing useful
with a traceback.
"""

from uuid import uuid4

import httpx
import pytest

from research_team.application import AutonomyPolicy
from research_team.application.autonomy import FETCH_TOOL, GATED_TOOLS
from research_team.application.corpus_read import CorpusReadError, StoredDocument
from research_team.application.grants import FetchGrant
from research_team.domain import DocumentRecord
from research_team.infrastructure.agent import fetch as fetch_module
from research_team.infrastructure.agent.fetch import (
    UNREADABLE,
    build_fetch_tool,
    format_page,
)
from research_team.infrastructure.agent.recall import PageMemo, Recall, url_key
from research_team.infrastructure.agent.search import build_search_tool

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


def _html_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, html=ARTICLE)


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


# ---- formatting ----


def test_the_page_is_returned_as_markdown_prose():
    text = format_page(ARTICLE, "https://ex.example/sev", limit=10_000)
    assert "# Incident severity" in text
    assert "revenue critical path" in text


def test_the_url_is_carried_with_the_text():
    """The citation is the point of fetching. A page whose text arrives
    without its address cannot be cited by anything downstream, and the model
    will confabulate a source rather than admit it lost one.
    """
    text = format_page(ARTICLE, "https://ex.example/sev", limit=10_000)
    assert "https://ex.example/sev" in text


def test_boilerplate_is_dropped():
    """Nav and footer are the bulk of a real page and none of its meaning.
    Keeping them would spend context on chrome and teach the model that
    "Home About Contact" is part of what it read.
    """
    text = format_page(ARTICLE, "https://ex.example/sev", limit=10_000)
    assert "Home About Contact" not in text
    assert "(c) 2026 Example" not in text


def test_a_long_page_is_capped_and_says_it_was():
    """Silent truncation is worse than visible truncation: the model would
    reason about a partial page believing it had the whole one.
    """
    text = format_page(ARTICLE, "https://ex.example/sev", limit=200)
    assert len(text) < 500
    assert "truncated" in text.lower()


def test_a_page_with_no_extractable_prose_says_so():
    """An app shell, a login wall, or a pure-JS page extracts to nothing.
    That is an ordinary thing for the web to be, not an exception.
    """
    assert format_page("<html><body></body></html>", "https://ex.example", limit=10) == (
        UNREADABLE
    )


def test_input_that_is_not_html_at_all_is_handled_like_any_other_unreadable_page():
    """`format_page` is total by construction. A server can send anything at
    all with a text/html content type, and the caller has no way to know.
    """
    assert format_page("not html at all", "https://ex.example", limit=10) == UNREADABLE


# ---- the tool ----


async def test_fetching_a_page_returns_its_prose():
    fetch = build_fetch_tool(client=_client(_html_response))
    text = await fetch.ainvoke({"url": "https://ex.example/sev"})
    assert "revenue critical path" in text


async def test_an_unreachable_host_is_reported_rather_than_raised():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope", request=request)

    fetch = build_fetch_tool(client=_client(handler))
    text = await fetch.ainvoke({"url": "https://ex.example"})
    assert "could not" in text.lower()


async def test_an_http_error_status_is_reported_with_its_code():
    """404 and 403 are the two the model can actually act on -- one means the
    URL is wrong, the other means this page will never be readable this way.
    """
    fetch = build_fetch_tool(client=_client(lambda r: httpx.Response(404)))
    text = await fetch.ainvoke({"url": "https://ex.example/gone"})
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
    text = await fetch.ainvoke({"url": "https://ex.example/p.pdf"})
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
    text = await fetch.ainvoke({"url": url})
    assert "http" in text.lower()
    assert seen == []


async def test_the_response_body_is_capped_before_extraction():
    """A hostile or merely enormous page should not be parsed in full just to
    throw most of it away -- `lxml` on a 500MB body is a way to lose the turn.
    """
    huge = "<html><body>" + ("<p>filler filler filler</p>" * 200_000) + "</body></html>"
    fetch = build_fetch_tool(
        client=_client(lambda r: httpx.Response(200, html=huge)), max_bytes=50_000
    )
    text = await fetch.ainvoke({"url": "https://ex.example/huge"})
    assert "truncated" in text.lower()


# ---- grants ----


def _grant(budget: int = 3, hosts: frozenset[str] | None = None) -> FetchGrant:
    return FetchGrant(run_id=uuid4(), hosts=hosts or frozenset({"ex.example"}), budget=budget)


def _redirect_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(302, headers={"location": "https://elsewhere.example/target"})


@pytest.mark.asyncio
async def test_under_a_grant_a_redirect_is_not_followed_and_names_the_location():
    """The security point of this task: a granted host that answers 302 to an
    ungranted one must not be silently followed, or the allowlist is
    decorative. The client here has no explicit `follow_redirects`, so this
    also pins that a 3xx reaching `fetch` is reported rather than treated as
    a page.
    """
    fetch = build_fetch_tool(client=_client(_redirect_response), grant=_grant())
    text = await fetch.ainvoke({"url": "https://ex.example/a"})
    assert "https://elsewhere.example/target" in text
    assert "not follow" in text.lower() or "did not follow" in text.lower()


@pytest.mark.asyncio
async def test_without_a_grant_the_owned_client_still_follows_redirects(monkeypatch):
    """Ungranted `fetch` builds its own client exactly as it did before this
    task -- `follow_redirects=True`. Captured via a spy on `httpx.AsyncClient`
    because a client injected by a test (as everywhere else in this file)
    bypasses the construction this test exists to check.
    """
    captured: dict = {}
    real_async_client = httpx.AsyncClient

    def spy(*args, **kwargs):
        captured.update(kwargs)
        kwargs["transport"] = httpx.MockTransport(_html_response)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(fetch_module.httpx, "AsyncClient", spy)
    fetch = build_fetch_tool()
    await fetch.ainvoke({"url": "https://ex.example/sev"})
    assert captured["follow_redirects"] is True


@pytest.mark.asyncio
async def test_under_a_grant_the_owned_client_does_not_follow_redirects(monkeypatch):
    captured: dict = {}
    real_async_client = httpx.AsyncClient

    def spy(*args, **kwargs):
        captured.update(kwargs)
        kwargs["transport"] = httpx.MockTransport(_html_response)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(fetch_module.httpx, "AsyncClient", spy)
    fetch = build_fetch_tool(grant=_grant())
    await fetch.ainvoke({"url": "https://ex.example/sev"})
    assert captured["follow_redirects"] is False


@pytest.mark.asyncio
async def test_a_successful_network_read_spends_one():
    grant = _grant(budget=3)
    fetch = build_fetch_tool(client=_client(_html_response), grant=grant)
    await fetch.ainvoke({"url": "https://ex.example/sev"})
    assert grant.remaining == 2


@pytest.mark.asyncio
async def test_a_redirect_spends_one_too():
    """A redirect is a request that left the process -- httpx sent the GET
    and got a response back, same as any other. Not spending it would let a
    grant be probed for free by chasing declined redirects.
    """
    grant = _grant(budget=3)
    fetch = build_fetch_tool(client=_client(_redirect_response), grant=grant)
    await fetch.ainvoke({"url": "https://ex.example/a"})
    assert grant.remaining == 2


@pytest.mark.asyncio
async def test_a_corpus_hit_does_not_spend():
    grant = _grant(budget=3)
    corpus = _StubCorpus([_stored("s1", "https://ex.example/sev")])
    fetch = build_fetch_tool(client=_client(_html_response), corpus=corpus, grant=grant)
    await fetch.ainvoke({"url": "https://ex.example/sev"})
    assert grant.remaining == 3


@pytest.mark.asyncio
async def test_a_memo_hit_does_not_spend():
    grant = _grant(budget=3)
    recall = Recall()
    fetch = build_fetch_tool(client=_client(_html_response), recall=recall, grant=grant)
    await fetch.ainvoke({"url": "https://ex.example/sev"})
    assert grant.remaining == 2
    await fetch.ainvoke({"url": "https://ex.example/sev"})
    assert grant.remaining == 2


@pytest.mark.asyncio
async def test_an_error_does_not_spend():
    grant = _grant(budget=3)
    fetch = build_fetch_tool(client=_failing_client(), grant=grant)
    await fetch.ainvoke({"url": "https://ex.example/a"})
    assert grant.remaining == 3


@pytest.mark.asyncio
async def test_an_http_status_error_does_not_spend():
    grant = _grant(budget=3)
    fetch = build_fetch_tool(client=_client(lambda r: httpx.Response(404)), grant=grant)
    await fetch.ainvoke({"url": "https://ex.example/gone"})
    assert grant.remaining == 3


@pytest.mark.asyncio
async def test_a_spent_grant_refuses_in_band_rather_than_attempting_the_request():
    """Not reachable through the gate (Task 3 refuses first), but "not
    reachable" is not "cannot happen" -- an in-band refusal is chosen over
    attempting the request because it is honest about why nothing came back,
    rather than quietly making a network call the grant no longer covers.
    """
    calls: list[int] = []
    grant = _grant(budget=1)
    grant.spend()
    assert grant.spent
    fetch = build_fetch_tool(client=_client(_counting(calls)), grant=grant)
    text = await fetch.ainvoke({"url": "https://ex.example/a"})
    assert calls == []
    assert "budget" in text.lower() or "exhausted" in text.lower()


@pytest.mark.asyncio
async def test_a_spent_grant_still_answers_from_the_corpus():
    """The budget bounds requests that leave the process; a cache hit is not
    one, so it should not be refused merely because the network budget ran
    out.
    """
    grant = _grant(budget=1)
    grant.spend()
    corpus = _StubCorpus([_stored("s1", "https://ex.example/sev")])
    fetch = build_fetch_tool(client=_client(_html_response), corpus=corpus, grant=grant)
    text = await fetch.ainvoke({"url": "https://ex.example/sev"})
    assert "stored prose" in text


@pytest.mark.asyncio
async def test_without_a_grant_nothing_spends_and_behaviour_is_unchanged():
    fetch = build_fetch_tool(client=_client(_html_response))
    text = await fetch.ainvoke({"url": "https://ex.example/sev"})
    assert "revenue critical path" in text


# ---- autonomy ----


def test_fetch_is_gated():
    assert FETCH_TOOL in GATED_TOOLS


def test_fetch_defaults_to_asking_even_though_other_tools_default_to_auto():
    """The whole reason fetch can be registered unconditionally: it is present
    in a default install but cannot leave the process without a person saying
    so, once.
    """
    policy = AutonomyPolicy()
    assert policy.level_for(FETCH_TOOL) == "ask"
    assert policy.level_for("write_file") == "auto"


def test_a_stricter_instance_default_still_wins_over_the_tool_floor():
    """`ask` is a floor, not an override. An operator who built the policy to
    deny everything did not mean "except fetch".
    """
    assert AutonomyPolicy(default="deny").level_for(FETCH_TOOL) == "deny"


def test_an_explicit_setting_overrides_the_floor_in_both_directions():
    policy = AutonomyPolicy()
    policy.set(FETCH_TOOL, "auto")
    assert policy.level_for(FETCH_TOOL) == "auto"


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

    async def list_documents(self):
        if self._error:
            raise self._error
        return [document.record for document in self._documents]

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
        record=DocumentRecord(
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

    text = await fetch.ainvoke({"url": "https://ex.example/sev"})

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

    text = await fetch.ainvoke({"url": "https://ex.example/sev"})

    assert "s1@0-12 of 12 chars" in text
    body = text.split("\n\n")[-1]
    assert len(body) == 12 - 0


@pytest.mark.asyncio
async def test_a_corpus_hit_matches_an_equivalent_url():
    corpus = _StubCorpus([_stored("s1", "https://ex.example/sev")])
    calls: list[int] = []
    fetch = build_fetch_tool(client=_client(_counting(calls)), corpus=corpus)

    await fetch.ainvoke({"url": "HTTPS://Ex.Example:443/sev#top"})

    assert calls == []


@pytest.mark.asyncio
async def test_the_same_page_twice_is_fetched_once():
    calls: list[int] = []
    fetch = build_fetch_tool(client=_client(_counting(calls)), recall=Recall())
    await fetch.ainvoke({"url": "https://ex.example/sev"})
    await fetch.ainvoke({"url": "https://ex.example/sev"})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_recalled_page_says_it_is_recalled_and_how_old():
    calls: list[int] = []
    fetch = build_fetch_tool(client=_client(_counting(calls)), recall=Recall())
    await fetch.ainvoke({"url": "https://ex.example/sev"})
    again = await fetch.ainvoke({"url": "https://ex.example/sev"})
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

    await fetch.ainvoke({"url": "https://ex.example/sev"})
    await fetch.ainvoke({"url": "https://ex.example/sev", "refresh": True})

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

    await fetch.ainvoke({"url": "https://ex.example/sev"})
    await fetch.ainvoke({"url": "https://ex.example/sev", "refresh": True})

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

    await fetch.ainvoke({"url": "https://ex.example/sev"})

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_page_dropped_between_listing_and_reading_still_reaches_the_network():
    """Covers the `document is None` branch of `stored_page`: the record is
    listed, matches by URI, and then a delete lands before `read_document`
    runs -- the one window `_StubCorpus.drop_on_read` exists to reproduce.
    """
    calls: list[int] = []
    corpus = _StubCorpus([_stored("s1", "https://ex.example/sev")], drop_on_read="s1")
    fetch = build_fetch_tool(client=_client(_counting(calls)), corpus=corpus)

    await fetch.ainvoke({"url": "https://ex.example/sev"})

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

    await fetch.ainvoke({"url": "https://ex.example/sev"})

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

    text = await fetch.ainvoke({"url": "https://ex.example/sev"})

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
    await fetch.ainvoke({"url": "https://ex.example/sev"})
    second = await fetch.ainvoke({"url": "https://ex.example/sev"})

    assert len(calls) == 2
    assert "revenue critical path" in second


@pytest.mark.asyncio
async def test_a_project_less_fetch_still_works():
    calls: list[int] = []
    fetch = build_fetch_tool(client=_client(_counting(calls)))
    text = await fetch.ainvoke({"url": "https://ex.example/sev"})
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

    text = await fetch.ainvoke({"url": "https://ex.example/sev"})

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
    fetched = await fetch.ainvoke({"url": url})

    assert "A paper" in searched
    assert "A paper" not in fetched
    assert f"url: {url}" in fetched

    searched_again = await search.ainvoke({"query": url})
    assert "A paper" in searched_again
    assert "revenue critical path" not in searched_again


# ---------------- retention (PageMemo) ----------------


def _body_client(body: str) -> httpx.AsyncClient:
    return _client(lambda request: httpx.Response(200, html=body))


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

    shown = await tool.ainvoke({"url": "https://example.com/long"})

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

    await tool.ainvoke({"url": "https://example.com/a"})

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

    shown = await tool.ainvoke({"url": "https://example.com/a"})

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

    await tool.ainvoke({"url": "https://example.com/shell"})

    assert pages.get("https://example.com/shell") is None


async def test_a_failed_fetch_is_not_retained():
    pages = PageMemo(stamp=lambda: "t")
    tool = build_fetch_tool(client=_failing_client(), pages=pages)

    await tool.ainvoke({"url": "https://example.com/gone"})

    assert pages.get("https://example.com/gone") is None


async def test_a_corpus_hit_is_not_retained():
    """Nothing project-scoped may enter a process-wide store. A corpus hit is
    one project's stored text; retaining it would serve it to another project's
    `remember_page`."""
    pages = PageMemo(stamp=lambda: "t")
    corpus = _corpus_holding("s1", text="stored body", uri="https://example.com/a")
    tool = build_fetch_tool(client=_body_client("<html/>"), corpus=corpus, pages=pages)

    await tool.ainvoke({"url": "https://example.com/a"})

    assert pages.get("https://example.com/a") is None


async def test_a_recall_hit_does_not_disturb_what_was_retained():
    """The memo answers the second fetch without a request, so nothing is
    re-retained and the first retention stands."""
    body = "<html><body><p>Real prose here, at length.</p></body></html>"
    pages = PageMemo(stamp=lambda: "t")
    recall = Recall()
    tool = build_fetch_tool(client=_body_client(body), recall=recall, pages=pages)

    await tool.ainvoke({"url": "https://example.com/a"})
    await tool.ainvoke({"url": "https://example.com/a"})

    retained = pages.get("https://example.com/a")
    assert retained is not None
    assert "Real prose" in retained.text


def test_fetch_corpus_prompt_names_remember_page():
    """The prompt is the only place the model learns which tool commits a
    fetched page. If it stopped naming `remember_page`, nothing else fails --
    the tool would just go undiscovered."""
    from research_team.infrastructure.agent.fetch import FETCH_CORPUS_PROMPT

    assert "call `remember_page` with its URL" in FETCH_CORPUS_PROMPT


def test_fetch_corpus_prompt_no_longer_asks_to_pass_page_text():
    """This is the transcription instruction the by-reference feature
    replaced: passing the fetched text and its citation lines to `remember`
    by hand. A future edit reinstating it would undo the feature while
    leaving every other test here, which checks what the prompt says rather
    than what it omits, green."""
    from research_team.infrastructure.agent.fetch import FETCH_CORPUS_PROMPT

    assert "pass it to `remember`" not in FETCH_CORPUS_PROMPT


async def test_refresh_replaces_what_was_retained():
    tool_pages = PageMemo(stamp=lambda: "t")
    client = _client_returning(
        "<html><body><p>First body, long enough.</p></body></html>",
        "<html><body><p>Second body, long enough.</p></body></html>",
    )
    tool = build_fetch_tool(client=client, recall=Recall(), pages=tool_pages)

    await tool.ainvoke({"url": "https://example.com/a"})
    await tool.ainvoke({"url": "https://example.com/a", "refresh": True})

    retained = tool_pages.get("https://example.com/a")
    assert retained is not None
    assert "Second body" in retained.text
