"""Folding a project's graph into the areas there are to learn in it.

The graph is the skeleton and embeddings are the tissue: relationships and
co-mentions say what documents *asserted* about two entities, and a semantic
edge says two entities are about the same thing when no document happened to
put them in a sentence together.

**This module's docstring used to argue against embeddings on three grounds,
and one of them was nonsense.** It said entity vectors "encode `entity.name`
rather than subject matter", as if embedding a name were a comparison of
spellings. It is not, and that is the entire reason embeddings exist: `glass`
and `cup` share no substring and sit close together in any competent space.
The two grounds that were real have both been dealt with rather than argued
around -- vectors were ephemeral, and are now folded from `EntitiesEmbedded`
at project open; and what is embedded is now the entity's *card*, carrying its
type, properties and named relations, because a bare name is thin rather than
because it is a string. See `infrastructure/knowledge/entity_embeddings.py`.

What survives of the original argument, and why the graph still leads: a
semantic edge is a hypothesis nobody stated, so it is weighted below an
asserted relationship and admitted only above a similarity floor. The graph
decides the shape; embeddings close the gaps in it.

Everything in this module is pure. It takes a graph and a co-mention map and
returns areas; it opens nothing, calls no model, and has no clock. That is
what makes the determinism claim testable, and the determinism claim is what
makes an area's slug safe to use as a directory name.
"""

from __future__ import annotations

import heapq
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from research_team.application.graph_read import Graph, GraphEntity, GraphRelationship
from research_team.application.name_shape import clause_shaped
from research_team.domain.learning_area import AreaMember, AreaProjection, LearningArea

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

#: How many entities this pass will cluster. Greedy modularity is superlinear,
#: and a refusal a person can see beats a projection that quietly consumes the
#: request. Matched to `graph_read.MAX_GRAPH_NODES` on purpose -- a lower
#: value here meant a graph the reader would hand over whole was still
#: unclusterable, and the owner's largest project (3,619 clusterable
#: entities) sat in exactly that gap at the old value of 2,000, so its
#: Curriculum and Catalog pages could not build at all. The number is where a
#: naive-heap implementation in CPython stays inside a few seconds on a dense
#: graph, measured rather than guessed -- see
#: `test_projection_clusters_a_dense_graph_at_the_cap_promptly`.
MAX_CLUSTERED_ENTITIES = 5_000

#: Above this fraction of the graph, a community is split once more.
#:
#: Modularity is content to return one community holding most of the graph,
#: and such a community is not an area -- it is the projection having failed
#: while returning a value. One re-run on the induced subgraph catches the
#: "two subjects got glued" case. It is bounded to a single recursion on
#: purpose: a genuinely homogeneous cluster splits into arbitrary halves
#: forever, and an arbitrary half is worse than an honest large area.
MAX_AREA_FRACTION = 0.4

#: Areas smaller than this are not shipped as areas. Their members are
#: absorbed into whichever surviving area holds their strongest neighbour, and
#: dropped only if they have no edge into any of them. Three is the smallest
#: set a person would call a topic; shipping forty two-member areas buries the
#: eight real ones, which is the failure this constant exists against.
MIN_AREA_SIZE = 3

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

#: The similarity below which a semantic edge is not drawn at all.
#:
#: On redstring's scale, which is `(1 + cosine) / 2` -- so 0.5 is orthogonal
#: and this is a cosine of about 0.66, not of 0.83. Set where two entity cards
#: have to genuinely be about the same subject rather than merely both being
#: prose in the same language, because an embedding's *nearest* neighbour
#: exists whether or not it is related to anything. Without a floor, the
#: sparsest corner of a graph gets the same five edges per node as the densest,
#: which is where a k-nearest-neighbour graph invents structure.
MIN_EMBEDDING_SCORE = 0.83


