"""The search tool, against a stubbed transport.

No test here reaches the network. The live test lives behind the `live`
marker, like the model tests do.
"""

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from research_team.infrastructure.agent.recall import Recall
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


def test_no_results_message_is_exact():
    """Pinned exactly, not just "contains" -- a wording or casing slip here
    is a real regression in what the model sees, not a cosmetic one.
    """
    assert format_results({"results": []}, limit=5) == "No results."


def test_a_result_missing_every_field_gets_named_placeholders():
    """`.get(key, "")` handles an absent field the same as an empty one; a
    real instance can omit a field entirely rather than send it empty, and
    the placeholder text is part of the contract with the model reading it.
    """
    text = format_results({"results": [{}]}, limit=5)
    assert text == "(untitled)\n(no url)\n(no snippet)"


def test_two_results_are_joined_by_a_blank_line():
    """The "\\n\\n" join is what lets the model tell blocks apart; pinning the
    exact separator (not just "a blank line appears somewhere") catches a
    mutation to the join string itself.
    """
    payload = {
        "results": [
            {"title": "One", "url": "https://a.example", "content": "First."},
            {"title": "Two", "url": "https://b.example", "content": "Second."},
        ]
    }
    text = format_results(payload, limit=5)
    assert text == ("One\nhttps://a.example\nFirst.\n\nTwo\nhttps://b.example\nSecond.")


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


async def test_the_default_cap_is_five_when_the_caller_does_not_choose_one():
    """`limit` defaults to 5 in the signature; a caller that never passes it
    (the ordinary case when the tool is wired up) still gets a bounded
    result set, not whatever the instance happens to send back.
    """
    six_results = {
        "results": [
            {"title": str(i), "url": f"https://{i}.example", "content": "x"} for i in range(6)
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=six_results)

    tool = build_search_tool("http://searx.local", client=_client(handler))
    text = await tool.ainvoke({"query": "anything"})

    assert text.count("\n\n") == 4  # 5 blocks joined by 4 separators
    assert "https://5.example" not in text


def test_format_results_rejects_a_non_dict_payload_without_raising():
    """`response.json()` only promises valid JSON, not the dict shape SearXNG's
    docs describe -- a list, string, or null is legal JSON a foreign instance
    can hand back. `format_results` must stay total for all of them.
    """
    assert isinstance(format_results([], limit=5), str)
    assert isinstance(format_results("oops", limit=5), str)
    assert isinstance(format_results(None, limit=5), str)


async def test_a_json_array_response_is_an_ordinary_tool_error_not_a_turn_failure():
    """A misconfigured instance or a proxy error page can render as a JSON
    array instead of the expected results object; the turn must survive it.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    tool = build_search_tool("http://searx.local", client=_client(handler))
    text = await tool.ainvoke({"query": "anything"})

    assert "not a results object" in text


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


# ---------------- recall ----------------


def _counting_handler(counter: list[int]):
    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(1)
        return httpx.Response(
            200,
            json={"results": [{"title": "T", "url": "https://ex.example/a", "content": "c"}]},
        )

    return handler


@pytest.mark.asyncio
async def test_the_same_query_twice_reaches_the_instance_once():
    calls: list[int] = []
    tool = build_search_tool(
        "http://searx.local", client=_client(_counting_handler(calls)), recall=Recall()
    )
    await tool.ainvoke({"query": "backward design"})
    await tool.ainvoke({"query": "backward design"})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_recalled_result_set_says_it_is_one():
    """Returning an earlier result set dressed as a fresh search would have
    the model reason about a snapshot as though it were current, with nothing
    in the transcript to show why.
    """
    calls: list[int] = []
    tool = build_search_tool(
        "http://searx.local", client=_client(_counting_handler(calls)), recall=Recall()
    )
    await tool.ainvoke({"query": "backward design"})
    again = await tool.ainvoke({"query": "backward design"})
    assert "searched" in again.lower()
    assert "https://ex.example/a" in again


@pytest.mark.asyncio
async def test_a_recalled_result_set_names_the_query_that_produced_it():
    """The safety net under normalization: a merge the agent cannot see is a
    wrong answer wearing a right one's label.
    """
    calls: list[int] = []
    tool = build_search_tool(
        "http://searx.local", client=_client(_counting_handler(calls)), recall=Recall()
    )
    await tool.ainvoke({"query": "Backward Design"})
    again = await tool.ainvoke({"query": "backward  design"})
    assert "Backward Design" in again


@pytest.mark.asyncio
async def test_a_different_query_is_a_different_search():
    calls: list[int] = []
    tool = build_search_tool(
        "http://searx.local", client=_client(_counting_handler(calls)), recall=Recall()
    )
    await tool.ainvoke({"query": "backward design"})
    await tool.ainvoke({"query": "design backward"})
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_a_failed_search_is_not_remembered():
    """Caching "could not reach the instance" would turn one outage into an
    hour of them, and the retry that would have worked never happens.
    """
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("down")
        return httpx.Response(
            200, json={"results": [{"title": "T", "url": "u", "content": "c"}]}
        )

    tool = build_search_tool("http://searx.local", client=_client(handler), recall=Recall())
    await tool.ainvoke({"query": "q"})
    second = await tool.ainvoke({"query": "q"})
    assert len(calls) == 2
    assert "T" in second


@pytest.mark.asyncio
async def test_a_malformed_payload_is_not_remembered():
    """A 200 with valid JSON that isn't a results object (a proxy error page
    serialized as JSON, say) doesn't raise -- `format_results` returns the
    malformed-payload message instead. That message must not be cached and
    served back as a recalled answer; the retry that would have succeeded
    never happens otherwise.
    """
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=[])

    tool = build_search_tool("http://searx.local", client=_client(handler), recall=Recall())
    await tool.ainvoke({"query": "q"})
    await tool.ainvoke({"query": "q"})
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_without_a_recall_every_search_reaches_the_instance():
    calls: list[int] = []
    tool = build_search_tool("http://searx.local", client=_client(_counting_handler(calls)))
    await tool.ainvoke({"query": "q"})
    await tool.ainvoke({"query": "q"})
    assert len(calls) == 2
