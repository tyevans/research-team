"""The fetch tool, against a stubbed transport.

No test here reaches the network, the same way the search tests do not. What
these pin is the shape of what reaches the model: a page is a citation plus
readable prose, capped, and every failure is prose rather than an exception --
a tool that raises costs the whole turn, and the model can do nothing useful
with a traceback.
"""

import asyncio
import itertools
from uuid import uuid4

import httpx
import pytest

from research_team.application import AutonomyPolicy
from research_team.application.autonomy import FETCH_TOOL, GATED_TOOLS
from research_team.application.corpus_read import (
    CorpusReadError,
    SourceListing,
    StoredDocument,
)
from research_team.application.grants import FetchGrant, GrantRegistry
from research_team.domain import TextRecord
from research_team.infrastructure.agent import fetch as fetch_module
from research_team.infrastructure.agent.approval import interrupt_config
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


# ---- grants ----


def _grant(budget: int = 3, hosts: frozenset[str] | None = None) -> FetchGrant:
    return FetchGrant(run_id=uuid4(), hosts=hosts or frozenset({"ex.example"}), budget=budget)


def _redirect_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(302, headers={"location": "https://elsewhere.example/target"})


@pytest.mark.asyncio
async def test_under_a_grant_a_redirect_is_not_followed_and_names_the_location():
    """Pins the 3xx *reporting* branch, not the grant: `_client()` builds an
    `httpx.AsyncClient` with httpx's own default (`follow_redirects=False`),
    so this test would pass identically with `grant=None` -- a `grant` is
    passed here only so the surrounding context reads like the feature this
    file is about, not because the assertion depends on it. The actual
    security property -- that a *granted* run's owned client is built
    without following redirects at all, in contrast to an ungranted one --
    is pinned by the two `monkeypatch` spy tests below
    (`test_without_a_grant_the_owned_client_still_follows_redirects` and
    `test_under_a_grant_the_owned_client_does_not_follow_redirects`), which
    inspect the `follow_redirects` kwarg `fetch` itself chooses. Per
    CLAUDE.md, a test that would pass with the change reverted must say so
    rather than read as reassurance -- this docstring is that disclosure.
    """
    fetch = build_fetch_tool(client=_client(_redirect_response), grant=_grant())
    text = await _invoke(fetch, {"url": "https://ex.example/a"})
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
    await _invoke(fetch, {"url": "https://ex.example/sev"})
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
    await _invoke(fetch, {"url": "https://ex.example/sev"})
    assert captured["follow_redirects"] is False


@pytest.mark.asyncio
async def test_a_covered_fetch_spends_one():
    """`_grant()`'s default hosts include `ex.example`, so this URL is what
    the grant actually authorized -- the spend is the grant's doing.
    """
    grant = _grant(budget=3)
    fetch = build_fetch_tool(client=_client(_html_response), grant=grant)
    await _invoke(fetch, {"url": "https://ex.example/sev"})
    assert grant.remaining == 2


@pytest.mark.asyncio
async def test_a_covered_redirect_spends_one_too():
    """A redirect is a request that left the process -- httpx sent the GET
    and got a response back, same as any other. Not spending it would let a
    grant be probed for free by chasing declined redirects.
    """
    grant = _grant(budget=3)
    fetch = build_fetch_tool(client=_client(_redirect_response), grant=grant)
    await _invoke(fetch, {"url": "https://ex.example/a"})
    assert grant.remaining == 2


@pytest.mark.asyncio
async def test_an_uncovered_fetch_under_a_grant_does_not_spend_but_still_succeeds():
    """A human approved this fetch at the gate -- `ex.other` is not in the
    grant's hosts, so the gate would not have covered it and would have
    interrupted for a person to decide. The person said yes. That approval,
    not the grant, is what authorized the call, so the grant is not spent:
    spending here would let human-approved fetches of any host silently
    drain a budget the grantor scoped to specific hosts.
    """
    grant = _grant(budget=3, hosts=frozenset({"ex.example"}))
    fetch = build_fetch_tool(client=_client(_html_response), grant=grant)
    text = await _invoke(fetch, {"url": "https://ex.other/sev"})
    assert "revenue critical path" in text
    assert grant.remaining == 3


@pytest.mark.asyncio
async def test_the_budget_is_unchanged_after_an_uncovered_fetch():
    grant = _grant(budget=1, hosts=frozenset({"ex.example"}))
    fetch = build_fetch_tool(client=_client(_html_response), grant=grant)
    await _invoke(fetch, {"url": "https://ex.other/sev"})
    assert grant.remaining == 1
    assert not grant.spent


@pytest.mark.asyncio
async def test_redirects_stay_off_for_an_uncovered_fetch_under_a_grant_too():
    """The redirect asymmetry tracks whether this is a granted run at all,
    not whether this particular call happened to be covered. A human
    approved fetching *this* URL; nobody approved wherever it might redirect
    to, so the same rule applies as a covered call: report the location
    instead of following it.
    """
    grant = _grant(budget=3, hosts=frozenset({"ex.example"}))
    fetch = build_fetch_tool(client=_client(_redirect_response), grant=grant)
    text = await _invoke(fetch, {"url": "https://ex.other/a"})
    assert "https://elsewhere.example/target" in text
    assert grant.remaining == 3


@pytest.mark.asyncio
async def test_a_corpus_hit_does_not_spend():
    grant = _grant(budget=3)
    corpus = _StubCorpus([_stored("s1", "https://ex.example/sev")])
    fetch = build_fetch_tool(client=_client(_html_response), corpus=corpus, grant=grant)
    await _invoke(fetch, {"url": "https://ex.example/sev"})
    assert grant.remaining == 3