class CoMentionPort(Protocol):
    """Which entities this project's passages name together.

    A port rather than a chunk-store call inside this module, for
    `GraphReadPort`'s own reason: everything above it speaks this
    application's vocabulary, and naming `StoredChunk` here would make a
    redstring schema change a change to the projection's contract.

    **Passages, not documents.** Two entities in one paragraph are evidence
    about the same thing; two entities in one fifty-page document are evidence
    that the document is long. The adapter reads chunks, which is the grain
    the corpus already stores and already rebuilds from the log.
    """

    async def passages(self, entity_ids: Sequence[str]) -> Sequence[frozenset[str]]:
        """One frozenset of entity ids per passage that names two or more.

        Passages naming fewer than two of `entity_ids` are omitted rather than
        returned empty: they carry no pair and the caller would drop them, so
        returning them is a wire cost with no reader.
        """
        ...


class SemanticPort(Protocol):
    """Which entities this project's embeddings put near each other.

    A port for `CoMentionPort`'s reason -- nothing here may name a redstring
    type -- and asymmetric with it in one way worth stating: this one is
    allowed to answer with nothing. Embeddings are switched off on plenty of
    installs, a project ingested before they were durable has none recorded,
    and a provider whose endpoint is down leaves them absent. All three arrive
    here as an empty sequence, and the projection is expected to be correct
    without them rather than degraded in a way a reader has to be told about.
    """

    async def neighbours(self, entity_ids: Sequence[str]) -> Sequence[tuple[str, str, float]]:
        """Close pairs among `entity_ids`, as `(left, right, score)`.

        `score` is on redstring's `(1 + cosine) / 2` scale. Pairs are
        unordered and each is expected at most once with `left < right`; an
        adapter that yields both directions doubles that pair's weight, which
        is why the ordering is the port's contract and not the caller's
        cleanup.
        """
        ...


@dataclass(frozen=True)
class _Community:
    """A live community during the merge, keyed by its lowest member id.

    Keyed by the *lowest member id* rather than by a counter, because the key
    is what ties break on and a counter would make the tie-break depend on
    allocation order -- which is to say on nothing defensible. With this key
    the tie-break is a property of the graph, so the same graph orders the
    same way on every machine.
    """

    key: str
    members: frozenset[str]


