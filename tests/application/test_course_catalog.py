"""Assembling a catalog from a curriculum, a grouper and the featured set."""

from uuid import uuid4

from research_team.application.course_catalog import CatalogService
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
    catalog = await _service().build(
        uuid4(),
        _curriculum(_area("people", 5, 2.0, "person"), _area("shows", 5, 2.0, "work")),
        featured={},
    )

    assert {c.key for c in catalog.sections.filed} >= {"person", "work"}
