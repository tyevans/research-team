"""What the area projection must do, chosen to separate it from its near-misses.

`CLAUDE.md` records the failure these tests are shaped against: a formula
correct on every case a test naturally reaches is indistinguishable from one
that is correct. So several tests below are built to fail under the *plausible
alternative implementation* rather than under an obviously broken one --
`test_a_passage_is_one_voice_however_long_it_is` fails against
un-normalised co-mention weighting, and `test_projection_is_deterministic`
fails against any implementation whose tie-break is insertion order. Neither
would fail against a naive but well-formed clusterer, which is the point.
"""

import random
import time

import pytest

from research_team.application.area_projection import (
    CO_MENTION_BUDGET,
    MAX_CLUSTERED_ENTITIES,
    MAX_PASSAGE_ENTITIES,
    GraphTooLarge,
    _co_mention_edges,
    project_areas,
    slugify,
)
from research_team.application.graph_read import Graph, GraphEntity, GraphRelationship


def entity(eid: str, name: str | None = None, etype: str = "concept") -> GraphEntity:
    return GraphEntity(entity_id=eid, name=name or eid.upper(), entity_type=etype)


def rel(a: str, b: str) -> GraphRelationship:
    return GraphRelationship(source_id=a, target_id=b, relationship_type="relates_to")


def graph(entities, relationships, *, truncated: bool = False) -> Graph:
    return Graph(
        entities=tuple(entities), relationships=tuple(relationships), truncated=truncated
    )


def two_clique_graph() -> Graph:
    """Two four-cliques joined by a single bridge.

    The textbook case with an unambiguous answer: modularity of the two-way
    split is far above modularity of the whole, so any correct implementation
    finds two communities. It is here as a floor, not as evidence -- a test
    that only this passes proves the code clusters *something*.
    """
    left = ["a1", "a2", "a3", "a4"]
    right = ["b1", "b2", "b3", "b4"]
    edges = []
    for group in (left, right):
        for i, x in enumerate(group):
            for y in group[i + 1 :]:
                edges.append(rel(x, y))
    edges.append(rel("a1", "b1"))
    return graph([entity(e) for e in left + right], edges)


def test_two_communities_separate():
    projection = project_areas(two_clique_graph(), [])

    assert len(projection.areas) == 2
    grouped = {frozenset(m.entity_id for m in area.members) for area in projection.areas}
    assert grouped == {
        frozenset({"a1", "a2", "a3", "a4"}),
        frozenset({"b1", "b2", "b3", "b4"}),
    }


def ring_graph(size: int = 12) -> Graph:
    """A ring of equal-weight edges: the most tie-dense graph there is.

    Every possible first merge has *identical* delta-Q, so the answer is
    decided entirely by the tie-break and by nothing else. That is why the
    determinism test uses this rather than the two-clique fixture, where the
    merges are so unambiguous that no tie-break is ever consulted and an
    order-dependent implementation passes.
    """
    ids = [f"n{i}" for i in range(size)]
    return graph(
        [entity(i) for i in ids],
        [rel(ids[i], ids[(i + 1) % size]) for i in range(size)],
    )


def test_projection_is_deterministic():
    """The same graph presented in any order projects identically.

    **This is the test the slug depends on.** An area's slug is a directory
    name under `/course/areas/` and a URL segment, so an ordering-dependent
    answer moves a course's home between two runs over one unchanged graph.

    **Proved red on 2026-08-22**, and it took two attempts to get a fixture
    that could prove anything. Against the plausible alternative -- an
    insertion counter in the heap key, which is the standard trick for
    avoiding comparison of payloads, plus unsorted adjacency iteration -- this
    test fails on **12 of 12 shuffles** with the ring and on **0 of 12** with
    the two-clique fixture it originally used. The cliques merge so
    unambiguously that the tie-break is never consulted, so the first version
    of this test passed against both implementations and proved nothing.
    """
    base = ring_graph()
    reference = project_areas(base, [])
    assert len(reference.areas) > 1, "a fixture that yields one area cannot detect reordering"

    rng = random.Random(7)
    for _ in range(12):
        entities = list(base.entities)
        relationships = list(base.relationships)
        rng.shuffle(entities)
        rng.shuffle(relationships)
        shuffled = project_areas(graph(entities, relationships), [])

        assert [a.slug for a in shuffled.areas] == [a.slug for a in reference.areas]
        assert [[m.entity_id for m in a.members] for a in shuffled.areas] == [
            [m.entity_id for m in a.members] for a in reference.areas
        ]


