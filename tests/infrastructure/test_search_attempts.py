"""Tests for search attempt bounding and per-turn counter behavior."""

import asyncio

import httpx

from research_team.infrastructure.agent.search import (
    MAX_EMPTY_SEARCHES,
    SearchAttempts,
    build_search_tool,
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


async def test_a_productive_search_is_never_bounded() -> None:
    """An intermittently productive search is not bounded at all.

    This is the deliberate consequence of removing `MAX_SEARCHES_PER_TURN` on
    2026-08-21: alternating hit-and-miss can search as long as the model keeps
    asking, and only a run of three consecutive empties stops it. The cost is
    stated rather than hidden -- a turn that never finds a settling answer can
    keep spending requests -- and is accepted because the bound that prevented
    it also cut a research round off at three searches.
    """
    responses = iter(
        [
            httpx.Response(200, json={"results": []}),
            httpx.Response(200, json={"results": []}),
            httpx.Response(200, json=PAYLOAD),
            httpx.Response(200, json={"results": []}),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    attempts = SearchAttempts()
    tool = build_search_tool("http://searx.local", client=_client(handler), attempts=attempts)
    for _ in range(3):
        await tool.ainvoke({"query": "q"})

    # The streak is clear -- the third call returned results -- so nothing
    # about `MAX_EMPTY_SEARCHES` is in play at the fourth, and nothing else
    # bounds it either: the fourth search is answered by the instance.
    assert attempts.exhausted() is False
    assert await tool.ainvoke({"query": "q"}) == "No results."
    assert attempts.exhausted() is False


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
    if the bound is ever implemented as a gate.

    Asserts `SEARCH_TOOL`'s absence from `TOOL_FLOORS`, not the dict's exact
    contents: the claim here is specifically about the search bound, and an
    exact-equality literal would fail every time an unrelated tool (most
    recently `fetch_media`) gained a floor of its own -- a change this test
    has no opinion about and should not need editing for.
    """
    from research_team.session.application.autonomy import SEARCH_TOOL, TOOL_FLOORS

    assert SEARCH_TOOL not in TOOL_FLOORS


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
    evidence for.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    attempts = SearchAttempts()
    tool = build_search_tool("http://searx.local", client=_client(handler), attempts=attempts)
    for _ in range(MAX_EMPTY_SEARCHES + 2):
        await tool.ainvoke({"query": "q"})

    assert not attempts.exhausted()


async def test_a_turn_may_search_as_many_times_as_it_likes() -> None:
    """No per-turn total bounds a productive search.

    Ten is not a threshold -- it is comfortably past the three that
    `MAX_SEARCHES_PER_TURN` allowed, so this fails loudly if any per-turn
    budget comes back. Every call must reach the instance.
    """
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=PAYLOAD)

    attempts = SearchAttempts()
    tool = build_search_tool("http://searx.local", client=_client(handler), attempts=attempts)
    for index in range(10):
        # A different query each time: `Recall` would otherwise serve the
        # repeats and the assertion would pass without any of them reaching
        # the instance.
        assert "No results." not in await tool.ainvoke({"query": f"q{index}"})

    assert len(calls) == 10
