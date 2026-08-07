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
from research_team.application.corpus_read import CorpusReadError, CorpusReadPort
from research_team.infrastructure.agent.corpus_tools import bounded, format_document
from research_team.infrastructure.agent.recall import Recall, describe_age, normalize_url

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


async def stored_page(corpus: CorpusReadPort, url: str, max_chars: int) -> str | None:
    """This page as the corpus already holds it, or None.

    Matched on `normalize_url` rather than on the stored string, so a URL that
    differs only in scheme case, a default port or a fragment is recognised as
    the same page. Scanning `list_documents` is O(corpus) per call; a corpus
    holds hundreds of records at most and the scan is a local read-model
    query, so an index would be machinery bought against a cost nobody has
    measured.

    A storage failure returns None rather than propagating. The corpus is an
    optimisation on this path, and an optimisation that can break the
    operation it accelerates is not one -- a Neo4j outage should cost a
    redundant fetch, not the page.
    """
    target = normalize_url(url)
    try:
        records = await corpus.list_documents()
    except CorpusReadError:
        return None
    match = next(
        (record for record in records if record.uri and normalize_url(record.uri) == target),
        None,
    )
    if match is None:
        return None
    try:
        document = await corpus.read_document(match.source_id)
    except CorpusReadError:
        return None
    if document is None:
        # Listed and then unreadable: a drop landed between the two calls.
        return None
    span = bounded(document.text, None, None, max_chars)
    return (
        "[recalled -- this page is already in this project's corpus, so it was "
        "not fetched again. Quote it from here; the offsets below are real.]\n\n"
        + format_document(document, span)
    )


def build_fetch_tool(
    *,
    max_chars: int = MAX_CHARS,
    max_bytes: int = MAX_BYTES,
    client: httpx.AsyncClient | None = None,
    recall: Recall | None = None,
    corpus: CorpusReadPort | None = None,
) -> BaseTool:
    """A `fetch` tool for reading one web page.

    `client` is injectable so tests can stub the transport; nothing in the
    suite touches the real network.
    """

    @tool(FETCH_TOOL)
    async def fetch(url: str, refresh: bool = False) -> str:
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
        if not refresh:
            # Corpus before memo: both avoid the request, and only one comes
            # back with offsets a claim can cite.
            if corpus is not None:
                found = await stored_page(corpus, url, max_chars)
                if found is not None:
                    return found
            if recall is not None:
                remembered = recall.get(url, key=normalize_url(url))
                if remembered is not None:
                    return (
                        f"[recalled -- read {describe_age(remembered.age_seconds)} in "
                        f"this process, not a fresh read. Pass refresh=True if the "
                        f"page is expected to have changed since.]\n\n{remembered.text}"
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
            if recall is not None and text is not UNREADABLE:
                # Only a page that was actually read. Remembering a failure
                # would turn one outage into an hour of them, and remembering
                # UNREADABLE would pin "this renders in the browser" for an
                # hour after a deploy fixed it.
                recall.put(url, text, key=normalize_url(url))
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
    "willing to cite, and not to confirm something the snippet already said "
    "plainly.\n\n"
    "You do not have to track what you have already read. A page this project "
    "has stored comes back from the corpus, with the offsets that make it "
    "quotable; a page read earlier in this process comes back as it was, "
    "marked as recalled and dated. Both say so plainly. If a page is expected "
    "to have changed since -- a changelog, a status page, a document revised "
    "during this run -- pass `refresh=True` and it will be read again. Do not "
    "pass it merely to be sure.\n\n"
    "When a fetched page is worth keeping, pass it to `remember` along with "
    "the `url:`, `title:` and `date:` lines printed above it. That is what "
    "lets a later session recognise the page instead of fetching it again."
)