def test_a_passage_is_one_voice_however_long_it_is():
    """Every passage contributes `CO_MENTION_BUDGET` in total, not per pair.

    Asserted on `_co_mention_edges` directly rather than through a projection,
    and that choice is the point rather than a convenience. Pairs grow
    quadratically with passage length while relationships grow linearly, so
    un-normalised weighting makes the longest passage decide the map -- but
    *whether* it does at any particular graph size depends on how cohesive
    that graph's real communities happen to be. An outcome test therefore
    passes or fails on the fixture's density rather than on the formula, which
    is exactly the `CLAUDE.md` failure: the first version of this test used two
    four-cliques, passed under both formulas, and proved nothing.

    Here the two formulas cannot agree. A two-entity passage and a
    twenty-entity passage give their pairs the same weight under the
    un-normalised form and weights 190x apart under this one.

    **Proved red on 2026-08-22** by replacing `share = CO_MENTION_BUDGET /
    pairs` with `share = CO_MENTION_BUDGET`.
    """
    small = frozenset({"a", "b"})
    large = frozenset(f"e{i}" for i in range(20))
    known = small | large

    edges, counted = _co_mention_edges([small, large], known)

    assert counted == 2
    assert edges[("a", "b")] == pytest.approx(CO_MENTION_BUDGET)
    assert sum(w for pair, w in edges.items() if pair != ("a", "b")) == pytest.approx(
        CO_MENTION_BUDGET
    )
    assert edges[("e0", "e1")] == pytest.approx(CO_MENTION_BUDGET / 190)


def test_an_index_like_passage_is_ignored_entirely():
    """A passage naming more than `MAX_PASSAGE_ENTITIES` licenses no inference.

    Not a performance guard. A passage listing forty entities is a contents
    page, an index or a glossary, and "these belong together" is false of it:
    everything in the project appears in it. Normalisation stops such a
    passage dominating by volume but cannot stop it wiring the whole graph
    into one blob at low weight.
    """
    everything = frozenset(f"e{i}" for i in range(MAX_PASSAGE_ENTITIES + 1))

    edges, counted = _co_mention_edges([everything], everything)

    assert edges == {}
    assert counted == 0


def test_co_mention_alone_can_form_an_area():
    """With no relationships at all, repeated co-mention still clusters.

    The case a relationship-only implementation gets wrong and never reports:
    a corpus whose extraction produced entities but few edges projects to
    nothing but singletons, every one of which `_absorb_small` then drops, and
    the endpoint answers with an empty area list while the graph is full. That
    is the silent-empty shape `CLAUDE.md` warns about, so it gets a test.
    """
    ids = [f"c{i}" for i in range(6)]
    passages = [frozenset({"c0", "c1", "c2"})] * 6 + [frozenset({"c3", "c4", "c5"})] * 6

    projection = project_areas(graph([entity(e) for e in ids], []), passages)

    assert len(projection.areas) == 2
    assert projection.relationship_count == 0
    assert projection.co_mention_count == 12


def test_an_unconnected_entity_is_dropped_rather_than_shipped_alone():
    base = two_clique_graph()
    with_orphan = graph([*base.entities, entity("lonely")], base.relationships)

    projection = project_areas(with_orphan, [])

    placed = {m.entity_id for area in projection.areas for m in area.members}
    assert "lonely" not in placed
    # Reported against what it was given, not against what it kept: a reader
    # who sees eight members over nine entities can tell one was dropped.
    assert projection.entity_count == 9


def test_a_small_group_is_absorbed_by_its_strongest_neighbour():
    base = two_clique_graph()
    extra = [entity("x1"), entity("x2")]
    edges = [*base.relationships, rel("x1", "x2"), rel("x1", "b2"), rel("x2", "b3")]

    projection = project_areas(graph([*base.entities, *extra], edges), [])

    home = {m.entity_id: area.slug for area in projection.areas for m in area.members}
    assert home["x1"] == home["b2"]


def test_a_self_relationship_does_not_change_the_answer():
    """Consolidation can leave an edge whose ends resolve to one entity.

    Kept at any weight it inflates that node's degree, which raises its `a_c`
    term and makes it *harder* to merge -- silently, in proportion to how
    often it was deduplicated. Nothing about that is a claim anyone made.
    """
    base = two_clique_graph()
    looped = graph(base.entities, [*base.relationships, rel("a1", "a1")])

    assert [[m.entity_id for m in a.members] for a in (project_areas(looped, [])).areas] == [
        [m.entity_id for m in a.members] for a in (project_areas(base, [])).areas
    ]


