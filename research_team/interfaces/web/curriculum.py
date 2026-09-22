"""Curriculum projection and authoring HTTP routes.

Extracted from catalog.py to separate curriculum graph navigation and
course authoring orchestration from course catalog browsing, sweeps,
and realization.
"""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from research_team.interfaces.web.authoring import RunAlreadyActive
from research_team.interfaces.web.presenters import (
    area_view,
    curriculum_view,
    path_view,
)

if TYPE_CHECKING:
    from research_team.interfaces.web.catalog import CatalogDeps


class NewAuthoring(BaseModel):
    """Which courses to write, and how long each should be.

    `area` absent means the whole path, which is the ordinary ask and so is
    the default rather than a flag. Naming one area is the narrower request,
    and it is the one that has to be spelled out -- the reverse arrangement
    would make "write everything" the thing a caller reaches by omission from
    a field they have to know exists.

    `lessons` is capped as well as floored. Four model turns per area is the
    fixed cost; a request for forty lessons is four turns asked to produce
    forty files, which no local model does well and which nobody reads. Twelve
    is where a unit stops being a unit.

    `take_over` releases whoever is holding the project first. Off by default
    and spelled the same as `join_project`'s flag, deliberately: a take-over
    ends somebody else's session, and the one thing
    `docs/design/the-holding-session-goes-backstage.md` §1 forbids is a
    console that resolves the lock silently on a person's behalf. The console
    asks first; this is what it sends when the answer is yes.
    """

    area: str | None = None
    lessons: int = Field(default=3, ge=1, le=12)
    take_over: bool = False


def _author_one_target(
    deps: "CatalogDeps",
    project_id: UUID,
    built: Any,
    by_slug: dict,
    subject: str,
    lesson_count: int = 3,
):
    """One target's authoring call, shared by `author_courses`'s run and
    `realize_course`'s single-area run -- one call into `CourseAuthor`,
    not two copies that could drift on what "the path's own slug" means.
    """

    async def _one(run_id: UUID, target: str):
        if deps.course_author is None:
            raise HTTPException(status_code=503, detail="course authoring is not configured")
        if target == built.path.slug:
            return await deps.course_author.author_path(
                project_id, built.path, by_slug, run_id=run_id
            )
        return await deps.course_author.author_area(
            project_id, by_slug[target], subject, lesson_count=lesson_count, run_id=run_id
        )

    return _one


async def _authoring_holder(deps: "CatalogDeps", project_id: UUID) -> UUID | None:
    """Who holds this project, asked because authoring is about to need it."""
    state = await deps.service.project_state(project_id)
    return state.active_session_id


async def _take_over_for_authoring(deps: "CatalogDeps", project_id: UUID) -> None:
    """Release whoever holds this project so an authoring run can join."""
    holder = await _authoring_holder(deps, project_id)
    if holder is None:
        return
    if deps.turns is not None and deps.turns.is_running(holder):
        raise HTTPException(
            status_code=409,
            detail="the holding session has a turn running; cancel it first",
        )
    await deps.service.release_project(holder)


