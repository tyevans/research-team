"""The Sources and Ingestion HTTP surface.

Its own module and its own router, for `export.py`, `settings.py`, `catalog.py`,
and `dialogues.py`'s reason: `create_app` is five thousand lines of closures and
modularizing these routes extracts ~750 lines from `app.py`.
"""

import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from eventsource import CommandRejectedError
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from research_team.application.knowledge import ExtractionNote, KnowledgeError
from research_team.application.research.corpus_editing import (
    CorpusEditor,
    DocumentExists,
    NotDropped,
)
from research_team.application.research.corpus_spans import quote
from research_team.application.research.document_extraction import (
    DocumentExtractor,
    UnknownDocument,
)
from research_team.application.research.media_acquisition import MAX_UPLOAD_BYTES
from research_team.application.research.perception import (
    MediaBytesMissing,
    MediaPerceiver,
    NotPerceivable,
    PerceptionPort,
    SourceDropped,
)
from research_team.application.shared.blobs import BlobStorePort
from research_team.infrastructure.persistence import CorpusRunner
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.infrastructure.persistence.read_models import OntologyRunner
from research_team.interfaces.web.extraction import ExtractionActivity
from research_team.interfaces.web.extraction_queue import ExtractionQueue
from research_team.interfaces.web.presenters import (
    source_text_view,
    source_view,
)

UPLOAD_CHUNK_BYTES = 1024 * 1024
"""How much is read from the request per iteration, matching
`FilesystemBlobStore.CHUNK_SIZE` for its reasons."""


def _max_upload_bytes() -> int:
    app_mod = sys.modules.get("research_team.interfaces.web.app")
    if app_mod is not None and hasattr(app_mod, "MAX_UPLOAD_BYTES"):
        return app_mod.MAX_UPLOAD_BYTES
    return MAX_UPLOAD_BYTES


class _UploadTooLarge(Exception):
    """The ceiling was crossed mid-stream. Raised from inside `put`'s loop."""


#: Leading bytes that identify a format, for the cases a browser gets wrong.
#: Deliberately short: this is not a content-type database, it is a correction
#: for `application/octet-stream`, which is what a browser sends for anything
#: the operating system has no association for -- `.mkv` and `.webm` on a bare
#: machine, most often. A format missing from here is stored under whatever the
#: browser said, which is the same behaviour as before sniffing existed.
_MAGIC_NUMBERS: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
    (b"OggS", "audio/ogg"),
    (b"ID3", "audio/mpeg"),
    (b"fLaC", "audio/flac"),
    # EBML, which is Matroska *and* WebM -- the magic number cannot tell them
    # apart, and reading far enough to find the DocType is more parsing than a
    # correction for a wrong header is worth. `video/webm` is the deliberate
    # choice of the two: it is the same container family, it is what a browser
    # will attempt, and being wrong costs a `<video>` that fails on codec
    # rather than one that never tries. `video/x-matroska` would be the
    # honest label for a `.mkv` and Chromium refuses to play it outright, so
    # the accurate answer is the less useful one here.
    (b"\x1a\x45\xdf\xa3", "video/webm"),
)


def _sniff_media_type(head: bytes) -> str | None:
    """What the leading bytes say this is, or `None` if they say nothing.

    The two container formats that cannot be a prefix table are handled first:
    ISO base media (`.mp4`, `.m4a`, `.mov`) puts `ftyp` at offset 4 behind a
    length, and RIFF puts its real form at offset 8.
    """
    if head[4:8] == b"ftyp":
        return "video/mp4"
    if head[:4] == b"RIFF":
        if head[8:12] == b"WAVE":
            return "audio/wav"
        if head[8:12] == b"AVI ":
            return "video/x-msvideo"
        return None
    for prefix, media_type in _MAGIC_NUMBERS:
        if head.startswith(prefix):
            return media_type
    return None


class _RangeNotSatisfiable(Exception):
    """A range starting past the end. 416, with the real length attached."""

    def __init__(self, total: int) -> None:
        super().__init__(f"range starts past the end of {total} bytes")
        self.total = total


