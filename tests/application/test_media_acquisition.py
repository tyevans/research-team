"""`download_media`, against a stubbed transport.

No test here reaches the network -- the transport is `httpx.MockTransport`,
as `tests/infrastructure/test_search.py`'s `_client` does. `download_media` is
shared by the accept worker (Task 11) and a gated agent tool (Task 13), so it
is exercised here once rather than twice downstream.
"""

import httpx
import pytest

from research_team.application.media_acquisition import (
    MediaTooLarge,
    UnsupportedMedia,
    download_media,
)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _html_client() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"<html><body>please log in</body></html>",
        )

    return _client(handler)


def _image_client(body: bytes = b"\xff\xd8\xff", content_type: str = "image/jpeg"):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": content_type}, content=body)

    return _client(handler)


def _redirect_client(location: str = "https://a.example/real.jpg"):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": location})

    return _client(handler)


async def _drain(stream) -> bytes:
    out = b""
    async for part in stream:
        out += part
    return out


async def test_an_html_interstitial_is_a_failure_and_not_a_source():
    """A judged candidate whose URL serves a login page must not become a
    corpus row whose bytes are HTML and whose transcript is empty."""
    with pytest.raises(UnsupportedMedia):
        await download_media(
            "https://a.example/x.jpg", client=_html_client(), max_bytes=10_000
        )


async def test_the_refused_media_type_is_reported():
    try:
        await download_media(
            "https://a.example/x.jpg", client=_html_client(), max_bytes=10_000
        )
        pytest.fail("expected UnsupportedMedia")
    except UnsupportedMedia as error:
        assert error.media_type == "text/html"


async def test_an_image_content_type_is_accepted():
    stream, media_type = await download_media(
        "https://a.example/x.jpg", client=_image_client(), max_bytes=10_000
    )
    assert media_type == "image/jpeg"
    assert await _drain(stream) == b"\xff\xd8\xff"


async def test_video_and_audio_are_also_accepted():
    for content_type in ("video/mp4", "audio/mpeg"):
        stream, media_type = await download_media(
            "https://a.example/x",
            client=_image_client(content_type=content_type),
            max_bytes=10_000,
        )
        assert media_type == content_type
        assert await _drain(stream) == b"\xff\xd8\xff"


async def test_a_body_over_the_ceiling_is_refused():
    body = b"a" * 20
    with pytest.raises(MediaTooLarge):
        stream, _ = await download_media(
            "https://a.example/x.jpg", client=_image_client(body=body), max_bytes=10
        )
        await _drain(stream)


async def test_a_redirect_is_reported_rather_than_followed():
    """Mirrors `fetch.py`'s decision on the read side: a redirect is
    reported rather than resolved automatically, so a caller with the
    authority to follow it can decide to. Surfaced as `UnsupportedMedia`
    naming the Location, since there is no media type to report yet.
    """
    with pytest.raises(UnsupportedMedia) as excinfo:
        await download_media(
            "https://a.example/x.jpg", client=_redirect_client(), max_bytes=10_000
        )
    assert "https://a.example/real.jpg" in str(excinfo.value)
