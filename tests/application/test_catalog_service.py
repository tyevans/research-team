"""Assembling a catalog from a curriculum, a grouper and the featured set."""

from datetime import UTC, datetime
from uuid import uuid4

from research_team.application.course_catalog import CachedBlurb, CatalogService
from research_team.application.curriculum import Curriculum
from research_team.domain.learning_area import (
    AreaMember,
    AreaProjection,
    LearningArea,
    LearningPath,
)
from research_team.infrastructure.knowledge.seeded_art import SeededArtProvider
from research_team.infrastructure.knowledge.type_plurality_grouper import TypePluralityGrouper


class _NoBlurbs:
    async def get(self, project_id, slug):
        return None

    async def all_for_project(self, project_id):
        return {}


class _CachedBlurbs:
    """A blurb cache with one row already generated, for the fallback tests.

    `all_for_project` cannot enumerate slugs the way a real store's query
    does -- this fake has no table to scan, only a fixed answer for whatever
    slug is asked. `_AnySlug` below stands in for that: every test using
    this fake builds a curriculum of exactly one area, so "the same blurb no
    matter which slug is looked up" is the honest shape of "one row cached".
    """

    def __init__(self, title: str) -> None:
        self._title = title

    def _blurb(self) -> CachedBlurb:
        return CachedBlurb(
            text="Some cached copy.",
            title=self._title,
            membership_hash="h",
            model="m",
            generated_at=datetime.now(UTC),
        )

    async def get(self, project_id, slug):
        return self._blurb()

    async def all_for_project(self, project_id):
        return _AnySlug(self._blurb())


class _AnySlug(dict):
    """A `Mapping` stand-in that answers `.get(slug)` with the same value
    for any key, for a fake cache that has no real per-slug table to scan."""

    def __init__(self, blurb: CachedBlurb) -> None:
        super().__init__()
        self._blurb = blurb

    def get(self, key, default=None):
        return self._blurb


class _TitledFor:
    """A blurb cache with a title for some slugs and nothing for the rest --
    for the toggle tests, where "unnamed" has to mean something distinct
    per-candidate rather than uniformly across the whole catalog."""

    def __init__(self, titled: set[str]) -> None:
        self._titled = titled

    def _blurb(self, slug: str) -> CachedBlurb:
        return CachedBlurb(
            text="Some cached copy.",
            title=f"{slug} Title",
            membership_hash="h",
            model="m",
            generated_at=datetime.now(UTC),
        )

    async def get(self, project_id, slug):
        if slug not in self._titled:
            return None
        return self._blurb(slug)

    async def all_for_project(self, project_id):
        return {slug: self._blurb(slug) for slug in self._titled}


def _area(slug: str, size: int, centrality: float, kind: str = "person") -> LearningArea:
    return LearningArea(
        slug=slug,
        members=tuple(
            AreaMember(
                entity_id=f"{slug}-{i}",
                name=f"{slug} {i}",
                entity_type=kind,
                centrality=centrality,
            )
            for i in range(size)
        ),
    )


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


def _service() -> CatalogService:
    return CatalogService(
        grouper=TypePluralityGrouper(), art=SeededArtProvider(), blurbs=_NoBlurbs()
    )


# Every test below that is not itself about naming or the unnamed toggle
# passes `include_unnamed=True` -- none of these seed a blurb cache, so every
# candidate they build is unnamed, and the default (`include_unnamed=False`)
# would filter every one of them before the assertion runs. Only the tests
# in the "the unnamed toggle" section below exercise the default.


async def test_the_hero_leads_with_the_most_prominent_candidate():
    catalog = await _service().build(
        uuid4(),
        _curriculum(_area("small", 2, 1.0), _area("big", 20, 5.0)),
        featured={},
        include_unnamed=True,
    )

    assert catalog.sections.hero[0].slug == "big"


async def test_a_featured_candidate_outranks_a_more_prominent_one():
    """The whole reason the override is in this increment: the derived score
    measures corpus coverage, not worth."""
    catalog = await _service().build(
        uuid4(),
        _curriculum(_area("small", 2, 1.0), _area("big", 20, 5.0)),
        featured={"small": 0},
        include_unnamed=True,
    )

    assert catalog.sections.hero[0].slug == "small"


async def test_a_featured_slug_that_names_no_area_is_reported_not_dropped():
    """Re-clustering moves slugs. Curation work that silently disappears is
    worse than curation work that is visibly stranded."""
    catalog = await _service().build(
        uuid4(), _curriculum(_area("big", 20, 5.0)), featured={"gone": 0}
    )

    assert catalog.unplaceable_featured == ("gone",)