def test_centrality_is_measured_inside_the_area():
    """A bridge is not an anchor.

    `b1` holds the only edge out of its clique, so its *global* degree is the
    highest in the graph. Ranked globally it would anchor its area, name it,
    and choose its directory. Ranked inside, it ties with its clique-mates.
    """
    projection = project_areas(two_clique_graph(), [])
    area = next(a for a in projection.areas if any(m.entity_id == "b1" for m in a.members))

    inside = {m.entity_id: m.centrality for m in area.members}
    assert inside["b1"] == pytest.approx(inside["b2"])


def test_truncation_is_carried_onto_the_projection():
    projection = project_areas(
        graph(two_clique_graph().entities, two_clique_graph().relationships, truncated=True),
        [],
    )
    assert projection.truncated is True


def test_projection_refuses_a_graph_above_the_cap():
    """Refused, not sampled. A curriculum over an arbitrary subset of a
    project is indistinguishable from a real one at every surface."""
    too_many = [entity(f"e{i}") for i in range(MAX_CLUSTERED_ENTITIES + 1)]

    with pytest.raises(GraphTooLarge):
        project_areas(graph(too_many, []), [])


def test_projection_clusters_a_dense_graph_at_the_cap_promptly():
    """A graph at the cap, dense rather than sparse, still returns in seconds.

    Dense because average degree is what costs time in greedy modularity, not
    entity count alone -- a sparse graph at the cap is comparatively cheap.
    Measured on this machine on 2026-08-24, over a planted-partition graph of
    `MAX_CLUSTERED_ENTITIES` entities, 30 communities, ~70 average degree
    (85% of edges intra-community, 15% inter): 5.33s. This asserts a 20s
    ceiling -- comfortable headroom over that single measurement rather than
    a number chosen to make the test pass, since wall-clock varies with the
    machine running it. If this starts failing, the honest fix is a faster
    clustering pass or a lower cap, not a larger ceiling.
    """
    rng = random.Random(1234)
    n = MAX_CLUSTERED_ENTITIES
    entities = [entity(f"e{i}") for i in range(n)]
    n_communities = 30
    by_community: dict[int, list[int]] = {}
    for i in range(n):
        by_community.setdefault(i % n_communities, []).append(i)

    avg_degree = 70
    n_edges = int(n * avg_degree / 2)
    relationships = []
    for _ in range(n_edges):
        if rng.random() < 0.85:
            members = by_community[rng.choice(list(by_community))]
            a, b = rng.sample(members, 2)
        else:
            a, b = rng.sample(range(n), 2)
        relationships.append(rel(f"e{a}", f"e{b}"))

    start = time.perf_counter()
    project_areas(graph(entities, relationships), [])
    elapsed = time.perf_counter() - start

    assert elapsed < 20.0, (
        f"clustering {n} dense entities took {elapsed:.2f}s, over the ceiling"
    )


def test_relationships_to_absent_entities_are_ignored():
    """A truncated graph's edges point at entities the caller was not given."""
    base = two_clique_graph()
    dangling = graph(base.entities, [*base.relationships, rel("a1", "not-in-this-graph")])

    projection = project_areas(dangling, [])
    assert projection.relationship_count == len(base.relationships)


def test_two_areas_anchored_on_the_same_name_get_distinct_slugs():
    left = ["a1", "a2", "a3", "a4"]
    right = ["b1", "b2", "b3", "b4"]
    edges = []
    for group in (left, right):
        for i, x in enumerate(group):
            for y in group[i + 1 :]:
                edges.append(rel(x, y))
    entities = [entity(e, name="Rome") for e in left + right]

    projection = project_areas(graph(entities, edges), [])

    slugs = [a.slug for a in projection.areas]
    assert slugs == ["rome", "rome-2"]


def test_slugify_never_returns_an_empty_segment():
    """An empty path segment resolves to the parent rather than 404ing, which
    is the worse failure because it looks like it worked."""
    assert slugify("!!!", fallback="fallback") == "fallback"
    assert slugify("Marcus Aurelius, Emperor", fallback="x") == "marcus-aurelius-emperor"


