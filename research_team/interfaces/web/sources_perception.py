"""Media perception analysis and transcription HTTP routes."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from research_team.interfaces.web.source_deps import SourceDeps
from research_team.knowledge.application import ExtractionNote
from research_team.research.application.document_extraction import UnknownDocument
from research_team.research.application.perception import (
    MediaBytesMissing,
    NotPerceivable,
    SourceDropped,
)

__all__ = [
    "sources_perception_router",
]


def _perception_of(deps: SourceDeps, project_id: UUID, source_id: str):
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
                    + (f"; {'; '.join(report.degradations)}" if report.degradations else "")
                ),
            )
        )
        return None

    return run


def sources_perception_router(
    deps: SourceDeps,
    check_project: Callable[[UUID], Awaitable[None]],
) -> APIRouter:
    """Router for media perception routes."""
    router = APIRouter()

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
        await check_project(project_id)

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
                project_id, source_id, _perception_of(deps, project_id, source_id)
            )
        ]
        return JSONResponse(
            status_code=202,
            content={"queued": len(queued), "source_ids": queued},
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
        await check_project(project_id)
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
            project_id, source_id, _perception_of(deps, project_id, source_id)
        )
        return JSONResponse(
            status_code=202, content={"queued": queued, "source_id": source_id}
        )

    return router