def curriculum_router(deps: "CatalogDeps") -> APIRouter:
    """The curriculum and authoring routes, ready for inclusion into the web app."""
    router = APIRouter()

    @router.get("/api/projects/{project_id}/curriculum")
    async def read_curriculum(project_id: UUID):
        """What this project turned out to be about, and in what order.

        A GET rather than a POST that stores something, because the projection
        is a pure function of a graph already folded from the log -- see
        `domain/learning_area.py` on why none of this is an aggregate. The
        cost of recomputation is paid by `CurriculumService`'s cache, not by
        making the reader ask for a projection and then poll for it.
        """
        await deps.require_project(project_id)
        return curriculum_view(await deps.curriculum_of(project_id))

    @router.get("/api/projects/{project_id}/curriculum/areas/{slug}")
    async def read_learning_area(project_id: UUID, slug: str):
        """One area with its full membership, not just its anchors.

        404 when the slug names no area, and that is the ordinary case rather
        than a fault: a browser holding a slug from a projection taken before
        the graph grew is exactly what a bookmark is.
        """
        await deps.require_project(project_id)
        area = (await deps.curriculum_of(project_id)).area(slug)
        if area is None:
            raise HTTPException(status_code=404, detail=f"no learning area {slug!r}")
        return area_view(area)

    @router.get("/api/projects/{project_id}/curriculum/paths/{slug}")
    async def read_learning_path(project_id: UUID, slug: str):
        """The complete path, or the prerequisite closure of one area.

        `complete` is the whole projection in order; any other slug is read as
        an area id and answered with everything needed to reach it. One route
        rather than two because they are the same object -- a cut of one
        digraph -- and two routes would invite two implementations that could
        disagree about whether A precedes B.
        """
        await deps.require_project(project_id)
        built = await deps.curriculum_of(project_id)
        if slug == built.path.slug:
            return path_view(built.path)
        if deps.curriculum is None:  # pragma: no cover -- `_curriculum` already raised
            raise HTTPException(
                status_code=503, detail="curriculum projection is not configured"
            )
        reader = await deps.graph_reader(project_id) if deps.graph_reader is not None else None
        co_mentions = (
            await deps.co_mentions(project_id) if deps.co_mentions is not None else None
        )
        semantic = await deps.semantic(project_id) if deps.semantic is not None else None
        cut = await deps.curriculum.path_toward(
            project_id,
            slug,
            reader,
            co_mentions,
            semantic,
        )
        if cut is None:
            raise HTTPException(status_code=404, detail=f"no learning area {slug!r}")
        return path_view(cut)

    @router.post("/api/projects/{project_id}/curriculum/author")
    async def author_courses(project_id: UUID, body: NewAuthoring):
        """Write the course for one area, or for every area on the path.

        202, matching `seed_topics`: the turns have not finished when this
        answers. What it hands back is a run that has *begun*, and the files
        it writes arrive over the log like any other `write_file` -- a client
        wanting them invalidates its file list on those frames rather than
        reading this response for them.

        409 when this project already has an authoring run in flight. One at a
        time, refused up front, for `AuthoringActivity`'s reason: a path is up
        to four model turns per area and a second run would interleave with
        the first on the same project.
        """
        if deps.course_author is None or deps.authoring is None:
            raise HTTPException(status_code=503, detail="course authoring is not configured")
        await deps.require_project(project_id)

        # Before the curriculum is folded, because a run that cannot join the
        # project is refused whatever the curriculum says, and folding it
        # first would spend that work on the way to a 409.
        if body.take_over:
            await _take_over_for_authoring(deps, project_id)
        else:
            holder = await _authoring_holder(deps, project_id)
            if holder is not None:
                # 409 naming the holder, not a 202 that dies in the
                # background 30ms later -- see `_authoring_holder` for what
                # that silence measured. The client's next call is this same
                # route with `take_over`, so the refusal names the flag
                # rather than only the problem.
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"this project is held by session {holder}; "
                        "retry with take_over to release it"
                    ),
                )

        built = await deps.curriculum_of(project_id)

        if body.area:
            if built.area(body.area) is None:
                raise HTTPException(status_code=404, detail=f"no learning area {body.area!r}")
            targets = [body.area]
        else:
            targets = list(built.path.area_slugs)
        if not targets:
            # 409 rather than 202-with-nothing-to-do. A run reported as started
            # over an empty target list settles instantly as "done" and reads,
            # on every surface, exactly like a run that authored everything.
            raise HTTPException(
                status_code=409,
                detail="this project has no learning areas yet; extract some sources first",
            )

        # The path's own overview file, authored last and only when the whole
        # path was asked for. Last because it links every area's `unit.md` and
        # is the one file that is wrong if an area's course does not exist yet;
        # only for a path because a single-area run has no order to write up.
        #
        # Appended to `targets` rather than run after them, so the one place
        # that reports progress reports this too -- a final step that ran
        # outside the target list would leave the panel saying "done" while a
        # model turn was still going.
        if not body.area:
            targets.append(built.path.slug)

        by_slug = built.by_slug
        # The project's own name is the subject every Stage 1 prompt is framed
        # against. Read here rather than passed in by the caller: a client that
        # could name the subject could aim a project's courses at a topic its
        # corpus knows nothing about, and the resulting unit would assess
        # material that is not there.
        subject = (await deps.service.project_state(project_id)).name or str(project_id)

        _one = _author_one_target(deps, project_id, built, by_slug, subject, body.lessons)

        try:
            frame = await deps.authoring.start(
                project_id, targets, _one, kind="area" if body.area else "path"
            )
        except RunAlreadyActive as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return JSONResponse(status_code=202, content=frame)

    @router.post("/api/projects/{project_id}/curriculum/author/cancel")
    async def cancel_authoring(project_id: UUID):
        """Stop this project's authoring run, keeping what it already wrote.

        Answers how many targets it abandoned, matching
        `cancel_extraction_queue` and `cancel_dispatch`, so the caller can say
        "stopped 6" rather than re-reading a status a moment later and
        inferring it. Zero when nothing was running, which is not an error: a
        stop control pressed twice is a person pressing a button, not a bad
        request.

        200 rather than 202, unlike the POST above: cancelling is synchronous
        here. What is *not* synchronous is the run reaching `cancelled` on the
        log -- the driving task appends that on its way out, after the model
        turn it just cancelled unwinds. A caller that re-reads immediately can
        still see `running`, which is why this answers the count rather than
        the frame.
        """
        if deps.authoring is None:
            raise HTTPException(status_code=503, detail="course authoring is not configured")
        await deps.require_project(project_id)
        return {"cancelled": deps.authoring.cancel(project_id)}

    @router.get("/api/projects/{project_id}/curriculum/author")
    async def get_authoring(project_id: UUID):
        """What the running authoring run has done, and the last one's account.

        200 with both halves `None` when nothing has run, matching `get_seed`:
        an absent run is a state, not a missing resource.

        `last` is read from the log rather than from memory, so a run that a
        restart interrupted still answers with the targets it authored and the
        sessions holding them -- reported with status `interrupted`, which is
        neither `done` nor `failed`. See `AuthoringActivity.last`.
        """
        await deps.require_project(project_id)
        if deps.authoring is None:
            return {"current": None, "last": None}
        return {
            "current": deps.authoring.current(project_id),
            "last": await deps.authoring.last(project_id),
        }

    return router