async def test_every_area_reaches_exactly_one_section():
    """A candidate that fell out of all three sections would vanish from the
    catalog and the catalog would still render."""
    areas = [_area(f"a{i}", i + 1, 1.0) for i in range(12)]
    catalog = await _service().build(
        uuid4(), _curriculum(*areas), featured={}, include_unnamed=True
    )

    placed = (
        [c.slug for c in catalog.sections.hero]
        + [c.slug for c in catalog.sections.highlights]
        + [c.slug for cat in catalog.sections.filed for c in cat.candidates]
    )
    assert sorted(placed) == sorted(a.slug for a in areas)
    assert len(placed) == len(set(placed))


async def test_areas_of_different_anchor_types_land_in_different_categories():
    """Categorisation, not placement.

    Asserted over every candidate in the catalog rather than over
    `sections.filed`: with two areas and `HERO_SIZE` at 5, both are promoted
    to the hero row, so `filed` is empty and an assertion against it would be
    testing the section cut-points rather than the grouper. An earlier draft
    did exactly that, and could only pass if the service emitted a `Category`
    with no candidates in it -- an empty tile shipped to the browser to
    satisfy a test.
    """
    catalog = await _service().build(
        uuid4(),
        _curriculum(_area("people", 5, 2.0, "person"), _area("shows", 5, 2.0, "work")),
        featured={},
        include_unnamed=True,
    )

    assert {c.slug: c.category for c in catalog.all_candidates} == {
        "people": "person",
        "shows": "work",
    }


async def test_a_candidate_with_no_cached_copy_falls_back_to_the_area_name():
    """So a cold catalog renders as it does today rather than as blank cards.
    Fails on an implementation that reads the cached title unconditionally.
    `include_unnamed=True`: this candidate has no cached title, so it is
    exactly what the toggle hides by default -- this test is about the
    fallback title, not about the toggle, so it asks to see it anyway."""
    area = _area("big", 20, 5.0)
    catalog = await CatalogService(
        grouper=TypePluralityGrouper(), art=SeededArtProvider(), blurbs=_NoBlurbs()
    ).build(uuid4(), _curriculum(area), featured={}, include_unnamed=True)

    assert catalog.sections.hero[0].title == area.display_name()


async def test_a_cached_title_is_preferred_over_the_area_name():
    area = _area("big", 20, 5.0)
    catalog = await CatalogService(
        grouper=TypePluralityGrouper(),
        art=SeededArtProvider(),
        blurbs=_CachedBlurbs("A Generated Title"),
    ).build(uuid4(), _curriculum(area), featured={})

    assert catalog.sections.hero[0].title == "A Generated Title"


async def test_a_cached_blurb_with_an_empty_title_falls_back_to_the_area_name():
    """`CourseBlurbRow.title` defaults to `""` for rows written before titles
    existed. An empty string is falsy, so `cached.title or area.display_name()`
    covers it without a separate branch. `include_unnamed=True` for the same
    reason as the no-cached-copy test above: an empty cached title is also
    "unnamed" by the toggle's own definition, and this test is about the
    fallback text, not the toggle."""
    area = _area("big", 20, 5.0)
    catalog = await CatalogService(
        grouper=TypePluralityGrouper(), art=SeededArtProvider(), blurbs=_CachedBlurbs("")
    ).build(uuid4(), _curriculum(area), featured={}, include_unnamed=True)

    assert catalog.sections.hero[0].title == area.display_name()


async def test_a_category_with_every_area_promoted_does_not_appear_filed_empty():
    """`sections.filed` means filed, not "every category that exists".

    Both areas here are promoted to hero (two areas, `HERO_SIZE` is 5), so
    their shared category has nothing left over. This pins that `filed` does
    not seed an empty `Category` for it -- a category tile with no candidates
    in it says nothing to a reader and exists only to make a key visible that
    `all_candidates` (used by `test_areas_of_different_anchor_types_...`
    above) already exposes without it.
    """
    catalog = await _service().build(
        uuid4(),
        _curriculum(_area("people", 5, 2.0, "person"), _area("shows", 5, 2.0, "work")),
        featured={},
        include_unnamed=True,
    )

    assert catalog.sections.filed == ()


# --- the unnamed toggle ---
#
# A candidate is "named" when it has a cached blurb whose `title` is
# non-empty (see `_TitledFor` above and `CatalogService.build`'s own
# reasoning on `named`/`has_name`). Default behaviour hides everything else,
# except a featured candidate, which is never hidden.