def slugify(name: str, *, fallback: str) -> str:
    """A directory-and-URL-safe form of `name`.

    ASCII-folded, lowercased, non-alphanumerics collapsed to single hyphens.
    `fallback` is used when nothing survives -- a name written entirely in a
    script this fold empties (or entirely in punctuation) would otherwise
    produce the empty string, and an empty path segment is a route that
    resolves to its parent rather than a 404, which is the worse failure
    because it looks like it worked.
    """
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    return cleaned[:60] or fallback


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

    The score is rescaled from `[MIN_EMBEDDING_SCORE, 1.0]` onto
    `[0, EMBEDDING_WEIGHT]` rather than used as a multiplier directly, and the
    difference is not cosmetic. Cosine similarities among real entity cards
    live in a narrow band near the top of the scale -- two unrelated documents
    of English prose score well above 0.5 -- so `EMBEDDING_WEIGHT * score`
    gives a pair that barely cleared the floor about four fifths the weight of
    a pair that is a perfect match, which is not a distinction, it is noise
    with a number on it. Rescaling makes the floor mean zero, so an edge admitted
    by a hair contributes by a hair.

    Pairs below the floor are dropped here as well as in the adapter. The
    adapter has the store and the cheaper filter; this is a pure function and
    is where the constant's meaning is testable.
    """
    span = 1.0 - MIN_EMBEDDING_SCORE
    edges: dict[tuple[str, str], float] = {}
    for left, right, score in pairs:
        if left == right or left not in known or right not in known:
            continue
        if score < MIN_EMBEDDING_SCORE:
            continue
        key = (left, right) if left < right else (right, left)
        weight = (
            EMBEDDING_WEIGHT * (score - MIN_EMBEDDING_SCORE) / span
            if span
            else EMBEDDING_WEIGHT
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


def _greedy_modularity(adjacency: Mapping[str, Mapping[str, float]]) -> list[frozenset[str]]:
    """Clauset-Newman-Moore, with every tie broken on entity ids.

    Chosen over label propagation because label propagation's answer depends
    on visit order and pinning the order pins the result to an arbitrary
    choice -- one that changes the moment an entity is added. Here the answer
    is a function of the graph alone, which is what lets a slug derived from it
    be used as a directory name and what makes a regression test mean anything.

    The heap holds candidate merges and is *lazy*: an entry whose communities
    have since merged into something else is discarded on pop rather than
    removed on merge. Eager removal needs an index from community to heap
    position and a sift on every touch, for a structure that is rebuilt
    constantly; the lazy form does strictly less work and cannot go stale in a
    way that changes the answer, because a stale entry is recognised by
    identity of the live community set before it is used.
    """
    total = sum(sum(row.values()) for row in adjacency.values()) / 2.0
    if total <= 0:
        return [frozenset({node}) for node in sorted(adjacency)]

    # `degree` and `between` are kept per *community*, not per node, and are
    # updated on merge. Recomputing them from members each round is the same
    # arithmetic done O(n) times more often.
    members: dict[str, frozenset[str]] = {node: frozenset({node}) for node in adjacency}
    degree: dict[str, float] = {node: sum(row.values()) for node, row in adjacency.items()}
    between: dict[str, dict[str, float]] = {
        node: dict(sorted(row.items())) for node, row in adjacency.items()
    }

    def delta(left: str, right: str) -> float:
        weight = between[left].get(right, 0.0)
        return weight / total - (degree[left] * degree[right]) / (2.0 * total * total)

    heap: list[tuple[float, str, str]] = []
    for left, row in between.items():
        for right in row:
            if left < right:
                heapq.heappush(heap, (-delta(left, right), left, right))

    while heap:
        negated, left, right = heapq.heappop(heap)
        # Stale: one end has been merged away, or the pair's score has moved
        # since it was pushed. Either way the live score is what decides.
        if left not in members or right not in members:
            continue
        if right not in between[left]:
            continue
        current = delta(left, right)
        if abs(current + negated) > 1e-12:
            heapq.heappush(heap, (-current, left, right))
            continue
        if current <= 0:
            break

        # The survivor is the lower key, so the community key stays the lowest
        # member id and the tie-break above stays a property of the graph.
        keep, drop = (left, right) if left < right else (right, left)
        members[keep] = members[keep] | members[drop]
        degree[keep] += degree[drop]

        for other, weight in between[drop].items():
            if other == keep:
                continue
            between[keep][other] = between[keep].get(other, 0.0) + weight
            between[other][keep] = between[other].get(keep, 0.0) + weight
            del between[other][drop]
        between[keep].pop(drop, None)
        del between[drop]
        del members[drop]
        del degree[drop]

        for other in sorted(between[keep]):
            pair = (keep, other) if keep < other else (other, keep)
            heapq.heappush(heap, (-delta(*pair), *pair))

    return [members[key] for key in sorted(members)]


def _split_oversized(
    communities: Sequence[frozenset[str]],
    adjacency: Mapping[str, Mapping[str, float]],
    total_nodes: int,
) -> list[frozenset[str]]:
    """One re-run over any community holding too much of the graph.

    Bounded to a single recursion. See `MAX_AREA_FRACTION` for why unbounded
    recursion is the wrong answer: it terminates on arbitrary halves of a
    genuinely homogeneous cluster, and an arbitrary half presented as a
    learning area is a lie a reader has no way to detect.
    """
    ceiling = max(MIN_AREA_SIZE, int(total_nodes * MAX_AREA_FRACTION))
    out: list[frozenset[str]] = []
    for community in communities:
        if len(community) <= ceiling:
            out.append(community)
            continue
        induced = {
            node: {n: w for n, w in adjacency[node].items() if n in community}
            for node in sorted(community)
        }
        parts = _greedy_modularity(induced)
        # A split that returns the input unchanged means modularity has nothing
        # left to say about this subgraph. Keeping the whole is then the honest
        # outcome; halving it here would be this function inventing a boundary
        # the graph does not have.
        out.extend(parts if len(parts) > 1 else [community])
    return out


def _absorb_small(
    communities: Sequence[frozenset[str]],
    adjacency: Mapping[str, Mapping[str, float]],
) -> list[frozenset[str]]:
    """Fold undersized communities into their members' strongest neighbours.

    A member with no edge into any surviving community is dropped from the
    projection entirely rather than parked in an "other" area. An area named
    "other" is the one a reader learns to ignore, and it grows: everything the
    algorithm could not place accumulates there and the map stops being
    falsifiable, which is the one job §8 of the design gives it.
    """
    survivors = [c for c in communities if len(c) >= MIN_AREA_SIZE]
    if not survivors:
        return []
    home: dict[str, int] = {}
    for index, community in enumerate(survivors):
        for node in community:
            home[node] = index

    additions: dict[int, set[str]] = {}
    for community in communities:
        if len(community) >= MIN_AREA_SIZE:
            continue
        for node in sorted(community):
            best_index: int | None = None
            best_weight = 0.0
            for neighbour, weight in sorted(adjacency[node].items()):
                index = home.get(neighbour)
                if index is None or weight <= best_weight:
                    continue
                best_index, best_weight = index, weight
            if best_index is not None:
                additions.setdefault(best_index, set()).add(node)

    return [
        community | frozenset(additions.get(index, set()))
        for index, community in enumerate(survivors)
    ]


#: How far down the centrality ranking `_naming_anchor` will look for a member
#: whose name is not a sentence.
#:
#: Small deliberately. An area's identity should come from its anchors, and the
#: twentieth-most-central member is not one -- a tidy name taken from the
#: periphery describes an area the reader is not looking at, which is worse
#: than an awkward name taken from its centre. Five is where the measured
#: graph's two badly-named areas both find a good candidate
#: (`observation-that-chloroplasts-resemble-cyanobacteria` at rank two,
#: `conspirators-arrested-in-the-city` at rank two) without reaching past the
#: members a reader would recognise as what the area is about.
MAX_ANCHOR_SCAN = 5


def _naming_anchor(ranked: Sequence[AreaMember]) -> AreaMember | None:
    """The member an area should be named after, most central first.

    Not simply `ranked[0]`, which is what produced
    `observation-that-chloroplasts-resemble-cyanobacteria` -- an eleven-entity
    area that is genuinely the evidence for endosymbiotic theory, wearing the
    name of one sentence inside it. Centrality says which member the area is
    *built around*; it says nothing about whether that member's name is the
    name of a thing.

    So: the most central member among the first `MAX_ANCHOR_SCAN` whose name is
    not clause-shaped, and the most central member of all when every one of
    them is. That fallback is the pre-existing behaviour, which matters --
    an area of nothing but sentences still gets a deterministic slug and a
    title, and degrades to exactly what it did before rather than to `area-1`.

    Rejected alternatives, both of which were considered on the measured graph:

    - *Preferring a shorter or nounier name among the top few.* Shortness is
      not the property in question -- `chlorophyll a` is short and
      `Andreas Franz Wilhelm Schimper` is long, and the long one is the better
      area name of the two. Every ordering by length that improved one area
      made another worse.
    - *A composite of two anchors* (`cyanobacteria-and-chloroplasts`). It reads
      well when the two anchors are peers and badly when they are not, which is
      the ordinary case, and it doubles the slug length against a 60-character
      truncation that then cuts the second anchor in half.
    - *Asking a model for a title.* Forbidden, and rightly: this function is
      pure and has no awaits, which is what makes `test_projection_is_deterministic`
      a test rather than a hope.

    Purity and determinism are untouched -- `clause_shaped` is a set-membership
    check over closed vocabularies, so the same graph names the same areas on
    every machine.
    """
    if not ranked:
        return None
    for member in ranked[:MAX_ANCHOR_SCAN]:
        if not clause_shaped(member.name):
            return member
    return ranked[0]


def _to_area(
    community: frozenset[str],
    adjacency: Mapping[str, Mapping[str, float]],
    by_id: Mapping[str, GraphEntity],
    taken: set[str],
) -> LearningArea:
    """One community as an area, with centrality measured inside it.

    Inside it, not across the graph: an entity wired to half the project but
    to nothing in the community it landed in is a bridge, and ranking by
    global degree would make it the anchor of an area it barely belongs to --
    and then the slug, the directory and the title would all be named after
    the wrong thing.
    """
    members = tuple(
        AreaMember(
            entity_id=node,
            name=by_id[node].name,
            entity_type=by_id[node].entity_type,
            centrality=round(sum(w for n, w in adjacency[node].items() if n in community), 6),
            temporal=by_id[node].temporal,
        )
        for node in sorted(community)
    )
    ranked = sorted(members, key=lambda m: (-m.centrality, m.entity_id))
    anchor = _naming_anchor(ranked)
    base = slugify(anchor.name, fallback=anchor.entity_id[:8]) if anchor else "area"
    slug = base
    # Two areas whose top anchors slug identically -- "Rome" the city and
    # "Rome" the republic, say -- would otherwise share a directory and the
    # second course written would overwrite the first. Suffixing is silent
    # because the collision is not the reader's problem to solve; losing a
    # course to it would be.
    suffix = 2
    while slug in taken:
        slug = f"{base}-{suffix}"
        suffix += 1
    taken.add(slug)
    # `title` is set here rather than left `None`, and that is half the fix.
    # `LearningArea.display_name` falls back to `anchors[0].name` -- the *most
    # central* member -- so choosing a different member for the slug and
    # leaving the title empty would put a clean name in the URL and go on
    # showing the sentence everywhere a reader looks. The two have to move
    # together or the change is cosmetic in the wrong direction.
    return LearningArea(slug=slug, members=members, title=anchor.name if anchor else None)


class GraphTooLarge(Exception):
    """The graph exceeds `MAX_CLUSTERED_ENTITIES`.

    Raised rather than sampled down to the cap. A projection over an arbitrary
    2,000 of 6,000 entities is a curriculum for a project that does not exist,
    and it is indistinguishable from a real one at every surface that shows
    it.
    """


def project_areas(
    graph: Graph,
    passages: Sequence[frozenset[str]],
    semantic: Sequence[tuple[str, str, float]] = (),
) -> AreaProjection:
    """The areas in one project's graph, deterministically.

    A pure function, and taking `passages` as a value rather than calling a
    port for them is what makes it one. The port call moved out to
    `CurriculumService` for two reasons: the same passages are wanted again by
    `learning_paths.order_areas`, so fetching them here would either read the
    corpus twice or make the second caller depend on the first's leftovers;
    and a function with no awaits is one a test can drive with a literal.
    Given the same graph and the same passages this returns the same areas, in
    the same order, with the same slugs, on every machine.
    `test_projection_is_deterministic` is what holds that, and it is not
    decoration -- the slug is a directory name.

    `semantic` is the embedding channel, as `(left, right, score)` triples
    from `SemanticPort`. Empty is the ordinary case on an install with
    embeddings off or a project ingested before they were durable, and it must
    stay ordinary: every count this returns is meaningful without it, and
    `used_embeddings` on the result is how a reader tells the two runs apart
    rather than having to infer it from the areas.
    """
    if len(graph.entities) > MAX_CLUSTERED_ENTITIES:
        raise GraphTooLarge(
            f"{len(graph.entities)} entities exceeds the {MAX_CLUSTERED_ENTITIES} "
            "this projection will cluster; narrow the project or raise the cap"
        )

    by_id = {e.entity_id: e for e in graph.entities}
    adjacency, asserted, counted, semantic_count = _adjacency(
        graph.entities, graph.relationships, passages, semantic
    )

    communities = _greedy_modularity(adjacency)
    communities = _split_oversized(communities, adjacency, len(adjacency))
    communities = _absorb_small(communities, adjacency)

    taken: set[str] = set()
    areas = tuple(
        _to_area(community, adjacency, by_id, taken)
        # Largest first, and ties on the lowest member id. Size is the order a
        # reader wants on a map -- the big areas are the ones that decide
        # whether the projection is right -- and the id keeps two equal-sized
        # areas from swapping places between runs.
        for community in sorted(communities, key=lambda c: (-len(c), min(c)))
    )

    return AreaProjection(
        areas=areas,
        entity_count=len(graph.entities),
        relationship_count=asserted,
        co_mention_count=counted,
        semantic_count=semantic_count,
        # The *drawn* edges, not the offered triples: a run handed a thousand
        # pairs that all fell below the floor used no embeddings in any sense a
        # reader cares about, and saying it did would make the flag agree with
        # the configuration rather than with the result.
        used_embeddings=semantic_count > 0,
        truncated=graph.truncated,
    )
