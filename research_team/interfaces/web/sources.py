"""The Sources and Ingestion HTTP surface.

Its own module and its own router, for `export.py`, `settings.py`, `catalog.py`,
and `dialogues.py`'s reason: `create_app` is five thousand lines of closures and
modularizing these routes extracts ~750 lines from `app.py`.
"""

from typing import Any
from uuid import UUID

from eventsource import CommandRejectedError
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.interfaces.web.presenters import (
    source_text_view,
    source_view,
)
from research_team.interfaces.web.sources_media import (
    UPLOAD_CHUNK_BYTES,
    SourceDeps,
    _first_bytes,
    _max_upload_bytes,
    _parse_byte_range,
    _RangeNotSatisfiable,
    _sniff_media_type,
    _UploadTooLarge,
    media_router,
)
from research_team.knowledge.application import KnowledgeError
from research_team.research.application.corpus_editing import (
    CorpusEditor,
    DocumentExists,
    NotDropped,
)
from research_team.research.application.corpus_spans import quote
from research_team.research.application.document_extraction import (
    UnknownDocument,
)

__all__ = [
    "UPLOAD_CHUNK_BYTES",
    "DropReason",
    "NewSource",
    "SourceDeps",
    "SourceEdit",
    "_RangeNotSatisfiable",
    "_UploadTooLarge",
    "_first_bytes",
    "_max_upload_bytes",
    "_parse_byte_range",
    "_sniff_media_type",
    "media_router",
    "source_router",
]


class NewSource(BaseModel):
    source_id: str
    text: str
    uri: str | None = None
    title: str | None = None
    note: str | None = None
    published_at: str | None = None


class SourceEdit(BaseModel):
    """Every field optional, and `None` means "leave it alone".

    There is deliberately no way to clear a field back to null through
    this: distinguishing "unset" from "set to null" needs a sentinel, and
    the console has no control that asks for it. A caller that wants an
    empty title sends "".
    """

    text: str | None = None
    uri: str | None = None
    title: str | None = None
    note: str | None = None
    published_at: str | None = None


class DropReason(BaseModel):
    reason: str


