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
from research_team.application.grants import FetchGrant
from research_team.infrastructure.agent.corpus_tools import bounded, format_document
from research_team.infrastructure.agent.recall import (
    PageMemo,
    Recall,
    describe_age,
    normalize_url,
    url_key,
)

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


def extract_page(html: str, url: str) -> tuple[str, str | None, str | None] | None:
    """One page's main content and metadata, or None when there is no prose.

    Split out of `format_page` so the text kept for `remember_page` and the
    text shown to the model come from a single extraction. Two extractions
    would eventually disagree, and the disagreement would surface as a corpus
    document that does not match the citation the model was reading from.

    Metadata is best-effort for `_citation`'s original reason: it reaches into
    a foreign document, and a page with no title is worth reading anyway.
    """
    text = trafilatura.extract(
        html,
        output_format="markdown",
        include_links=True,
        include_tables=True,
    )
    if not text or not text.strip():
        return None
    title = date = None
    try:
        metadata = extract_metadata(html)
    except Exception:  # noqa: BLE001 - foreign parser; absent metadata is not a failure
        metadata = None
    if metadata is not None:
        title = (getattr(metadata, "title", None) or "").strip() or None
        date = (getattr(metadata, "date", None) or "").strip() or None
    return text.strip(), title, date


def _citation(url: str, title: str | None, date: str | None) -> str:
    """A `url` line, plus title and date when the page offered them.

    The URL leads the output because the citation is the reason for fetching.
    Text that arrives without its address cannot be cited by anything
    downstream, and a model that has lost a source will confabulate one rather
    than say so.
    """
    lines = [f"url: {url}"]
    if title:
        lines.append(f"title: {title}")
    if date:
        lines.append(f"date: {date}")
    return "\n".join(lines)


def truncate_page(citation: str, text: str, limit: int) -> str:
    """A citation plus as much of `text` as fits under `limit`, marked if cut.

    Silent truncation is worse than visible truncation: the model would
    reason about a partial page believing it had the whole one.
    """
    if len(text) > limit:
        text = text[:limit].rstrip() + _TRUNCATED
    return "\n\n".join(part for part in (citation, text) if part)


