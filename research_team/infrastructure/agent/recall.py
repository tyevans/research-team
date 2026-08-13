"""What the network tools remember having already served.

Two tools leave this process, and until now neither had any way to know it was
about to ask for something it already had. The corpus answers that question
durably for pages the project chose to keep; this answers it for the rest, for
as long as the process lives.

In-process and deliberately not persistent. A durable record of every page
ever fetched -- as opposed to every page deliberately kept -- would make
fetching permanent, which `remember`'s own prompt is careful to say it is not,
and would need a retention policy, a read model, and an answer to why it is
not the corpus. The failure that actually recurs is narrower than that: the
same page twice in one long-running process, after the first read was
compacted out of context. That is what this covers.

**The normalization rule, which is the whole design:** two requests share an
entry only if the instance would have returned the same results for both.
Case, whitespace and Unicode form clear that bar. Term order, stopwords and
stemming do not -- an engine ranks `"assessment design backward"` differently
from `"backward design assessment"`, so merging them returns results for a
question that was not asked while labelling them as answering the one that
was. That is a wrong answer wearing a right one's label, traded for a saved
request against a search instance the operator runs themselves. There is no
version of that trade worth making, which is why nothing here stems, sorts or
embeds.

`Recalled.asked` is the safety net under all of it. Every hit can report the
request that actually produced it, so a merge the agent did not intend is
visible in the response and costs a turn rather than an answer.
"""

import time
import unicodedata
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

CAPACITY = 128
"""How many responses are held. Entries are page bodies of up to `MAX_CHARS`,
in a process that may be a web server running for days; unbounded, this is a
leak whose size is set by how much research the agent does."""

TTL_SECONDS = 3600.0
"""How long an entry stays usable.

`fetch` has `refresh=True` as an explicit override and `web_search` has
nothing, so without expiry a long-lived process would pin a stale result set
and present it as current for as long as it ran. An hour is short enough that
a page which changed is re-read within a working session, and long enough to
cover the case this exists for."""

_DEFAULT_PORTS = {"http": "80", "https": "443"}


def normalize_query(request: str) -> str:
    """A search query, folded only where an instance is already insensitive.

    NFKC first so that visually identical text composed differently -- a
    precomposed accent against a combining one -- does not produce two
    entries. Then casefold, which is the full-Unicode form of lowercasing and
    the right one for a comparison key. Then whitespace collapse.

    Nothing else. See this module's docstring for why the list stops here.
    """
    folded = unicodedata.normalize("NFKC", request).casefold()
    return " ".join(folded.split())


def normalize_url(url: str) -> str:
    """A URL, folded only where two spellings address the same resource.

    Scheme and host are case-insensitive by RFC 3986 and are folded. A default
    port is equivalent to no port and is dropped. A fragment never reaches the
    server at all, so two URLs differing only in one are one request. An empty
    path is `/`.

    The path, query and everything else are left exactly alone. Paths are
    case-sensitive on any server that says they are, and folding one would
    merge two genuinely different pages -- which is the same failure as
    merging two search queries, arriving through a different door.

    Total, because both callers hand it text the model wrote: the URL passed
    to `fetch`, and every `uri` in the corpus, which `remember` accepts as free
    text. `urlsplit(...).port` raises `ValueError` on a port that is not a
    number in range, so one stored document with `uri="http://host:port/x"`
    would otherwise raise on every `fetch` in that project forever. A string
    this malformed matches nothing, which is the right outcome; returning it
    unparsed costs a redundant request, while raising costs the whole turn.
    """
    trimmed = url.strip()
    try:
        parts = urlsplit(trimmed)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        return trimmed
    if port is not None and _DEFAULT_PORTS.get(parts.scheme.lower()) != str(port):
        host = f"{host}:{port}"
    return urlunsplit((parts.scheme.lower(), host, parts.path or "/", parts.query, ""))


_FIELD = "\x1f"
"""Separates the query from the parameters in a search key.

A unit separator because `normalize_query` cannot emit one: Python counts
`\\x1f` as whitespace, so `str.split` consumes it and the collapse turns it
into a space. A query cannot therefore be written to look like a parameter
suffix and land on a parameterised search's entry.
`test_a_parameter_value_cannot_be_forged_from_the_query_text` fails if this
becomes a printable character.
"""


def query_key(
    request: str,
    *,
    engines: str | None = None,
    categories: str | None = None,
    time_range: str | None = None,
) -> str:
    """The memo key for a search query, with the parameters that change it.

    One `Recall` serves two tools, so the kind of request has to be part of
    the key. Without it the keyspaces overlap wherever a normalized query and
    a normalized URL can be the same string -- which is exactly the case of a
    bare URL pasted as a query, something models do routinely. `web_search`
    would then answer a later `fetch` of that URL with its snippet list,
    labelled as the page, with no `url:` header and no body: a wrong answer
    wearing a right one's label, which is the failure this whole module is
    built to avoid.

    The three SearXNG parameters join it for the same reason, read through
    this module's normalization rule: fold only where the upstream is already
    insensitive, and an instance is emphatically *not* insensitive to these --
    changing what it returns is the entire reason for sending them. Keyed on
    the query alone, the same words with `time_range="year"` would be answered
    from the unrestricted search's entry.

    The values are compared exactly, with none of the folding the query gets.
    Whether `Arxiv` reaches the same engine as `arxiv`, or `news,it` the same
    set as `it,news`, is a question about a given instance's configuration,
    and this module does not get to assume the generous answer -- an extra
    request is the cost of guessing wrong in the safe direction.

    An unparameterised call keys byte-for-byte as it did before the parameters
    existed, which is the overwhelming majority of searches.
    """
    key = f"q:{normalize_query(request)}"
    for name, value in (
        ("engines", engines),
        ("categories", categories),
        ("time_range", time_range),
    ):
        if value is not None:
            key += f"{_FIELD}{name}={value}"
    return key


