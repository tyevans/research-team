"""Web search, via a SearXNG instance.

The one tool in this system that leaves the process. It is registered only when
an instance is configured, and it is gated by the autonomy policy like the file
tools are -- both of which are what keep "nothing escapes" an accurate
statement about a default install rather than a fond memory.

Results are capped and flattened before they reach the model. An uncapped
result set is a context leak of exactly the kind the `elide` and `compact`
strategies exist to clean up afterwards, and it is cheaper not to make the mess.
"""

import httpx
from langchain_core.tools import BaseTool, tool

from research_team.application import SEARCH_TOOL
from research_team.infrastructure.agent.recall import Recall, describe_age

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


def format_recalled(recalled, query: str) -> str:
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


def build_search_tool(
    base_url: str,
    *,
    limit: int = 5,
    client: httpx.AsyncClient | None = None,
    recall: Recall | None = None,
) -> BaseTool:
    """A `web_search` tool against one SearXNG instance.

    `client` is injectable so tests can stub the transport; nothing in the
    suite touches the real network. `recall` is optional so callers that don't
    want the behavior (or Task 6's wiring, before it lands) still get a tool
    that works.
    """

    @tool(SEARCH_TOOL)
    async def web_search(query: str) -> str:
        """Search the web. Returns titles, URLs, and short snippets."""
        if recall is not None:
            remembered = recall.get(query)
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
            if recall is not None:
                # Only a result set is remembered. A transport failure cached
                # for an hour turns one outage into an hour of them, and the
                # retry that would have succeeded never happens.
                recall.put(query, results)
            return results
        except ValueError:
            # Not JSON. Overwhelmingly the default-settings case, and worth
            # naming precisely -- the model cannot fix it, but the person
            # reading the log can.
            return _JSON_DISABLED
        except httpx.HTTPError as error:
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
