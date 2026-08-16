"""Fetching one media asset, at a URL the model has decided it wants.

Last of the media-acquisition tools, and on purpose: it shares
`application/media_acquisition.py`'s `download_media` with `MediaAcceptWorker`
-- the same content-type check, the same streamed byte ceiling, the same three
named refusals -- so that a human accepting a judged proposal and a model
reaching for a specific asset directly answer "is this actually media, and is
it small enough" through one implementation, not two that could drift.

It also shares the *store*: on success this calls `CorpusEditor.store_media`,
the same call `MediaAcceptWorker.run` makes, for the same reason -- one path
from bytes to a corpus row rather than two that could disagree about, say,
whether the blob is written before or after the aggregate command. Unlike the
worker, this tool does not perceive eagerly; that is a design choice, not an
oversight -- perception here would make a single tool call block on a second
network-and-model round trip the caller did not ask for, and an unperceived
medium is already an ordinary, visible state (`MediaPerceiver.unperceived`).

Gated the way `fetch.py` is, for the same reason stated in that module and in
`TOOL_FLOORS`: this is a network tool present in a default install with
nothing else standing in front of it, reaching a URL the model chose. Read
`TOOL_FLOORS`'s docstring in `application/autonomy.py` before touching the
floor here -- it already states the property this tool relies on, and the
extra cost `fetch_media` carries over `fetch` (bytes to disk, not just text).

Errors are reported to the model as prose, following `fetch.py`'s convention,
not raised: an agent turn that raises loses the turn, and `UnsupportedMedia`,
`MediaMoved` and `MediaTooLarge` are all things a model can act on -- stop,
re-fetch the real location, or accept that the asset does not fit.
"""

import hashlib
from uuid import UUID

import httpx
from langchain_core.tools import BaseTool, tool

from research_team.application.autonomy import FETCH_MEDIA_TOOL
from research_team.application.corpus_editing import CorpusEditor
from research_team.application.media_acquisition import (
    MAX_UPLOAD_BYTES,
    MediaMoved,
    MediaTooLarge,
    UnsupportedMedia,
    download_media,
)

TIMEOUT = httpx.Timeout(30.0)
"""Longer than `fetch.py`'s 15s: a media asset is commonly larger than a page
and the ceiling below already bounds how much of it this tool will pull."""


def _source_id_for(url: str) -> str:
    """A stable, content-free `source_id` for a directly-fetched asset.

    A proposal has `proposal_id` to reuse (see `MediaAcceptWorker.run`); a
    direct fetch has no id at all until this tool invents one. Derived from
    the URL, not the bytes: the id has to exist *before* the download to be
    the thing `store_media` is called with, so it cannot be content-addressed
    the way the blob underneath it already is.

    Deterministic on purpose, mirroring the worker's own reasoning: fetching
    the same URL twice lands on the same `source_id`, so a retried call
    revises the existing record (`corpus.py`'s media branch allows a re-store
    onto an id that already holds media -- see `CorpusEditor.store_media`'s
    docstring) rather than accumulating a second row for one asset. Two
    different URLs get different ids because the hash is over the whole URL,
    not a truncation likely to collide.
    """
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return f"fetch:{digest}"


