"""The catalog and curriculum HTTP routes.

Its own module and its own router, for `export.py` and `settings.py`'s reason:
`create_app` is five thousand lines of closures over a few dozen optional
collaborators, and extracting these routes eliminates monolithic
route closures from `app.py`.

Curriculum navigation and course authoring routes are factored into
`curriculum.py`, while course realization lifecycle and unit inspection routes
are in `catalog_realization.py`.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from eventsource import AggregateRepository
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from research_team.curriculum.application import CurriculumService
from research_team.curriculum.application.course_authoring import CourseAuthor
from research_team.curriculum.application.course_catalog import (
    ArtGeneratorPort,
    BlurbTextPort,
    Catalog,
    CatalogService,
    OutlineTextPort,
)
from research_team.curriculum.application.course_realization import CourseService
from research_team.curriculum.domain.course import Course
from research_team.infrastructure.knowledge.library_art import LibraryArtProvider
from research_team.infrastructure.persistence.read_models import CatalogFeatureStore
from research_team.interfaces.web.art_sweep import (
    ArtReroll,
    ArtSweep,
    RerollAlreadyActive,
)
from research_team.interfaces.web.art_sweep import SweepAlreadyActive as ArtSweepAlreadyActive
from research_team.interfaces.web.authoring import AuthoringActivity
from research_team.interfaces.web.blurb_sweep import BlurbSweep, SweepAlreadyActive
from research_team.interfaces.web.catalog_realization import course_realization_router
from research_team.interfaces.web.curriculum import NewAuthoring, curriculum_router
from research_team.interfaces.web.presenters import (
    catalog_category_view,
    catalog_view,
    course_detail_view,
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
    features = deps.catalog_features()
    if features is None:
        raise HTTPException(status_code=503, detail="the course catalog is not configured")
    built = await deps.curriculum_of(project_id)
    featured = await features.featured_for(project_id)
    return await deps.catalog.build(
        project_id, built, featured, include_unnamed=include_unnamed
    )


def catalog_router(deps: CatalogDeps) -> APIRouter:
    """The catalog and curriculum routes, ready for `app.include_router`."""
    router = APIRouter()

    # Curriculum routes mounted first
    router.include_router(curriculum_router(deps))

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
        catalog_built = await _catalog(deps, project_id, include_unnamed=True)
        detail = await deps.course_service.detail(project_id, built, catalog_built, slug)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"no course {slug!r}")
        return course_detail_view(detail)

    # Mount course realization routes (/unit, /realize, /abandon)
    router.include_router(course_realization_router(deps, _catalog))

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

    return router


__all__ = [
    "CatalogDeps",
    "CatalogFeatureRecorder",
    "CatalogFeatureRecorders",
    "CatalogFeatures",
    "FeatureCourse",
    "NewAuthoring",
    "catalog_router",
    "course_realization_router",
    "curriculum_router",
]
