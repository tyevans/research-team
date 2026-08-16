"""Dates the model returns must reach the graph, or be kept where they fell.

These start from the real defect rather than from the adapter's shape. On
2026-08-15 the Ancient Rome project held 2,525 entities and 8 temporal
extents, and one of those 8 -- the Edict of Milan, `original_text` "313" --
was stored as 0313-08-25 at DAY precision, 25 August being the publication
date of the Wikipedia article it was extracted from. The date was not missing;
it was invented.

Every test here drives a real `build_graph` through `RedstringKnowledge.ingest`
with a canned provider answer, so what is asserted is what the store and the
event actually hold, not what a helper returned. Per CLAUDE.md's note on
projections: asserting that the ingest *succeeded* would pass with the whole
correction removed, so each assertion is on a stored value.
"""

from uuid import uuid4

import pytest
from eventsource import collect
from redstring import FakeLlmProvider, document_stream

from research_team.application.knowledge import SourceRef
from research_team.infrastructure.knowledge.redstring_adapter import RAW_TEMPORAL_PROPERTY


async def extracted_entities(store, project_id, source_id):
    """The entities of the `DocumentExtracted` this ingest appended.

    The event rather than the graph store, deliberately: the event is what the
    original measurement folded to find 8 dated entities in 2,525, so an
    assertion here is against the same surface the defect was counted on.
    """
    stream = document_stream(tenant_id=project_id, source_id=source_id)
    envelopes = await collect(store.read_stream(stream))
    return envelopes[0].event.entities


def answer_dated(expression: str) -> dict:
    """One event entity carrying `expression`, and nothing else to distract."""
    return {
        "entities": [
            {
                "name": "Edict of Milan",
                "entity_type": "event",
                "temporal_expression": expression,
            }
        ],
        "relationships": [],
    }


async def ingest_dated(tmp_path, build_adapter, expression: str):
    """Ingest one document whose single entity carries `expression`.

    `published_at` is set, and set to a date whose month and day are nothing
    like January the 1st, because the bug being tested is precisely that those
    two numbers leak out of it and into the entity's date.
    """
    project_id = uuid4()
    adapter, store, _ = build_adapter(
        tmp_path,
        project_id,
        provider=FakeLlmProvider(by_substring={}, default=answer_dated(expression)),
    )
    await adapter.ingest(
        SourceRef(
            source_id="edict-of-milan",
            uri="https://en.wikipedia.org/wiki/Edict_of_Milan",
            title="Edict of Milan - Wikipedia",
            text="The Edict of Milan was issued in " + expression + ". " * 40,
            published_at="2003-08-25",
        )
    )
    entities = await extracted_entities(store, project_id, "edict-of-milan")
    return next(e for e in entities if e.name == "Edict of Milan")


def answer_dated_in_properties(expression: str) -> dict:
    """The shape the model actually returns, measured against the real one.

    `temporal_expression` inside `properties`, and the schema field left
    empty. See `TestTheModelPutsTheDateInProperties` for why this is the
    ordinary case rather than a malformed answer.
    """
    return {
        "entities": [
            {
                "name": "Edict of Thessalonica",
                "entity_type": "event",
                "properties": {
                    "temporal_expression": expression,
                    "outcome": "Nicene Christianity received normative status",
                },
            }
        ],
        "relationships": [],
    }


@pytest.mark.asyncio
class TestTheModelPutsTheDateInProperties:
    """The defect that actually emptied the timeline.

    Traced against qwen3.8-27b-mtp on the real 'Edict of Milan' article on
    2026-08-15: across three chunks, *every* `ExtractedEntity` came back with
    `temporal_expression=None`, while the entities' `properties` held
    `{"temporal_expression": "AD 380", "outcome": ...}`. The model is
    answering the prompt; it just files the answer alongside `outcome`,
    `role` and `creator` -- the properties the domain schema declares -- and
    those all live in the free-form `properties` dict.

    That is a reasonable reading of the prompt, which says to put the date "in
    that entity's `temporal_expression` field". The schema's own per-type
    fields are exactly what `properties` is, so nothing distinguishes this one
    as belonging somewhere else.

    `_build_extent` reads only the schema field, so the date is dropped before
    any parsing is attempted. This is upstream of every parsing defect the
    other tests here cover: those only matter once the field is populated.
    """

    async def test_a_date_filed_under_properties_still_dates_the_entity(
        self, tmp_path, build_adapter
    ):
        project_id = uuid4()
        adapter, store, _ = build_adapter(
            tmp_path,
            project_id,
            provider=FakeLlmProvider(
                by_substring={}, default=answer_dated_in_properties("AD 380")
            ),
        )
        await adapter.ingest(
            SourceRef(
                source_id="thessalonica",
                uri="https://en.wikipedia.org/wiki/Edict_of_Thessalonica",
                title="Edict of Thessalonica - Wikipedia",
                text="The Edict of Thessalonica was issued in AD 380. " * 40,
                published_at="2003-08-25",
            )
        )
        entities = await extracted_entities(store, project_id, "thessalonica")
        entity = next(e for e in entities if e.name == "Edict of Thessalonica")

        assert entity.temporal is not None
        assert entity.temporal.start_date.year == 380
        assert entity.temporal.precision.name == "YEAR"

    async def test_the_schemas_own_properties_are_left_alone(self, tmp_path, build_adapter):
        """Lifting one key must not disturb the others it sits beside."""
        project_id = uuid4()
        adapter, store, _ = build_adapter(
            tmp_path,
            project_id,
            provider=FakeLlmProvider(
                by_substring={}, default=answer_dated_in_properties("AD 380")
            ),
        )
        await adapter.ingest(
            SourceRef(
                source_id="thessalonica",
                uri="https://en.wikipedia.org/wiki/Edict_of_Thessalonica",
                title="Edict of Thessalonica - Wikipedia",
                text="The Edict of Thessalonica was issued in AD 380. " * 40,
                published_at="2003-08-25",
            )
        )
        entities = await extracted_entities(store, project_id, "thessalonica")
        entity = next(e for e in entities if e.name == "Edict of Thessalonica")

        assert entity.properties["outcome"] == "Nicene Christianity received normative status"


