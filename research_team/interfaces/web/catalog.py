"""The catalog and curriculum HTTP routes.

Its own module and its own router, for `export.py` and `settings.py`'s reason:
`create_app` is five thousand lines of closures over a few dozen optional
collaborators, and extracting these routes eliminates ~850 lines of monolithic
route closures from `app.py`.

The cost of the split is the dependency record below: these routes need
several of `create_app`'s closures (`_require_project`, `_curriculum`, etc.)
because they already encode what a 404, 422 and 503 mean here.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from eventsource import AggregateRepository
from eventsource.domain import CommandRejectedError
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from research_team.application.course_authoring import CourseAuthor
from research_team.application.course_catalog import (
    ArtGeneratorPort,
    BlurbTextPort,
    Catalog,
    CatalogService,
    OutlineTextPort,
)
from research_team.application.course_realization import CourseService
from research_team.application.curriculum import CurriculumService
from research_team.application.frontmatter import parse_frontmatter
from research_team.domain.curriculum.course import (
    AbandonCourse,
    Course,
    RealizeCourse,
    course_stream_id,
)
from research_team.infrastructure.knowledge.library_art import LibraryArtProvider
from research_team.infrastructure.persistence.read_models import CatalogFeatureStore
from research_team.interfaces.web.art_sweep import (
    ArtReroll,
    ArtSweep,
    RerollAlreadyActive,
)
from research_team.interfaces.web.art_sweep import SweepAlreadyActive as ArtSweepAlreadyActive
from research_team.interfaces.web.authored_files import (
    is_path_file,
    path_file,
    split_area,
)
from research_team.interfaces.web.authoring import AuthoringActivity, RunAlreadyActive
from research_team.interfaces.web.blurb_sweep import BlurbSweep, SweepAlreadyActive
from research_team.interfaces.web.presenters import (
    area_view,
    catalog_category_view,
    catalog_view,
    course_detail_view,
    curriculum_view,
    path_view,
)


class CatalogFeatureRecorder(Protocol):
    """What a route needs to record one person's featuring decision.

    A protocol rather than the concrete `EventStoreCatalogFeatureRecorder`
    directly, matching `OntologyDiscoveryService`'s own port-facing neighbours
    in this file: the route only ever calls `feature`/`unfeature`, and naming
    the concrete class here would make this interface layer name a class that
    belongs to `infrastructure`.
    """

    async def feature(self, slug: str, rank: int) -> None: ...

    async def unfeature(self, slug: str) -> None: ...


CatalogFeatures = Callable[[], CatalogFeatureStore | None]
"""The read side of course featuring, resolved when a request needs it.

A getter rather than the store itself, matching `app.py`:
`CatalogFeatureStore.open` needs a running event loop, so
`Application.catalog_features` is `None` until `start()`.
"""

CatalogFeatureRecorders = Callable[[UUID], CatalogFeatureRecorder]
"""One project's `CatalogFeatureRecorder`, built on demand."""


class FeatureCourse(BaseModel):
    rank: int = 0


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


@dataclass(frozen=True)
class CatalogDeps:
    """What the catalog and curriculum routes need from `create_app`'s closure.

    A record rather than a long parameter list, so adding another dependency
    does not re-order callers. Everything here is already built in
    `create_app`; nothing is constructed in this module.
    """

    require_project: Callable[[UUID], Awaitable[Any]]
    curriculum_of: Callable[[UUID], Awaitable[Any]]
    service: Any
    turns: Any | None = None
    curriculum: CurriculumService | None = None
    graph_reader: Callable[[UUID], Awaitable[Any]] | None = None
    co_mentions: Callable[[UUID], Awaitable[Any]] | None = None
    semantic: Callable[[UUID], Awaitable[Any]] | None = None
    catalog: CatalogService | None = None
    catalog_features: CatalogFeatures | None = None
    catalog_recorder: CatalogFeatureRecorders | None = None
    course_service: CourseService | None = None
    course_repository: AggregateRepository[Course] | None = None
    course_author: CourseAuthor | None = None
    authoring: AuthoringActivity | None = None
    blurb_sweep: BlurbSweep | None = None
    blurb_writer: BlurbTextPort | None = None
    outline_writer: OutlineTextPort | None = None
    art_sweep: ArtSweep | None = None
    art_reroll: ArtReroll | None = None
    art_generator: ArtGeneratorPort | None = None
    art_matcher: LibraryArtProvider | None = None


