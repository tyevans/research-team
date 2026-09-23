"""Media upload, streaming, sniffing, and perception HTTP surface."""

from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from eventsource import CommandRejectedError
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.interfaces.web.deps import SourceDeps
from research_team.interfaces.web.media_streaming import (
    _MAGIC_NUMBERS,
    UPLOAD_CHUNK_BYTES,
    _first_bytes,
    _max_upload_bytes,
    _parse_byte_range,
    _RangeNotSatisfiable,
    _sniff_media_type,
    _UploadTooLarge,
)
from research_team.interfaces.web.presenters import source_view
from research_team.interfaces.web.sources_perception import sources_perception_router
from research_team.research.application.corpus_editing import CorpusEditor

__all__ = [
    "UPLOAD_CHUNK_BYTES",
    "_MAGIC_NUMBERS",
    "SourceDeps",
    "_RangeNotSatisfiable",
    "_UploadTooLarge",
    "_first_bytes",
    "_max_upload_bytes",
    "_parse_byte_range",
    "_sniff_media_type",
    "media_router",
    "sources_perception_router",
]


def media_router(deps: SourceDeps) -> APIRouter:
    """Router for media uploads, byte-range streaming, and perception runs."""
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
        for listing in await _reader(project_id).list_sources(include_dropped=True):
            if listing.record.source_id == source_id:
                return source_view(listing)
        raise HTTPException(status_code=404, detail=f"no document {source_id!r}")

    # Mount perception routes
    router.include_router(sources_perception_router(deps, _check_project))

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

    return router