def build_fetch_media_tool(
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
    client: httpx.AsyncClient | None = None,
    editor: CorpusEditor | None = None,
    project_id: UUID | None = None,
) -> BaseTool:
    """A `fetch_media` tool for pulling one image, video or audio asset.

    `client` is injectable so tests can stub the transport with
    `httpx.MockTransport` -- nothing in the suite touches the real network,
    matching `fetch.py` and `test_media_acquisition.py`.

    `max_bytes` defaults to `MAX_UPLOAD_BYTES`, the same ceiling
    `MediaAcceptWorker` enforces on the accept path -- one number, so a model
    pulling an asset directly is bound by the same limit a human accepting a
    proposal is. Passing it through rather than hardcoding it here is what
    keeps that agreement visible at the call site instead of implicit.

    `editor` and `project_id` together are what let this tool store what it
    downloads; both are required together (`RuntimeError` if only one is
    given, since a caller half-wiring this is a bug, not a valid shape) and
    both `None` is refused too -- there is no build of this tool that drains
    an asset and reports success without storing it, because that tool is
    exactly the defect this module was written to fix. See `composition.py`
    for why the pair is only available once a project is attached: storing
    requires somewhere to store *to*, and there is no such place before then.

    This tool does not follow a redirect (`download_media` never does -- see
    `MediaMoved`'s docstring).
    """
    if editor is None or project_id is None:
        raise RuntimeError(
            "build_fetch_media_tool requires both editor and project_id -- "
            "a fetch_media that cannot store what it downloads is not this tool"
        )

    @tool(FETCH_MEDIA_TOOL)
    async def fetch_media(url: str) -> str:
        """Fetch one media asset by URL, store it in this project's corpus,
        and report whether it could be read.

        Use this once you know which specific image, video or audio file you
        want -- not to browse. It reads image/*, video/* and audio/* content
        types only; anything else, including an HTML page at that URL, is
        refused by name rather than silently accepted. There is a size
        ceiling this tool enforces regardless of how autonomy is configured
        for it (see `MAX_UPLOAD_BYTES`) -- a very large asset is refused
        partway through, not admitted because the tool was allowed to run
        without asking.
        """
        owned = client is None
        http = client or httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False)
        try:
            try:
                stream, media_type = await download_media(
                    url, client=http, max_bytes=max_bytes
                )
            except MediaMoved as error:
                # Actionable, per `MediaMoved`'s own docstring: a model told
                # the real location can fetch it directly, rather than being
                # told only that the fetch failed.
                return (
                    f"That URL redirected to {error.location}, which was not followed. "
                    "Fetch that URL directly if you still want this asset."
                )
            except UnsupportedMedia as error:
                # A dead end, not something to retry: the URL answered, and
                # what it answered with is not media this tool can use.
                return (
                    f"That URL returned {error.media_type or '(no content-type)'}, which is "
                    "not image, video or audio -- fetch_media cannot use it."
                )
            except httpx.HTTPError as error:
                # `download_media` never calls `raise_for_status()` -- an
                # error status with a non-media content-type reads as
                # `UnsupportedMedia` above, which is the more actionable of
                # the two answers for a URL that responded at all. What
                # reaches here is a transport failure: DNS, TLS, a refused
                # connection, a timeout.
                return f"Could not reach that media: {error}"

            source_id = _source_id_for(url)
            try:
                # `store_media` reads the stream itself (`_blobs.put`), so
                # counting bytes here the way the drain-only version of this
                # tool used to would mean reading the body twice. The stored
                # `MediaRecord`'s `byte_count` is what the report below uses
                # instead -- one read, matching `MediaAcceptWorker.run`.
                record = await editor.store_media(
                    project_id,
                    source_id,
                    stream,
                    media_type,
                    uri=url,
                    fetched_at=None,
                )
            except MediaTooLarge as error:
                # Bounded regardless of autonomy: turning this tool to `auto`
                # authorizes leaving the process, not lifting the ceiling
                # enforced where the bytes actually stream. See
                # `TOOL_FLOORS`'s `fetch_media` entry.
                return (
                    f"That media exceeds the {max_bytes}-byte ceiling ({error.total} bytes "
                    "read before it was refused) -- fetch_media cannot take it."
                )
            except BaseException:
                # Mirrors `MediaAcceptWorker.run`'s handling of the same
                # failure mode -- see its comment. `store_media` can raise
                # after it has started reading `stream` (a blob-store I/O
                # error, most plausibly), which leaves `download_media`'s
                # generator suspended mid-iteration; its own `finally` only
                # fires on exhaustion or an explicit `aclose()`, so an
                # abandoned suspended generator would hold the connection
                # open until garbage collection gets to it -- not promised to
                # happen promptly, or at all, for a suspended coroutine.
                await stream.aclose()
                raise

            return (
                f"Fetched and stored {record.byte_count} bytes of {media_type} "
                f"from {url} as {source_id!r}."
            )
        finally:
            if owned:
                await http.aclose()

    return fetch_media