async def test_an_unnamed_candidate_is_hidden_by_default():
    catalog = await CatalogService(
        grouper=TypePluralityGrouper(),
        art=SeededArtProvider(),
        blurbs=_TitledFor({"named"}),
    ).build(
        uuid4(),
        _curriculum(_area("named", 20, 5.0), _area("unnamed", 20, 4.0)),
        featured={},
    )

    assert [c.slug for c in catalog.all_candidates] == ["named"]


async def test_include_unnamed_true_shows_it():
    catalog = await CatalogService(
        grouper=TypePluralityGrouper(),
        art=SeededArtProvider(),
        blurbs=_TitledFor({"named"}),
    ).build(
        uuid4(),
        _curriculum(_area("named", 20, 5.0), _area("unnamed", 20, 4.0)),
        featured={},
        include_unnamed=True,
    )

    assert {c.slug for c in catalog.all_candidates} == {"named", "unnamed"}


async def test_unnamed_count_reports_how_many_are_hidden():
    catalog = await CatalogService(
        grouper=TypePluralityGrouper(),
        art=SeededArtProvider(),
        blurbs=_TitledFor({"named"}),
    ).build(
        uuid4(),
        _curriculum(
            _area("named", 20, 5.0), _area("unnamed-1", 20, 4.0), _area("unnamed-2", 20, 3.0)
        ),
        featured={},
    )

    assert catalog.unnamed_count == 2


async def test_unnamed_count_is_reported_even_when_shown():
    """The toggle has to say how many *would* be hidden while it is showing
    them, or a reader flipping it back off has no idea what they are about
    to lose -- a switch with no indication anything is behind it."""
    catalog = await CatalogService(
        grouper=TypePluralityGrouper(),
        art=SeededArtProvider(),
        blurbs=_TitledFor({"named"}),
    ).build(
        uuid4(),
        _curriculum(_area("named", 20, 5.0), _area("unnamed", 20, 4.0)),
        featured={},
        include_unnamed=True,
    )

    assert catalog.unnamed_count == 1


async def test_a_featured_candidate_is_never_hidden_even_if_unnamed():
    """Someone deliberately pinned this candidate. Hiding it would make
    curation silently vanish -- the exact failure `unplaceable_featured`
    exists to avoid for a slug that moves, extended here to a slug that was
    never named."""
    catalog = await CatalogService(
        grouper=TypePluralityGrouper(),
        art=SeededArtProvider(),
        blurbs=_NoBlurbs(),
    ).build(
        uuid4(),
        _curriculum(_area("pinned", 20, 5.0)),
        featured={"pinned": 0},
    )

    assert [c.slug for c in catalog.all_candidates] == ["pinned"]
    assert catalog.unnamed_count == 0


async def test_a_featured_unnamed_candidate_does_not_count_toward_unnamed_count():
    """`unnamed_count` is what the toggle hides, and a featured candidate is
    never hidden -- counting it would tell a reader the toggle has more
    behind it than flipping it actually reveals."""
    catalog = await CatalogService(
        grouper=TypePluralityGrouper(),
        art=SeededArtProvider(),
        blurbs=_TitledFor(set()),
    ).build(
        uuid4(),
        _curriculum(_area("pinned", 20, 5.0), _area("plain-unnamed", 20, 4.0)),
        featured={"pinned": 0},
    )

    assert catalog.unnamed_count == 1


class _CountingBlurbs:
    """A `BlurbCachePort` that counts calls to each method -- for proving
    `build` reads the cache once per catalog rather than once per area. An
    assertion on the *data* `build` returns would pass under both the N+1
    version and the batched one; only the call count tells them apart."""

    def __init__(self) -> None:
        self.get_calls = 0
        self.all_for_project_calls = 0

    async def get(self, project_id, slug):
        self.get_calls += 1
        return None

    async def all_for_project(self, project_id):
        self.all_for_project_calls += 1
        return {}


async def test_build_reads_the_blurb_cache_once_regardless_of_area_count():
    """Was one `get` per area -- an N+1 over the curriculum's areas. This
    fails on that version (`all_for_project_calls == 0`, `get_calls == 3`)
    and passes on the batched one."""
    blurbs = _CountingBlurbs()
    areas = [_area("a", 5, 3.0), _area("b", 5, 2.0), _area("c", 5, 1.0)]

    await CatalogService(
        grouper=TypePluralityGrouper(), art=SeededArtProvider(), blurbs=blurbs
    ).build(uuid4(), _curriculum(*areas), featured={})

    assert blurbs.all_for_project_calls == 1
    assert blurbs.get_calls == 0
