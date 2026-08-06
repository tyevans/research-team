"""Reading one web page, as prose.

Search says a page exists; this reads it. Without it the agent's picture of
anything it did not already know is five snippets deep, which is enough to name
a source and never enough to cite one.

The second tool that leaves the process, and the one that does so at a URL the
model chose. So it is gated with a floor of `ask` rather than by configuration:
`web_search` can be withheld by not configuring a SearXNG instance, and there
is no equivalent switch for fetching an arbitrary address. See `TOOL_FLOORS`.

What comes back is main content, not a page. Boilerplate is most of a real
page's bytes and none of its meaning, and it would be recorded permanently in
the session log either way -- so the extraction happens here, before the text
is anything the rest of the system has to carry.
"""

from urllib.parse import urlsplit

import httpx
import trafilatura
from langchain_core.tools import BaseTool, tool
from trafilatura.metadata import extract_metadata

from research_team.application.autonomy import FETCH_TOOL

TIMEOUT = httpx.Timeout(15.0)

MAX_BYTES = 2_000_000
"""How much of a response body is parsed. Bounded because `lxml` on an
unbounded body is a way to lose a turn to a page nobody meant to fetch."""

MAX_CHARS = 20_000
"""How much extracted prose reaches the model. About five thousand tokens --
enough for a long article, short of the point where one page crowds out the
conversation it was fetched to inform."""

UNREADABLE = (
    "That URL returned no readable prose. Pages that render entirely in the "
    "browser, login walls, and pure-navigation pages all look like this. The "
    "page may exist and still not be readable this way."
)

_TRUNCATED = "\n\n[truncated -- the page continues beyond what was read]"

_HEADERS = {
    # Named honestly, and with somewhere to complain to. A server that refuses
    # this is refusing an agent, which is a decision it is entitled to make and
    # one we should not dress up by pretending to be a browser.
    #
    # The contact URL is not decoration: Wikimedia's User-Agent policy refuses
    # a UA without one, and a bare "research-team/0.1" gets a 403 from
    # en.wikipedia.org while this exact string gets a 200. Several large sites
    # apply the same rule. Identifying ourselves *more* specifically is what
    # buys access here, which is a happier state of affairs than usual.
    "User-Agent": (
        "research-team/0.1 (https://github.com/tyevans/research-team; agent fetch)"
    ),
    "Accept": "text/html,application/xhtml+xml",
}


def format_page(html: str, url: str, limit: int = MAX_CHARS) -> str:
    """Extract one page's main content as markdown, headed by its citation.

    Total by construction, like `format_results`: a server can send anything at
    all under a `text/html` content type, and an app shell that extracts to
    nothing is an ordinary thing for the web to be rather than an exception for
    the agent to reason about. Both arrive here as `None` from trafilatura and
    leave as the same sentence.

    The URL leads the output because the citation is the reason for fetching.
    Text that arrives without its address cannot be cited by anything
    downstream, and a model that has lost a source will confabulate one rather
    than say so.
    """
    text = trafilatura.extract(
        html,
        output_format="markdown",
        include_links=True,
        include_tables=True,
    )
    if not text or not text.strip():
        return UNREADABLE
    if len(text) > limit:
        text = text[:limit].rstrip() + _TRUNCATED
    return "\n\n".join(part for part in (_citation(html, url), text.strip()) if part)


def _citation(html: str, url: str) -> str:
    """A `url` line, plus title and date when the page offers them.

    Best-effort on purpose: metadata extraction reaches into a foreign
    document, and a page with no title is worth reading anyway. Anything it
    raises is treated as an absent title rather than a failed fetch.
    """
    title = date = None
    try:
        metadata = extract_metadata(html)
    except Exception:  # noqa: BLE001 - foreign parser; absent metadata is not a failure
        metadata = None
    if metadata is not None:
        title = (getattr(metadata, "title", None) or "").strip() or None
        date = (getattr(metadata, "date", None) or "").strip() or None
    lines = [f"url: {url}"]
    if title:
        lines.append(f"title: {title}")
    if date:
        lines.append(f"date: {date}")
    return "\n".join(lines)


def build_fetch_tool(
    *,
    max_chars: int = MAX_CHARS,
    max_bytes: int = MAX_BYTES,
    client: httpx.AsyncClient | None = None,
) -> BaseTool:
    """A `fetch` tool for reading one web page.

    `client` is injectable so tests can stub the transport; nothing in the
    suite touches the real network.
    """

    @tool(FETCH_TOOL)
    async def fetch(url: str) -> str:
        """Read one web page and return its main content as markdown text."""
        scheme = urlsplit(url).scheme.lower()
        if scheme not in ("http", "https"):
            # Refused before the transport rather than left to httpx. A scheme
            # it does not support today it might support tomorrow, and a fetch
            # tool that grew the ability to read local files would be a way
            # around the file tools -- and around the event log they write to.
            return (
                f"Only http and https URLs can be fetched; {scheme or 'that'} is not "
                "one. Use the file tools to read the workspace."
            )
        owned = client is None
        http = client or httpx.AsyncClient(
            timeout=TIMEOUT, follow_redirects=True, headers=_HEADERS
        )
        try:
            response = await http.get(url, headers=_HEADERS)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            media_type = content_type.split(";")[0].strip().lower()
            if media_type and "html" not in media_type and "xml" not in media_type:
                return (
                    f"That URL returned {media_type}, which this tool cannot read -- "
                    "it reads HTML pages. No text this time."
                )
            body = response.content[:max_bytes]
            truncated = len(response.content) > max_bytes
            html = body.decode(response.encoding or "utf-8", errors="replace")
            text = format_page(html, url, limit=max_chars)
            if truncated and text is not UNREADABLE and not text.endswith(_TRUNCATED):
                text += _TRUNCATED
            return text
        except httpx.HTTPStatusError as error:
            # The status is the actionable part: 404 means the URL is wrong,
            # 403 means this page will not be readable this way at all.
            return (
                f"Could not read that page: the server returned {error.response.status_code}."
            )
        except httpx.HTTPError as error:
            return f"Could not reach that page: {error}"
        except UnicodeError as error:
            return f"Could not decode that page: {error}"
        finally:
            if owned:
                await http.aclose()

    return fetch


FETCH_PROMPT = (
    "\n\nYou can read one web page with the `fetch` tool. It returns the "
    "page's main content as text, with the URL it came from -- keep that URL "
    "with anything you write down from the page, because it is the only "
    "record of where the claim came from.\n\n"
    "What it returns is a snapshot at the moment you fetched, recorded "
    "permanently in this session's log. Navigation, adverts and footers are "
    "stripped before you see them, so a page that reads as unexpectedly short "
    "may simply have had little to say. A page that renders in the browser -- "
    "an app shell, a login wall -- will come back empty however many times you "
    "ask; treat that as an answer rather than something to retry.\n\n"
    "Fetch when a search snippet is not enough to make a claim you would be "
    "willing to cite. Do not fetch a page you have already read this session, "
    "and do not fetch to confirm something the snippet already said plainly."
)
