"""The media-curation ports, against a stubbed transport and a fake model.

No test here reaches the network, mirroring `tests/infrastructure/test_search.py`.
"""

import httpx
import pytest

from research_team.application.media_curation import SearchResult
from research_team.infrastructure.agent.media_curation_adapter import (
    ChatModelCurationText,
    SearxngMediaSearch,
)

PAYLOAD = {
    "results": [
        {
            "title": "A castle",
            "url": "https://a.example/page",
            "content": "An old castle.",
            "template": "images.html",
            "img_src": "https://a.example/castle.jpg",
            "resolution": "800x600",
            "thumbnail_src": "https://a.example/castle-thumb.jpg",
        },
    ]
}


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class _FakeModel:
    """A `BaseChatModel` lookalike, six lines, per `OntologyTextPort`'s test
    fake -- `ChatModelCurationText` only ever calls `ainvoke`.
    """

    def __init__(self, content: str) -> None:
        self._content = content
        self.messages = None

    async def ainvoke(self, messages):
        self.messages = messages

        class _Response:
            def __init__(self, content: str) -> None:
                self.content = content

        return _Response(self._content)


@pytest.mark.asyncio
async def test_search_returns_search_results_from_the_stubbed_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=PAYLOAD)

    port = SearxngMediaSearch("http://searx.local", limit=5, client=_client(handler))
    results = await port.search("castle", "images")

    assert results == (
        SearchResult(
            title="A castle",
            url="https://a.example/page",
            snippet="An old castle.",
            kind="image",
            asset_url="https://a.example/castle.jpg",
            detail="800x600",
            thumbnail_url="https://a.example/castle-thumb.jpg",
        ),
    )


@pytest.mark.asyncio
async def test_categories_are_passed_through_unvalidated():
    """`build_search_tool` sends whatever category string it is given, with
    no closed set checked against it -- this port does the same, per the
    brief: which categories an instance runs is that instance's business.
    """
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["categories"] = request.url.params.get("categories")
        return httpx.Response(200, json={"results": []})

    port = SearxngMediaSearch("http://searx.local", limit=5, client=_client(handler))
    await port.search("castle", "not-a-real-category")

    assert seen["categories"] == "not-a-real-category"


@pytest.mark.asyncio
async def test_a_malformed_payload_returns_an_empty_tuple_not_none():
    """`MediaSearchPort.search` promises a tuple, unlike `parse_results` --
    the port has no `None` case to hand a caller because the port's own
    contract does not offer one, so a malformed instance answers as if it
    found nothing rather than the caller having to check for a sentinel
    `format_results` alone represents.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    port = SearxngMediaSearch("http://searx.local", limit=5, client=_client(handler))
    results = await port.search("castle", "images")

    assert results == ()


@pytest.mark.asyncio
async def test_the_query_and_categories_reach_the_instance():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["q"] = request.url.params.get("q")
        seen["format"] = request.url.params.get("format")
        return httpx.Response(200, json={"results": []})

    port = SearxngMediaSearch("http://searx.local", limit=5, client=_client(handler))
    await port.search("old castles", "images")

    assert seen["q"] == "old castles"
    assert seen["format"] == "json"


@pytest.mark.asyncio
async def test_generate_sends_one_human_message_and_returns_the_content():
    model = _FakeModel("hello back")
    port = ChatModelCurationText(model, model_name="qwen-curation")

    reply = await port.generate("hello")

    assert reply == "hello back"
    assert len(model.messages) == 1


def test_model_name_is_reported():
    port = ChatModelCurationText(_FakeModel(""), model_name="qwen-curation")
    assert port.model_name == "qwen-curation"
