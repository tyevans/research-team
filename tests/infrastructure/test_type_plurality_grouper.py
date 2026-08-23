"""Grouping areas by what their anchors are, over areas shaped like real ones."""

from research_team.domain.learning_area import AreaMember, LearningArea
from research_team.infrastructure.knowledge.type_plurality_grouper import (
    TypePluralityGrouper,
)


def _area(slug: str, *types: str) -> LearningArea:
    return LearningArea(
        slug=slug,
        members=tuple(
            AreaMember(
                entity_id=f"{slug}-{i}",
                name=f"{slug}-{i}",
                entity_type=t,
                centrality=float(len(types) - i),
            )
            for i, t in enumerate(types)
        ),
    )


def test_an_area_is_grouped_by_the_commonest_type_among_its_anchors():
    grouper = TypePluralityGrouper()

    grouped = grouper.group([_area("crew", "person", "person", "work")])

    assert grouped["crew"] == "person"


def test_a_tie_breaks_on_the_type_of_the_most_central_anchor():
    """Ties are routine -- an area of two people and two works is ordinary --
    and an arbitrary tiebreak would move a card between categories on reruns
    over an unchanged graph. Anchors are already ranked by centrality, so the
    top one decides."""
    grouper = TypePluralityGrouper()

    grouped = grouper.group([_area("mixed", "work", "person")])

    # `work` is first, so it has the higher centrality in `_area`.
    assert grouped["mixed"] == "work"


def test_an_area_with_no_members_gets_the_unclassified_key_rather_than_crashing():
    grouper = TypePluralityGrouper()

    grouped = grouper.group([LearningArea(slug="empty", members=())])

    assert grouped["empty"] == "unclassified"


def test_every_area_handed_in_comes_back_out():
    """A grouper that silently dropped an area would delete courses from the
    catalog, and the catalog would still render."""
    grouper = TypePluralityGrouper()

    grouped = grouper.group([_area("a", "person"), _area("b", "work"), _area("c", "location")])

    assert set(grouped) == {"a", "b", "c"}