def source_router(deps: SourceDeps) -> APIRouter:
    router = APIRouter()
    router.include_router(media_router(deps))

    async def _check_project(project_id: UUID) -> None:
        if deps.require_project is not None:
            await deps.require_project(project_id)

    def _reader(project_id: UUID) -> ProjectCorpusReader:
        if deps.reader_of is not None:
            return deps.reader_of(project_id)
        if deps.corpus is None or deps.blob_store is None:
            raise HTTPException(status_code=503, detail="no corpus read model is configured")
        return ProjectCorpusReader(deps.corpus, project_id, deps.blob_store)

    def _editor() -> CorpusEditor:
        if deps.editor is None:
            raise HTTPException(status_code=503, detail="no corpus is configured")
        return deps.editor

    async def _source_row(project_id: UUID, source_id: str) -> dict[str, Any]:
        """The written document, read back through the listing.

        Read back rather than composed from the request, so the answer is what
        the corpus holds rather than what the caller sent -- `sha256` and
        `char_count` are computed in the fold and a client that trusted its own
        echo would render a digest nothing verified.
        """
        for listing in await _reader(project_id).list_sources(include_dropped=True):
            if listing.record.source_id == source_id:
                return source_view(listing)
        raise HTTPException(status_code=404, detail=f"no document {source_id!r}")

    def _extraction_of(project_id: UUID, source_id: str):
        """A factory the queue can await later, closing over nothing mutable.

        Deliberately not the coroutine itself: an item that waits in the deque
        for a minute would otherwise be a live coroutine nobody has awaited,
        and one dropped by `cancel` would be one nobody ever will.
        """
        assert deps.extractor is not None  # both call sites guard above

        async def run():
            return await deps.extractor.extract(project_id, source_id)

        return run

    @router.post("/api/projects/{project_id}/sources", status_code=201)
    async def upload_source(project_id: UUID, body: NewSource):
        """Store a document a person is holding, rather than one an agent found.

        Every other way into this corpus is an agent path -- `remember`,
        `remember_page`, the automatic keep on `fetch` -- and this is the
        first that is not.
        """
        await _check_project(project_id)
        try:
            await _editor().store(
                project_id,
                body.source_id,
                body.text,
                uri=body.uri,
                title=body.title,
                note=body.note,
                published_at=body.published_at,
            )
        except DocumentExists as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except KnowledgeError as error:
            # The blank-id refusal and the length cap, both `store_source`'s.
            raise HTTPException(status_code=400, detail=str(error)) from error
        except CommandRejectedError as error:
            # `decide`'s separator refusal: a `source_id` holding a `/` would be
            # stored and then unreachable, because every route naming a source
            # spends it as one path segment. 400 beside the blank-id refusal
            # rather than 409 -- nothing conflicts, the id is simply not one
            # this API can address. The media route maps the same exception to
            # 409 because there it means a kind clash with a document that
            # exists, which genuinely is a conflict.
            raise HTTPException(status_code=400, detail=str(error)) from error
        return await _source_row(project_id, body.source_id)

    @router.post("/api/projects/{project_id}/sources/{source_id}/drop")
    async def drop_source(project_id: UUID, source_id: str, body: DropReason):
        await _check_project(project_id)
        try:
            await _editor().drop(project_id, source_id, body.reason)
        except UnknownDocument as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except CommandRejectedError as error:
            # The blank reason and the double drop, both the aggregate's.
            raise HTTPException(status_code=409, detail=str(error)) from error
        return await _source_row(project_id, source_id)

    @router.post("/api/projects/{project_id}/sources/{source_id}/restore")
    async def restore_source(project_id: UUID, source_id: str):
        await _check_project(project_id)
        try:
            await _editor().restore(project_id, source_id)
        except UnknownDocument as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except NotDropped as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except CommandRejectedError as error:
            # `Corpus.decide`'s refusal for a `StoreSourceDocument` or
            # `StoreDerivedText` this restore re-stores. No reachable case
            # exists today -- the derivedness guards that could have
            # triggered this were fixed before this arm was needed -- but
            # the next guard added to either command would otherwise land
            # here as an unhandled exception and a 500, matching
            # `upload_source`'s pattern.
            raise HTTPException(status_code=409, detail=str(error)) from error
        return await _source_row(project_id, source_id)

    @router.patch("/api/projects/{project_id}/sources/{source_id}")
    async def revise_source(project_id: UUID, source_id: str, body: SourceEdit):
        await _check_project(project_id)
        try:
            await _editor().revise(
                project_id,
                source_id,
                text=body.text,
                uri=body.uri,
                title=body.title,
                note=body.note,
                published_at=body.published_at,
            )
        except UnknownDocument as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except CommandRejectedError as error:
            # `decide`'s refusal, which `KnowledgeError` below does not
            # catch. No reachable case exists today -- the derivedness
            # guards that could have triggered this were fixed before this
            # arm was needed -- but the next guard on
            # `StoreSourceDocument`/`StoreSourceMedia`/`StoreDerivedText`
            # would otherwise land here as an unhandled exception and a 500,
            # matching `upload_source`'s pattern.
            raise HTTPException(status_code=409, detail=str(error)) from error
        except KnowledgeError as error:
            # Two guards reach here, and `decide` is neither of them. `_store`'s
            # length cap: missing until review, when a PATCH over the cap was an
            # unhandled exception and a 500, where `upload_source` already
            # answered 400 for the same error. And `revise`'s refusal of a
            # `text` against a media id -- that one has no other handler, so
            # `test_patching_text_onto_a_media_source_is_refused` fails here
            # rather than at the editor if this branch narrows.
            raise HTTPException(status_code=400, detail=str(error)) from error
        return await _source_row(project_id, source_id)

    @router.post("/api/projects/{project_id}/sources/extract")
    async def extract_all_sources(project_id: UUID):
        """Queue every stored document that has no graph. 202, none of it has run.

        **This whole block is registered ahead of the `/sources` reads, and has
        to stay there.** FastAPI matches in declaration order, so a literal
        segment that could also be a `{source_id}` must be declared first --
        the reason `dispatch_topic` gives. Two collisions are live here, and
        the second was found by a test rather than by reading: `extract` would
        be read as a `source_id` by `/sources/{source_id}/extract`, and
        `extraction-queue` would be read as one by `GET
        /sources/{source_id}`, which answered 404 "no such source" for the
        catch-up route until these moved above it.

        `queued` counts what this press actually took on, not what was asked
        for -- the queue refuses a document it already holds, so pressing this
        twice while the first pass drains answers 0 the second time rather
        than claiming to have started the same work again.

        The set is computed here rather than inside the queue because it is a
        corpus question, and the queue deliberately knows nothing about
        corpora. It is computed once, at press time: a document extracted by
        something else while this queue drains is still in the deque and will
        be extracted again. Harmless -- extraction is idempotent in effect --
        and cheaper than re-asking the projection before every item.
        """
        if deps.extractor is None or deps.extract_queue is None:
            raise HTTPException(
                status_code=503, detail="document extraction is not configured"
            )
        await _check_project(project_id)
        pending = await deps.extractor.unextracted(project_id)
        queued = [
            source_id
            for source_id in pending
            if deps.extract_queue.start(
                project_id, source_id, _extraction_of(project_id, source_id)
            )
        ]
        return JSONResponse(
            status_code=202,
            content={"queued": len(queued), "source_ids": queued},
        )

    @router.post("/api/projects/{project_id}/sources/reindex")
    async def reindex_sources(project_id: UUID):
        """Chunk every stored document again, and say how many. 200, it has run.

        Registered inside the literal-segment block above for that block's
        reason: `reindex` would otherwise be read as a `{source_id}`.

        200 and not 202, unlike its `extract` neighbours: chunking makes no
        model call, so there is nothing to queue and the work is finished when
        this answers. See `DocumentExtractor.reindex` for what that costs on a
        large corpus and why the queue was not worth building anyway.

        The repair this exists for is a corpus stored before chunk indexing
        shipped: it has no `DocumentChunked` events, so replay leaves its chunk
        store empty and every entity reads as unmentioned.
        `/api/corpus/rebuild` does not help -- it rebuilds the corpus documents
        table, which is derived from the log, where these chunks are not.

        Safe at any time: `index` is idempotent through the adapter's event
        store, so a second run on an unchanged corpus rewrites nothing.
        """
        if deps.extractor is None:
            raise HTTPException(
                status_code=503, detail="document extraction is not configured"
            )
        await _check_project(project_id)
        return {"indexed": await deps.extractor.reindex(project_id)}

    @router.get("/api/projects/{project_id}/sources/ungrouped")
    async def ungrouped_sources(project_id: UUID, include_examined: bool = False):
        """Every extracted document no ontology pass has read. 200, it is a read.

        **`include_examined=true` answers a different question on purpose: every
        extracted document, examined or not.** It is what a re-read is driven
        from, and it exists because "examined" is not "correctly examined". A
        pass records a document as read whether the model stated no classes,
        stated some the verifier refused, or stated some in a chunk whose reply
        was unreadable -- `OntologyDiscoveryService.discover` names all three
        and keeps none of them apart on the event. Measured 2026-08-24 on the
        owner's corpus: of two examined documents, one genuinely stated none and
        one stated `interactive components` {mcq, cloze, flashcard} and had it
        dropped because the quoted evidence spanned a hard line wrap and so was
        not found verbatim. Both render as "states no classes" and neither is
        reachable from the default list ever again.

        So the parameter is the cheap half of that fix: it does not make the
        verifier better, it makes a second attempt possible after someone has.
        The expensive half -- a locator that tolerates wrapping -- is a separate
        change, and this one is worth having without it because the model is
        not deterministic either.

        The name is `include_examined` rather than `all`, because it says which
        exclusion is being lifted. The other two -- unextracted, and media --
        still apply, and a re-read wants them to: neither is a document a pass
        could have got wrong.

        Re-reading is safe rather than merely permitted. `OntologyDiscovered`
        replaces a source's classes wholesale and the projection keys on
        `source_id`, so a second pass over a document that already has classes
        supersedes them rather than duplicating them. What it costs is one model
        call per document, which is why nothing does this on a schedule.

        Registered inside the literal-segment block above for that block's
        reason: `ungrouped` would otherwise be read as a `{source_id}` by
        `GET /sources/{source_id}`, which is the bug that block records
        happening twice already.

        **This route is the join `DocumentExtractor.ungrouped` was written
        for.** That method takes `examined` as a parameter rather than fetching
        it, deliberately -- it knows the corpus and the graph, and the ontology
        tables belong to a projection it has no reason to depend on. So the two
        halves have sat in the tree unconnected, with tests on each and nothing
        driving both: `ungrouped()` had no production caller at all, and the
        sweep it describes had never run. That is the `CoMentionPort` shape
        this repository has met before, caught here before it could ship.

        **503 when either half is unwired, not an empty 200**, for
        `read_ontology`'s reason and more sharply. An empty list is the correct
        answer for a corpus that has been fully grouped, so a misconfigured
        build answering the same thing tells a reader "there is nothing left to
        do" about a project nothing has ever examined -- and the control this
        backs would render as finished on exactly the project that needs it
        most.

        `sourceIds` in camelCase, unlike `source_ids` on the extract-all
        neighbour below. The two disagree and this one follows the ontology
        payloads it is read beside; the neighbour is not changed here because
        its shape is already in a client.
        """
        if deps.extractor is None or deps.ontology is None:
            raise HTTPException(status_code=503, detail="ontology discovery is not configured")
        await _check_project(project_id)
        examined: set[str] = set()
        if not include_examined:
            examined = await deps.ontology.sources_with_classes(project_id)
        pending = await deps.extractor.ungrouped(project_id, examined=examined)
        return {"sourceIds": list(pending)}

    @router.post("/api/projects/{project_id}/sources/{source_id}/extract")
    async def extract_source(project_id: UUID, source_id: str):
        """Queue one stored document for extraction. 202, because it has not run.

        202 with `queued` rather than 409 when the project is busy, for
        `dispatch_topic`'s reason: this backs a control on every document row,
        and a control that usually refuses is a control people stop pressing.

        The document is read here -- not left for the queue -- so an unknown
        `source_id` is a 404 the caller can see. Deferred, it would fail
        asynchronously against a row that does not exist.

        `queued: false` is a 202 rather than a 409: the document *is* going to
        be extracted, because it is already in the queue or already running,
        which is what the caller wanted. Saying so plainly lets the client
        avoid claiming it started something it did not.
        """
        if deps.extractor is None or deps.extract_queue is None:
            raise HTTPException(
                status_code=503, detail="document extraction is not configured"
            )
        await _check_project(project_id)
        if await _reader(project_id).read_document(source_id) is None:
            raise HTTPException(
                status_code=404, detail=f"no source {source_id!r} in project {project_id}"
            )
        queued = deps.extract_queue.start(
            project_id, source_id, _extraction_of(project_id, source_id)
        )
        return JSONResponse(
            status_code=202, content={"queued": queued, "source_id": source_id}
        )

    @router.get("/api/projects/{project_id}/sources/extraction-queue")
    async def get_extraction_queue(project_id: UUID):
        """What is extracting, what is waiting, and how each document's last one went.

        The catch-up read the queue cannot do without, and -- unlike
        `/dispatch` -- the *only* read: this queue publishes no frames, because
        `ExtractionActivity` already carries the running item's progress over
        the live feed. See `extraction_queue.py` on what that leaves stale.

        Three empty answers rather than a 503 when unwired, matching
        `get_dispatch`: a build with no queue has nothing extracting, which is
        a state and not an error. The POSTs above are where a client learns the
        feature is absent.
        """
        await _check_project(project_id)
        if deps.extract_queue is None:
            return {"running": None, "queued": [], "finished": []}
        return {
            "running": deps.extract_queue.current(project_id),
            "queued": list(deps.extract_queue.queued(project_id)),
            "finished": deps.extract_queue.finished(project_id),
        }

    @router.post("/api/projects/{project_id}/sources/extraction-queue/cancel")
    async def cancel_extraction_queue(project_id: UUID):
        """Stop the running extraction and drop everything waiting, for this project.

        Answers how many went, matching `cancel_dispatch`, so the caller can
        say "stopped 12" rather than guessing from a queue it re-reads a moment
        later.
        """
        await _check_project(project_id)
        if deps.extract_queue is None:
            raise HTTPException(
                status_code=503, detail="document extraction is not configured"
            )
        return {"cancelled": deps.extract_queue.cancel(project_id)}

    @router.get("/api/projects/{project_id}/sources")
    async def list_sources(project_id: UUID, include_dropped: bool = False):
        """Every source this project has stored. Metadata only, never text.

        `include_dropped` defaults to False, so the agent's own `list_sources`
        tool -- which calls the port behind this route directly, not this
        route -- is unaffected either way; the default here exists only so a
        browser doing the same request the agent's tool makes sees the same
        thing. A caller that opts in sees dropped documents too, each with
        the reason it was excluded: the corpus keeps them for that reason.
        """
        await _check_project(project_id)
        reader = _reader(project_id)
        summaries = await reader.list_sources(include_dropped=include_dropped)
        return [source_view(summary) for summary in summaries]

    @router.get("/api/projects/{project_id}/sources/{source_id}")
    async def read_source(
        project_id: UUID, source_id: str, start: int | None = None, end: int | None = None
    ):
        """One source's text, or a character range of it, with its real offsets.

        The range is clamped rather than validated: `quote` returns what the
        document actually has for the range asked, and the response reports
        those offsets. A caller guessing past the end of a document is the
        ordinary case -- it is how you page through one -- so answering with
        the last characters and honest offsets is more useful than a 422 that
        makes the caller compute the bound it was asking the server for.

        `include_dropped=True`, unlike `list_sources` above: the console lists
        dropped rows and lets you open one, and the reader is where someone
        decides whether to restore it -- refusing to show the text of the
        document being judged is refusing at exactly the wrong moment. The
        agent's own `read_source` tool goes through `ProjectCorpusReader` on a
        different path and keeps the default, so its view of the corpus is
        unchanged.
        """
        reader = _reader(project_id)
        await _check_project(project_id)
        document = await reader.read_document(source_id, include_dropped=True)
        if document is None:
            raise HTTPException(
                status_code=404, detail=f"no source {source_id!r} in project {project_id}"
            )
        text = document.text
        span = quote(text, start or 0, len(text) if end is None else end)
        return source_text_view(document, span)

    return router
