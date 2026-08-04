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

TIMEOUT = httpx.Timeout(10.0)

_JSON_DISABLED = (
    "The SearXNG instance did not return JSON. Its JSON API is disabled by "
    "default -- the instance needs `formats: [json]` under `search:` in its "
    "settings.yml. No results this time."
)


def format_results(payload: dict, limit: int) -> str:
    """Flatten a SearXNG payload to title/url/snippet, capped at `limit`.

    Total by construction: an instance is a foreign system and a missing key is
    an ordinary thing for one to return, not an exception for the agent to
    reason about.
    """
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


def build_search_tool(
    base_url: str,
    *,
    limit: int = 5,
    client: httpx.AsyncClient | None = None,
) -> BaseTool:
    """A `web_search` tool against one SearXNG instance.

    `client` is injectable so tests can stub the transport; nothing in the
    suite touches the real network.
    """

    @tool(SEARCH_TOOL)
    async def web_search(query: str) -> str:
        """Search the web. Returns titles, URLs, and short snippets."""
        owned = client is None
        http = client or httpx.AsyncClient(timeout=TIMEOUT)
        try:
            response = await http.get(
                f"{base_url}/search",
                params={"q": query, "format": "json"},
            )
            response.raise_for_status()
            payload = response.json()
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
        return format_results(payload, limit)

    return web_search
