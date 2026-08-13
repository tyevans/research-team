"""Web search, via a SearXNG instance.

The one tool in this system that leaves the process. It is registered only when
an instance is configured, and it is gated by the autonomy policy like the file
tools are -- both of which are what keep "nothing escapes" an accurate
statement about a default install rather than a fond memory.

Results are capped and flattened before they reach the model. An uncapped
result set is a context leak of exactly the kind the `elide` and `compact`
strategies exist to clean up afterwards, and it is cheaper not to make the mess.
"""

from contextvars import ContextVar
from dataclasses import dataclass

import httpx
from langchain_core.tools import BaseTool, tool

from research_team.application import SEARCH_TOOL
from research_team.infrastructure.agent.recall import Recall, Recalled, describe_age, query_key

TIMEOUT = httpx.Timeout(10.0)

_JSON_DISABLED = (
    "The SearXNG instance did not return JSON. Its JSON API is disabled by "
    "default -- the instance needs `formats: [json]` under `search:` in its "
    "settings.yml. No results this time."
)

_MALFORMED_PAYLOAD = (
    "The SearXNG instance returned JSON that was not a results object -- a "
    "misconfigured instance or a proxy error page can do this. No results "
    "this time."
)

MAX_EMPTY_SEARCHES = 3
"""Consecutive `"No results."` answers before `web_search` stops asking.

Not a floor and not a gate -- see `SearchAttempts`. The number is a guess at
where "still worth trying a different phrasing" turns into "this is not
findable," and it is cheap to change if the guess is wrong; nothing else
depends on the exact value.
"""


@dataclass
class _Counter:
    """One turn's streak of empty searches.

    A class and not an `int` on purpose -- see `SearchAttempts`.
    """

    empty: int = 0


class SearchAttempts:
    """How many consecutive searches this turn came back with nothing.

    Deliberately not a permission mechanism: it does not withhold `web_search`
    from the tool list the way `TOOL_FLOORS` withholds `fetch`, and nothing
    here touches the autonomy policy. It changes what the tool *returns* past
    the bound, which the model is free to act on or ignore -- the same shape
    `fetch`'s `UNREADABLE` notice uses for a page that will never render.

    Only `"No results."` counts. An unreachable instance, a non-JSON payload,
    or a malformed one is not an absent answer -- it is search failing to
    happen at all, and counting it would tell the model to record a gap
    (a claim that the search was tried and nothing was there) it has no
    evidence for. `build_search_tool` enforces this by comparing the result
    string, not by catching exceptions here.

    The instance is process-wide -- `build_application` constructs one for the
    one `web_search` tool the whole process shares -- but the *count* is not:
    it lives in a `ContextVar` that `SearchAttemptsMiddleware.begin_turn`
    refreshes before each turn's first model call, so two turns running
    concurrently hold two counts. The tool and its SearXNG client are still
    built once; only the counter is per-turn, which is the whole of what needs
    to be. `test_two_concurrent_turns_do_not_bound_each_other` fails if that
    stops being true.

    **What the var holds is a mutable counter, never a bare `int`, and that is
    load-bearing.** A child task copies its parent's context at spawn: a value
    set before the spawn is visible in the child, but a `set()` performed
    inside the child is invisible to the parent and to siblings. Storing a
    mutable object means the tool mutates state the middleware installed and
    can still see, whether or not langgraph runs a tool call in the same task
    as `before_agent`. Simplifying this to an integer would leave every test
    passing and lose the count on any turn whose tool calls run in child tasks.
    """

    def __init__(self) -> None:
        # One counter shared by every context that never had one installed:
        # a tool built without the middleware around it -- a test, or any
        # caller wiring the tool alone -- stays unbounded-per-process rather
        # than raising, exactly as it behaved when the count lived on the
        # instance. It is a field rather than the var's default because ruff's
        # B039 rejects mutable ContextVar defaults, and rightly: a default is
        # evaluated once and shared, which here is the intent but is the bug
        # everywhere else.
        self._unwired = _Counter()
        # Per-instance rather than module-level so two applications in one
        # process do not share a count.
        self._counter: ContextVar[_Counter | None] = ContextVar(
            f"search_attempts_{id(self):x}", default=None
        )

    def _current(self) -> _Counter:
        installed = self._counter.get()
        return self._unwired if installed is None else installed

    def begin_turn(self) -> None:
        """Install a fresh count for this turn.

        Distinct from `reset()`: `reset()` clears whatever counter this context
        can already see, which is what a productive search wants. This replaces
        it, so a turn cannot clear a concurrent turn's streak.
        """
        self._counter.set(_Counter())

    def record_empty(self) -> int:
        """One more consecutive empty result this turn; returns the new count."""
        counter = self._current()
        counter.empty += 1
        return counter.empty

    def reset(self) -> None:
        """Any non-empty result clears this turn's streak."""
        self._current().empty = 0

    def exhausted(self) -> bool:
        return self._current().empty >= MAX_EMPTY_SEARCHES


