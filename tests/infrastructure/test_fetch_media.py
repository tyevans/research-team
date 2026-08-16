"""`fetch_media`: the gated tool over `download_media`.

The transport is `httpx.MockTransport` throughout, as
`test_media_acquisition.py` uses for the primitive this tool shares -- no
test here reaches the network. `download_media`'s own refusal shapes are
already covered there; what is new here is that the tool turns each of them
into distinct, actionable prose rather than letting them propagate -- the
whole reason this module exists as a thin wrapper rather than the primitive
being registered as a tool directly.

`_editor` mirrors `test_media_acquisition.py`'s own `editor` fixture almost
exactly -- same `open_knowledge` stub that is never meant to be called, same
reasoning for why. Not imported from there: pulling a fixture across a
package boundary for one helper would be a stranger dependency than
duplicating five lines that are unlikely to drift, since both copies exist to
assert the same underlying `CorpusEditor.store_media` contract, not to share
behavior.
"""

from uuid import UUID, uuid4

import httpx
import pytest
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.testing import InMemoryTestHarness

from research_team.application.corpus_editing import CorpusEditor
from research_team.domain.corpus import Corpus, MediaRecord
from research_team.infrastructure.agent.fetch_media import build_fetch_media_tool
from research_team.infrastructure.persistence.blob_store import FilesystemBlobStore


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _editor(tmp_path) -> tuple[CorpusEditor, AggregateRepository[Corpus]]:
    corpus_repo: AggregateRepository[Corpus] = AggregateRepository(
        InMemoryTestHarness().event_store, Corpus
    )

    async def open_knowledge(target_project_id: UUID):
        raise NotImplementedError("store_media does not call open_knowledge")

    editor = CorpusEditor(
        open_knowledge=open_knowledge,
        # Never called by `store_media` (see its own docstring: no existence
        # check against text), so a reader that would break if used is the
        # honest stand-in -- matching `test_media_acquisition.py`'s fixture.
        readers=lambda target_project_id: None,
        corpus=corpus_repo,
        blobs=FilesystemBlobStore(tmp_path / "blobs"),
    )
    return editor, corpus_repo


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
async def test_fetching_an_image_stores_it_and_reports_size_and_type(tmp_path):
    """The defect this task exists to fix: a tool that only reported a size
    and a type, with nothing stored, would pass a test that checked only the
    returned string. This asserts the corpus row exists too.
    """
    editor, corpus_repo = _editor(tmp_path)
    project_id = uuid4()
    client = _image_client(body=b"\xff\xd8\xff\xe0" * 100, content_type="image/jpeg")
    tool = build_fetch_media_tool(client=client, editor=editor, project_id=project_id)

    result = await tool.ainvoke({"url": "https://a.example/photo.jpg"})

    assert "400 bytes" in result
    assert "image/jpeg" in result
    assert "https://a.example/photo.jpg" in result

    corpus = await corpus_repo.load_or_create(project_id)
    stored = [
        record for record in corpus.state.documents.values() if isinstance(record, MediaRecord)
    ]
    assert len(stored) == 1
    assert stored[0].uri == "https://a.example/photo.jpg"
    assert stored[0].byte_count == 400


@pytest.mark.asyncio
async def test_fetching_the_same_url_twice_revises_one_row_not_two(tmp_path):
    """`_source_id_for` is deterministic over the URL, so a retried fetch
    (the model asking again, a crash-and-resume) lands on the id it already
    used -- `store_media` revises that record rather than the corpus
    accumulating a second row for one asset.
    """
    editor, corpus_repo = _editor(tmp_path)
    project_id = uuid4()
    client = _image_client(body=b"\xff\xd8\xff", content_type="image/jpeg")
    tool = build_fetch_media_tool(client=client, editor=editor, project_id=project_id)

    await tool.ainvoke({"url": "https://a.example/photo.jpg"})
    await tool.ainvoke({"url": "https://a.example/photo.jpg"})

    corpus = await corpus_repo.load_or_create(project_id)
    stored = [
        record for record in corpus.state.documents.values() if isinstance(record, MediaRecord)
    ]
    assert len(stored) == 1


@pytest.mark.asyncio
async def test_an_unsupported_media_type_is_named_and_told_apart_from_a_move(tmp_path):
    """A model reading this should learn "stop, this is not media" -- not
    something worded so close to a redirect notice that it reads the same.
    """
    editor, corpus_repo = _editor(tmp_path)
    project_id = uuid4()
    client = _html_client()
    tool = build_fetch_media_tool(client=client, editor=editor, project_id=project_id)

    result = await tool.ainvoke({"url": "https://a.example/gallery"})

    assert "text/html" in result
    assert "not image, video or audio" in result
    assert "redirected" not in result
    corpus = await corpus_repo.load_or_create(project_id)
    assert corpus.state.documents == {}


@pytest.mark.asyncio
async def test_a_move_names_the_location_a_model_can_act_on(tmp_path):
    """Told apart from `UnsupportedMedia`: this is something to *act* on, not
    a dead end -- so the notice carries the address to fetch instead.
    """
    editor, corpus_repo = _editor(tmp_path)
    project_id = uuid4()
    client = _redirect_client(location="https://a.example/real.jpg")
    tool = build_fetch_media_tool(client=client, editor=editor, project_id=project_id)

    result = await tool.ainvoke({"url": "https://a.example/moved.jpg"})

    assert "https://a.example/real.jpg" in result
    assert "not followed" in result
    assert "not image, video or audio" not in result
    corpus = await corpus_repo.load_or_create(project_id)
    assert corpus.state.documents == {}


@pytest.mark.asyncio
async def test_media_over_the_ceiling_is_refused_and_named_as_a_ceiling(tmp_path):
    editor, corpus_repo = _editor(tmp_path)
    project_id = uuid4()
    client = _image_client(body=b"\x00" * 1000, content_type="image/png")
    tool = build_fetch_media_tool(
        client=client, editor=editor, project_id=project_id, max_bytes=100
    )

    result = await tool.ainvoke({"url": "https://a.example/huge.png"})

    assert "ceiling" in result
    assert "100" in result
    corpus = await corpus_repo.load_or_create(project_id)
    assert corpus.state.documents == {}


@pytest.mark.asyncio
async def test_a_transport_failure_is_reported_rather_than_raised(tmp_path):
    editor, _corpus_repo = _editor(tmp_path)
    project_id = uuid4()
    client = _unreachable_client()
    tool = build_fetch_media_tool(client=client, editor=editor, project_id=project_id)

    result = await tool.ainvoke({"url": "https://a.example/photo.jpg"})

    assert "Could not reach" in result


def test_building_the_tool_without_a_place_to_store_is_refused(tmp_path):
    """The whole point of this task: there is no build of this tool that
    drains an asset and reports success without storing it. Half-wiring it
    (only one of `editor`/`project_id`) is refused too, not silently treated
    as "no storage" -- that shape is a caller bug, not a valid configuration.
    """
    editor, _corpus_repo = _editor(tmp_path)

    with pytest.raises(RuntimeError):
        build_fetch_media_tool()

    with pytest.raises(RuntimeError):
        build_fetch_media_tool(editor=editor)

    with pytest.raises(RuntimeError):
        build_fetch_media_tool(project_id=uuid4())
