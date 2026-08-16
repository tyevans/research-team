"""Fetching one media asset, at a URL the model has decided it wants.

Last of the media-acquisition tools, and on purpose: it shares
`application/media_acquisition.py`'s `download_media` with `MediaAcceptWorker`
-- the same content-type check, the same streamed byte ceiling, the same three
named refusals -- so that a human accepting a judged proposal and a model
reaching for a specific asset directly answer "is this actually media, and is
it small enough" through one implementation, not two that could drift.

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

import httpx
from langchain_core.tools import BaseTool, tool

from research_team.application.autonomy import FETCH_MEDIA_TOOL
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


def build_fetch_media_tool(
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
    client: httpx.AsyncClient | None = None,
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

    This tool does not follow a redirect (`download_media` never does -- see
    `MediaMoved`'s docstring) and does not store what it downloads anywhere:
    it drains the asset to confirm it exists, is the right kind, and fits
    under the ceiling, and reports that back as prose. Wiring a fetched asset
    into the corpus is a decision about *this session's* project and grant,
    made by whatever composes this tool with one -- not something a shared
    primitive should assume every caller wants.
    """

    @tool(FETCH_MEDIA_TOOL)
    async def fetch_media(url: str) -> str:
        """Fetch one media asset by URL and report whether it could be read.

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

            total = 0
            try:
                # `download_media`'s iterator owns the response and closes it
                # in a `finally` on exhaustion or `aclose()` -- see its
                # docstring. Draining the loop to completion is what triggers
                # that close on the success path; `MediaTooLarge` triggers it
                # from inside the generator itself, and the `except` below
                # does not need its own `aclose()` for that reason.
                async for chunk in stream:
                    total += len(chunk)
            except MediaTooLarge as error:
                # Bounded regardless of autonomy: turning this tool to `auto`
                # authorizes leaving the process, not lifting the ceiling
                # enforced where the bytes actually stream. See
                # `TOOL_FLOORS`'s `fetch_media` entry.
                return (
                    f"That media exceeds the {max_bytes}-byte ceiling ({error.total} bytes "
                    "read before it was refused) -- fetch_media cannot take it."
                )

            return f"Fetched {total} bytes of {media_type} from {url}."
        finally:
            if owned:
                await http.aclose()

    return fetch_media
