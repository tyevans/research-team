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


class _CachedBlurbs:
    """A blurb cache with one row already generated, for the fallback tests."""

    def __init__(self, title: str) -> None:
        self._title = title

    async def get(self, project_id, slug):
        return CachedBlurb(
            text="Some cached copy.",
            title=self._title,
            membership_hash="h",
            model="m",
            generated_at=datetime.now(UTC),
        )


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


async def test_the_hero_leads_with_the_most_prominent_candidate():
    catalog = await _service().build(
        uuid4(), _curriculum(_area("small", 2, 1.0), _area("big", 20, 5.0)), featured={}
    )

    assert catalog.sections.hero[0].slug == "big"


async def test_a_featured_candidate_outranks_a_more_prominent_one():
    """The whole reason the override is in this increment: the derived score
    measures corpus coverage, not worth."""
    catalog = await _service().build(
        uuid4(),
        _curriculum(_area("small", 2, 1.0), _area("big", 20, 5.0)),
        featured={"small": 0},
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
    catalog = await _service().build(uuid4(), _curriculum(*areas), featured={})

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
    )

    assert {c.slug: c.category for c in catalog.all_candidates} == {
        "people": "person",
        "shows": "work",
    }


async def test_a_candidate_with_no_cached_copy_falls_back_to_the_area_name():
    """So a cold catalog renders as it does today rather than as blank cards.
    Fails on an implementation that reads the cached title unconditionally."""
    area = _area("big", 20, 5.0)
    catalog = await CatalogService(
        grouper=TypePluralityGrouper(), art=SeededArtProvider(), blurbs=_NoBlurbs()
    ).build(uuid4(), _curriculum(area), featured={})

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
    covers it without a separate branch."""
    area = _area("big", 20, 5.0)
    catalog = await CatalogService(
        grouper=TypePluralityGrouper(), art=SeededArtProvider(), blurbs=_CachedBlurbs("")
    ).build(uuid4(), _curriculum(area), featured={})

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
    )

    assert catalog.sections.filed == ()