def format_page(html: str, url: str, limit: int = MAX_CHARS) -> str:
    """Extract one page's main content as markdown, headed by its citation.

    Total by construction: a server can send anything at all under a
    `text/html` content type, and an app shell that extracts to nothing is an
    ordinary thing for the web to be rather than an exception for the agent to
    reason about. Both arrive here as `None` from `extract_page` and leave as
    the same sentence.
    """
    extracted = extract_page(html, url)
    if extracted is None:
        return UNREADABLE
    text, title, date = extracted
    return truncate_page(_citation(url, title, date), text, limit)


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

    Checked before the memo, which has a consequence worth knowing: after a
    `refresh=True` read of a page that is also in the corpus, the next plain
    call hits the corpus again and returns the older stored copy, not the
    fresh one -- the fresh read is visible only on the turn that asked for
    it, until something re-stores it. That follows from "corpus before
    memo" and is intended, but it is the one place the ordering surprises a
    reader.
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
    pages: PageMemo | None = None,
    grant: FetchGrant | None = None,
) -> BaseTool:
    """A `fetch` tool for reading one web page.

    `client` is injectable so tests can stub the transport; nothing in the
    suite touches the real network. `pages` retains the whole extraction
    (rather than the `max_chars` excerpt the model is shown) so a later
    `remember_page` can store more of a page than the model ever had to
    retype.

    `grant` is the pre-authorization an unattended run was given (see
    `application/grants.py`). It changes two things, both load-bearing:

    - The owned client stops following redirects, for *every* call made
      while a grant is attached to this tool -- not only ones the grant
      covers. See the spend note below for why coverage and redirect
      handling are not the same switch. A declined redirect is reported in
      band with the location it named, so the model can fetch that URL
      itself if a covered call would reach it.
    - A request that leaves the process spends one from the grant, but only
      when `grant.covers(url)` is true *at the moment the response comes
      back* -- i.e. the grant is what let this specific call through, not
      merely that a grant object exists. This is Fix 1: the approval gate
      (a different task) lets a *covered* fetch through without asking, and
      refers everything else -- including a fetch whose host was never
      granted -- to a human. When that human approves an out-of-scope fetch,
      the call reaches this tool with a grant attached but not covering it,
      and spending in that case would silently drain a budget the grantor
      scoped to specific hosts using an approval that was never the grant's
      to charge. `covers()` folds the budget check in too (a spent grant
      covers nothing), so this single condition also keeps a request from
      spending past zero. A corpus hit and a memo hit never reach this
      check at all, so neither spends regardless of coverage; an httpx
      error or an HTTP error status also does not spend, because nothing was
      learned that a retry couldn't also fail to learn -- only a response
      that actually came back, for a call the grant covered, counts.

    This makes the host check appear twice -- once in the gate, once here --
    for two different questions. The gate asks "may this call proceed
    without waking a person up?" This tool asks "was the grant, specifically,
    what authorized the call that already happened?" They read the same
    `hosts` set but answer at different moments for different purposes (before
    the call decides whether to ask; after it decides whether to charge), and
    collapsing them into one shared check would either make the gate spend
    budget it hasn't yet confirmed a human didn't already authorize, or make
    this tool's spend depend on gate internals it has no access to. Do not
    refactor them together.

    A grant that is spent, or that simply does not cover this URL, no longer
    causes the tool to refuse outright (an earlier version of this code did,
    and that was a bug fixed in the same change that added the `covers()`
    check above: a human who approves a fetch the grant does not cover is
    the mechanism working as designed, and refusing that fetch here would
    override an approval nobody asked this tool to second-guess). The tool
    only ever declines to *spend*; it never declines to *fetch* on the
    grant's account. Whether the fetch happens at all is decided once, at
    the gate.

    This tool's `covers(url)` and the gate's `covers(url)` (a different
    call, in `approval.py`, made before this tool ever runs) are NOT
    guaranteed to observe the same `remaining` count. Both calls read the
    same `FetchGrant`, but the gate evaluates every `fetch` call in one
    model message before any of them runs, and this tool's own check
    happens after an `await http.get(...)` that the gate's check never
    waited on -- so N covered calls dispatched in a single message can all
    see the gate's "not yet spent" answer, all leave the process, and all
    reach this `covers()` check before any of their `spend()`s has landed.
    The result is at most N requests beyond the budget in one batch, N being
    a number the model chooses by how many `fetch` calls it puts in one
    message -- not unbounded across a run, because `spend()` still floors
    `remaining` at zero and every subsequent call is refused at the gate
    once it is. The *scope* holds regardless: every one of those N calls
    still had to pass `covers()`'s host check, so this is an accounting gap
    in the count, not a hole in which hosts are reachable. Closing it needs
    a reservation taken at the gate before it decides not to interrupt, with
    this tool consuming the reservation instead of a fresh check -- a change
    to the gate/`FetchGrant` seam this task does not own. Tracked as a
    follow-up against the gate (Task 3's `approval.py`) and its wiring
    (Task 7), not fixed here.
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
                remembered = recall.get(url, key=url_key(url))
                if remembered is not None:
                    return (
                        f"[recalled -- read {describe_age(remembered.age_seconds)} in "
                        f"this process, not a fresh read. Pass refresh=True if the "
                        f"page is expected to have changed since.]\n\n{remembered.text}"
                    )
        owned = client is None
        http = client or httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=grant is None,
            headers=_HEADERS,
        )
        try:
            response = await http.get(url, headers=_HEADERS)
            if response.is_redirect:
                # Checked before `raise_for_status()`: with redirects off, a
                # 3xx with a Location is exactly what `raise_for_status`
                # treats as an error (`HTTPStatusError` naming the location
                # itself), which would fall into the "error, don't spend"
                # branch below -- wrong, because the GET still left the
                # process and got an answer. Spent and reported here instead,
                # before that branch ever sees it -- and only if the grant is
                # what authorized *this* call (Fix 1: see the docstring).
                if grant is not None and grant.covers(url):
                    grant.spend()
                location = response.headers.get("location", "(no Location header)")
                # Worded to be true whether or not `grant` is set: in
                # production this branch is unreachable without one (the
                # ungranted owned client has follow_redirects=True, so httpx
                # resolves 3xx before this tool ever sees a response), but an
                # injected client -- every test in this file uses one -- can
                # still hand back a 3xx regardless of `grant`, and a message
                # that named "a granted fetch" would be false in that case.
                return (
                    f"That URL redirected to {location}, which was not followed. "
                    "Fetch that URL directly if you still want it."
                )
            response.raise_for_status()
            if grant is not None and grant.covers(url):
                # Spent here, not at `http.get()`: an HTTPStatusError is
                # raised by `raise_for_status()`, one line above, and an
                # error is not a use of the budget (see the docstring). A
                # request that gets this far actually left the process and
                # came back with a usable response -- and `covers(url)` is
                # what confirms the grant, not a human approval, is who
                # authorized it.
                grant.spend()
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
            extracted = extract_page(html, url)
            if extracted is None:
                return UNREADABLE
            full, title, date = extracted
            if pages is not None:
                # The whole extraction, not the excerpt below it. `max_chars`
                # is what one page may cost the conversation; it was never
                # meant to be what the corpus can hold, and was only ever that
                # because a document could not reach the corpus except through
                # the model's own output.
                pages.put(url, text=full, uri=url, title=title, published_at=date)
            shown = full
            if len(shown) > max_chars:
                shown = shown[:max_chars].rstrip() + _TRUNCATED
            text = "\n\n".join(part for part in (_citation(url, title, date), shown) if part)
            if truncated and not text.endswith(_TRUNCATED):
                text += _TRUNCATED
            if recall is not None:
                # Only a page that was actually read. Remembering a failure
                # would turn one outage into an hour of them.
                recall.put(url, text, key=url_key(url))
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
    "You do not have to track what you have already read. A page read earlier "
    "in this process comes back as it was, marked as recalled and dated. If a "
    "page is expected to have changed since -- a changelog, a status page, a "
    "document revised during this run -- pass `refresh=True` and it will be "
    "read again. Do not pass it merely to be sure."
)


FETCH_CORPUS_PROMPT = (
    "\n\nA page this project has already stored comes back from the corpus "
    "rather than the network, with the offsets that make it quotable, and says "
    "so plainly. When a fetched page is worth keeping, call `remember_page` "
    "with its URL. That is what lets a later session recognise the page "
    "instead of fetching it again."
)
"""The part of the `fetch` prompt that only holds inside a project.

Split out of `FETCH_PROMPT` because that one is appended to every session,
while the corpus and `remember` exist only once a project is attached. A
project-less session told that its reads come back from the corpus has been
told something false about the tool it is holding, and would look for a
`remember` it does not have.
"""
