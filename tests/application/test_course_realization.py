"""The course detail read: a candidate, its outline, its full membership, and
-- for a realized course -- how far it has drifted since it was frozen.

`CourseService` is the assembler; `RealizedCoursePort` is what supplies the
frozen side. Both ports here are faked in-process rather than against a real
store, matching `test_catalog_service.py`'s own convention -- the store
classes in `infrastructure/persistence/read_models.py` have their own tests.
"""

from datetime import UTC, datetime
from uuid import uuid4

from research_team.application.course_catalog import CachedOutline, DraftOutline
from research_team.application.course_realization import (
    CourseService,
    RealizedCourse,
)
from research_team.application.curriculum import Curriculum
from research_team.domain.learning_area import (
    AreaMember,
    AreaProjection,
    LearningArea,
    LearningPath,
)


def _member(entity_id: str, kind: str = "person") -> AreaMember:
    return AreaMember(entity_id=entity_id, name=entity_id, entity_type=kind, centrality=1.0)


def _area(slug: str, *entity_ids: str) -> LearningArea:
    return LearningArea(slug=slug, members=tuple(_member(e) for e in entity_ids))


def _curriculum(*areas: LearningArea) -> Curriculum:
    return Curriculum(
        projection=AreaProjection(
            areas=areas,
            entity_count=sum(a.size for a in areas),
            relationship_count=0,
            co_mention_count=0,
        ),
        path=LearningPath(
            slug="all",
            title="All",
            area_slugs=tuple(a.slug for a in areas),
            edges=(),
        ),
    )


class _StubCatalog:
    """A `Catalog`-shaped stand-in exposing only `all_candidates` -- the one
    property `CourseService.detail` needs to find its slug, so a test does
    not have to build a whole `CatalogService.build()` result to supply it."""

    def __init__(self, *candidates) -> None:
        self.all_candidates = tuple(candidates)


class _FakeOutlineWriter:
    """Records how many times it was asked to write, and returns a fixed
    answer -- `None` for the refusal tests, a `DraftOutline` otherwise."""

    def __init__(self, result: DraftOutline | None) -> None:
        self._result = result
        self.calls = 0

    async def write(self, title, anchors):
        self.calls += 1
        return self._result

    @property
    def model_name(self) -> str:
        return "fake-outline-writer"


class _FakeOutlineCache:
    def __init__(self, cached: CachedOutline | None = None) -> None:
        self._cached = cached
        self.put_calls = 0

    async def get(self, project_id, slug):
        return self._cached

    async def put(
        self, project_id, slug, promise, sections, membership_hash, model, generated_at
    ):
        self.put_calls += 1
        self._cached = CachedOutline(
            promise=promise,
            sections=sections,
            membership_hash=membership_hash,
            model=model,
            generated_at=generated_at,
        )


class _FakeRealizedCourses:
    """`RealizedCoursePort` stand-in -- an in-memory list rather than
    `CourseStore`, which has its own tests against a real database."""

    def __init__(self, *courses: RealizedCourse) -> None:
        self._courses = list(courses)

    async def for_project(self, project_id):
        return tuple(self._courses)

    async def get(self, project_id, slug):
        return next((c for c in self._courses if c.slug == slug), None)


def _draft() -> DraftOutline:
    return DraftOutline(
        promise="Learn the basics",
        sections=(("Intro", "Where it starts"),),
    )


def _realized(
    slug: str = "warp-drive",
    *,
    member_entity_ids: tuple[str, ...] = ("e1", "e2"),
    membership_hash: str = "hash-v1",
) -> RealizedCourse:
    return RealizedCourse(
        slug=slug,
        title="Warp Drive",
        member_entity_ids=member_entity_ids,
        membership_hash=membership_hash,
        realized_at=datetime(2026, 8, 20, tzinfo=UTC),
        authored_session_id=None,
    )


def _candidate(slug: str = "warp-drive", membership_hash: str = "hash-v1"):
    from research_team.domain.course_catalog import ArtRef, CourseCandidate

    area = _area(slug, "e1", "e2")
    return CourseCandidate(
        slug=slug,
        title="Warp Drive",
        category="unclassified",
        prominence=1.0,
        size=area.size,
        membership_hash=membership_hash,
        anchors=area.members,
        art=ArtRef(url="x", alt="x"),
    )


async def test_a_missing_outline_is_generated_and_cached():
    writer = _FakeOutlineWriter(_draft())
    cache = _FakeOutlineCache(cached=None)
    service = CourseService(
        realized=_FakeRealizedCourses(),
        outline_writer=writer,
        outline_cache=cache,
    )
    curriculum = _curriculum(_area("warp-drive", "e1", "e2"))
    catalog = _StubCatalog(_candidate())

    detail = await service.detail(uuid4(), curriculum, catalog, "warp-drive")

    assert writer.calls == 1
    assert cache.put_calls == 1
    assert detail is not None
    assert detail.outline is not None
    assert detail.outline.promise == "Learn the basics"


