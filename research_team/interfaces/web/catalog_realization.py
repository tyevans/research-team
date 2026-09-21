"""Course realization, abandonment, and authored unit inspection routes.

Extracted from catalog.py to isolate course realization lifecycle and
rendered unit/lesson inspection from catalog browsing and background sweeps.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from eventsource.domain import CommandRejectedError
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from research_team.curriculum.application.course_catalog import Catalog
from research_team.curriculum.application.frontmatter import parse_frontmatter
from research_team.curriculum.domain.course import (
    AbandonCourse,
    RealizeCourse,
    course_stream_id,
)
from research_team.interfaces.web.authored_files import (
    is_path_file,
    path_file,
    split_area,
)
from research_team.interfaces.web.authoring import RunAlreadyActive
from research_team.interfaces.web.curriculum import (
    _author_one_target,
    _authoring_holder,
)

if TYPE_CHECKING:
    from research_team.interfaces.web.catalog import CatalogDeps

CatalogGetter = Callable[..., Awaitable[Catalog]]


def course_realization_router(
    deps: "CatalogDeps",
    get_catalog: CatalogGetter,
) -> APIRouter:
    """Routes governing course realization, abandonment, and authored unit reading."""
    router = APIRouter()

    @router.get("/api/projects/{project_id}/catalog/{slug}/unit")
    async def read_course_unit(project_id: UUID, slug: str):
        """The markdown the authoring turns wrote for this course, as text a
        browser renders -- not as an attachment.

        **The gap this closes.** Everything downstream of `realize` already
        worked: the three UbD turns write `/course/areas/<slug>/unit.md` and
        its lessons into their session's workspace, `authoring_runs` records
        which session that was, and `export.py` resolves both. But every route
        that read those files set `Content-Disposition` -- that module's own
        docstring says none of them "returns a body a browser would render in
        place" -- so a realized course's page could offer a download or a link
        into the agent transcript and nothing else. A product whose stated end
        is "where learners go to learn" terminated in a zip file.

        **Three states, and they are the point of the shape below.**
        `CourseDetail.outline` deliberately conflates "the model refused" with
        "nothing has generated one yet", and its docstring argues that is fine
        because both render as "no outline yet". That argument does not
        survive being applied to a whole course: a reader who lands on
        "nothing here" must be able to tell *nobody has written this* from
        *it is being written right now*, because the first is a button to
        press and the second is a reason to wait. So `state` is explicit --
        `authored`, `authoring`, `unauthored` -- rather than inferred by a
        client from a null field.

        **The order the states are decided in, and what it costs.** Files
        first: if a session recorded against this slug holds course markdown,
        that is `authored`, *even while a later run is rewriting it*. The
        alternative was to let an in-flight run win and show a spinner over a
        course that exists and is readable, which trades a reader's whole
        course for a progress indicator they can already see in the authoring
        panel. The cost is that a re-author in progress is invisible from this
        payload alone; that is deliberate, and the run panel is where it
        shows.

        A recorded session that holds *no* files under the prefix falls
        through to the run check rather than answering `authored` with
        nothing in it. An empty `authored` would be the same silence this
        route exists to end, wearing the word that means the opposite.

        **`authoring` requires the slug to be among a live run's targets**,
        not merely that some run is live. A path run over eight other areas
        tells this reader nothing about theirs, and "being written right now"
        about a course nobody queued is a promise the system will not keep.

        **`unitPath` is here so the console can render widgets.** The lessons
        already carried their workspace paths; the unit carried only its text,
        because the first reader of this payload put both through a plain
        markdown renderer. That reader was wrong -- a lesson's
        ```component:mcq``` fence is not markdown, and rendering it as one
        prints the widget's yaml source as a code block. The console now asks
        `GET /api/sessions/{id}/files/parsed` for each file, which needs a
        session id and a *path*, and the unit had no path to give. Measured on
        2026-08-24 against the `resolution` course: 19 component blocks, 10 of
        them in the unit, so a fix that reached only the lessons would have
        left more than half of them raw.

        503 when authoring is unwired, matching `read_course_detail` beside
        it: a build with no authoring cannot answer any of the three states
        truthfully, and `unauthored` would read as a fact about the course.
        `service.load` raising for a session id the table names is left to
        propagate -- a recorded session that cannot be opened is a broken
        record, and answering `unauthored` would file it as ordinary absence.
        """
        await deps.require_project(project_id)
        if deps.authoring is None:
            raise HTTPException(status_code=503, detail="course authoring is not configured")

        session_id = await deps.authoring.authored_session_for(project_id, slug)
        if session_id is not None:
            session = await deps.service.load(session_id)
            if is_path_file(session, slug):
                entry = session.state.files.get(path_file(slug)) or {}
                _, body = parse_frontmatter(entry.get("content", ""))
                return {
                    "slug": slug,
                    "state": "authored",
                    "sessionId": str(session_id),
                    "unitPath": path_file(slug),
                    "unit": body,
                    "lessons": [],
                }
            unit, lessons = split_area(session, slug)
            if unit is not None or lessons:
                return {
                    "slug": slug,
                    "state": "authored",
                    "sessionId": str(session_id),
                    "unitPath": None if unit is None else unit[0],
                    "unit": None if unit is None else parse_frontmatter(unit[1])[1],
                    "lessons": [
                        {"path": path, "markdown": parse_frontmatter(content)[1]}
                        for path, content in lessons
                    ],
                }

        live = deps.authoring.active(project_id)
        if live is not None and slug in (live.get("targets") or []):
            return {
                "slug": slug,
                "state": "authoring",
                "sessionId": None,
                "unitPath": None,
                "unit": None,
                "lessons": [],
            }

        return {
            "slug": slug,
            "state": "unauthored",
            "sessionId": None,
            "unitPath": None,
            "unit": None,
            "lessons": [],
        }

    @router.post("/api/projects/{project_id}/catalog/{slug}/realize", status_code=202)
    async def realize_course(project_id: UUID, slug: str):
        """Record that a person has decided this cluster is a course, then
        try to start writing it.

        **The decision is appended first, unconditionally on the slug naming
        a current candidate and not already being realized.** Authoring is
        then attempted, and `RunAlreadyActive` is caught rather than left to
        become this route's own 409 -- see the module's Task 9 brief: whether
        a person can *choose* a course must not depend on whether someone
        else's authoring run happens to be in flight. `authoring` is `None`
        and `reason` is set on that path; a caller invalidates the run panel
        on the next `curriculum/author` attempt rather than reading a frame
        from this response.

        **The frozen membership is the area's full membership, not its
        anchors** -- `CourseCandidate.anchors` is capped at 12 (Task 9's
        brief), and freezing that would make every course's fit report drift
        that is an artifact of the cap rather than a fact about the cluster.
        404 for a slug naming no current candidate; 409 when `decide` refuses
        a second `RealizeCourse` on an already-realized stream.
        """
        await deps.require_project(project_id)
        if deps.course_repository is None:
            raise HTTPException(status_code=503, detail="course realization is not configured")
        built = await deps.curriculum_of(project_id)
        catalog_built = await get_catalog(deps, project_id, include_unnamed=True)
        candidate = next((c for c in catalog_built.all_candidates if c.slug == slug), None)
        if candidate is None:
            raise HTTPException(status_code=404, detail=f"no course {slug!r}")

        area = built.area(slug)
        member_ids = tuple(m.entity_id for m in area.members) if area is not None else ()

        aggregate = await deps.course_repository.load_or_create(
            course_stream_id(project_id, slug).aggregate_id
        )
        try:
            aggregate.execute(
                RealizeCourse(
                    project_id=project_id,
                    slug=slug,
                    title=candidate.title,
                    member_entity_ids=member_ids,
                    membership_hash=candidate.membership_hash,
                    realized_at=datetime.now(UTC),
                )
            )
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        await deps.course_repository.save(aggregate)

        authoring_frame: dict[str, Any] | None = None
        reason: str | None = None
        held_by: UUID | None = None
        if deps.authoring is None or deps.course_author is None:
            reason = "course authoring is not configured"
        else:
            held_by = await _authoring_holder(deps, project_id)
            if held_by is not None:
                reason = f"this project is held by session {held_by}"
            else:
                subject = (await deps.service.project_state(project_id)).name or str(
                    project_id
                )
                _one = _author_one_target(deps, project_id, built, built.by_slug, subject)
                try:
                    authoring_frame = await deps.authoring.start(
                        project_id, [slug], _one, kind="area"
                    )
                except RunAlreadyActive as error:
                    reason = str(error)

        return JSONResponse(
            status_code=202,
            content={
                "realized": True,
                "authoring": authoring_frame,
                "reason": reason,
                "heldBy": None if held_by is None else str(held_by),
            },
        )

    @router.post("/api/projects/{project_id}/catalog/{slug}/abandon")
    async def abandon_course(project_id: UUID, slug: str):
        """Withdraw the decision that this cluster is a course.

        Does not cancel a running authoring run and does not delete anything
        that run wrote -- the decision is withdrawn, not the work it caused
        (Task 9's brief). 409 when `decide` refuses -- the course was never
        realized, or was already abandoned.
        """
        await deps.require_project(project_id)
        if deps.course_repository is None:
            raise HTTPException(status_code=503, detail="course realization is not configured")
        aggregate = await deps.course_repository.load_or_create(
            course_stream_id(project_id, slug).aggregate_id
        )
        try:
            aggregate.execute(AbandonCourse(project_id=project_id, slug=slug))
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        await deps.course_repository.save(aggregate)
        return {"slug": slug, "realized": False}

    return router
