"""`ProjectTimelineReader` over an in-memory store.

Fixtures build entities directly rather than running extraction: the reader's
job is turning stored entities into bands, and an extraction step in the way
would mean a failure here could be a failure there.
"""

from datetime import UTC, datetime
from uuid import uuid4

from redstring import (
    Alias,
    DatePrecision,
    Entity,
    ExtractionMethod,
    InMemoryGraphStore,
    Provenance,
    TemporalExtent,
    UncertaintyMarker,
)

from research_team.application.timeline_read import TimelineInterval
from research_team.infrastructure.knowledge.timeline_reader import ProjectTimelineReader

TENANT_ID = uuid4()


def _entity(
    entity_id,
    name: str,
    entity_type: str = "event",
    *,
    temporal: TemporalExtent | None = None,
) -> Entity:
    """Copied from `tests/application/test_graph_read.py`'s own `_entity`.

    redstring 0.8.0 requires `tenant_id`, `normalized_name` and `provenance`
    beyond what the brief this test was written against assumed; kept
    identical to the canonical fixture rather than reinvented so the two
    suites seed an `InMemoryGraphStore` the same way.
    """
    return Entity(
        id=entity_id,
        tenant_id=TENANT_ID,
        name=name,
        normalized_name=name.lower(),
        entity_type=entity_type,
        # Fixed rather than `datetime.now`: nothing under test reads
        # `observed_at`, and a moving value in a fixture is a difference that
        # shows up in a failure diff without meaning anything.
        provenance=Provenance(
            observed_at=datetime(2026, 1, 1, tzinfo=UTC),
            extraction_method=ExtractionMethod.MANUAL,
            confidence=1.0,
        ),
        temporal=temporal,
    )


def _year(year: int) -> TemporalExtent:
    return TemporalExtent(
        start_date=datetime(year, 1, 1, tzinfo=UTC), precision=DatePrecision.YEAR
    )


async def _reader_over(entities: list[Entity]) -> ProjectTimelineReader:
    store = InMemoryGraphStore()
    if entities:
        await store.upsert_entities(entities)
    return ProjectTimelineReader(project_id=TENANT_ID, store=store)


async def test_a_dated_entity_becomes_a_band_carrying_both_its_text_and_its_interval():
    """The two quantities `TimelineBand` keeps apart.

    `extent` is what the document said; `start`/`end` is what gets drawn.
    Asserted together because an implementation that filled one from the other
    would satisfy either assertion alone.
    """
    reader = await _reader_over([_entity(uuid4(), "Waterloo", temporal=_year(1815))])

    timeline = await reader.timeline()

    (band,) = timeline.bands
    assert band.name == "Waterloo"
    assert band.extent == "1815"
    assert band.start == "1815-01-01T00:00:00+00:00"
    assert band.end == "1816-01-01T00:00:00+00:00"


async def test_undated_entities_are_absent_from_the_bands_and_counted_instead():
    """The ordinary case, not the edge case.

    Most entities in a real graph are not events. A timeline showing two bands
    with no denominator reads as "this project contains two things".
    """
    reader = await _reader_over(
        [
            _entity(uuid4(), "Waterloo", temporal=_year(1815)),
            _entity(uuid4(), "Trafalgar", temporal=_year(1805)),
            _entity(uuid4(), "Cavalry", temporal=None),
            _entity(uuid4(), "Artillery", temporal=TemporalExtent()),
            _entity(uuid4(), "Third act", temporal=TemporalExtent(sequence_position=3)),
        ]
    )

    timeline = await reader.timeline()

    assert [band.name for band in timeline.bands] == ["Trafalgar", "Waterloo"]
    assert timeline.undated_count == 3


async def test_bands_are_ordered_by_when_they_begin():
    reader = await _reader_over(
        [
            _entity(uuid4(), "Third", temporal=_year(1900)),
            _entity(uuid4(), "First", temporal=_year(1700)),
            _entity(uuid4(), "Second", temporal=_year(1800)),
        ]
    )

    timeline = await reader.timeline()

    assert [band.name for band in timeline.bands] == ["First", "Second", "Third"]


