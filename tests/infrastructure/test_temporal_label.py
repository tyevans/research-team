"""The model's wording, not the parser's, is what a reader is shown.

`_DatingProvider` rewrites 'AD 476' to '0476' so redstring's parser reads it
as a year rather than filling in a month and day. That rewrite is a
parsing detail and has no business on a timeline band or a graph node, where
'0476' reads as a bug rather than as a date.

These are unit tests over `entity_extent_label`, not the readers, because the
readers need a live graph store and the thing being decided here is a choice
between two strings.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

from redstring import DatePrecision, TemporalExtent, UncertaintyMarker

from research_team.infrastructure.knowledge.redstring_adapter import RAW_TEMPORAL_PROPERTY
from research_team.infrastructure.knowledge.temporal_rendering import entity_extent_label


def entity(*, temporal=None, properties=None):
    return SimpleNamespace(temporal=temporal, properties=properties or {})


YEAR_476 = TemporalExtent(
    start_date=datetime(476, 1, 1, tzinfo=UTC),
    precision=DatePrecision.YEAR,
    uncertainty=UncertaintyMarker.EXACT,
    original_text="0476",
)


def test_the_models_wording_wins_over_the_normalised_text() -> None:
    """Fails with `render_extent` alone, which returns the '0476' it was given."""
    labelled = entity(temporal=YEAR_476, properties={RAW_TEMPORAL_PROPERTY: "AD 476"})

    assert entity_extent_label(labelled) == "AD 476"


def test_an_entity_with_no_raw_wording_falls_back_to_the_extent() -> None:
    """Everything extracted before this property existed still renders.

    Events are not rewritten, so the whole existing graph is entities with a
    `temporal` and no `temporal_expression` property.
    """
    assert entity_extent_label(entity(temporal=YEAR_476)) == "0476"


def test_a_bc_entity_is_labelled_from_its_wording_alone() -> None:
    """The case with no extent at all to fall back on.

    A BC date has no representable `TemporalExtent`, so before this the
    entity had nothing to show. Its wording is the only date it will have
    until BC has a representation, and showing it beats showing nothing.
    """
    labelled = entity(properties={RAW_TEMPORAL_PROPERTY: "44 BC"})

    assert entity_extent_label(labelled) == "44 BC"


def test_an_undated_entity_has_no_label() -> None:
    assert entity_extent_label(entity()) is None
