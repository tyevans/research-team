"""Tests exercising fetch grants, budgets, redirect safety, and autonomy policies.

Covers host authorization, budget spending and enforcement, redirect gating under
grants, autonomy floors/overrides, and concurrent budget claim reservation.
"""

import asyncio
import itertools
from uuid import uuid4

import httpx
import pytest

from research_team.infrastructure.agent import fetch as fetch_module
from research_team.infrastructure.agent.approval import interrupt_config
from research_team.infrastructure.agent.fetch import build_fetch_tool
from research_team.infrastructure.agent.recall import Recall
from research_team.research.application.corpus_read import (
    SourceListing,
    StoredDocument,
    TextSourceUri,
)
from research_team.research.domain import TextRecord
from research_team.session.application.autonomy import FETCH_TOOL, GATED_TOOLS, AutonomyPolicy
from research_team.tenancy.application.grants import FetchGrant, GrantRegistry

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
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope", request=request)

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


def _counting(counter: list[int]):
    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(1)
        return httpx.Response(200, html=ARTICLE)

    return handler


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