async def _catalog(
    deps: CatalogDeps, project_id: UUID, *, include_unnamed: bool = False
) -> Catalog:
    """This project's catalog, assembled over its curriculum and its
    featured overrides.

    503 rather than an empty catalog when `catalog` or `catalog_features`
    is unwired, matching `_curriculum`'s own reasoning: an empty catalog is
    the right answer for a project with no graph, and an unwired build
    answering the same thing would be indistinguishable from that --
    exactly the failure this feature is arranged against.

    `include_unnamed` defaults false, matching the front page's own
    default -- a caller that only needs one candidate by slug (course
    detail, realize) does not care which candidates the front page is
    currently hiding, since a hidden candidate's slug still resolves.
    The sweep route below passes `True` explicitly: it exists to *give*
    unnamed candidates a title, so it is the one caller that must see
    the set the toggle hides.
    """
    if deps.catalog is None or deps.catalog_features is None:
        raise HTTPException(status_code=503, detail="the course catalog is not configured")
    # Resolved here rather than closed over at wiring time: the store does
    # not exist until the server's lifespan has run `start()`. See
    # `CatalogFeatures`. A getter that still answers `None` at request time
    # is a build whose lifespan never ran, and 503 is the honest answer.
    features = deps.catalog_features()
    if features is None:
        raise HTTPException(status_code=503, detail="the course catalog is not configured")
    built = await deps.curriculum_of(project_id)
    featured = await features.featured_for(project_id)
    return await deps.catalog.build(
        project_id, built, featured, include_unnamed=include_unnamed
    )


