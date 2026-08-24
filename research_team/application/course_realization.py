"""The course detail read: a candidate, its outline, its full membership, and
-- for a realized course -- how far the cluster has drifted since it was
frozen.

`OutlineTextPort`, `OutlineCachePort`, `CachedOutline` and `DraftOutline` live
in `course_catalog.py` rather than here (Task 4; controller ruling R2) -- this
module holds only the port over realized courses and the assembler that joins
a catalog candidate to its frozen counterpart.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from research_team.application.course_catalog import (
    CachedOutline,
    OutlineCachePort,
    OutlineTextPort,
)
from research_team.application.curriculum import Curriculum
from research_team.domain.course import CourseFit, fit_of
from research_team.domain.course_catalog import CourseCandidate


@dataclass(frozen=True)
class RealizedCourse:
    """A realized course, in this layer's own vocabulary.

    Not `CourseRow`: that type carries a `project_id` a caller already
    supplied and an `abandoned` flag this layer never needs to see --
    `RealizedCoursePort` implementations only ever return non-abandoned rows
    -- and importing it here would put `infrastructure.persistence` in a
    module `tests/test_architecture.py` keeps free of it, `CachedBlurb`'s
    reason restated for this port.
    """

    slug: str
    title: str
    member_entity_ids: tuple[str, ...]
    membership_hash: str
    realized_at: datetime
    authored_session_id: UUID | None


class RealizedCoursePort(Protocol):
    """The stored realized courses for one project.

    Backed by `CourseStore` at composition time, joined against
    `AuthoringRunStore.authored_session_for` for `authored_session_id` --
    that join is the adapter's job, not this port's; the port hands back
    the already-joined `RealizedCourse`.
    """

    async def for_project(self, project_id: UUID) -> Sequence[RealizedCourse]: ...

    async def get(self, project_id: UUID, slug: str) -> RealizedCourse | None: ...


@dataclass(frozen=True)
class RealizedCourseView:
    """A realized course's frozen facts plus how it compares to the live
    cluster right now -- the whole reason `CourseDetail.course` is this and
    not the bare `RealizedCourse`, which knows nothing about drift."""

    realized_at: datetime
    membership_hash: str
    fit: CourseFit
    authored_session_id: UUID | None


@dataclass(frozen=True)
class CourseDetail:
    """One course detail page's worth of state.

    `course` is `None` for a candidate nobody has realized -- an ordinary
    state, not a degraded one: every cluster is browsable before anyone
    decides it is a course. `outline` is `None` both when nothing has been
    generated yet and when the model refused; the page cannot tell those
    apart from this value alone, and does not need to -- both render as "no
    outline yet".
    """

    candidate: CourseCandidate
    outline: CachedOutline | None
    members: tuple = ()
    course: RealizedCourseView | None = None


class CourseService:
    """Assembles a course detail page from a curriculum, a catalog and the
    realized-course store."""

    def __init__(
        self,
        *,
        realized: RealizedCoursePort,
        outline_writer: OutlineTextPort,
        outline_cache: OutlineCachePort,
    ) -> None:
        self._realized = realized
        self._outline_writer = outline_writer
        self._outline_cache = outline_cache

    async def detail(
        self,
        project_id: UUID,
        curriculum: Curriculum,
        catalog,
        slug: str,
    ) -> CourseDetail | None:
        """The candidate, its outline and (if realized) its drift.

        `None` when `slug` names no candidate in `catalog.all_candidates` --
        the route has nothing to render, matching `CatalogService`'s own
        "unplaceable" handling rather than inventing a page for a slug that
        does not exist in the current catalog. A stranded realized course
        (its slug names no *current cluster*) is exactly this case and is
        deliberately not reachable here -- see `orphans()`.
        """
        candidate = next((c for c in catalog.all_candidates if c.slug == slug), None)
        if candidate is None:
            return None

        outline = await self._outline_for(project_id, candidate)

        area = curriculum.area(slug)
        members = tuple(area.members) if area is not None else ()

        course_view: RealizedCourseView | None = None
        realized = await self._realized.get(project_id, slug)
        if realized is not None:
            course_view = RealizedCourseView(
                realized_at=realized.realized_at,
                membership_hash=realized.membership_hash,
                fit=fit_of(realized.member_entity_ids, area),
                authored_session_id=realized.authored_session_id,
            )

        return CourseDetail(
            candidate=candidate, outline=outline, members=members, course=course_view
        )

    async def _outline_for(
        self, project_id: UUID, candidate: CourseCandidate
    ) -> CachedOutline | None:
        """The cached outline if it is fresh, else a freshly generated one.

        A miss and a stale hit take the same path: write, and cache only a
        non-refusal (see the module docstring on `CourseDetail.outline` for
        why a refusal and "never generated" render identically, and the
        brief's own reasoning for why a refusal must not be cached -- it is
        usually a bad sample, not a property of the cluster, and caching it
        would make the card permanently blank with nothing able to retry it).
        """
        cached = await self._outline_cache.get(project_id, candidate.slug)
        if cached is not None and cached.membership_hash == candidate.membership_hash:
            return cached

        draft = await self._outline_writer.write(candidate.title, candidate.anchors)
        if draft is None:
            return None

        generated_at = datetime.now(UTC)
        await self._outline_cache.put(
            project_id,
            candidate.slug,
            draft.promise,
            draft.sections,
            candidate.membership_hash,
            self._outline_writer.model_name,
            generated_at,
        )
        return CachedOutline(
            promise=draft.promise,
            sections=draft.sections,
            membership_hash=candidate.membership_hash,
            model=self._outline_writer.model_name,
            generated_at=generated_at,
        )

    async def orphans(
        self, project_id: UUID, curriculum: Curriculum
    ) -> tuple[RealizedCourse, ...]:
        """Realized courses whose slug names no cluster in the current
        curriculum.

        The only surface these have: `detail()` looks the slug up in
        `catalog.all_candidates`, which a stranded course is by definition
        absent from -- re-clustering moved the slug it was realized under,
        so there is no candidate for a route to key on. Compared against
        `curriculum.by_slug` rather than the catalog, because a candidate can
        be absent from the catalog for reasons that have nothing to do with
        stranding (see `Catalog.unplaceable_featured`'s own case) -- what
        `orphans()` reports on is specifically "no cluster", not "no card".
        """
        by_slug = curriculum.by_slug
        courses = await self._realized.for_project(project_id)
        return tuple(c for c in courses if c.slug not in by_slug)
