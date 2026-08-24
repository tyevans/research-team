"""The art library cache. A cache, not a projection -- nothing on the event
log describes a piece of art, matching `test_course_blurbs.py` for
`CourseBlurbStore`."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from research_team.infrastructure.persistence.read_models import ArtStore


@pytest.fixture
async def store(db_path):
    opened = await ArtStore.open(db_path)
    try:
        yield opened
    finally:
        await opened.close()


async def test_a_stored_piece_of_art_round_trips(store):
    art_id = uuid4()
    await store.put(
        art_id,
        svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>',
        description="A rotated square in blue and orange.",
        tags=["geometric", "blue"],
        palette="work",
        created_at=datetime.now(UTC),
        source="generated",
    )

    row = await store.get(art_id)

    assert row is not None
    assert row.description == "A rotated square in blue and orange."
    assert row.tags == ["geometric", "blue"]
    assert row.palette == "work"
    assert row.source == "generated"
    assert row.uses == 0


async def test_an_unknown_id_returns_none(store):
    assert await store.get(uuid4()) is None


async def test_all_returns_every_row(store):
    first, second = uuid4(), uuid4()
    for art_id in (first, second):
        await store.put(
            art_id,
            svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>',
            description=f"piece {art_id}",
            tags=[],
            palette="",
            created_at=datetime.now(UTC),
            source="seeded",
        )

    rows = await store.all()

    assert {row.id for row in rows} == {first, second}


async def test_increment_uses_bumps_the_counter(store):
    art_id = uuid4()
    await store.put(
        art_id,
        svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"/>',
        description="reused piece",
        tags=[],
        palette="",
        created_at=datetime.now(UTC),
        source="generated",
    )

    await store.increment_uses(art_id)
    await store.increment_uses(art_id)

    row = await store.get(art_id)
    assert row is not None
    assert row.uses == 2


async def test_increment_uses_on_an_unknown_id_does_not_raise(store):
    # No row to bump; the method is a no-op rather than an error, matching
    # every other store's tolerance for a caller racing an id that never
    # got written -- see `ArtStore.increment_uses`'s docstring.
    await store.increment_uses(uuid4())
