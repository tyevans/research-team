"""URL normalization shared by the domain and the network tools.

Moved here from `infrastructure/agent/recall.py`, where it was written for
`Recall`'s memo keys, when `MediaProposals.decide` needed the same fold for
`ignored_assets` keys. The domain cannot import `infrastructure` --
`tests/test_architecture.py` enforces that direction -- so the function moved
rather than being duplicated; `recall.py` re-exports it so every existing
caller (`fetch.py`, its tests, `recall.py`'s own `query_key`) is untouched.
"""

from urllib.parse import urlsplit, urlunsplit

_DEFAULT_PORTS = {"http": "80", "https": "443"}


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

    Total, because every caller hands it text a model wrote: the URL passed
    to `fetch`, every `uri` in the corpus, and now every `asset_url` a
    proposal names. `urlsplit(...).port` raises `ValueError` on a port that is
    not a number in range, so one stored document with `uri="http://host:port/x"`
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
