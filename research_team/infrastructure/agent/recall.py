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
    """
    parts = urlsplit(url.strip())
    host = parts.hostname or ""
    port = parts.port
    if port is not None and _DEFAULT_PORTS.get(parts.scheme.lower()) != str(port):
        host = f"{host}:{port}"
    return urlunsplit((parts.scheme.lower(), host, parts.path or "/", parts.query, ""))


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