def _author_one_target(
    deps: CatalogDeps,
    project_id: UUID,
    built: Any,
    by_slug: dict,
    subject: str,
    lesson_count: int = 3,
):
    """One target's authoring call, shared by `author_courses`'s run and
    `realize_course`'s single-area run below -- one call into `CourseAuthor`,
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


async def _authoring_holder(deps: CatalogDeps, project_id: UUID) -> UUID | None:
    """Who holds this project, asked because authoring is about to need it."""
    state = await deps.service.project_state(project_id)
    return state.active_session_id


async def _take_over_for_authoring(deps: CatalogDeps, project_id: UUID) -> None:
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


def catalog_router(deps: CatalogDeps) -> APIRouter:
    """The catalog and curriculum routes, ready for `app.include_router`."""
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

    @router.get("/api/projects/{project_id}/catalog/categories/{key}")
    async def read_catalog_category(project_id: UUID, key: str, unnamed: bool = False):
        """One category's page.

        **Registered ahead of the feature/unfeature routes below**, matching
        the `/sources/extract` block's own comment: a literal segment that
        could also be read as a path parameter has to be declared first, or
        FastAPI's declaration-order matching reads it as one. `GET
        /catalog/blurbs` below is the same situation against `GET
        /catalog/{slug}` (Task 9): both are one segment past `/catalog`, one
        of them is literal, and the literal one has to come first or a
        project's course named `blurbs` would be unreachable and every other
        project's sweep progress would read as "no such course". `GET`/`POST
        /catalog/art` further below is the identical situation with the art
        sweep in place of the blurb sweep -- registered ahead of
        `/catalog/{slug}` for the same reason, no separate comment needed.

        404 for a key nothing in this catalog uses, not an empty category --
        an empty category and a misspelled key are different answers, and a
        reader needs to tell them apart.
        """
        await deps.require_project(project_id)
        page = catalog_category_view(
            await _catalog(deps, project_id, include_unnamed=unnamed), key
        )
        if page is None:
            raise HTTPException(status_code=404, detail=f"no category {key!r}")
        return page

    @router.get("/api/projects/{project_id}/catalog/blurbs")
    async def read_blurb_sweep_progress(project_id: UUID):
        """Where the last (or current) blurb sweep on this project stands.

        **Registered ahead of `GET /catalog/{slug}` below** -- see
        `read_catalog_category`'s docstring. `_NOT_RUNNING`'s shape (see
        `blurb_sweep.py`) is what a project that has never swept and a
        project whose sweep just finished both answer, so this never needs
        its own 404 case.
        """
        await deps.require_project(project_id)
        if deps.blurb_sweep is None:
            raise HTTPException(status_code=503, detail="blurb sweeping is not configured")
        return deps.blurb_sweep.progress(project_id)

    @router.post("/api/projects/{project_id}/catalog/blurbs", status_code=202)
    async def start_blurb_sweep(project_id: UUID):
        """Write catalog copy and outlines for every candidate whose cached
        copy or outline is missing or stale, in the background.

        Outline generation used to happen inside `GET /catalog/{slug}` on a
        cache miss -- a model call awaited behind a click. It now happens
        only here; `CourseService._outline_for` is cache-read-only. See
        `blurb_sweep.py`'s module docstring for why this is folded into the
        existing copy sweep rather than a second one running beside it.

        409 when a sweep is already running on this project -- one at a time,
        `BlurbSweep.start`'s own reason: two sweeps racing would both read and
        write the same cache entries.
        """
        await deps.require_project(project_id)
        if (
            deps.blurb_sweep is None
            or deps.blurb_writer is None
            or deps.outline_writer is None
        ):
            raise HTTPException(status_code=503, detail="blurb sweeping is not configured")
        # `include_unnamed=True`: the whole point of a sweep is to give an
        # unnamed candidate a title, so the one caller that must see them is
        # this one -- the default-hidden set on the front page is exactly the
        # backlog this route exists to work through.
        built = await _catalog(deps, project_id, include_unnamed=True)
        try:
            frame = await deps.blurb_sweep.start(
                project_id, built.all_candidates, deps.blurb_writer, deps.outline_writer
            )
        except SweepAlreadyActive as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return JSONResponse(status_code=202, content=frame)

    @router.get("/api/projects/{project_id}/catalog/art")
    async def read_art_sweep_progress(project_id: UUID):
        """Where the last (or current) art sweep on this project stands.
        Mirrors `read_blurb_sweep_progress` exactly -- see its docstring and
        `read_catalog_category`'s for why this is registered ahead of `GET
        /catalog/{slug}` below."""
        await deps.require_project(project_id)
        if deps.art_sweep is None:
            raise HTTPException(status_code=503, detail="art sweeping is not configured")
        return deps.art_sweep.progress(project_id)

    @router.post("/api/projects/{project_id}/catalog/art", status_code=202)
    async def start_art_sweep(project_id: UUID, force: bool = False):
        """Generate art for every candidate the library has neither assigned
        nor matched, in the background.

        `force=true` re-illustrates *every* candidate, ignoring an existing
        assignment (fresh or drifted) and skipping the library-match check
        too -- see `art_sweep.py`'s module docstring for why a forced sweep
        has to actually call the model for every card rather than quietly
        re-matching most of them back to what they already had. The default
        (`force=False`) is unchanged from before this feature: someone
        pressing the ordinary "Illustrate the catalog" button must not
        suddenly pay for a model call per card that already has art.

        409 when a sweep is already running on this project, matching
        `start_blurb_sweep`'s reason.
        """
        await deps.require_project(project_id)
        if deps.art_sweep is None or deps.art_generator is None or deps.art_matcher is None:
            raise HTTPException(status_code=503, detail="art sweeping is not configured")
        built = await _catalog(deps, project_id, include_unnamed=True)
        try:
            frame = await deps.art_sweep.start(
                project_id,
                built.all_candidates,
                deps.art_generator,
                deps.art_matcher,
                force=force,
            )
        except ArtSweepAlreadyActive as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return JSONResponse(status_code=202, content=frame)

    @router.get("/api/projects/{project_id}/catalog/{slug}/art/reroll")
    async def read_art_reroll_progress(project_id: UUID, slug: str):
        """Where the last (or current) reroll of this candidate's art
        stands. Mirrors `read_art_sweep_progress`, keyed one level narrower
        -- see `ArtReroll`'s docstring."""
        await deps.require_project(project_id)
        if deps.art_reroll is None:
            raise HTTPException(status_code=503, detail="art rerolling is not configured")
        return deps.art_reroll.progress(project_id, slug)

    @router.post("/api/projects/{project_id}/catalog/{slug}/art/reroll", status_code=202)
    async def start_art_reroll(project_id: UUID, slug: str):
        """Drop this candidate's art assignment and generate a fresh piece,
        skipping the library search entirely -- see `ArtReroll`'s docstring
        for why re-matching would usually hand back the very picture the
        person is trying to get away from.

        404 for a slug naming no current candidate, matching
        `read_course_detail`'s reasoning. 409 when this candidate is already
        mid-reroll.
        """
        await deps.require_project(project_id)
        if deps.art_reroll is None or deps.art_generator is None:
            raise HTTPException(status_code=503, detail="art rerolling is not configured")
        built = await _catalog(deps, project_id, include_unnamed=True)
        candidate = next((c for c in built.all_candidates if c.slug == slug), None)
        if candidate is None:
            raise HTTPException(status_code=404, detail=f"no course {slug!r}")
        try:
            frame = await deps.art_reroll.start(
                project_id, slug, candidate, deps.art_generator
            )
        except RerollAlreadyActive as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return JSONResponse(status_code=202, content=frame)

    @router.get("/api/projects/{project_id}/catalog/{slug}")
    async def read_course_detail(project_id: UUID, slug: str):
        """One cluster's detail page: its candidate card, its outline, its
        full membership, and -- if realized -- how far it has drifted.

        404 for a slug naming no candidate in the current catalog, matching
        `CourseService.detail`'s own reasoning: a stranded realized course
        (one whose slug names no *current* cluster) is deliberately not
        reachable through this route -- see `orphans()`.
        """
        await deps.require_project(project_id)
        if deps.course_service is None:
            raise HTTPException(status_code=503, detail="course realization is not configured")
        built = await deps.curriculum_of(project_id)
        # `include_unnamed=True`: a slug is looked up directly here, and a
        # candidate the front page currently hides by default must not 404
        # just for being unnamed -- the toggle governs what the front page
        # shows, not which slugs exist.
        catalog_built = await _catalog(deps, project_id, include_unnamed=True)
        detail = await deps.course_service.detail(project_id, built, catalog_built, slug)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"no course {slug!r}")
        return course_detail_view(detail)

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
                # A target that wrote the path overview rather than an area:
                # one file, no lessons. Asked of the workspace rather than
                # inferred from the slug, for `is_path_file`'s reason.
                entry = session.state.files.get(path_file(slug)) or {}
                # `learning_plan_prompt` asks for a YAML frontmatter block on
                # every file it writes, and markdown reads a `key: value` line
                # immediately followed by `---` as a setext heading -- so a
                # reader handed the raw file sees a fabricated `<h2>` made of
                # the frontmatter's own fields sitting above the real `# `
                # heading the file opens with. `parse_frontmatter` already
                # exists for `application/components.py`'s parser; using it
                # here rather than a second notion of "what frontmatter is" in
                # the console.
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
        # `include_unnamed=True` for `read_course_detail`'s reason above: a
        # slug looked up directly must not 404 for being unnamed.
        catalog_built = await _catalog(deps, project_id, include_unnamed=True)
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
            # Asked before starting rather than after failing -- see
            # `_authoring_holder`. No `take_over` flag on *this* route: the
            # realization is already appended by the time we get here and a
            # second click answers 409, so the retry has to be a different
            # call anyway. `POST /curriculum/author` with `take_over` is that
            # call, and putting the take-over on one route rather than two
            # keeps the release of somebody else's session in one place.
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
                # Named, not merely counted: the console's whole offer is
                # "held by <this session> -- take it?", and a reason string
                # the client has to parse a UUID out of is the version of
                # that offer which breaks the first time the wording changes.
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

    @router.post("/api/projects/{project_id}/catalog/{slug}/feature")
    async def feature_course(project_id: UUID, slug: str, body: FeatureCourse):
        """Put one candidate on the front page, at the given rank.

        No check that `slug` names a current area: a slug is derived from an
        area's top anchor, so re-clustering can move it, and a feature aimed
        ahead of the graph that will eventually hold it is exactly the case
        `Catalog.unplaceable_featured` reports rather than refuses.
        """
        await deps.require_project(project_id)
        if deps.catalog_recorder is None:
            raise HTTPException(status_code=503, detail="catalog curation is not configured")
        await deps.catalog_recorder(project_id).feature(slug, body.rank)
        return {"slug": slug, "rank": body.rank}

    @router.post("/api/projects/{project_id}/catalog/{slug}/unfeature")
    async def unfeature_course(project_id: UUID, slug: str):
        """Take one candidate off the front page.

        Unfeaturing a slug that was never featured is accepted rather than
        refused, matching `CatalogFeatureStore.unfeature`'s own reasoning:
        there is no aggregate here to enforce a precondition against, and a
        second click doing nothing is not an error.
        """
        await deps.require_project(project_id)
        if deps.catalog_recorder is None:
            raise HTTPException(status_code=503, detail="catalog curation is not configured")
        await deps.catalog_recorder(project_id).unfeature(slug)
        return {"slug": slug}

    @router.get("/api/projects/{project_id}/catalog")
    async def read_catalog(project_id: UUID, unnamed: bool = False):
        """The front page: hero, highlights, and everything else by category.

        `unnamed=true` shows candidates with no cached title -- default false
        because a title-less card falls back to `LearningArea.display_name()`,
        the single most central *entity* in the cluster, and reads as an
        entity name rather than a course.
        """
        await deps.require_project(project_id)
        return catalog_view(await _catalog(deps, project_id, include_unnamed=unnamed))

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