def url_key(url: str) -> str:
    """The memo key for a fetched page. See `query_key` for why it is prefixed."""
    return f"u:{normalize_url(url)}"


def describe_age(seconds: float) -> str:
    """How long ago, in words, for a sentence the model reads.

    Coarse on purpose: the decision this informs is "is this still good
    enough", and a figure to the second invites precision the entry does not
    have -- it was fetched once, at a moment nothing here recorded to that
    resolution.
    """
    if seconds < 1:
        return "just now"
    if seconds < 60:
        return f"{int(seconds)} seconds ago"
    if seconds < 3600:
        return f"{int(seconds // 60)} minutes ago"
    return f"{int(seconds // 3600)} hours ago"


@dataclass(frozen=True)
class Recalled:
    """One remembered response, and enough context to present it honestly."""

    text: str

    asked: str
    """The request as the caller originally wrote it, not as it was keyed.

    Reported back so a response can say which request these results are for.
    Without it a normalization that merged too much would be invisible, and an
    invisible merge is the only kind that does damage.
    """

    age_seconds: float


class Recall:
    """A bounded, expiring, least-recently-used memo.

    Not thread-safe and not trying to be: one process, one event loop, and
    every caller is inside an `async def` that never awaits mid-update. A lock
    here would be ceremony around an operation that cannot interleave.
    """

    def __init__(
        self,
        *,
        capacity: int = CAPACITY,
        ttl_seconds: float = TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._capacity = capacity
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: OrderedDict[str, tuple[str, str, float]] = OrderedDict()

    def get(self, request: str, *, key: str | None = None) -> Recalled | None:
        """What was served for `request` before, or None.

        An expired entry is dropped on the way out rather than left to the
        eviction path. It is already known to be useless, and keeping it would
        let dead weight hold a slot against a live entry.
        """
        resolved = key if key is not None else normalize_query(request)
        entry = self._entries.get(resolved)
        if entry is None:
            return None
        asked, text, stored_at = entry
        age = self._clock() - stored_at
        if age > self._ttl:
            del self._entries[resolved]
            return None
        self._entries.move_to_end(resolved)
        return Recalled(text=text, asked=asked, age_seconds=age)

    def put(self, request: str, text: str, *, key: str | None = None) -> None:
        """Remember what `request` returned, evicting the coldest if full."""
        resolved = key if key is not None else normalize_query(request)
        self._entries[resolved] = (request, text, self._clock())
        self._entries.move_to_end(resolved)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)


def _utc_now() -> str:
    """The wall-clock moment a page was read, as text.

    Text rather than a `datetime` because that is what it becomes:
    `SourceDocumentStored.fetched_at` is a `str | None`, matching
    `published_at`, which is text because sources report dates in whatever
    shape they please. Converting here and back would buy nothing.
    """
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class RetainedPage:
    """One page as `fetch` read it, kept for `remember_page`.

    Distinct from `Recalled` in the two ways that matter. `text` is the whole
    extraction rather than the excerpt the model was shown, so the corpus is
    capped by its own limit rather than by the context budget. And the
    provenance is fields, not a citation header to be parsed back out -- a page
    whose own prose opens with something header-shaped would otherwise be
    stored under whatever that text claimed.
    """

    text: str
    uri: str
    title: str | None
    published_at: str | None
    fetched_at: str


class PageMemo:
    """What `fetch` retained, by URL, for as long as the process lives.

    Separate from `Recall` rather than an extension of it. `Recall` is shared
    with `web_search`, whose entries are flattened result blocks with no `uri`,
    no title and no fetch time; widening it would put four permanently-absent
    fields on every search entry. The cost of the split is this class's
    eviction logic, which is `Recall`'s again -- paid to keep one store with
    one value type serving two tools.

    Process-wide and shared across projects, under `Recall`'s invariant and for
    its reason: this holds only responses from public URLs, which are the same
    bytes whoever asked. **Nothing project-scoped may ever go in it** -- a
    project-derived value here would turn a shared cache into a cross-project
    read.

    Not persistent. A durable record of every page ever fetched would make
    fetching permanent, which `remember`'s own prompt says it is not. Retaining
    more text in an ephemeral store is not that; retaining it across restarts
    would be.
    """

    def __init__(
        self,
        *,
        capacity: int = CAPACITY,
        ttl_seconds: float = TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        stamp: Callable[[], str] = _utc_now,
    ) -> None:
        self._capacity = capacity
        self._ttl = ttl_seconds
        self._clock = clock
        self._stamp = stamp
        self._entries: OrderedDict[str, tuple[RetainedPage, float]] = OrderedDict()

    def get(self, url: str) -> RetainedPage | None:
        """The page retained for `url`, or None if it was never read here,
        has expired, or was evicted. All three are ordinary."""
        key = url_key(url)
        entry = self._entries.get(key)
        if entry is None:
            return None
        page, stored_at = entry
        if self._clock() - stored_at > self._ttl:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return page

    def put(
        self,
        url: str,
        *,
        text: str,
        uri: str,
        title: str | None = None,
        published_at: str | None = None,
    ) -> None:
        """Retain `url`'s full text and provenance, evicting the coldest if full."""
        key = url_key(url)
        self._entries[key] = (
            RetainedPage(
                text=text,
                uri=uri,
                title=title,
                published_at=published_at,
                fetched_at=self._stamp(),
            ),
            self._clock(),
        )
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)