def _parse_byte_range(header: str, total: int) -> tuple[int, int] | None:
    """`Range: bytes=…` as an inclusive `(start, end)`, or `None` to ignore it.

    `None` for anything this does not understand -- multiple ranges, a unit
    that is not `bytes`, a malformed header -- because RFC 9110 says a
    recipient that cannot satisfy a Range must ignore it and answer 200 with
    the whole representation. Answering 400 instead would break a client that
    was entitled to ask.

    An end below the start (`bytes=2-1`) is ignored too, and that is a
    distinction worth keeping straight: RFC 9110 §14.1.1 makes a
    `last-byte-pos` below `first-byte-pos` an *invalid* byte-range-spec, and
    an invalid ranges-specifier must be ignored rather than refused. Only a
    range starting at or past the end is genuinely *unsatisfiable*, and that
    is what raises `_RangeNotSatisfiable` -- there the client asked for bytes
    that do not exist and a 200 would silently give it different ones.

    The three forms, all of which a browser sends: `bytes=2-5` (both ends),
    `bytes=2-` (open-ended, what a `<video>` sends first), and `bytes=-500`
    (the last 500 bytes, which is how a player finds an MP4's trailing
    `moov` atom).

    **Every form is decided against `total` in one place, at the bottom.** The
    suffix branch used to return before reaching it, and against a zero-byte
    blob that produced `(0, -1)` and a response header of
    `content-range: bytes 0--1/0` -- not a valid `Content-Range`, and a strict
    client is entitled to call the response broken.
    `test_a_suffix_range_against_an_empty_blob_answers_416` is what fails if
    any branch takes a short cut past the guard again.
    """
    unit, _, spec = header.partition("=")
    if unit.strip().lower() != "bytes" or "," in spec:
        return None
    first, sep, last = spec.strip().partition("-")
    if not sep:
        return None
    try:
        if not first:
            if not last:
                return None
            length = int(last)
            if length <= 0:
                return None
            # Suffix form: the last N bytes, which for a blob shorter than N
            # begins at byte zero. Its end is `None` -- "to the last byte" --
            # rather than `total - 1`, so that an empty blob reaches the
            # unsatisfiable check below instead of arriving there as an end of
            # -1 that looks like the invalid spec it is not.
            start, requested_end = max(0, total - length), None
        else:
            start = int(first)
            requested_end = None if not last else int(last)
    except ValueError:
        return None
    if requested_end is not None and requested_end < start:
        return None
    if start >= total:
        raise _RangeNotSatisfiable(total)
    # An absent end means "to the last byte", and an end past the last byte is
    # clamped rather than refused -- a client that asks for more than there is
    # gets what there is, which is what a player expects.
    return start, total - 1 if requested_end is None else min(requested_end, total - 1)


async def _first_bytes(stream: AsyncIterator[bytes], length: int) -> AsyncIterator[bytes]:
    """The first `length` bytes of a stream, then stop.

    Only the *tail* is trimmed here. The head is `BlobStorePort.open`'s
    `start`, which is a real `seek` -- this used to discard the prefix chunk
    by chunk instead, which made a seek into a 400MB film a ~300MB read, per
    seek, per viewer, while every byte-for-byte test stayed green. The
    trimming that remains cannot be pushed down the same way: the store reads
    in megabyte chunks and a range rarely ends on one.

    What a test would fail on: the arithmetic is off-by-one-prone in both
    directions -- an inclusive end read as exclusive truncates every seek by
    one byte -- and `test_the_range_forms_a_browser_actually_sends` holds it
    at both edges, open-ended, suffix and clamped.
    """
    sent = 0
    async for part in stream:
        remaining = length - sent
        if len(part) >= remaining:
            yield part[:remaining]
            return
        sent += len(part)
        yield part


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


@dataclass(frozen=True)
class SourceDeps:
    """What the source and ingestion routes need from `create_app`'s closure.

    A record rather than a long parameter list, matching `ExportDeps`,
    `SettingsDeps`, and `CatalogDeps`. Everything here is already built in
    `create_app`; nothing is constructed in this module.
    """

    require_project: Callable[[UUID], Awaitable[None]] | None = None
    corpus: CorpusRunner | None = None
    blob_store: BlobStorePort | None = None
    editor: CorpusEditor | None = None
    extractor: DocumentExtractor | None = None
    extract_queue: ExtractionQueue | None = None
    ontology: OntologyRunner | None = None
    perception: PerceptionPort | None = None
    perceiver: MediaPerceiver | None = None
    extraction: ExtractionActivity | None = None
    reader_of: Callable[[UUID], ProjectCorpusReader] | None = None


