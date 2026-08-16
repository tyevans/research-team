"""Queueing a stored document for extraction, over HTTP.

Built from doubles rather than the `app_and_client` fixture, following
`test_ask_routes.py`: `create_app` takes every dependency separately, and
these four routes need a corpus runner, a project state and a queue -- none of
which is worth starting a real application and a real projection to obtain.
What they do *not* need is a model, which is the point: nothing here extracts
anything.

The 202s are the interesting part. Both POSTs answer 202 rather than 409 for
`dispatch_topic`'s reason -- a control on every row must not usually refuse --
and both distinguish "queued by this press" from "already going", which is
what lets the page avoid claiming it started something it did not.
"""

from dataclasses import dataclass
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.application.document_extraction import DocumentExtractor
from research_team.application.knowledge import IngestReport, SourceRef
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.infrastructure.persistence.read_models import CorpusDocumentRow
from research_team.interfaces.web.app import create_app
from research_team.interfaces.web.extraction_queue import ExtractionQueue

PROJECT = UUID("11111111-1111-1111-1111-111111111111")

_UNUSED_BLOBS = object()
"""No route exercised here reads media, so `read_media` is never called -- a
real `BlobStorePort` would be dead weight in a file about extraction queues."""


@dataclass
class _State:
    status: str = "created"


class Service:
    """Just enough for `_require_project`: a project that exists, or does not."""

    def __init__(self, *, exists: bool = True) -> None:
        self._exists = exists

    async def project_state(self, project_id: UUID) -> _State:
        return _State(status="created" if self._exists else "new")


class Runner:
    """Stands in for `CorpusRunner` behind `ProjectCorpusReader`."""

    def __init__(self, *documents: tuple[str, bool]) -> None:
        self._rows = {
            source_id: CorpusDocumentRow(
                id=CorpusDocumentRow.row_id(PROJECT, source_id),
                project_id=PROJECT,
                source_id=source_id,
                sha256="0" * 64,
                char_count=3,
                text="abc",
                extracted_at="2026-01-01T00:00:00+00:00" if extracted else None,
            )
            for source_id, extracted in documents
        }

    async def get(self, project_id: UUID, source_id: str, *, include_dropped: bool = False):
        return self._rows.get(source_id)

    async def list_all(self, project_id: UUID, *, include_dropped: bool = False):
        """`CorpusRunner.list_all`'s shape: whole rows, text only here -- no
        test in this file stores media, so `self._rows` (all `CorpusDocumentRow`)
        is the entire answer."""
        return list(self._rows.values())


class Knowledge:
    def __init__(self) -> None:
        self.ingested: list[str] = []
        self.indexed: list[str] = []

    async def index(self, source: SourceRef) -> None:
        self.indexed.append(source.source_id)

    async def ingest(self, source: SourceRef, *, report=None) -> IngestReport:
        self.ingested.append(source.source_id)
        return IngestReport(
            source_id=source.source_id,
            entity_count=1,
            relationship_count=0,
            domain=None,
            domain_confidence=None,
        )


def _app(runner: Runner, queue: ExtractionQueue, *, knowledge=None, exists: bool = True):
    knowledge = knowledge or Knowledge()

    async def open_knowledge(_project_id):
        return knowledge

    return create_app(
        service=Service(exists=exists),
        feed=None,
        turns=None,
        corpus=runner,
        # `create_app` refuses to build a reader without a blob store -- a
        # build wired for text reads but not media reads answers 503 rather
        # than pretending both are wired. The single-source extract route
        # resolves its document through that reader, so omitting this here
        # turns every one of its 404/202 assertions into a 503.
        blob_store=_UNUSED_BLOBS,
        extractor=DocumentExtractor(
            open_knowledge=open_knowledge,
            corpus_readers=lambda project_id: ProjectCorpusReader(
                runner, project_id, _UNUSED_BLOBS
            ),
        ),
        extract_queue=queue,
    )


@pytest.fixture
def queue():
    return ExtractionQueue()


async def _client(api):
    return AsyncClient(transport=ASGITransport(app=api), base_url="http://test")


async def test_queueing_one_document_answers_202_and_extracts_it(queue):
    knowledge = Knowledge()
    api = _app(Runner(("s1", False)), queue, knowledge=knowledge)

    async with await _client(api) as http:
        response = await http.post(f"/api/projects/{PROJECT}/sources/s1/extract")

    assert response.status_code == 202
    assert response.json() == {"queued": True, "source_id": "s1"}

    await queue.wait(PROJECT)
    assert knowledge.ingested == ["s1"]


async def test_queueing_the_same_document_twice_answers_202_and_queued_false(queue):
    """Not a 409: the document *is* going to be extracted, which is what was asked.

    Proved red by returning `True` unconditionally from the route -- the page
    then reports "queued" twice for one piece of work, and a bulk press during
    a drain would claim to have started a corpus it had not.
    """
    knowledge = Knowledge()
    api = _app(Runner(("s1", False)), queue, knowledge=knowledge)

    async with await _client(api) as http:
        first = await http.post(f"/api/projects/{PROJECT}/sources/s1/extract")
        second = await http.post(f"/api/projects/{PROJECT}/sources/s1/extract")

    assert first.json()["queued"] is True
    assert second.status_code == 202
    assert second.json()["queued"] is False

    await queue.wait(PROJECT)
    assert knowledge.ingested == ["s1"]