async def test_a_cached_outline_whose_hash_matches_is_not_regenerated():
    writer = _FakeOutlineWriter(_draft())
    cache = _FakeOutlineCache(
        cached=CachedOutline(
            promise="Cached promise",
            sections=(("A", "B"),),
            membership_hash="hash-v1",
            model="fake-outline-writer",
            generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
    )
    service = CourseService(
        realized=_FakeRealizedCourses(),
        outline_writer=writer,
        outline_cache=cache,
    )
    curriculum = _curriculum(_area("warp-drive", "e1", "e2"))
    catalog = _StubCatalog(_candidate(membership_hash="hash-v1"))

    detail = await service.detail(uuid4(), curriculum, catalog, "warp-drive")

    assert writer.calls == 0
    assert detail.outline is not None
    assert detail.outline.promise == "Cached promise"


async def test_a_cached_outline_whose_hash_disagrees_is_regenerated():
    """The staleness mechanism. A version that only checks presence passes the
    first two tests and never regenerates after a single drift."""
    writer = _FakeOutlineWriter(_draft())
    cache = _FakeOutlineCache(
        cached=CachedOutline(
            promise="Stale promise",
            sections=(("A", "B"),),
            membership_hash="hash-v0",
            model="fake-outline-writer",
            generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
    )
    service = CourseService(
        realized=_FakeRealizedCourses(),
        outline_writer=writer,
        outline_cache=cache,
    )
    curriculum = _curriculum(_area("warp-drive", "e1", "e2"))
    catalog = _StubCatalog(_candidate(membership_hash="hash-v1"))

    detail = await service.detail(uuid4(), curriculum, catalog, "warp-drive")

    assert writer.calls == 1
    assert detail.outline.promise == "Learn the basics"


async def test_a_refused_outline_is_not_cached():
    """So the next visit retries. Caching a refusal makes the blank permanent
    and gives nothing a way to clear it."""
    writer = _FakeOutlineWriter(None)
    cache = _FakeOutlineCache(cached=None)
    service = CourseService(
        realized=_FakeRealizedCourses(),
        outline_writer=writer,
        outline_cache=cache,
    )
    curriculum = _curriculum(_area("warp-drive", "e1", "e2"))
    catalog = _StubCatalog(_candidate())

    detail = await service.detail(uuid4(), curriculum, catalog, "warp-drive")

    assert cache.put_calls == 0
    assert detail.outline is None


async def test_a_missing_candidate_yields_no_detail():
    """A version reaching into `RealizedCoursePort` for the title when the
    catalog has nothing would paper over a slug that no longer names a
    cluster -- that is `orphans()`'s job, not `detail`'s."""
    service = CourseService(
        realized=_FakeRealizedCourses(),
        outline_writer=_FakeOutlineWriter(_draft()),
        outline_cache=_FakeOutlineCache(),
    )
    curriculum = _curriculum(_area("other", "e9"))

    detail = await service.detail(uuid4(), curriculum, _StubCatalog(), "warp-drive")

    assert detail is None


async def test_a_realized_course_reports_its_fit_against_the_current_cluster():
    project_id = uuid4()
    realized = _realized(member_entity_ids=("e1", "e2"))
    service = CourseService(
        realized=_FakeRealizedCourses(realized),
        outline_writer=_FakeOutlineWriter(_draft()),
        outline_cache=_FakeOutlineCache(),
    )
    # The live cluster kept e1, dropped e2, and gained e3.
    curriculum = _curriculum(_area("warp-drive", "e1", "e3"))
    catalog = _StubCatalog(_candidate())

    detail = await service.detail(project_id, curriculum, catalog, "warp-drive")

    assert detail is not None
    assert detail.course is not None
    assert detail.course.fit.kept == ("e1",)
    assert detail.course.fit.added == ("e3",)
    assert detail.course.fit.dropped == ("e2",)
    assert detail.course.fit.orphaned is False


async def test_orphans_lists_a_realized_course_whose_slug_names_no_cluster():
    """The route cannot reach these -- the candidate does not exist -- so this
    is the only surface they have. A version returning () passes every other
    test in this file."""
    project_id = uuid4()
    stranded = _realized(slug="ancient-rome", member_entity_ids=("e1",))
    service = CourseService(
        realized=_FakeRealizedCourses(stranded),
        outline_writer=_FakeOutlineWriter(_draft()),
        outline_cache=_FakeOutlineCache(),
    )
    # No area named "ancient-rome" in the current curriculum -- re-clustering
    # moved the slug, which is exactly the state orphans() exists to surface.
    curriculum = _curriculum(_area("something-else", "e1"))

    result = await service.orphans(project_id, curriculum)

    assert len(result) == 1
    assert result[0].slug == "ancient-rome"


async def test_orphans_omits_a_realized_course_whose_slug_still_names_a_cluster():
    project_id = uuid4()
    still_current = _realized(slug="warp-drive", member_entity_ids=("e1", "e2"))
    service = CourseService(
        realized=_FakeRealizedCourses(still_current),
        outline_writer=_FakeOutlineWriter(_draft()),
        outline_cache=_FakeOutlineCache(),
    )
    curriculum = _curriculum(_area("warp-drive", "e1", "e2"))

    result = await service.orphans(project_id, curriculum)

    assert result == ()
