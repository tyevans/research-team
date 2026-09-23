"""HTML extraction, citation formatting, and stored page recall for web fetch.

Separated from `fetch.py`'s tool builder so that text extraction, citation
construction, and corpus-backed recall can be maintained and tested
independently of LangChain tool binding and grant budget tracking.
"""

import httpx
import trafilatura
from trafilatura.metadata import extract_metadata

from research_team.infrastructure.agent.corpus_tools import (
    bounded,
    excerpt_artifact,
    format_document,
)
from research_team.infrastructure.agent.recall import (
    normalize_url,
)
from research_team.research.application.corpus_read import CorpusReadError, CorpusReadPort
from research_team.session.application.tool_artifacts import Excerpt

__all__ = [
    "MAX_BYTES",
    "MAX_CHARS",
    "TIMEOUT",
    "UNREADABLE",
    "_HEADERS",
    "_TRUNCATED",
    "_citation",
    "extract_page",
    "stored_page",
]

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
"""The ceiling on what this tool can read, and a decision rather than a default.

A headless browser would lift it, and was refused. The cost is not the install:
it is a browser binary, a download step in CI, and a resource profile unlike
anything else in this process. What it buys is a *new class of failure* on the
path to a citation -- render timeouts, anti-bot challenges, and pages that
succeed slowly enough to change what a turn costs -- where today an app shell
fails one way, immediately, and says so.

The sentence above is already the honest answer. A model that reads it can
`record_gap`, which is what the coverage machinery wants from a source nobody
could reach; a rendered page that times out half the time produces something
worse than a gap, which is an intermittent one.

Revisit when a corpus this project actually wants is behind an app shell. That
is the fact that would change the answer, and until it exists the argument
above holds. See BACKLOG.md.
"""

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

    Split out of a `format_page` that no longer exists, so that the text kept
    for `remember_page` and the text shown to the model come from a single
    extraction. Two extractions would eventually disagree, and the
    disagreement would surface as a corpus document that does not match the
    citation the model was reading from. The single caller is the fetch tool,
    which composes this with `_citation` itself.

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


def _citation(
    url: str, title: str | None, date: str | None, source_id: str | None = None
) -> str:
    """A `url` line, plus title and date when the page offered them.

    The URL leads the output because the citation is the reason for fetching.
    Text that arrives without its address cannot be cited by anything
    downstream, and a model that has lost a source will confabulate one rather
    than say so.

    `source_id` rides along when the page was kept, and only then. It is not
    cosmetic: the id is derived from the url now rather than being the url
    (`application/knowledge.py`), so this line is the only way the model learns
    what to pass to `link_source` -- which does not verify that the id it is
    handed exists, and so would record a dangling link in silence. Absent when
    `keep` did not run or failed, because naming an id the corpus does not hold
    is the failure this is here to avoid.
    """
    lines = [f"url: {url}"]
    if source_id:
        lines.append(f"source_id: {source_id}")
    if title:
        lines.append(f"title: {title}")
    if date:
        lines.append(f"date: {date}")
    return "\n".join(lines)


async def stored_page(
    corpus: CorpusReadPort, url: str, max_chars: int
) -> tuple[str, Excerpt] | None:
    """This page as the corpus already holds it, or None.

    Matched on `normalize_url` rather than on the stored string, so a URL that
    differs only in scheme case, a default port or a fragment is recognised as
    the same page. Scanning is O(corpus) per call and stays that way: the scan
    itself is 5.7 ms over 500 sources (measured 2026-08-16), so an index is
    still machinery bought against nothing.

    What did have to change is *what* is scanned. This called `list_sources`,
    which loads every live document's body to render records nothing here
    reads -- 48.1 ms and 22.5 MB peak per call at 500 documents of 40,000
    characters, on a call that runs on every `fetch`. `list_text_uris` is the
    same scan over two columns: 5.7 ms and 0.16 MB. See its docstring for the
    attribution and `BACKLOG.md` B84 for the rest.

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
        # Text only, and now by construction rather than by filtering: a media
        # source at this URL has no text for `read_document` to return, and
        # matching it here would just fall through to "unreadable" below for a
        # reason that has nothing to do with a drop.
        sources = await corpus.list_text_uris()
    except CorpusReadError:
        return None
    match = next(
        (source for source in sources if normalize_url(source.uri) == target),
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
    text = (
        "[recalled -- this page is already in this project's corpus, so it was "
        "not fetched again. Quote it from here; the offsets below are real.]\n\n"
        + format_document(document, span)
    )
    return text, excerpt_artifact(document, span)
