"""Recall and query memoization tests for the search tool against stubbed transports."""

import httpx
import pytest

from research_team.infrastructure.agent.recall import Recall
from research_team.infrastructure.agent.search import build_search_tool

PAYLOAD = {
    "results": [
        {"title": "Event sourcing", "url": "https://a.example", "content": "A log."},
        {"title": "CQRS", "url": "https://b.example", "content": "Two models."},
        {"title": "Third", "url": "https://c.example", "content": "Extra."},
    ]
}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


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


# ---------------- engines, categories, time_range ----------------


def _recording_handler(seen: list[httpx.QueryParams]):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params)
        return httpx.Response(200, json=PAYLOAD)

    return handler


async def test_a_search_with_no_parameters_sends_exactly_what_it_always_sent():
    """The unparameterised call is the overwhelming majority of searches and
    is the one path a real instance is known to work against. This fails if
    an unset parameter is sent empty rather than omitted -- which is not a
    cosmetic difference: SearXNG reads an empty `time_range` and an absent one
    differently.
    """
    seen: list[httpx.QueryParams] = []
    tool = build_search_tool("http://searx.local", client=_client(_recording_handler(seen)))
    await tool.ainvoke({"query": "event sourcing"})

    assert dict(seen[0]) == {"q": "event sourcing", "format": "json"}


async def test_the_parameters_reach_the_instance_when_a_call_supplies_them():
    seen: list[httpx.QueryParams] = []
    tool = build_search_tool("http://searx.local", client=_client(_recording_handler(seen)))
    await tool.ainvoke(
        {
            "query": "q",
            "engines": "arxiv",
            "categories": "science",
            "time_range": "year",
        }
    )

    assert dict(seen[0]) == {
        "q": "q",
        "format": "json",
        "engines": "arxiv",
        "categories": "science",
        "time_range": "year",
    }


async def test_an_instance_default_applies_to_a_call_that_names_nothing():
    seen: list[httpx.QueryParams] = []
    tool = build_search_tool(
        "http://searx.local",
        client=_client(_recording_handler(seen)),
        categories="science",
    )
    await tool.ainvoke({"query": "q"})

    assert seen[0]["categories"] == "science"


async def test_a_call_overrides_the_instance_default():
    """The default is a starting point, not a policy: a deployment aimed at
    scholarly work still has to let one question reach the news."""
    seen: list[httpx.QueryParams] = []
    tool = build_search_tool(
        "http://searx.local",
        client=_client(_recording_handler(seen)),
        categories="science",
        time_range="year",
    )
    await tool.ainvoke({"query": "q", "categories": "news"})

    assert seen[0]["categories"] == "news"
    # The parameter the call said nothing about keeps the default rather than
    # being cleared by the override of its neighbour.
    assert seen[0]["time_range"] == "year"


def _distinguishing_handler(calls: list[str]):
    """Answers differently depending on `time_range`, as a real instance does.

    The whole point of the parameter is that the answer changes; a stub that
    returned the same payload either way could not tell a correct memo from a
    colliding one.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        window = request.url.params.get("time_range", "all")
        calls.append(window)
        return httpx.Response(
            200,
            json={"results": [{"title": f"result-{window}", "url": "u", "content": "c"}]},
        )

    return handler


async def test_a_time_range_does_not_hit_the_unrestricted_memo():
    """The failure this test exists for is not a wasted request; it is a wrong
    answer wearing a right one's label. Against a key of the query alone the
    second call never leaves the process and comes back with `result-all`,
    marked as recalled and therefore trusted, for a question that asked for
    the last year.
    """
    calls: list[str] = []
    tool = build_search_tool(
        "http://searx.local", client=_client(_distinguishing_handler(calls)), recall=Recall()
    )
    await tool.ainvoke({"query": "backward design"})
    second = await tool.ainvoke({"query": "backward design", "time_range": "year"})

    # Asserted before the call log on purpose: the defect is the answer, not
    # the saved request, and this is the line that names it.
    assert "result-all" not in second
    assert "result-year" in second
    assert calls == ["all", "year"]


@pytest.mark.parametrize(
    "params",
    [
        {"time_range": "year"},
        {"engines": "arxiv"},
        {"categories": "science"},
    ],
)
async def test_each_parameter_keeps_its_search_apart_from_the_unrestricted_one(params):
    calls: list[int] = []
    tool = build_search_tool(
        "http://searx.local", client=_client(_counting_handler(calls)), recall=Recall()
    )
    await tool.ainvoke({"query": "backward design"})
    await tool.ainvoke({"query": "backward design", **params})

    assert len(calls) == 2


async def test_the_same_parameterised_search_twice_still_reaches_the_instance_once():
    """Extending the key must not disable recall for parameterised searches --
    that would be a memo that only works for the case it was already working
    for.
    """
    calls: list[int] = []
    tool = build_search_tool(
        "http://searx.local", client=_client(_counting_handler(calls)), recall=Recall()
    )
    await tool.ainvoke({"query": "q", "time_range": "year"})
    await tool.ainvoke({"query": "q", "time_range": "year"})

    assert len(calls) == 1


async def test_an_instance_default_is_part_of_the_key_a_call_is_stored_under():
    """The default reaches the instance, so it must reach the key too. Two
    tools with different defaults are two different searches for the same
    words -- and a per-call argument matching the default must find the memo
    the defaulted call left.
    """
    calls: list[str] = []
    recall = Recall()
    defaulted = build_search_tool(
        "http://searx.local",
        client=_client(_distinguishing_handler(calls)),
        recall=recall,
        time_range="year",
    )
    plain = build_search_tool(
        "http://searx.local", client=_client(_distinguishing_handler(calls)), recall=recall
    )

    await defaulted.ainvoke({"query": "q"})
    await plain.ainvoke({"query": "q"})
    await plain.ainvoke({"query": "q", "time_range": "year"})

    assert calls == ["year", "all"]
