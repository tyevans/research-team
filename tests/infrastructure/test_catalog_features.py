"""The featured projection, over a real store rather than a fake.

Every assertion is on *rows*, never on "no exception was raised": an event no
projection handles counts as applied, so a build with this projection
unregistered serves an empty hero row and a 200. See CLAUDE.md under *Events*.
"""

from uuid import uuid4

import pytest

from research_team.domain.catalog_curation import CourseFeatured, CourseUnfeatured
from research_team.infrastructure.persistence.read_models import (
    CatalogFeatureProjection,
    CatalogFeatureStore,
)


@pytest.fixture
async def store(db_path):
    opened = await CatalogFeatureStore.open(db_path)
    try:
        yield opened
    finally:
        await opened.close()


async def test_a_featured_slug_is_readable_with_its_rank(store):
    project = uuid4()
    projection = CatalogFeatureProjection(store)

    await projection.handle(
        CourseFeatured(aggregate_id=project, project_id=project, slug="warp", rank=2)
    )

    assert await store.featured_for(project) == {"warp": 2}


async def test_unfeaturing_removes_it(store):
    """Not proof that `@handles(CourseFeatured)` is wired: with that decorator
    removed the feature call above is silently dropped, `featured_for` was
    already `{}`, and this assertion passes unchanged. Verified by removing
    the decorator on 2026-08-23 -- this was one of two tests (of four) that
    stayed green. Its own coverage is the unfeature handler, which the two
    tests above cannot exercise."""
    project = uuid4()
    projection = CatalogFeatureProjection(store)
    await projection.handle(
        CourseFeatured(aggregate_id=project, project_id=project, slug="warp", rank=2)
    )

    await projection.handle(
        CourseUnfeatured(aggregate_id=project, project_id=project, slug="warp")
    )

    assert await store.featured_for(project) == {}


async def test_featuring_the_same_slug_again_moves_its_rank_rather_than_duplicating(store):
    """Idempotent by row id, which is what lets the route be a plain POST with
    no read-modify-write and no version check."""
    project = uuid4()
    projection = CatalogFeatureProjection(store)
    await projection.handle(
        CourseFeatured(aggregate_id=project, project_id=project, slug="warp", rank=2)
    )

    await projection.handle(
        CourseFeatured(aggregate_id=project, project_id=project, slug="warp", rank=0)
    )

    assert await store.featured_for(project) == {"warp": 0}


async def test_one_projects_features_are_invisible_to_another(store):
    """Also stays green with `@handles(CourseFeatured)` removed -- `theirs` was
    never featured through either path, so this asserts an empty dict against
    an empty dict. Its coverage is project-scoping, not the feature handler."""
    mine, theirs = uuid4(), uuid4()
    projection = CatalogFeatureProjection(store)
    await projection.handle(
        CourseFeatured(aggregate_id=mine, project_id=mine, slug="warp", rank=0)
    )

    assert await store.featured_for(theirs) == {}