# An area's name comes from a member, and some members are sentences. These
# four are shaped against the *plausible* implementation -- naming from
# `anchors[0]`, which is what shipped and what anyone would write first --
# rather than against a broken one. See `application/name_shape.py` for the
# measure and `docs/design/curriculum-input-quality.md` §2 for the graph that
# produced `observation-that-chloroplasts-resemble-cyanobacteria`.


def _naming_fixture(names: dict[str, str]) -> Graph:
    """Two disjoint cliques: six nodes to name, nine to keep the ceiling clear.

    The six are a clique so every member's within-area centrality is equal and
    the ranking falls through to entity id -- which makes `a0`..`a5` the anchor
    order, exactly and on every machine, without the test having to reason
    about weights. The nine exist only so `MAX_AREA_FRACTION` leaves the six
    intact; at fifteen nodes the ceiling is six, and without them the area
    under test is split before it is ever named.
    """
    a = [f"a{i}" for i in range(6)]
    b = [f"b{i}" for i in range(9)]
    edges = [
        rel(x, y) for group in (a, b) for i, x in enumerate(group) for y in group[i + 1 :]
    ]
    return graph([entity(e, names.get(e)) for e in a + b], edges)


def _area_of(projection, prefix: str):
    return next(
        area for area in projection.areas if area.anchors[0].entity_id.startswith(prefix)
    )


def test_an_area_is_not_named_after_a_sentence():
    """The most central member is a proposition; the name comes from the next.

    Proved red on 2026-08-22 by replacing `_naming_anchor`'s body with
    `return ranked[0]` -- the implementation that shipped. The slug comes back
    as `chloroplasts-are-found-in-the-leaves-of-plants`, which is the real
    defect in miniature.
    """
    area = _area_of(
        project_areas(
            _naming_fixture(
                {
                    "a0": "Chloroplasts are found in the leaves of plants",
                    "a1": "Cyanobacteria",
                }
            ),
            [],
        ),
        "a",
    )
    assert area.slug == "cyanobacteria"
    assert area.anchors[0].name == "Chloroplasts are found in the leaves of plants", (
        "the ranking itself must be untouched; only the name taken from it changes"
    )


def test_the_title_is_set_from_the_same_member_as_the_slug():
    """A clean slug with an empty title is half a fix and looks like a whole one.

    `LearningArea.display_name` falls back to `anchors[0].name`, so an area
    left titleless goes on *showing* the sentence in the console and in every
    authored course while the URL looks fine. Proved red on 2026-08-22 by
    dropping the `title=` argument from `_to_area`'s `LearningArea(...)`: the
    slug assertion in the test above still passes, and this test and
    `test_an_area_of_nothing_but_sentences_keeps_its_top_anchor` both fail.
    """
    area = _area_of(
        project_areas(
            _naming_fixture(
                {
                    "a0": "Chloroplasts are found in the leaves of plants",
                    "a1": "Cyanobacteria",
                }
            ),
            [],
        ),
        "a",
    )
    assert area.title == "Cyanobacteria"
    assert area.display_name() == "Cyanobacteria"


def test_an_area_of_nothing_but_sentences_keeps_its_top_anchor():
    """Degradation is to the old behaviour, not to a placeholder.

    Every candidate is clause-shaped, so there is no better name available and
    inventing one (`area-1`, a hash) would trade a bad name for a meaningless
    one. Proved red on 2026-08-22 by making `_naming_anchor` return `None` when
    it finds no clean candidate: the slug falls back to an entity-id prefix,
    which is the failure this asserts against.
    """
    sentences = {
        f"a{i}": f"Chloroplast number {i} is found in the leaves of plants" for i in range(6)
    }
    area = _area_of(project_areas(_naming_fixture(sentences), []), "a")
    assert area.slug.startswith("chloroplast-number-0-is-found")
    assert area.title == sentences["a0"]


def test_the_scan_for_a_clean_name_does_not_reach_the_periphery():
    """A tidy name at rank six does not get to name the area.

    The bound is the point: an area's identity should come from its anchors,
    and a name lifted from a member the reader would not recognise as central
    describes something else. Proved red on 2026-08-22 by removing the
    `[:MAX_ANCHOR_SCAN]` slice -- the slug becomes `cyanobacteria`, taken from
    the *least* central member of six.
    """
    names = {
        f"a{i}": f"Chloroplast number {i} is found in the leaves of plants" for i in range(5)
    }
    names["a5"] = "Cyanobacteria"
    area = _area_of(project_areas(_naming_fixture(names), []), "a")
    assert area.slug.startswith("chloroplast-number-0-is-found")
