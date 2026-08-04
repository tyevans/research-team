"""The search tool, against a stubbed transport.

No test here reaches the network. The live test lives behind the `live`
marker, like the model tests do.
"""

import httpx
from hypothesis import given
from hypothesis import strategies as st

from research_team.infrastructure.agent.search import build_search_tool, format_results

PAYLOAD = {
    "results": [
        {"title": "Event sourcing", "url": "https://a.example", "content": "A log."},
        {"title": "CQRS", "url": "https://b.example", "content": "Two models."},
        {"title": "Third", "url": "https://c.example", "content": "Extra."},
    ]
}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_results_are_formatted_with_title_url_and_snippet():
    text = format_results(PAYLOAD, limit=5)
    assert "Event sourcing" in text
    assert "https://a.example" in text
    assert "A log." in text


def test_the_result_cap_is_honoured():
    text = format_results(PAYLOAD, limit=2)
    assert "Event sourcing" in text
    assert "Third" not in text


def test_no_results_says_so_rather_than_returning_nothing():
    assert "no results" in format_results({"results": []}, limit=5).lower()


async def test_a_query_reaches_the_instance_and_comes_back_formatted():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=PAYLOAD)

    tool = build_search_tool("http://searx.local", limit=5, client=_client(handler))
    text = await tool.ainvoke({"query": "event sourcing"})

    assert "format=json" in seen["url"]
    assert "event+sourcing" in seen["url"] or "event%20sourcing" in seen["url"]
    assert "Event sourcing" in text


async def test_a_non_json_response_names_the_setting_that_causes_it():
    """SearXNG ships with the JSON API disabled; say so instead of exploding."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    tool = build_search_tool("http://searx.local", client=_client(handler))
    text = await tool.ainvoke({"query": "anything"})

    assert "formats" in text
    assert "settings.yml" in text


async def test_an_unreachable_instance_is_an_ordinary_tool_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    tool = build_search_tool("http://searx.local", client=_client(handler))
    text = await tool.ainvoke({"query": "anything"})

    assert "could not reach" in text.lower()


@given(
    st.lists(
        st.fixed_dictionaries(
            {
                "title": st.text(max_size=200),
                "url": st.text(max_size=200),
                "content": st.text(max_size=500),
            }
        ),
        max_size=50,
    ),
    st.integers(min_value=1, max_value=10),
)
def test_formatting_never_raises_and_never_exceeds_the_cap(results, limit):
    """Whatever an instance returns, formatting is total and bounded."""
    text = format_results({"results": results}, limit=limit)
    assert isinstance(text, str)
    shown = text.count("\n\n")
    assert shown <= limit
