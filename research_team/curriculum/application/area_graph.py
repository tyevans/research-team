"""Graph edge construction for curriculum area projection.

Builds the undirected weighted adjacency graph from asserted relationships,
co-mention passages, and semantic embedding vectors.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from research_team.knowledge.application.graph_read import (
    GraphEntity,
    GraphRelationship,
)

#: Weight of one extracted relationship. The unit the other weights are
#: expressed against, so it is 1.0 by definition rather than by tuning: a
#: model read a document and asserted a connection, which is the strongest
#: evidence this system ever has that two things belong together.
RELATION_WEIGHT = 1.0

#: The most weight one passage may contribute in total, spread across every
#: pair of entities it mentions. Well below `RELATION_WEIGHT` because a
#: co-mention is genuinely weaker evidence than an assertion -- two entities
#: named in one paragraph are often merely adjacent -- and because the
#: aggregate is what carries the signal. A hundred passages agreeing outweigh
#: one relationship; one passage never does.
CO_MENTION_BUDGET = 0.5

#: Passages naming more entities than this contribute nothing.
#:
#: Not a performance guard -- a 40-entity passage is 780 pairs, which is
#: nothing. It is a *relevance* guard. A passage listing forty entities is a
#: table of contents, an index, or a glossary, and the "these belong together"
#: inference it licenses is false: everything in the project appears in it. The
#: normalisation in `_co_mention_edges` already stops such a passage dominating
#: by volume, but it cannot stop it wiring the whole graph into one blob at low
#: weight, which is exactly what a curriculum must not be.
MAX_PASSAGE_ENTITIES = 25

#: Weight of one semantic edge at the similarity floor, rising to this value
#: at a perfect match. Below `RELATION_WEIGHT` and above one passage's whole
#: budget, which is the ordering the evidence deserves: a model read a document
#: and asserted a relationship; a passage put two names near each other; an
#: embedding says two entities *look* like the same subject and no document
#: ever said so. Strong enough to join two clusters nothing co-mentions, never
#: strong enough to overrule an assertion.
EMBEDDING_WEIGHT = 0.6

#: How many semantic neighbours each entity may contribute.
#:
#: Small on purpose, and it is the guard that matters most here. Similarity is
#: dense -- every entity has a nearest neighbour, and in a graph of 500
#: entities an unbounded pass is 125,000 edges, every one of them non-zero.
#: That does not refine a clustering, it dissolves it: modularity over a
#: near-complete graph has no communities to find. Keeping only each entity's
#: closest few leaves the graph sparse, which is the condition the whole
#: method depends on.
EMBEDDING_NEIGHBOURS = 5

#: How far above an entity's *own* neighbour distribution a pair has to stand
#: before it is drawn, in standard deviations.
#:
#: **This replaced an absolute cosine floor (`MIN_EMBEDDING_SCORE = 0.83`) on
#: 2026-08-29, and the reason is a measurement rather than a preference.** The
#: floor's docstring claimed it was set "where two entity cards have to
#: genuinely be about the same subject". Against `qwen3-embedding-0.6b` over
#: real `card_text` cards it was not: 20 entities across four disjoint domains
#: (computing, marine biology, monetary policy, baroque music), all 190 pairs
#: scored on redstring's `(1 + cosine) / 2` scale --
#:
#:     unrelated (cross-domain, n=150)  median 0.6783  p95 0.7543  max 0.7808
#:     related   (within-domain, n=40)  median 0.8274  p95 0.9294  max 0.9550
#:
#: -- so 0.83 sat at the *median of genuinely related pairs*, not near the
#: unrelated band. It discarded 21 of 40 true pairs, including five entities'
#: own correct nearest neighbour (London -> Ada Lovelace at 0.8039, Harpsichord
#: -> Brandenburg Concertos at 0.8157, Counterpoint at 0.8205, Leipzig at
#: 0.8237, Ada Lovelace -> Charles Babbage at 0.8276). Precision 1.00, recall
#: 0.475.
#:
#: The worse half is what an absolute floor does to a *single-domain* corpus,
#: which is what a real project graph is. Every one of those four domains is
#: five entities and ten possible pairs, and 0.83 kept:
#:
#:     baroque music     1/10        marine biology  5/10
#:     computing         3/10        monetary policy 10/10  (a complete graph)
#:
#: The floor is not measuring structure, it is measuring how high in the scale
#: that corpus's vocabulary happens to sit -- and on the finance corpus it
#: admitted every pair, which is precisely the k-nearest-neighbour-invents-
#: structure failure it was written to prevent. A relative cut at z=1.0 kept
#: 3, 4, 3 and 4 across the same four, and on the multi-domain corpus scored
#: precision 0.974 at recall 0.925 against 0.83's 1.000 at 0.475 -- it
#: dominates the absolute floor over the whole trade-off frontier (absolute
#: 0.80 gets 1.000/0.675; relative z=1.25 gets 1.000/0.800).
#:
#: **And an absolute cosine is a per-model constant wearing a universal one's
#: clothes.** The embedding model is a setting (`embedding_model` in
#: `domain/settings.py`, `AGENT_EMBEDDING_MODEL`), so a user pointing at a
#: different provider silently changes what 0.83 means -- every model has its
#: own band, and nothing here would have said so. A z-score is computed from
#: whatever the configured model returns for *this project's* entities, so it
#: survives a model swap; a cosine does not.
#:
#: 1.0 rather than 1.25 or 0.75: 1.25 buys the last 2.6% of precision for 12.5%
#: of recall, and 0.75 admits a cross-domain pair per 9 drawn. Neither is a
#: cliff, which is the point -- the instrument is not fragile at its setting
#: the way 0.83 was, where every live pair sat within 0.07 of the constant.
MIN_NEIGHBOUR_STANDOUT = 1.0

#: The standout above `MIN_NEIGHBOUR_STANDOUT` at which a semantic edge earns
#: `EMBEDDING_WEIGHT` in full. Pairs above it are clipped rather than scaled
#: further: the top of a z distribution is set by how tight the *rest* of the
#: row is, so an entity with one near-duplicate and eighteen strangers can
#: reach z=4 without that pair being any better evidence than one at z=2.
STANDOUT_SPAN = 1.0


def _co_mention_edges(
    passages: Iterable[frozenset[str]],
    known: frozenset[str],
) -> tuple[dict[tuple[str, str], float], int]:
    """Weighted pair contributions from co-mention, and how many passages counted.

    Each passage contributes `CO_MENTION_BUDGET` **in total**, divided among
    its pairs. That normalisation is the whole design and it is worth being
    explicit about what it prevents: without it a passage naming twenty
    entities contributes 190 unit edges against a project that may hold only a
    few hundred relationships in total, and the projection becomes a picture of
    which passage was longest rather than of what the project is about. With
    it, a passage is one voice however much of it there is.
    """
    edges: dict[tuple[str, str], float] = {}
    counted = 0
    for passage in passages:
        members = sorted(passage & known)
        if len(members) < 2 or len(members) > MAX_PASSAGE_ENTITIES:
            continue
        counted += 1
        pairs = len(members) * (len(members) - 1) // 2
        share = CO_MENTION_BUDGET / pairs
        for i, left in enumerate(members):
            for right in members[i + 1 :]:
                edges[(left, right)] = edges.get((left, right), 0.0) + share
    return edges, counted


def _semantic_edges(
    pairs: Iterable[tuple[str, str, float]],
    known: frozenset[str],
) -> dict[tuple[str, str], float]:
    """Weighted pair contributions from embedding similarity.

    The port's third element is a *standout* -- how many standard deviations
    the pair sits above that entity's own similarity row -- not a cosine, and
    it is rescaled from `[MIN_NEIGHBOUR_STANDOUT, +STANDOUT_SPAN]` onto
    `[0, EMBEDDING_WEIGHT]` rather than used as a multiplier directly. The
    rescale is the same idea the absolute floor's version had and is not
    cosmetic: an edge admitted by a hair has to contribute by a hair, or the
    threshold becomes the only decision the channel makes.

    Clipped at the top, which the cosine version did not need. A z has no
    ceiling, and `EMBEDDING_WEIGHT * z` would let one entity with a
    near-duplicate and a tight row outweigh an asserted relationship.

    Pairs below the cut are dropped here as well as in the adapter. The
    adapter has the store and computes the standout; this is a pure function
    and is where the constant's meaning is testable.
    """
    edges: dict[tuple[str, str], float] = {}
    for left, right, standout in pairs:
        if left == right or left not in known or right not in known:
            continue
        if standout < MIN_NEIGHBOUR_STANDOUT:
            continue
        key = (left, right) if left < right else (right, left)
        weight = EMBEDDING_WEIGHT * min(
            1.0, (standout - MIN_NEIGHBOUR_STANDOUT) / STANDOUT_SPAN
        )
        # `max`, not `+`: an adapter yielding a pair twice (both directions,
        # or once per endpoint's neighbour list) must not make that pair twice
        # as attractive as one reported once. Idempotent by construction is
        # worth more here than trusting the port's contract, because the
        # failure is a silently better-connected pair rather than an error.
        edges[key] = max(edges.get(key, 0.0), weight)
    return edges


def _adjacency(
    entities: Sequence[GraphEntity],
    relationships: Sequence[GraphRelationship],
    passages: Iterable[frozenset[str]],
    semantic: Iterable[tuple[str, str, float]] = (),
) -> tuple[dict[str, dict[str, float]], int, int, int]:
    """The undirected weighted graph the merge runs over.

    Self-loops are dropped rather than kept at any weight. redstring can
    record a relationship whose ends resolve to one entity after
    consolidation, and such an edge adds to a node's degree without ever
    connecting it to anything -- which inflates `a_c` in the modularity term
    and makes a hub *harder* to merge, silently, in proportion to how many
    times it was deduplicated. Nothing about that is a claim anyone made.
    """
    known = frozenset(e.entity_id for e in entities)
    adjacency: dict[str, dict[str, float]] = {e.entity_id: {} for e in entities}

    asserted = 0
    for rel in relationships:
        left, right = rel.source_id, rel.target_id
        if left == right or left not in known or right not in known:
            continue
        asserted += 1
        adjacency[left][right] = adjacency[left].get(right, 0.0) + RELATION_WEIGHT
        adjacency[right][left] = adjacency[right].get(left, 0.0) + RELATION_WEIGHT

    co_edges, counted = _co_mention_edges(passages, known)
    for (left, right), weight in co_edges.items():
        adjacency[left][right] = adjacency[left].get(right, 0.0) + weight
        adjacency[right][left] = adjacency[right].get(left, 0.0) + weight

    semantic_edges = _semantic_edges(semantic, known)
    for (left, right), weight in semantic_edges.items():
        adjacency[left][right] = adjacency[left].get(right, 0.0) + weight
        adjacency[right][left] = adjacency[right].get(left, 0.0) + weight

    return adjacency, asserted, counted, len(semantic_edges)


__all__ = [
    "CO_MENTION_BUDGET",
    "EMBEDDING_NEIGHBOURS",
    "EMBEDDING_WEIGHT",
    "MAX_PASSAGE_ENTITIES",
    "MIN_NEIGHBOUR_STANDOUT",
    "RELATION_WEIGHT",
    "STANDOUT_SPAN",
    "_adjacency",
    "_co_mention_edges",
    "_semantic_edges",
]