@pytest.mark.asyncio
class TestARelativeDateIsRefused:
    """A narrative relative date must not be read against `published_at`.

    'two years earlier' came back on the Edict of Serdica in the same traced
    run. Resolved against the article's publication date it means 2001; the
    text means two years before 313. redstring raises
    `AmbiguousReferenceDateError` only when there is no reference date at all,
    and for these documents there always is one -- so the wrong answer is the
    one that parses cleanly.

    This is the same failure as the fabricated day, one level up: a vantage
    point that is right for a news article is nonsense for an encyclopedia
    entry narrating antiquity.
    """

    async def test_two_years_earlier_dates_nothing(self, tmp_path, build_adapter):
        project_id = uuid4()
        adapter, store, _ = build_adapter(
            tmp_path,
            project_id,
            provider=FakeLlmProvider(
                by_substring={}, default=answer_dated_in_properties("two years earlier")
            ),
        )
        await adapter.ingest(
            SourceRef(
                source_id="serdica",
                uri="https://en.wikipedia.org/wiki/Edict_of_Serdica",
                title="Edict of Serdica - Wikipedia",
                text="The Edict of Serdica was issued two years earlier. " * 40,
                published_at="2003-08-25",
            )
        )
        entities = await extracted_entities(store, project_id, "serdica")
        entity = next(e for e in entities if e.name == "Edict of Thessalonica")

        assert entity.temporal is None or entity.temporal.start_date is None
        assert entity.properties[RAW_TEMPORAL_PROPERTY] == "two years earlier"


@pytest.mark.asyncio
class TestAnAncientYearIsNotInvented:
    async def test_a_three_digit_year_keeps_year_precision(self, tmp_path, build_adapter):
        """The exact value that is wrong in the real database.

        Fails against the unfixed adapter with `start_date` 0313-08-25 and
        precision DAY -- the article's own month and day.
        """
        entity = await ingest_dated(tmp_path, build_adapter, "313")

        assert entity.temporal is not None
        assert entity.temporal.start_date.year == 313
        assert entity.temporal.start_date.month == 1
        assert entity.temporal.start_date.day == 1
        assert entity.temporal.precision.name == "YEAR"

    async def test_an_ad_year_is_dated_at_all(self, tmp_path, build_adapter):
        entity = await ingest_dated(tmp_path, build_adapter, "AD 476")

        assert entity.temporal is not None
        assert entity.temporal.start_date.year == 476
        assert entity.temporal.precision.name == "YEAR"

    async def test_a_century_is_dated_at_all(self, tmp_path, build_adapter):
        """`the 2nd century AD` yields no extent whatsoever unfixed."""
        entity = await ingest_dated(tmp_path, build_adapter, "the 2nd century AD")

        assert entity.temporal is not None
        assert entity.temporal.start_date.year == 101
        assert entity.temporal.end_date.year == 200


@pytest.mark.asyncio
class TestTheModelsOwnWordsSurvive:
    async def test_the_raw_expression_is_kept_on_the_entity(self, tmp_path, build_adapter):
        """Normalising rewrites the text the parser sees; a reader wants the original.

        Without this the timeline would label the Edict of Milan '0476',
        which is the normalisation leaking into the interface.
        """
        entity = await ingest_dated(tmp_path, build_adapter, "AD 476")

        assert entity.properties[RAW_TEMPORAL_PROPERTY] == "AD 476"

    async def test_a_bc_date_is_kept_even_though_it_cannot_be_dated(
        self, tmp_path, build_adapter
    ):
        """The half that is not fixed, pinned so the loss stays visible.

        `datetime.MINYEAR` is 1, so 44 BC has no representation in
        `TemporalExtent` and the entity is genuinely undated. What must not
        happen is that the model's answer disappears with it: this assertion
        is the difference between a date we cannot draw yet and a date nobody
        can tell was ever extracted.
        """
        entity = await ingest_dated(tmp_path, build_adapter, "44 BC")

        assert entity.temporal is None or entity.temporal.start_date is None
        assert entity.properties[RAW_TEMPORAL_PROPERTY] == "44 BC"

    async def test_an_undated_entity_gains_no_property(self, tmp_path, build_adapter):
        """The ordinary case stays clean.

        Most entities are undated, and writing an empty marker onto every one
        of them would put a field in the event payload that means nothing.

        **This one passes with the change reverted**, unlike the five above
        it. It is not evidence the correction works; it is the guard against
        the correction applying itself where there was nothing to correct,
        and it only earns its place if that ever regresses.
        """
        project_id = uuid4()
        adapter, store, _ = build_adapter(
            tmp_path,
            project_id,
            provider=FakeLlmProvider(
                by_substring={},
                default={
                    "entities": [{"name": "Roman Senate", "entity_type": "organization"}],
                    "relationships": [],
                },
            ),
        )
        await adapter.ingest(
            SourceRef(
                source_id="senate",
                uri="https://en.wikipedia.org/wiki/Roman_Senate",
                title="Roman Senate",
                text="The Senate was a deliberative body. " * 40,
                published_at="2003-08-25",
            )
        )
        entities = await extracted_entities(store, project_id, "senate")
        entity = next(e for e in entities if e.name == "Roman Senate")

        assert RAW_TEMPORAL_PROPERTY not in entity.properties
