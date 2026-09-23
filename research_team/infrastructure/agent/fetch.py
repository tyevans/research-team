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

from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from urllib.parse import urlsplit

import httpx
from langchain_core.tools import BaseTool, InjectedToolCallId, tool

from research_team.infrastructure.agent.fetch_extraction import (
    _HEADERS,
    _TRUNCATED,
    MAX_BYTES,
    MAX_CHARS,
    TIMEOUT,
    UNREADABLE,
    _citation,
    extract_page,
    stored_page,
)
from research_team.infrastructure.agent.recall import (
    PageMemo,
    Recall,
    describe_age,
    url_key,
)
from research_team.research.application.corpus_read import CorpusReadPort
from research_team.session.application.autonomy import FETCH_TOOL
from research_team.session.application.tool_artifacts import Acknowledgement, Excerpt
from research_team.tenancy.application.grants import FetchGrant

__all__ = [
    "FETCH_CORPUS_PROMPT",
    "FETCH_PROMPT",
    "MAX_BYTES",
    "MAX_CHARS",
    "TIMEOUT",
    "UNREADABLE",
    "_HEADERS",
    "_TRUNCATED",
    "_citation",
    "build_fetch_tool",
    "extract_page",
    "stored_page",
]


def build_fetch_tool(
    *,
    max_chars: int = MAX_CHARS,
    max_bytes: int = MAX_BYTES,
    client: httpx.AsyncClient | None = None,
    recall: Recall | None = None,
    corpus: CorpusReadPort | None = None,
    pages: PageMemo | None = None,
    grant: FetchGrant | None = None,
    # Returns the `source_id` the page was stored under, or None when nothing
    # was stored -- the citation names it only in the first case. See
    # `composition.py`'s `keep` for why the id is no longer the url.
    keep: Callable[[str], Awaitable[str | None]] | None = None,
) -> BaseTool:
    """A `fetch` tool for reading one web page.

    `client` is injectable so tests can stub the transport; nothing in the
    suite touches the real network. `pages` retains the whole extraction
    (rather than the `max_chars` excerpt the model is shown) so a later
    `remember_page` can store more of a page than the model ever had to
    retype.

    `keep` is called with the url after a successful read, and is how an
    unattended run stops depending on the model choosing to save what it read.
    A callable taking a url rather than the page itself, deliberately: it
    keeps this module ignorant of `SourceRef` and the corpus, and the page it
    would be handed is already in `pages` under exactly that key.

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

    **This section used to describe an open batch over-spend; it is closed
    now, mostly on the other side of the seam, with one piece that had to
    land here.** The gate (`approval.py`'s `_covered`) used to only *read*
    `covers(url)` before deciding not to interrupt, and the gate evaluates
    every `fetch` call in one model message before any of them runs -- so N
    covered calls dispatched in a single message could all see the same
    "not yet spent" answer and all leave the process, N being a number the
    model chooses by how many `fetch` calls it puts in one message.
    `task-5-review.md` reproduced it against the real tool: ten requests on
    a budget of one.

    The first fix was `FetchGrant.reserve(url)`, called by the gate instead
    of `covers(url)`: it claims a unit of budget *as it answers*, with no
    `await` between the claim and the write, so the second call evaluated in
    the same synchronous batch sees the first one's claim and is refused.
    That closed the batch, and a whole-branch review found what it opened:
    `interrupt()` raises `GraphInterrupt`, and langgraph re-executes the
    whole gate pass on `Command(resume=...)`, so a plain-count reservation
    got claimed *again* for a call already holding one -- at low remaining
    budget this flipped an admitted call to refused on the resume pass and
    crashed the turn. The fix was keying `_reserved` by tool-call id, which
    makes re-evaluating the same call idempotent -- see `FetchGrant.reserve`.

    Making that fix land needed this tool to know its own call's id, because
    the review's second finding was that a claim taken at the gate is left
    stuck by *every* return path here that answers without a network read --
    a corpus hit, a memo hit, an httpx error, an HTTP error status -- since
    none of them called `spend()`, and in a research run over a growing
    corpus those are the common case, not the exception. `tool_call_id`
    above (`InjectedToolCallId`, uninfluenceable by the model) is what lets
    the outer `try`/`finally` release a claim this call never redeemed,
    regardless of which of the returns above fired. `spend()` still releases
    the id it redeems on its own, so `covers()`-then-`spend()` reads exactly
    as it always did; `release()` after it is a documented no-op. See
    `FetchGrant`'s docstring for the fuller argument and what is still true
    without a rollback mechanism: a stuck claim can only ever make a later
    `reserve()` more conservative, never let more be spent than the real
    budget.
    """

    @tool(FETCH_TOOL, response_format="content_and_artifact")
    async def fetch(
        url: str,
        refresh: bool = False,
        *,
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> tuple[str, dict[str, Any]]:
        """Read one web page and return its main content as markdown text.

        `tool_call_id` is injected by the framework from the real `ToolCall`
        that invoked this run -- never settable by the model, because it is
        stripped from the schema the model sees (`InjectedToolCallId`'s whole
        point). That matters here specifically: it is the same id the gate
        (`approval.py`'s `_covered`) claimed a budget unit under via
        `grant.reserve(call_id, url)`, and the outer `try`/`finally` below
        releases that exact claim on every return path, whether or not this
        call actually spent it. A model-settable id would let a call release
        -- and so re-admit -- a *different* call's still-outstanding claim,
        which is exactly the over-admission this reservation system exists to
        rule out; that is why this is `Annotated[..., InjectedToolCallId]`
        and not a plain keyword argument with a default.
        """
        try:
            try:
                scheme = urlsplit(url).scheme.lower()
            except ValueError:
                # Malformed URLs (e.g. invalid IPv6) raise ValueError from
                # urlsplit. A gate approval can let one reach the tool; refusing
                # it safely keeps the turn intact rather than crashing (B42).
                scheme = ""
            if scheme not in ("http", "https"):
                # Refused before the transport rather than left to httpx. A
                # scheme it does not support today it might support tomorrow,
                # and a fetch tool that grew the ability to read local files
                # would be a way around the file tools -- and around the
                # event log they write to.
                text_out = (
                    f"Only http and https URLs can be fetched; {scheme or 'that'} is not "
                    "one. Use the file tools to read the workspace."
                )
                return text_out, Acknowledgement(
                    action=FETCH_TOOL, subject=url, detail=text_out, ok=False
                ).as_artifact()
            if not refresh:
                # Corpus before memo: both avoid the request, and only one
                # comes back with offsets a claim can cite. Both return before
                # any budget is spent -- the outer `finally` is what stops a
                # reservation taken for this call from sitting there forever.
                if corpus is not None:
                    found = await stored_page(corpus, url, max_chars)
                    if found is not None:
                        found_text, found_excerpt = found
                        return found_text, found_excerpt.as_artifact()
                if recall is not None:
                    remembered = recall.get(url, key=url_key(url))
                    if remembered is not None:
                        # A memo hit carries no title, uri metadata or true
                        # document length distinct from what was retained --
                        # unlike a corpus hit, there is no `StoredDocument` to
                        # build a real `Excerpt` from, only the text `Recall`
                        # kept. `char_count=len(text)` and a full-span excerpt
                        # is honest about that: the ruler draws the whole bar
                        # filled, which is what "this is everything retained"
                        # actually looks like, rather than claiming a range
                        # into a document this call never re-measured.
                        recalled_text = (
                            f"[recalled -- read {describe_age(remembered.age_seconds)} in "
                            f"this process, not a fresh read. Pass refresh=True if the "
                            f"page is expected to have changed since.]\n\n{remembered.text}"
                        )
                        return recalled_text, Excerpt(
                            source_id=url,
                            title=None,
                            label=None,
                            start=0,
                            end=len(remembered.text),
                            char_count=len(remembered.text),
                            text=remembered.text,
                            uri=url,
                        ).as_artifact()
            owned = client is None
            http = client or httpx.AsyncClient(
                timeout=TIMEOUT,
                follow_redirects=grant is None,
                headers=_HEADERS,
            )
            try:
                response = await http.get(url, headers=_HEADERS)
                if response.is_redirect:
                    # Checked before `raise_for_status()`: with redirects off,
                    # a 3xx with a Location is exactly what `raise_for_status`
                    # treats as an error (`HTTPStatusError` naming the
                    # location itself), which would fall into the "error,
                    # don't spend" branch below -- wrong, because the GET
                    # still left the process and got an answer. Spent and
                    # reported here instead, before that branch ever sees it
                    # -- and only if the grant is what authorized *this* call
                    # (Fix 1: see the docstring).
                    if grant is not None and grant.covers(url):
                        grant.spend(tool_call_id)
                    location = response.headers.get("location", "(no Location header)")
                    # Worded to be true whether or not `grant` is set: in
                    # production this branch is unreachable without one (the
                    # ungranted owned client has follow_redirects=True, so
                    # httpx resolves 3xx before this tool ever sees a
                    # response), but an injected client -- every test in this
                    # file uses one -- can still hand back a 3xx regardless of
                    # `grant`, and a message that named "a granted fetch"
                    # would be false in that case.
                    text_out = (
                        f"That URL redirected to {location}, which was not followed. "
                        "Fetch that URL directly if you still want it."
                    )
                    return text_out, Acknowledgement(
                        action=FETCH_TOOL, subject=url, detail=text_out, ok=False
                    ).as_artifact()
                response.raise_for_status()
                if grant is not None and grant.covers(url):
                    # Spent here, not at `http.get()`: an HTTPStatusError is
                    # raised by `raise_for_status()`, one line above, and an
                    # error is not a use of the budget (see the docstring). A
                    # request that gets this far actually left the process
                    # and came back with a usable response -- and
                    # `covers(url)` is what confirms the grant, not a human
                    # approval, is who authorized it.
                    grant.spend(tool_call_id)
                content_type = response.headers.get("content-type", "")
                media_type = content_type.split(";")[0].strip().lower()
                if media_type and "html" not in media_type and "xml" not in media_type:
                    text_out = (
                        f"That URL returned {media_type}, which this tool cannot read -- "
                        "it reads HTML pages. No text this time."
                    )
                    return text_out, Acknowledgement(
                        action=FETCH_TOOL, subject=url, detail=text_out, ok=False
                    ).as_artifact()
                body = response.content[:max_bytes]
                truncated = len(response.content) > max_bytes
                html = body.decode(response.encoding or "utf-8", errors="replace")
                extracted = extract_page(html, url)
                if extracted is None:
                    return UNREADABLE, Acknowledgement(
                        action=FETCH_TOOL, subject=url, detail=UNREADABLE, ok=False
                    ).as_artifact()
                full, title, date = extracted
                if pages is not None:
                    # The whole extraction, not the excerpt below it.
                    # `max_chars` is what one page may cost the conversation;
                    # it was never meant to be what the corpus can hold, and
                    # was only ever that because a document could not reach
                    # the corpus except through the model's own output.
                    pages.put(url, text=full, uri=url, title=title, published_at=date)
                kept: str | None = None
                if keep is not None:
                    # After `pages.put`, never before: `keep` reads the page
                    # back out of the memo by url, so the memo has to hold it
                    # first. Ordered rather than combined because the memo is
                    # process-local and always wanted, while `keep` reaches a
                    # project's corpus and exists only for an unattended run.
                    #
                    # Failure here does not fail the fetch. The page was read
                    # and the model is about to be shown it; losing the corpus
                    # copy is worth strictly less than losing the read, and
                    # `keep`'s own implementation is what decides how loudly to
                    # complain. See `composition.py`'s `granted_tools`.
                    kept = await keep(url)
                shown = full
                if len(shown) > max_chars:
                    shown = shown[:max_chars].rstrip() + _TRUNCATED
                text = "\n\n".join(
                    part for part in (_citation(url, title, date, kept), shown) if part
                )
                if truncated and not text.endswith(_TRUNCATED):
                    text += _TRUNCATED
                if recall is not None:
                    # Only a page that was actually read. Remembering a
                    # failure would turn one outage into an hour of them.
                    recall.put(url, text, key=url_key(url))
                # `end` is `len(shown)` before the truncation marker was
                # appended, not `len(text)` -- the marker and the citation
                # header are not page content, and the ruler this draws is
                # against the *document*, the same distinction
                # `excerpt_artifact` makes for a corpus read.
                artifact = Excerpt(
                    source_id=kept or url,
                    title=title,
                    label=None,
                    start=0,
                    end=min(len(full), max_chars),
                    char_count=len(full),
                    text=shown,
                    uri=url,
                )
                return text, artifact.as_artifact()
            except httpx.HTTPStatusError as error:
                # The status is the actionable part: 404 means the URL is
                # wrong, 403 means this page will not be readable this way at
                # all. Not spent -- and per the outer `finally`, not left
                # reserved either.
                text_out = (
                    f"Could not read that page: the server returned "
                    f"{error.response.status_code}."
                )
                return text_out, Acknowledgement(
                    action=FETCH_TOOL, subject=url, detail=text_out, ok=False
                ).as_artifact()
            except httpx.HTTPError as error:
                text_out = f"Could not reach that page: {error}"
                return text_out, Acknowledgement(
                    action=FETCH_TOOL, subject=url, detail=text_out, ok=False
                ).as_artifact()
            except UnicodeError as error:
                text_out = f"Could not decode that page: {error}"
                return text_out, Acknowledgement(
                    action=FETCH_TOOL, subject=url, detail=text_out, ok=False
                ).as_artifact()
            finally:
                if owned:
                    await http.aclose()
        finally:
            # Every return path above lands here, spent or not. `release()`
            # is a plain `set.discard`, so this is a harmless no-op when
            # `grant` is `None`, when this call never held a reservation (a
            # human-approved, out-of-scope fetch), or when `spend()` already
            # released this exact id two lines up -- and it is exactly what
            # stops a corpus hit, a memo hit, or an httpx/HTTP error from
            # leaving a claim stuck forever. See `FetchGrant`'s docstring for
            # why an unreleased claim was a real problem, not an accepted one.
            if grant is not None:
                grant.release(tool_call_id)

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