async def test_circa_and_exact_draw_alike_and_read_differently():
    """Both halves, because either alone permits a wrong implementation.

    The intervals matching pins the decision not to invent a margin. The
    markers differing pins that the decision is still visible to a reader --
    an implementation that dropped `uncertainty` would pass the first half.
    """
    reader = await _reader_over(
        [
            _entity(
                uuid4(),
                "Circa",
                temporal=TemporalExtent(
                    start_date=datetime(1850, 1, 1, tzinfo=UTC),
                    precision=DatePrecision.YEAR,
                    uncertainty=UncertaintyMarker.CIRCA,
                ),
            ),
            _entity(
                uuid4(),
                "Exact",
                temporal=TemporalExtent(
                    start_date=datetime(1850, 1, 1, tzinfo=UTC),
                    precision=DatePrecision.YEAR,
                    uncertainty=UncertaintyMarker.EXACT,
                ),
            ),
        ]
    )

    timeline = await reader.timeline()

    by_name = {band.name: band for band in timeline.bands}
    assert (by_name["Circa"].start, by_name["Circa"].end) == (
        by_name["Exact"].start,
        by_name["Exact"].end,
    )
    assert by_name["Circa"].uncertainty == "CIRCA"
    assert by_name["Exact"].uncertainty == "EXACT"


async def test_a_before_marker_leaves_the_start_open():
    reader = await _reader_over(
        [
            _entity(
                uuid4(),
                "Ancient",
                temporal=TemporalExtent(
                    start_date=datetime(1500, 1, 1, tzinfo=UTC),
                    precision=DatePrecision.YEAR,
                    uncertainty=UncertaintyMarker.BEFORE,
                ),
            )
        ]
    )

    (band,) = (await reader.timeline()).bands

    assert band.start is None
    assert band.end == "1500-01-01T00:00:00+00:00"


async def test_entity_type_restricts_which_entities_are_banded():
    reader = await _reader_over(
        [
            _entity(uuid4(), "A battle", entity_type="event", temporal=_year(1815)),
            _entity(uuid4(), "A general", entity_type="person", temporal=_year(1815)),
        ]
    )

    timeline = await reader.timeline(entity_type="event")

    assert [band.name for band in timeline.bands] == ["A battle"]


async def test_an_interval_restricts_the_bands_to_the_ones_it_intersects():
    """The window, doing something -- an adapter that dropped `interval=` on
    the floor would return all three and fail here.
    """
    reader = await _reader_over(
        [
            _entity(uuid4(), "Too early", temporal=_year(1700)),
            _entity(uuid4(), "Inside", temporal=_year(1815)),
            _entity(uuid4(), "Too late", temporal=_year(1900)),
        ]
    )

    timeline = await reader.timeline(
        interval=TimelineInterval(
            start=datetime(1800, 1, 1, tzinfo=UTC), end=datetime(1850, 1, 1, tzinfo=UTC)
        )
    )

    assert [band.name for band in timeline.bands] == ["Inside"]


async def test_an_interval_open_at_one_end_bounds_only_the_other():
    """`None` as infinity outwards, which is the half of `Bounds` a caller
    reaches by parsing only `from`. Asserted with the *upper* end open so a
    translation that silently swapped the two would return "Too early" and
    fail.
    """
    reader = await _reader_over(
        [
            _entity(uuid4(), "Too early", temporal=_year(1700)),
            _entity(uuid4(), "Inside", temporal=_year(1815)),
            _entity(uuid4(), "Later still", temporal=_year(1900)),
        ]
    )

    timeline = await reader.timeline(
        interval=TimelineInterval(start=datetime(1800, 1, 1, tzinfo=UTC), end=None)
    )

    assert [band.name for band in timeline.bands] == ["Inside", "Later still"]


