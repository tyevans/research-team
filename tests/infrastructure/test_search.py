"""The search tool, against a stubbed transport.

No test here reaches the network. The live test lives behind the `live`
marker, like the model tests do.
"""

import asyncio

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from research_team.infrastructure.agent.recall import Recall
from research_team.infrastructure.agent.search import (
    MAX_EMPTY_SEARCHES,
    SearchAttempts,
    build_search_tool,
    format_results,
)
from research_team.infrastructure.agent.search_middleware import SearchAttemptsMiddleware

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


# ---------------- bounding empty searches ----------------


def _empty_handler(calls: list[int]):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"results": []})

    return handler


async def test_search_stops_after_repeated_empty_results() -> None:
    """Not a permission change: the agent is allowed to search. It is being
    told that searching again will not help, in the shape `fetch` already uses
    for a page that will never render."""
    calls: list[int] = []
    attempts = SearchAttempts()
    tool = build_search_tool(
        "http://searx.local", client=_client(_empty_handler(calls)), attempts=attempts
    )
    for _ in range(MAX_EMPTY_SEARCHES):
        result = await tool.ainvoke({"query": "q"})
        assert result == "No results."

    # One more, past the bound: no request is made, and the notice names both
    # the count and the tool to reach for instead.
    result = await tool.ainvoke({"query": "q"})
    assert len(calls) == MAX_EMPTY_SEARCHES
    assert str(MAX_EMPTY_SEARCHES) in result
    assert "record_gap" in result


async def test_the_counter_resets_on_any_result() -> None:
    """An intermittently productive search is never bounded."""
    responses = iter(
        [
            httpx.Response(200, json={"results": []}),
            httpx.Response(200, json={"results": []}),
            httpx.Response(200, json=PAYLOAD),
            httpx.Response(200, json={"results": []}),
            httpx.Response(200, json={"results": []}),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    attempts = SearchAttempts()
    tool = build_search_tool("http://searx.local", client=_client(handler), attempts=attempts)
    for _ in range(5):
        result = await tool.ainvoke({"query": "q"})

    # Never crossed MAX_EMPTY_SEARCHES consecutive misses, so the last call
    # still reached the instance rather than returning the bound notice.
    assert result == "No results."


def test_the_counter_resets_at_the_turn_boundary() -> None:
    """A turn does not inherit the previous turn's misses."""
    attempts = SearchAttempts()
    for _ in range(MAX_EMPTY_SEARCHES):
        attempts.record_empty()
    assert attempts.exhausted()

    middleware = SearchAttemptsMiddleware(attempts)
    assert middleware.name == "search_attempts"
    middleware.before_agent({})

    assert not attempts.exhausted()


def test_the_bound_does_not_touch_the_autonomy_policy() -> None:
    """B24 rejects counting as a permission mechanism by name. This test fails
    if the bound is ever implemented as a gate."""
    from research_team.application.autonomy import TOOL_FLOORS

    assert TOOL_FLOORS == {"fetch": "ask", "advance_stage": "ask"}


async def test_two_concurrent_turns_do_not_bound_each_other() -> None:
    """The claim the whole per-turn contract rests on.

    One `SearchAttempts`, one tool and one middleware -- exactly the
    process-wide wiring `build_application` produces -- driven by two asyncio
    tasks. The events pin the interleaving so the failure is deterministic
    rather than a race: both turns start, then turn A exhausts its streak,
    then turn B searches for the first time in its own turn.

    Against a counter held on the instance this fails on B's assertion: A's
    three empty searches bound B, and B is handed the notice instead of a
    result. It passes only if each turn's count lives in its own context.
    """
    attempts = SearchAttempts()
    middleware = SearchAttemptsMiddleware(attempts)
    calls: list[int] = []
    tool = build_search_tool(
        "http://searx.local", client=_client(_empty_handler(calls)), attempts=attempts
    )

    a_started = asyncio.Event()
    b_started = asyncio.Event()
    a_exhausted = asyncio.Event()

    async def turn_a() -> str:
        middleware.before_agent({})
        a_started.set()
        await b_started.wait()
        for _ in range(MAX_EMPTY_SEARCHES):
            await tool.ainvoke({"query": "a"})
        a_exhausted.set()
        return await tool.ainvoke({"query": "a"})

    async def turn_b() -> str:
        await a_started.wait()
        middleware.before_agent({})
        b_started.set()
        await a_exhausted.wait()
        return await tool.ainvoke({"query": "b"})

    a_result, b_result = await asyncio.gather(turn_a(), turn_b())

    # A tried three times and nothing was there, so A is told to stop.
    assert "record_gap" in a_result
    # B has tried nothing. Its first search must reach the instance.
    assert b_result == "No results."


async def test_a_turn_starts_at_zero_however_the_last_one_ended() -> None:
    """`before_agent` installs a fresh count rather than decrementing or
    trusting whatever the previous turn left behind. Reverting the middleware
    to a no-op fails this on the second turn's first search."""
    attempts = SearchAttempts()
    middleware = SearchAttemptsMiddleware(attempts)
    calls: list[int] = []
    tool = build_search_tool(
        "http://searx.local", client=_client(_empty_handler(calls)), attempts=attempts
    )

    middleware.before_agent({})
    for _ in range(MAX_EMPTY_SEARCHES):
        await tool.ainvoke({"query": "q"})
    assert "record_gap" in await tool.ainvoke({"query": "q"})

    middleware.before_agent({})
    assert await tool.ainvoke({"query": "q"}) == "No results."


def test_exhausted_turns_true_exactly_at_the_bound() -> None:
    """Off-by-one guard: the notice must not fire one search early, which
    would tell a model to give up while a phrasing it has not tried remains."""
    attempts = SearchAttempts()
    for _ in range(MAX_EMPTY_SEARCHES - 1):
        attempts.record_empty()
    assert not attempts.exhausted()
    attempts.record_empty()
    assert attempts.exhausted()


async def test_a_tool_built_without_middleware_still_counts() -> None:
    """`build_search_tool` is reachable without the agent around it -- tests,
    and any caller wiring the tool alone. That path never calls `before_agent`,
    so it depends on the var's default existing. It is unbounded-per-process
    rather than raising, which is what it was before the count moved."""
    attempts = SearchAttempts()
    calls: list[int] = []
    tool = build_search_tool(
        "http://searx.local", client=_client(_empty_handler(calls)), attempts=attempts
    )
    for _ in range(MAX_EMPTY_SEARCHES):
        assert await tool.ainvoke({"query": "q"}) == "No results."
    assert "record_gap" in await tool.ainvoke({"query": "q"})


async def test_errors_are_not_counted() -> None:
    """An unreachable instance or a malformed payload is not an absent
    answer -- counting it would tell the model to record a gap it has no
    evidence for."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    attempts = SearchAttempts()
    tool = build_search_tool("http://searx.local", client=_client(handler), attempts=attempts)
    for _ in range(MAX_EMPTY_SEARCHES + 2):
        await tool.ainvoke({"query": "q"})

    assert not attempts.exhausted()
