"""`fetch_media`: the gated tool over `download_media`.

The transport is `httpx.MockTransport` throughout, as
`test_media_acquisition.py` uses for the primitive this tool shares -- no
test here reaches the network. `download_media`'s own refusal shapes are
already covered there; what is new here is that the tool turns each of them
into distinct, actionable prose rather than letting them propagate -- the
whole reason this module exists as a thin wrapper rather than the primitive
being registered as a tool directly.
"""

import httpx
import pytest

from research_team.infrastructure.agent.fetch_media import build_fetch_media_tool


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _image_client(body: bytes = b"\xff\xd8\xff", content_type: str = "image/jpeg"):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": content_type}, content=body)

    return _client(handler)


def _html_client():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"<html><body>please log in</body></html>",
        )

    return _client(handler)


def _redirect_client(location: str = "https://a.example/real.jpg"):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": location})

    return _client(handler)


def _unreachable_client():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    return _client(handler)


@pytest.mark.asyncio
async def test_fetching_an_image_reports_its_size_and_type():
    client = _image_client(body=b"\xff\xd8\xff\xe0" * 100, content_type="image/jpeg")
    tool = build_fetch_media_tool(client=client)

    result = await tool.ainvoke({"url": "https://a.example/photo.jpg"})

    assert "400 bytes" in result
    assert "image/jpeg" in result
    assert "https://a.example/photo.jpg" in result


@pytest.mark.asyncio
async def test_an_unsupported_media_type_is_named_and_told_apart_from_a_move():
    """A model reading this should learn "stop, this is not media" -- not
    something worded so close to a redirect notice that it reads the same.
    """
    client = _html_client()
    tool = build_fetch_media_tool(client=client)

    result = await tool.ainvoke({"url": "https://a.example/gallery"})

    assert "text/html" in result
    assert "not image, video or audio" in result
    assert "redirected" not in result


@pytest.mark.asyncio
async def test_a_move_names_the_location_a_model_can_act_on():
    """Told apart from `UnsupportedMedia`: this is something to *act* on, not
    a dead end -- so the notice carries the address to fetch instead.
    """
    client = _redirect_client(location="https://a.example/real.jpg")
    tool = build_fetch_media_tool(client=client)

    result = await tool.ainvoke({"url": "https://a.example/moved.jpg"})

    assert "https://a.example/real.jpg" in result
    assert "not followed" in result
    assert "not image, video or audio" not in result


@pytest.mark.asyncio
async def test_media_over_the_ceiling_is_refused_and_named_as_a_ceiling():
    client = _image_client(body=b"\x00" * 1000, content_type="image/png")
    tool = build_fetch_media_tool(client=client, max_bytes=100)

    result = await tool.ainvoke({"url": "https://a.example/huge.png"})

    assert "ceiling" in result
    assert "100" in result


@pytest.mark.asyncio
async def test_a_transport_failure_is_reported_rather_than_raised():
    client = _unreachable_client()
    tool = build_fetch_media_tool(client=client)

    result = await tool.ainvoke({"url": "https://a.example/photo.jpg"})

    assert "Could not reach" in result