@pytest.mark.asyncio
async def test_a_memo_hit_does_not_spend():
    grant = _grant(budget=3)
    recall = Recall()
    fetch = build_fetch_tool(client=_client(_html_response), recall=recall, grant=grant)
    await _invoke(fetch, {"url": "https://ex.example/sev"})
    assert grant.remaining == 2
    await _invoke(fetch, {"url": "https://ex.example/sev"})
    assert grant.remaining == 2


@pytest.mark.asyncio
async def test_an_error_does_not_spend():
    grant = _grant(budget=3)
    fetch = build_fetch_tool(client=_failing_client(), grant=grant)
    await _invoke(fetch, {"url": "https://ex.example/a"})
    assert grant.remaining == 3


@pytest.mark.asyncio
async def test_an_http_status_error_does_not_spend():
    grant = _grant(budget=3)
    fetch = build_fetch_tool(client=_client(lambda r: httpx.Response(404)), grant=grant)
    await _invoke(fetch, {"url": "https://ex.example/gone"})
    assert grant.remaining == 3


@pytest.mark.asyncio
async def test_a_spent_grant_no_longer_refuses_an_approved_fetch():
    """Fix round 1: the tool no longer refuses outright when `grant.spent` is
    true. `covers()` already answers `False` for every host once a grant is
    spent, so a spent grant looks identical to an out-of-scope host from the
    spend check's point of view -- and an out-of-scope host reaching this
    tool got here because a human approved it at the gate. Refusing it in
    band would block a fetch a person just said yes to, which is worse than
    the case this used to guard against. Nothing is spent (already zero,
    and `covers()` is `False`), but the request itself proceeds.
    """
    calls: list[int] = []
    grant = _grant(budget=1)
    grant.spend()
    assert grant.spent
    fetch = build_fetch_tool(client=_client(_counting(calls)), grant=grant)
    text = await _invoke(fetch, {"url": "https://ex.example/a"})
    assert len(calls) == 1
    assert "revenue critical path" in text
    assert grant.remaining == 0


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
    text = await _invoke(fetch, {"url": "https://ex.example/sev"})
    assert "stored prose" in text


@pytest.mark.asyncio
async def test_without_a_grant_nothing_spends_and_behaviour_is_unchanged():
    fetch = build_fetch_tool(client=_client(_html_response))
    text = await _invoke(fetch, {"url": "https://ex.example/sev"})
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

    async def list_sources(self):
        if self._error:
            raise self._error
        # `extracted=False` throughout: nothing on the `fetch` path reads it,
        # and a double that varied it would imply this port's caller cares
        # which documents have graphs. It does not -- it is matching URLs.
        return [
            SourceListing(record=document.record, extracted=False)
            for document in self._documents
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

    await _invoke(tool, {"url": "https://example.com/a"})
    await _invoke(tool, {"url": "https://example.com/a", "refresh": True})

    retained = tool_pages.get("https://example.com/a")
    assert retained is not None
    assert "Second body" in retained.text


# ---- the gate + tool together: the batch over-spend, end to end ----


@pytest.mark.asyncio
async def test_ten_gathered_covered_fetches_on_a_budget_of_one_hit_the_transport_once():
    """The reproduction from `task-5-review.md`, run against the real gate
    and the real tool rather than described: ten `fetch` calls covered by the
    same grant, a budget of one, gathered the way `langgraph`'s `ToolNode`
    actually runs a message's tool calls (`asyncio.gather`).

    Two phases, matching production: `HumanInTheLoopMiddleware.after_model`
    evaluates `when` for every call *before* any tool runs (synchronous, no
    `await` between them), and only the calls that were not interrupted ever
    reach `ToolNode`, which then runs them concurrently. This test does both
    steps for real -- the `when` loop is the exact shape `after_model` walks
    a message's tool calls in -- rather than asserting on the grant alone,
    so the fix is pinned at the same seam the review found it broken at.
    """
    calls = 0

    def _counting_html(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, html=ARTICLE)

    session_id = uuid4()
    grant = FetchGrant(run_id=session_id, hosts=frozenset({"ex.example"}), budget=1)
    grants = GrantRegistry()
    grants.register(session_id, grant)
    policy = AutonomyPolicy(default="auto")
    policy.set(FETCH_TOOL, "ask")
    when = interrupt_config(policy, session_id=session_id, grants=grants)[FETCH_TOOL]["when"]

    class _Call:
        def __init__(self, call_id: str, url: str) -> None:
            self.tool_call = {"name": FETCH_TOOL, "args": {"url": url}, "id": call_id}

    url = "https://ex.example/page"
    # Ten distinct calls, as a real message would carry -- each of langgraph's
    # own tool calls has its own id, which is exactly what the fix in
    # `FetchGrant.reserve` keys on.
    ids = [f"t{i}" for i in range(10)]
    # Phase 1: exactly how `after_model` walks one message's tool calls --
    # synchronously, before any of them runs.
    admitted = [call_id for call_id in ids if not when(_Call(call_id, url))]
    assert len(admitted) == 1  # the fix, at the gate: only one claim fit

    fetch = build_fetch_tool(client=_client(_counting_html), grant=grant)
    # Phase 2: only the admitted calls ever reach a tool at all -- an
    # interrupted call is parked for a human, not run -- and the ones that do
    # run concurrently, exactly as `ToolNode` runs them. Invoked under the
    # same id it was admitted under, so the tool's own release in its
    # `finally` redeems the exact claim the gate took.
    await asyncio.gather(
        *(_invoke(fetch, {"url": url}, call_id=call_id) for call_id in admitted)
    )

    assert calls == 1
    assert grant.remaining == 0


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