def format_results(payload: object, limit: int) -> str:
    """Flatten a SearXNG payload to title/url/snippet, capped at `limit`.

    Total by construction: an instance is a foreign system, and `response.json()`
    only promises valid JSON, not a dict shaped the way SearXNG's docs say --
    a proxy error page rendered as JSON, or a future API change, can hand back
    a list, a string, or null just as easily. A missing key inside a well-formed
    payload is an ordinary thing for a search instance to send, not an exception
    for the agent to reason about; a payload that isn't a dict at all gets the
    same treatment, not a crash.
    """
    if not isinstance(payload, dict):
        return _MALFORMED_PAYLOAD
    results = payload.get("results") or []
    chosen = results[:limit]
    if not chosen:
        return "No results."
    blocks = []
    for result in chosen:
        # Every field is normalized to a non-empty placeholder: a blank line
        # inside a block, from an empty url or snippet, would read as a block
        # separator to anything counting on the "\n\n" join below.
        title = str(result.get("title", "")).strip() or "(untitled)"
        url = str(result.get("url", "")).strip() or "(no url)"
        snippet = " ".join(str(result.get("content", "")).split()) or "(no snippet)"
        blocks.append(f"{title}\n{url}\n{snippet}")
    return "\n\n".join(blocks)


def format_recalled(recalled: Recalled, query: str) -> str:
    """An earlier result set, labelled with when and for what.

    Names the query that produced the entry rather than the one just asked,
    because normalization means they need not be identical. A model that can
    see the difference can ask again; one that cannot would take results for a
    neighbouring question as answering its own.
    """
    asked = "" if recalled.asked == query else f" for {recalled.asked!r}"
    return (
        f"[recalled -- searched{asked} {describe_age(recalled.age_seconds)} in this "
        f"process, not a fresh search]\n\n{recalled.text}"
    )


def _exhausted_notice(count: int) -> str:
    """What `web_search` says instead of searching, past the bound.

    Names the count so the number in the notice always matches
    `MAX_EMPTY_SEARCHES` even if that constant changes, and names
    `record_gap` explicitly -- the tool the model should reach for is not
    something it should have to infer from "stop searching."
    """
    return (
        f"web_search has returned no results {count} times in a row this turn. "
        "Searching again is unlikely to find something the last "
        f"{count} attempts did not. If you looked and did not find it, call "
        "`record_gap` to say so rather than searching again."
    )


def build_search_tool(
    base_url: str,
    *,
    limit: int = 5,
    client: httpx.AsyncClient | None = None,
    recall: Recall | None = None,
    attempts: SearchAttempts | None = None,
) -> BaseTool:
    """A `web_search` tool against one SearXNG instance.

    `client` is injectable so tests can stub the transport; nothing in the
    suite touches the real network. `recall` is optional so callers that don't
    want the behavior (or Task 6's wiring, before it lands) still get a tool
    that works. `attempts` is likewise optional -- nothing wires it into the
    application yet; that is Task 6.
    """

    @tool(SEARCH_TOOL)
    async def web_search(query: str) -> str:
        """Search the web. Returns titles, URLs, and short snippets."""
        if attempts is not None and attempts.exhausted():
            # Past the bound, the request is never made -- the whole point is
            # that another search would not help, so there is nothing to gain
            # by spending the round trip to confirm it.
            return _exhausted_notice(MAX_EMPTY_SEARCHES)
        if recall is not None:
            # Keyed explicitly rather than through `Recall`'s default, which
            # would key on the bare normalized query and collide with `fetch`'s
            # URL keys. See `query_key`.
            remembered = recall.get(query, key=query_key(query))
            if remembered is not None:
                return format_recalled(remembered, query)
        owned = client is None
        http = client or httpx.AsyncClient(timeout=TIMEOUT)
        try:
            response = await http.get(
                f"{base_url}/search",
                params={"q": query, "format": "json"},
            )
            response.raise_for_status()
            payload = response.json()
            results = format_results(payload, limit)
            if attempts is not None:
                # Only the literal "No results." counts as an empty answer --
                # everything else that reaches this line (a genuine result
                # set, or the malformed-payload sentinel handled below) is not
                # evidence that nothing is out there.
                if results == "No results.":
                    attempts.record_empty()
                else:
                    attempts.reset()
            if recall is not None and results is not _MALFORMED_PAYLOAD:
                # Only a genuine result set is remembered -- and "No results."
                # counts as one; it's an answer, not a failure. A 200 with a
                # malformed body (a proxy error page serialized as JSON, say)
                # doesn't raise, so `format_results` returns this sentinel by
                # identity rather than a fresh string each time; caching it
                # would serve the same "not a results object" message back as
                # a *recalled* answer for up to an hour, and the retry that
                # would have succeeded never happens -- the same failure this
                # transport-error guard exists to prevent, reached by a path
                # that never raises.
                recall.put(query, results, key=query_key(query))
            return results
        except ValueError:
            # Not JSON. Overwhelmingly the default-settings case, and worth
            # naming precisely -- the model cannot fix it, but the person
            # reading the log can. Not counted: the instance never answered
            # the question, so this is not evidence of an absent result.
            return _JSON_DISABLED
        except httpx.HTTPError as error:
            # Unreachable, not empty -- an outage is not the model having
            # looked and found nothing, and must not be counted as if it were.
            return f"Could not reach the search instance: {error}"
        finally:
            if owned:
                await http.aclose()

    return web_search


SEARCH_PROMPT = (
    "\n\nYou can search the web with the `web_search` tool. What it returns is "
    "a snapshot at the moment you searched, recorded permanently in this "
    "session's log -- not a live view you can refresh by asking again. Asking "
    "the same question twice returns the first answer, marked as recalled and "
    "naming the query it came from; if that query is not the one you meant, "
    "ask a different one rather than the same one again. If a search is "
    "refused, that refusal is your answer for this turn.\n\n"
    "Search when your own knowledge is stale or thin for the question at "
    "hand, not reflexively on every question you could plausibly answer "
    "yourself -- each search is a real request against a real instance, not a "
    "free way to double-check."
)