async def test_no_interval_bands_everything_dated():
    """The default path, pinned because `interval` was threaded through it
    late: this would have passed before that change and must go on passing.
    """
    reader = await _reader_over(
        [
            _entity(uuid4(), "Early", temporal=_year(1700)),
            _entity(uuid4(), "Late", temporal=_year(1900)),
        ]
    )

    timeline = await reader.timeline()

    assert [band.name for band in timeline.bands] == ["Early", "Late"]


async def test_a_windowed_read_still_counts_every_undated_entity():
    """The denominator is not narrowed by the window, and the subtraction it
    replaced would have got this wrong.

    `len(everything) - len(bands)` would answer 2 here -- reporting the entity
    dated outside the window as undated -- so this fails against the
    implementation that predates `interval`.
    """
    reader = await _reader_over(
        [
            _entity(uuid4(), "Inside", temporal=_year(1815)),
            _entity(uuid4(), "Outside", temporal=_year(1900)),
            _entity(uuid4(), "Cavalry", temporal=None),
        ]
    )

    timeline = await reader.timeline(
        interval=TimelineInterval(
            start=datetime(1800, 1, 1, tzinfo=UTC), end=datetime(1850, 1, 1, tzinfo=UTC)
        )
    )

    assert [band.name for band in timeline.bands] == ["Inside"]
    assert timeline.undated_count == 1


async def test_a_negative_limit_returns_one_band_rather_than_dropping_the_last():
    """The lower clamp, which is not cosmetic.

    Without `max(1, ...)` a limit of -1 reaches `bands[:-1]`, and Python's
    slice semantics return every band *but the last* while `truncated` blames
    the cap. This test fails on that implementation with three bands where it
    expects one.
    """
    reader = await _reader_over(
        [_entity(uuid4(), f"Event {n}", temporal=_year(1800 + n)) for n in range(4)]
    )

    timeline = await reader.timeline(limit=-1)

    assert [band.name for band in timeline.bands] == ["Event 0"]
    assert timeline.truncated is True


async def test_the_cap_sets_truncated_and_a_graph_at_exactly_the_cap_does_not():
    """Both directions, because the off-by-one is the whole risk.

    A drawing missing bars looks exactly like a drawing with none to miss, and
    a complete drawing wrongly flagged sends a reader looking for entities
    that are all there.
    """
    reader = await _reader_over(
        [_entity(uuid4(), f"Event {n}", temporal=_year(1800 + n)) for n in range(5)]
    )

    assert (await reader.timeline(limit=3)).truncated is True
    assert (await reader.timeline(limit=5)).truncated is False


async def test_an_absorbed_entity_does_not_draw_beside_the_one_that_absorbed_it():
    """A merge is not a delete, and on a timeline that shows as corroboration.

    `find_entities` returns absorbed entities deliberately -- the row is what
    `undo_merge` restores. Two bars with identical extents and near-identical
    names read as two sources agreeing, which is the opposite of what one
    entity counted twice means.
    """
    canonical = _entity(uuid4(), "Waterloo", temporal=_year(1815))
    absorbed = _entity(uuid4(), "Battle of Waterloo", temporal=_year(1815))
    store = InMemoryGraphStore()
    await store.upsert_entities([canonical, absorbed])
    await store.upsert_alias(
        Alias(
            id=uuid4(),
            tenant_id=TENANT_ID,
            canonical_entity_id=canonical.id,
            alias_entity_id=absorbed.id,
            merged_at=datetime.now(UTC),
            merge_reason="the same battle under two names",
        )
    )
    reader = ProjectTimelineReader(project_id=TENANT_ID, store=store)

    timeline = await reader.timeline()

    assert [band.name for band in timeline.bands] == ["Waterloo"]


async def test_an_empty_project_is_an_empty_timeline_rather_than_an_error():
    reader = await _reader_over([])

    timeline = await reader.timeline()

    assert timeline.bands == ()
    assert timeline.undated_count == 0
    assert timeline.truncated is False