async def test_an_unknown_source_is_404_and_queues_nothing(queue):
    """The document is resolved by the route, not deferred to the queue.

    Deferred, this would answer 202 and fail minutes later against a row that
    does not exist -- which is to say, nowhere.
    """
    api = _app(Runner(("s1", False)), queue)

    async with await _client(api) as http:
        response = await http.post(f"/api/projects/{PROJECT}/sources/nope/extract")

    assert response.status_code == 404
    assert queue.queued(PROJECT) == ()


async def test_an_unknown_project_is_404(queue):
    api = _app(Runner(("s1", False)), queue, exists=False)

    async with await _client(api) as http:
        response = await http.post(f"/api/projects/{PROJECT}/sources/s1/extract")

    assert response.status_code == 404


async def test_extract_all_takes_only_the_documents_with_no_graph(queue):
    knowledge = Knowledge()
    api = _app(Runner(("s1", True), ("s2", False), ("s3", False)), queue, knowledge=knowledge)

    async with await _client(api) as http:
        response = await http.post(f"/api/projects/{PROJECT}/sources/extract")

    assert response.status_code == 202
    assert response.json() == {"queued": 2, "source_ids": ["s2", "s3"]}

    await queue.wait(PROJECT)
    assert knowledge.ingested == ["s2", "s3"]


async def test_extract_all_pressed_twice_does_not_queue_anything_twice(queue):
    """`queued` counts what this press took on, not what it looked at.

    Proved red by counting `pending` rather than the starts that returned
    True: the second press then answers 3 while queueing nothing, which is the
    one number the page shows.
    """
    knowledge = Knowledge()
    api = _app(Runner(("s1", False), ("s2", False), ("s3", False)), queue, knowledge=knowledge)

    async with await _client(api) as http:
        first = await http.post(f"/api/projects/{PROJECT}/sources/extract")
        second = await http.post(f"/api/projects/{PROJECT}/sources/extract")

    assert first.json()["queued"] == 3
    assert second.json() == {"queued": 0, "source_ids": []}

    await queue.wait(PROJECT)
    assert knowledge.ingested == ["s1", "s2", "s3"]


async def test_the_queue_reads_back_what_is_waiting(queue):
    api = _app(Runner(("s1", False), ("s2", False), ("s3", False)), queue)

    async with await _client(api) as http:
        await http.post(f"/api/projects/{PROJECT}/sources/extract")
        response = await http.get(f"/api/projects/{PROJECT}/sources/extraction-queue")

    body = response.json()
    assert response.status_code == 200
    # Nothing has been given a turn of the loop yet, so all three are still
    # waiting and none is running -- the honest answer at this instant.
    assert body["queued"] == ["s1", "s2", "s3"]
    assert body["running"] is None
    assert body["finished"] == []

    await queue.wait(PROJECT)


async def test_cancelling_says_how_many_went(queue):
    api = _app(Runner(("s1", False), ("s2", False)), queue)

    async with await _client(api) as http:
        await http.post(f"/api/projects/{PROJECT}/sources/extract")
        response = await http.post(f"/api/projects/{PROJECT}/sources/extraction-queue/cancel")

    assert response.json() == {"cancelled": 2}
    await queue.wait(PROJECT)


async def test_a_build_without_extraction_wiring_refuses_the_posts_and_answers_the_read():
    """503 on the writes, empty on the read -- matching `dispatch`'s split.

    A build with no queue has nothing extracting, which is a state rather than
    an error; the POSTs are where a client learns the feature is absent.
    """
    api = create_app(service=Service(), feed=None, turns=None, corpus=Runner(("s1", False)))

    async with await _client(api) as http:
        assert (
            await http.post(f"/api/projects/{PROJECT}/sources/s1/extract")
        ).status_code == 503
        assert (await http.post(f"/api/projects/{PROJECT}/sources/extract")).status_code == 503
        assert (await http.post(f"/api/projects/{PROJECT}/sources/reindex")).status_code == 503
        read = await http.get(f"/api/projects/{PROJECT}/sources/extraction-queue")

    assert read.status_code == 200
    assert read.json() == {"running": None, "queued": [], "finished": []}


async def test_reindex_chunks_every_document_and_answers_200_synchronously(queue):
    """200 with a count, not a 202: chunking makes no model call, so the work
    is finished when the response is written and there is no queue to report
    on. Fails if the route defers to `extract_queue` or filters on
    `extracted`."""
    knowledge = Knowledge()
    api = _app(Runner(("s1", True), ("s2", False)), queue, knowledge=knowledge)

    async with await _client(api) as http:
        response = await http.post(f"/api/projects/{PROJECT}/sources/reindex")

    assert response.status_code == 200
    assert response.json() == {"indexed": 2}
    assert knowledge.indexed == ["s1", "s2"]
    assert knowledge.ingested == []
    assert queue.queued(PROJECT) == ()


async def test_reindex_on_an_unknown_project_is_404(queue):
    """`reindex` is a literal segment declared ahead of `{source_id}`; a 404
    for a *project* here (rather than 'no source "reindex"') is what shows the
    ordering still holds."""
    api = _app(Runner(("s1", False)), queue, exists=False)

    async with await _client(api) as http:
        response = await http.post(f"/api/projects/{PROJECT}/sources/reindex")

    assert response.status_code == 404
