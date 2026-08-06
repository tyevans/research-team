"""The fetch tool, against a stubbed transport.

No test here reaches the network, the same way the search tests do not. What
these pin is the shape of what reaches the model: a page is a citation plus
readable prose, capped, and every failure is prose rather than an exception --
a tool that raises costs the whole turn, and the model can do nothing useful
with a traceback.
"""

import httpx
import pytest

from research_team.application import AutonomyPolicy
from research_team.application.autonomy import FETCH_TOOL, GATED_TOOLS
from research_team.infrastructure.agent.fetch import (
    UNREADABLE,
    build_fetch_tool,
    format_page,
)

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