def source_router(deps: SourceDeps) -> APIRouter:
    router = APIRouter()

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

    def _perception_of(project_id: UUID, source_id: str):
        """A factory the queue can await later -- `_extraction_of`'s shape.

        Returns `None` rather than an `IngestReport`: perception extracts
        nothing, and reporting `entities: 0` for a finished transcription
        would read as "extraction found nothing" instead of "no extraction
        happened". `_drain` omits both counts for a `None`.

        The `failed` note is reported here rather than left to the queue,
        because the queue publishes nothing: without it a perception that
        raised would leave the pane on `perceiving` forever, with the only
        account of the failure sitting in a catch-up route nothing refetches.
        The exception is re-raised so the queue still records the outcome.

        **No route status for `PerceivedTextTooLong`, and that is not an
        omission.** This runs behind the 202 already answered above, so there
        is nothing left to map it to -- B93's ruling. `except Exception`
        below is broad enough to catch it along with everything else this
        path can raise; it lands on the pane as a `failed` note with the cap
        and the actual length in `detail`, the same as any other perception
        failure.
        """
        assert deps.perceiver is not None  # the route guards above

        def _note(note: ExtractionNote) -> None:
            if deps.extraction is not None:
                deps.extraction.reporter(project_id)(note)

        async def run():
            _note(ExtractionNote(source_id=source_id, stage="perceiving"))
            try:
                report = await deps.perceiver.perceive(project_id, source_id)
            except Exception as error:
                _note(ExtractionNote(source_id=source_id, stage="failed", detail=str(error)))
                raise
            _note(
                ExtractionNote(
                    source_id=source_id,
                    stage="perceived",
                    detail=(
                        f"{report.char_count} characters as {report.source_id}"
                        + (
                            f"; {'; '.join(report.degradations)}"
                            if report.degradations
                            else ""
                        )
                    ),
                )
            )
            return None

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

    @router.post("/api/projects/{project_id}/sources/media", status_code=201)
    async def upload_media(
        project_id: UUID,
        file: Annotated[UploadFile, File()],
        source_id: Annotated[str | None, Form()] = None,
        uri: Annotated[str | None, Form()] = None,
        title: Annotated[str | None, Form()] = None,
        note: Annotated[str | None, Form()] = None,
        published_at: Annotated[str | None, Form()] = None,
    ):
        """Store bytes a person is holding: a recording, a scan, a slide deck.

        The media twin of `upload_source`, and multipart rather than JSON for
        the reason the ceiling exists: a base64 field would put a gigabyte
        through a JSON parser and hold it in memory twice over. The bytes go
        to the blob store a megabyte at a time and never accumulate here.

        `source_id` defaults to the filename, because a person uploading
        `keynote.mp4` has already named it and asking twice is friction with
        no payoff. Unlike `upload_source` there is no 409 on a repeat: a
        second store under the same id is a *revision* of a media source, and
        `Corpus.decide` has the only opinion on that -- see
        `CorpusEditor.store_media`, which declines to re-pay the check.

        **Declared ahead of `/sources/{source_id}/drop` and its siblings for
        the reason `extract_all_sources` gives**: FastAPI matches in
        declaration order, and while `media` and `{source_id}/drop` do not
        currently collide, the neighbourhood is one where they have twice.
        """
        await _check_project(project_id)
        head = await file.read(UPLOAD_CHUNK_BYTES)
        media_type = file.content_type
        if not media_type or media_type == "application/octet-stream":
            # Browsers send `application/octet-stream` for plenty of things
            # that are not: it is what they fall back to when the operating
            # system has no association for the extension, which on a bare
            # machine includes `.mkv` and `.webm`. Storing that verbatim would
            # make the content route answer with a type no `<video>` will
            # play, and the record would carry the wrong answer forever --
            # nothing re-sniffs a stored blob.
            media_type = _sniff_media_type(head) or media_type or "application/octet-stream"

        async def chunks() -> AsyncIterator[bytes]:
            """The upload, bounded. See `MAX_UPLOAD_BYTES` on why it raises
            from inside the loop rather than reporting a total afterwards."""
            total = 0
            part = head
            limit = _max_upload_bytes()
            while part:
                total += len(part)
                if total > limit:
                    raise _UploadTooLarge(total)
                yield part
                part = await file.read(UPLOAD_CHUNK_BYTES)

        try:
            record = await _editor().store_media(
                project_id,
                source_id or file.filename or "upload",
                chunks(),
                media_type,
                uri=uri,
                title=title,
                note=note,
                published_at=published_at,
            )
        except _UploadTooLarge as error:
            raise HTTPException(
                status_code=413,
                detail=f"upload exceeds {_max_upload_bytes()} bytes",
            ) from error
        except CommandRejectedError as error:
            # Two of `decide`'s refusals reach here, and only one is a conflict.
            # The first is a `source_id` that already holds *text*, which
            # `_kind_of` will not let media take over -- a real 409. The second
            # is the separator refusal, which is a bad id rather than a clash
            # and would be better as a 400; it is left at 409 because the id on
            # this path comes from the form field or the filename, and a
            # browser does not put a `/` in either, so the case is close to
            # unreachable and splitting the handler would cost more than it
            # buys. If a caller ever hits it, the detail names the `/`.
            # There is no blank-id refusal on this path -- that check
            # lives in `RedstringKnowledge.store_source`, which media
            # deliberately does not go through (`corpus_editing.py`'s module
            # docstring) -- so a form field of `"   "` is stored verbatim as a
            # whitespace id. A literal `""` is unreachable: the fallback chain
            # above takes the filename and then `"upload"`.
            raise HTTPException(status_code=409, detail=str(error)) from error
        return await _source_row(project_id, record.source_id)

    @router.get("/api/projects/{project_id}/sources/{source_id}/content")
    async def read_source_content(project_id: UUID, source_id: str, request: Request):
        """A media source's actual bytes, whole or in ranges.

        Three refusals, and the distinction between the first two is the point:

        - **404** when `read_media` answers `None`. Either no such id, or an
          id that holds *text* -- a text source's bytes live in the event log,
          not the blob store, so this is the wrong route for it rather than a
          thing that has gone missing.
        - **410** when the record is here and its blob is not. A dangling
          reference is a real and different state, and an operator told 404
          goes looking for an ingest that never happened instead of for bytes
          that went away.
        - **416** for a range starting past the end, with `Content-Range:
          bytes */<length>` so the client can correct itself in one round trip.

        Range support lands here rather than with the citation slice that
        needs it, because without it a `<video>` will not seek: Chromium
        treats a response with no `Accept-Ranges` as unseekable and downloads
        the whole file before it will play at all. The alternative was
        shipping a player that stalls on a two-hour recording and calling it
        a later task.

        `include_dropped=True`, matching `read_source`: the console lists
        dropped rows and lets you open one, and refusing to play the recording
        somebody is deciding whether to restore is refusing at exactly the
        wrong moment.
        """
        await _check_project(project_id)
        handle = await _reader(project_id).read_media(source_id, include_dropped=True)
        if handle is None:
            raise HTTPException(
                status_code=404,
                detail=f"no media source {source_id!r} in project {project_id}",
            )
        if handle.stat is None:
            raise HTTPException(
                status_code=410,
                detail=f"the bytes for {source_id!r} are no longer stored",
            )
        total = handle.stat.byte_count
        headers = {"Accept-Ranges": "bytes"}
        requested = request.headers.get("range")
        span = None
        if requested:
            try:
                span = _parse_byte_range(requested, total)
            except _RangeNotSatisfiable as error:
                raise HTTPException(
                    status_code=416,
                    detail=str(error),
                    headers={"Content-Range": f"bytes */{total}", "Accept-Ranges": "bytes"},
                ) from error
        if span is None:
            headers["Content-Length"] = str(total)
            return StreamingResponse(
                handle.open(), media_type=handle.record.media_type, headers=headers
            )
        start, end = span
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
        headers["Content-Length"] = str(end - start + 1)
        return StreamingResponse(
            # `open(start)` seeks; `_first_bytes` trims the tail. Reading from
            # zero and discarding would answer identically and cost the whole
            # prefix -- see `BlobStorePort.open`.
            _first_bytes(handle.open(start), end - start + 1),
            status_code=206,
            media_type=handle.record.media_type,
            headers=headers,
        )

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

    @router.post("/api/projects/{project_id}/sources/perceive")
    async def perceive_all_sources(project_id: UUID):
        """Queue every stored medium with no transcript. 202, none of it has run.

        B94's remaining half, and the caller `MediaPerceiver.unperceived` was
        written for -- that method's docstring has said "this has no caller yet"
        since it shipped, and described the rule this route now runs rather than
        one anything ran. **Read it before changing the set here**: the
        exclusions are subtle in one direction (a dropped medium is not a
        candidate) and subtle in the other (a dropped *transcript* still counts
        its parent as perceived, because superseding a derived source erases the
        drop and returns it to extraction).

        Registered inside the literal-segment block for that block's reason:
        `perceive` would otherwise be read as a `{source_id}` by
        `/sources/{source_id}/perceive` one screen down.

        **The capability check is here and the per-source refusals are not**,
        which is the one place this diverges from its neighbour
        `perceive_source`. That route resolves the id first so a typo, a text
        id, a dropped source and a missing blob each get their own status --
        a distinction worth drawing for a press aimed at one row. Here the set
        comes from the corpus rather than from a caller, so there is no id to be
        wrong about, and resolving every medium up front would read every blob's
        record to answer a question the enqueue is about to ask again. A medium
        whose bytes have gone reports `failed` on the pane, which is where the
        rest of a batch's failures already land. An install with no model at all
        still refuses the press, for `perceive_source`'s reason: accepting work
        it cannot do and failing a minute later is worse than a refusal.

        `queued` counts what this press took on, not what was asked for -- the
        queue refuses a medium it already holds, so a second press while the
        first drains answers 0 rather than claiming to have started it again.
        """
        if deps.perceiver is None or deps.perception is None or deps.extract_queue is None:
            raise HTTPException(status_code=503, detail="perception is not configured")
        await _check_project(project_id)

        capabilities = deps.perception.capabilities()
        if not capabilities.any_model():
            raise HTTPException(
                status_code=503,
                detail=(
                    "this install cannot perceive media: " + "; ".join(capabilities.missing())
                ),
            )

        pending = await deps.perceiver.unperceived(project_id)
        queued = [
            source_id
            for source_id in pending
            if deps.extract_queue.start(
                project_id, source_id, _perception_of(project_id, source_id)
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

    @router.post("/api/projects/{project_id}/sources/{source_id}/perceive")
    async def perceive_source(project_id: UUID, source_id: str):
        """Queue one stored medium for perception. 202, because it has not run.

        **Queued rather than run inline, and through the extraction queue
        rather than one of its own.** Transcribing an hour of audio takes
        minutes, which is longer than any client should hold a connection, and
        it is the same kind of slow thing happening to the same source rows --
        so it reports through `ExtractionActivity` (stages `perceiving` and
        `perceived`) and waits behind whatever else that project has running.
        A second pane and a second queue would be a second thing to watch and
        a second thing to cancel, for one workflow. See `extraction_queue.py`.

        **Everything that can be refused is refused here, before the enqueue.**
        A 404 delivered later through a progress pane is a 404 nobody connects
        to the button they pressed. `perceiver.resolve` is what draws the four
        source-side distinctions -- it is the same call `perceive` makes when
        the job starts, so the route and the job cannot drift -- and the
        capability check is separate because it is not about this source at
        all. The mapping:

        - **404** no such media source. A typo, or an ingest that never ran.
        - **409** the id holds text. There is nothing in prose to perceive,
          and this is not the same mistake as a typo.
        - **409** the source was dropped, with the reason. It exists and
          somebody excluded it on purpose; restoring it is the operator's move
          and the detail says so, because "no such source" would send them
          looking for an ingest that did happen.
        - **410** the record is here and its blob is not, matching what
          `/content` already answers for the same dangling reference one click
          away.
        - **503** this install has no vision model and no transcriber, naming
          which, because a refusal that can only say "not configured" sends
          nobody anywhere. Not 501: the route exists and the install is short
          of something an operator can supply.

        The capability check is synchronous (`capabilities()` is, on purpose)
        and happens at the route rather than in the job, so an unconfigured
        install refuses the press instead of accepting work it cannot do and
        failing a minute later.

        `queued: false` is still a 202, for `extract_source`'s reason: the
        medium *is* going to be perceived, because it is already queued.
        """
        if deps.perceiver is None or deps.perception is None or deps.extract_queue is None:
            raise HTTPException(status_code=503, detail="perception is not configured")
        await _check_project(project_id)
        try:
            await deps.perceiver.resolve(project_id, source_id)
        except UnknownDocument as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except NotPerceivable as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except SourceDropped as error:
            raise HTTPException(
                status_code=409,
                detail=f"{error}; restore it first if it should inform this project",
            ) from error
        except MediaBytesMissing as error:
            raise HTTPException(status_code=410, detail=str(error)) from error

        capabilities = deps.perception.capabilities()
        if not capabilities.any_model():
            raise HTTPException(
                status_code=503,
                detail=(
                    "this install cannot perceive media: " + "; ".join(capabilities.missing())
                ),
            )

        queued = deps.extract_queue.start(
            project_id, source_id, _perception_of(project_id, source_id)
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
