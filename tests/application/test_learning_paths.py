"""What the ordering must guarantee, and what it must refuse to hide.

Several of these are invariants rather than examples, because the failures
that matter here are not "the order is wrong" -- nobody can adjudicate that
from a fixture -- but "the order silently lost an area", "the order disagrees
with itself between two views of it", and "a mutual dependency was resolved
without saying so". Those are checkable.
"""

import random

import pytest

from research_team.application.graph_read import GraphRelationship
from research_team.application.learning_paths import (
    MIN_EDGE_WEIGHT,
    _breadth,
    _leading_year,
    full_path,
    path_to,
)
from research_team.domain.learning_area import AreaMember, LearningArea


def member(eid: str, *, temporal: str | None = None) -> AreaMember:
    return AreaMember(
        entity_id=eid,
        name=eid.upper(),
        entity_type="concept",
        centrality=1.0,
        temporal=temporal,
    )


def area(slug: str, ids: list[str], *, temporal: str | None = None) -> LearningArea:
    return LearningArea(slug=slug, members=tuple(member(i, temporal=temporal) for i in ids))


def rel(a: str, b: str, *, inferred: bool = False) -> GraphRelationship:
    return GraphRelationship(
        source_id=a, target_id=b, relationship_type="uses", inferred=inferred
    )


FOUNDATION = area("foundation", ["f1", "f2", "f3"])
APPLIED = area("applied", ["p1", "p2", "p3"])


def test_the_cited_area_comes_first():
    """Direction, not size and not alphabet.

    `applied` sorts first alphabetically and both areas are the same size, so
    an implementation that fell back to either would put it first. Every
    relationship runs from the applied entities *to* the foundation ones,
    which is what "applied depends on foundation" looks like in a graph.
    """
    relationships = [rel("p1", "f1"), rel("p2", "f2"), rel("p3", "f3")]

    path = full_path([APPLIED, FOUNDATION], relationships, [])

    assert path.area_slugs == ("foundation", "applied")


def test_a_mutual_dependency_is_marked_rather_than_resolved_silently():
    """Two areas that genuinely interleave produce a contested edge.

    The edge that had to be dropped to linearise is kept and flagged. A clean
    order with it thrown away would be the more confident answer and the less
    true one, and the reader deciding whether to trust the path is exactly the
    one who needs to know a coin was flipped.
    """
    third = area("theory", ["t1", "t2", "t3"])
    relationships = [
        rel("p1", "f1"),
        rel("p2", "f2"),
        rel("f1", "t1"),
        rel("f2", "t2"),
        rel("t1", "p1"),
        rel("t2", "p2"),
    ]

    path = full_path([APPLIED, FOUNDATION, third], relationships, [])

    assert len(path.area_slugs) == 3
    assert path.contested, "a three-way cycle produced no contested edge"
    assert all(
        e.before in path.area_slugs and e.after in path.area_slugs for e in path.contested
    )


def test_every_area_appears_exactly_once():
    """The invariant a silently-truncated curriculum would break.

    A path missing an area renders perfectly and reads as complete, which is
    the failure mode `CLAUDE.md` describes for a missing projection. Asserted
    over a graph dense enough to have cycles, because that is where a
    topological sort drops things.
    """
    areas = [area(f"a{i}", [f"a{i}-{j}" for j in range(3)]) for i in range(6)]
    rng = random.Random(3)
    ids = [m.entity_id for a in areas for m in a.members]
    relationships = [rel(rng.choice(ids), rng.choice(ids)) for _ in range(60)]

    path = full_path(areas, relationships, [])

    assert sorted(path.area_slugs) == sorted(a.slug for a in areas)
    assert len(set(path.area_slugs)) == len(path.area_slugs)


def test_a_destination_path_is_a_subsequence_of_the_full_path():
    """Two paths that disagreed about order would be two curricula.

    The strongest invariant in this module and the one a reader implicitly
    relies on: opening "everything needed for X" must not reorder what the
    complete path already said, or a learner who switches views is told two
    incompatible things and has no way to choose.
    """
    areas = [area(f"a{i}", [f"a{i}-{j}" for j in range(3)]) for i in range(6)]
    rng = random.Random(11)
    ids = [m.entity_id for a in areas for m in a.members]
    relationships = [rel(rng.choice(ids), rng.choice(ids)) for _ in range(60)]

    complete = full_path(areas, relationships, [])
    for destination in complete.area_slugs:
        cut = path_to(destination, areas, relationships, [])
        assert cut is not None
        assert destination in cut.area_slugs
        positions = [complete.area_slugs.index(s) for s in cut.area_slugs]
        assert positions == sorted(positions), destination


def test_a_destination_that_is_not_an_area_is_not_an_error():
    assert path_to("no-such-area", [FOUNDATION, APPLIED], [], []) is None


def test_ordering_is_deterministic():
    areas = [area(f"a{i}", [f"a{i}-{j}" for j in range(3)]) for i in range(6)]
    rng = random.Random(5)
    ids = [m.entity_id for a in areas for m in a.members]
    relationships = [rel(rng.choice(ids), rng.choice(ids)) for _ in range(50)]
    reference = full_path(areas, relationships, [])

    shuffler = random.Random(99)
    for _ in range(8):
        shuffled_areas = list(areas)
        shuffled_rels = list(relationships)
        shuffler.shuffle(shuffled_areas)
        shuffler.shuffle(shuffled_rels)
        assert full_path(shuffled_areas, shuffled_rels, []).area_slugs == reference.area_slugs


def test_an_inferred_edge_does_not_vote():
    """Inferred edges are arithmetic over two dates, not something a document
    said. Counting them would let the temporal signal in a second time through
    the term that is supposed to be checkable against a source."""
    inferred_only = [rel("p1", "f1", inferred=True) for _ in range(20)]

    path = full_path([APPLIED, FOUNDATION], inferred_only, [])

    assert not [e for e in path.edges if "cited" in e.reason]


def test_breadth_is_a_mean_so_a_big_area_is_not_foundational_by_size():
    """Separates the mean from the sum.

    A sum makes breadth a second, noisier size signal, so the largest cluster
    would always sort first regardless of how thinly its entities are spread.
    Here the small area's entities appear in three passages each and the large
    area's in one each -- under a sum the large area wins 9 to 6.
    """
    small = area("small", ["s1", "s2"])
    large = area("large", ["l1", "l2", "l3", "l4", "l5", "l6", "l7", "l8", "l9"])
    presence = {"s1": 3, "s2": 3, **{f"l{i}": 1 for i in range(1, 10)}}

    assert _breadth(small, presence) > _breadth(large, presence)


def test_no_edge_is_claimed_between_areas_with_no_evidence():
    """Without a floor every pair gets an edge and the digraph is complete --
    a total order with no structure in it, presented as confidently as a real
    one."""
    path = full_path([FOUNDATION, APPLIED], [], [])

    assert len(path.area_slugs) == 2
    assert all(e.weight >= MIN_EDGE_WEIGHT for e in path.edges)
    assert path.edges == ()


@pytest.mark.parametrize(
    ("rendered", "expected"),
    [
        ("AD 380", 380),
        ("380", 380),
        ("44 BC", -44),
        ("44 BCE", -44),
        ("c. 1200-1250", 1200),
        (None, None),
        ("early spring", None),
    ],
)
def test_leading_year_reads_what_it_can_and_gives_up_otherwise(rendered, expected):
    assert _leading_year(rendered) == expected
