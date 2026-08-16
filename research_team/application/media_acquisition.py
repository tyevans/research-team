"""Bytes from a URL into the corpus -- one implementation, two callers.

`download_media` is the primitive shared by the accept worker (a human
approves a judged candidate) and a gated agent tool (the model asks for one
directly). Both need the same answer to "is this actually media, and is it
small enough" -- writing it twice would let the two paths drift on exactly
the check that matters most.

That check is why `UnsupportedMedia` is not a nicety. A judged candidate
whose URL turns out to serve an HTML interstitial -- a login wall, a consent
page, a "your download will begin shortly" shim -- is a *failure*, not a
source. Nothing downstream can tell "this row is empty because the page was
gated" from "this row is empty because the transcriber found nothing to
transcribe" unless the HTML is refused before it is ever stored. A corpus row
with HTML bytes and an empty transcript is worse than no row at all: it reads
as a successful acquisition.

`max_bytes` is a parameter rather than an import of `MAX_UPLOAD_BYTES` from
`interfaces/web/app.py` -- the application layer names no framework and
imports nothing from an outer layer (`tests/test_architecture.py`). Callers
pass that same constant in; this module only enforces whatever ceiling it is
given.
"""

from collections.abc import AsyncIterator

import httpx

_HEADERS = {
    # Identical string to `infrastructure/agent/fetch.py`'s `_HEADERS`.
    # Named honestly, with a contact URL, because that is what buys access
    # from Wikimedia and sites with a similar User-Agent policy -- see that
    # module's comment. A download tool that disguised itself as a browser
    # would be a worse trade even where it worked: it borrows trust the
    # operator did not extend to this software.
    "User-Agent": (
        "research-team/0.1 (https://github.com/tyevans/research-team; agent fetch)"
    ),
}

_ACCEPTED_PREFIXES = ("image/", "video/", "audio/")


class UnsupportedMedia(Exception):
    """The URL did not answer with `image/*`, `video/*` or `audio/*`.

    Also raised for a redirect: this module does not follow one (see
    `download_media`'s docstring for why), and a 3xx response has no media
    type of its own to report, so the Location is folded into the message
    instead of inventing one.
    """

    def __init__(self, media_type: str, *, detail: str | None = None):
        self.media_type = media_type
        message = detail or f"unsupported media type: {media_type or '(none)'}"
        super().__init__(message)


class MediaTooLarge(Exception):
    """The body exceeded `max_bytes` partway through streaming.

    Raised from inside the chunk loop, once `total` crosses the ceiling --
    the same shape `app.py`'s `upload_media` chunk generator uses for the
    same reason: reporting a total only after reading the whole body would
    mean reading a body sized specifically to make that expensive.
    """

    def __init__(self, total: int):
        self.total = total
        super().__init__(f"media exceeds the {total} byte ceiling")


async def download_media(
    url: str, *, client: httpx.AsyncClient, max_bytes: int
) -> tuple[AsyncIterator[bytes], str]:
    """Fetch `url`'s bytes, refusing anything that is not image/video/audio.

    Redirects are not followed. `fetch.py` makes the same choice when a
    grant is in play and for a reason that applies here without a grant in
    the picture at all: an unattended acquisition following a redirect would
    be leaving the process to a second address nobody judged, on the same
    authority that only covered the first one. The caller sees the Location
    in `UnsupportedMedia` and can re-issue the call against it deliberately,
    which is a decision rather than something this primitive makes silently.

    The content-type check happens on the response headers, before any of
    the body is read. Streaming a gigabyte to discover it was an HTML
    interstitial would make the refusal this module exists for cost exactly
    what it was meant to avoid; `httpx.AsyncClient.send(..., stream=True)`
    returns headers without pulling the body, so the check and the refusal
    both happen before a single byte of it is asked for.
    """
    request = client.build_request("GET", url, headers=_HEADERS)
    response = await client.send(request, stream=True)

    if response.is_redirect:
        location = response.headers.get("location", "(no Location header)")
        await response.aclose()
        raise UnsupportedMedia(
            "", detail=f"that URL redirected to {location}, which was not followed"
        )

    content_type = response.headers.get("content-type", "")
    media_type = content_type.split(";")[0].strip().lower()
    if not media_type.startswith(_ACCEPTED_PREFIXES):
        await response.aclose()
        raise UnsupportedMedia(media_type)

    async def chunks() -> AsyncIterator[bytes]:
        # Same shape as `app.py`'s upload `chunks()`: raise from inside the
        # loop, mid-stream, rather than buffering the whole body to measure
        # it first. `aiter_bytes()` is what `stream=True` buys -- the
        # headers above were already read without touching this.
        total = 0
        try:
            async for part in response.aiter_bytes():
                total += len(part)
                if total > max_bytes:
                    raise MediaTooLarge(total)
                yield part
        finally:
            await response.aclose()

    return chunks(), media_type
