"""The catalog's value objects, and the two derivations over them."""

from research_team.domain.course_catalog import (
    ArtRef,
    CourseCandidate,
    membership_hash,
    prominence_of,
)
from research_team.domain.learning_area import AreaMember, LearningArea


def _area(slug: str, *members: tuple[str, float]) -> LearningArea:
    return LearningArea(
        slug=slug,
        members=tuple(
            AreaMember(entity_id=n, name=n, entity_type="person", centrality=c)
            for n, c in members
        ),
    )


def test_prominence_prefers_a_well_connected_area_over_a_merely_large_one():
    """Size and centrality *disagree* here, deliberately.

    An area whose size and centrality agree cannot distinguish this formula
    from `size` alone, and a test built from one representative example would
    pass under both. See CLAUDE.md on formulas correct on every case a test
    naturally reaches.
    """
    big_and_loose = _area("big", *[(f"e{i}", 0.1) for i in range(20)])
    small_and_tight = _area("tight", *[(f"t{i}", 3.0) for i in range(4)])

    assert prominence_of(small_and_tight) > prominence_of(big_and_loose)


def test_prominence_is_zero_for_an_area_with_no_members():
    """Not a crash and not a division by zero: an empty area is a real thing
    a degenerate projection can produce, and it must sort last rather than
    fail the whole catalog."""
    assert prominence_of(LearningArea(slug="empty", members=())) == 0.0


def test_membership_hash_ignores_member_order():
    """The hash answers "is this the same set of entities", so two reads of
    one cluster that happened to order members differently must agree --
    otherwise every request invalidates every blurb."""
    one = _area("a", ("x", 1.0), ("y", 2.0))
    other = _area("a", ("y", 2.0), ("x", 1.0))

    assert membership_hash(one) == membership_hash(other)


def test_membership_hash_changes_when_an_entity_joins():
    grown = _area("a", ("x", 1.0), ("y", 2.0), ("z", 1.0))

    assert membership_hash(_area("a", ("x", 1.0), ("y", 2.0))) != membership_hash(grown)


def test_a_candidate_carries_the_current_membership_hash_so_staleness_is_computable():
    """Without this the client holds a blurb's hash and nothing to compare
    against, and 'this copy is behind' becomes uncomputable rather than merely
    unrendered."""
    area = _area("a", ("x", 1.0), ("y", 2.0))
    candidate = CourseCandidate(
        slug="a",
        title="A",
        category="person",
        prominence=prominence_of(area),
        size=area.size,
        membership_hash=membership_hash(area),
        anchors=area.anchors,
        art=ArtRef(url="data:,x", alt="A"),
    )

    assert candidate.membership_hash == membership_hash(area)
