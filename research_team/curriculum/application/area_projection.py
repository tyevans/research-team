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
asserted relationship and admitted only when it stands out from the entity's
own neighbourhood. The graph decides the shape; embeddings close the gaps in
it. That admission test was an absolute cosine floor until 2026-08-29 and is
now relative; `MIN_NEIGHBOUR_STANDOUT` carries the measurement that changed
it, and the short version is that a cosine floor is a per-model constant and
the embedding model is a setting.

Everything in this module is pure. It takes a graph and a co-mention map and
returns areas; it opens nothing, calls no model, and has no clock. That is
what makes the determinism claim testable, and the determinism claim is what
makes an area's slug safe to use as a directory name.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Protocol

from research_team.curriculum.application.area_clustering import (
    MAX_AREA_FRACTION,
    MIN_AREA_SIZE,
    _absorb_small,
    _greedy_modularity,
    _split_oversized,
)
from research_team.curriculum.application.area_graph import (
    CO_MENTION_BUDGET,
    EMBEDDING_NEIGHBOURS,
    EMBEDDING_WEIGHT,
    MAX_PASSAGE_ENTITIES,
    MIN_NEIGHBOUR_STANDOUT,
    RELATION_WEIGHT,
    STANDOUT_SPAN,
    _adjacency,
    _co_mention_edges,
    _semantic_edges,
)
from research_team.curriculum.domain.learning_area import (
    AreaMember,
    AreaProjection,
    LearningArea,
)
from research_team.knowledge.application.graph_read import (
    Graph,
    GraphEntity,
)
from research_team.knowledge.application.name_shape import clause_shaped

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
        """Close pairs among `entity_ids`, as `(left, right, standout)`.

        **`standout` is not a similarity.** It is how far above its own
        endpoint's neighbour distribution the pair sits, in standard
        deviations -- so 0 is "as close as this entity is to everything" and
        `MIN_NEIGHBOUR_STANDOUT` is the cut. It used to be a cosine on
        redstring's `(1 + cosine) / 2` scale, and the constant that read it
        was per-model without saying so; see `MIN_NEIGHBOUR_STANDOUT` for the
        measurement that changed it.

        A relative measure also puts the decision where the adapter has the
        information: this module sees pairs, and only the adapter sees the
        distribution a pair has to stand out from.

        Pairs are unordered and each is expected at most once with
        `left < right`; an adapter that yields both directions doubles that
        pair's weight, which is why the ordering is the port's contract and
        not the caller's cleanup.
        """
        ...


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


__all__ = [
    "CO_MENTION_BUDGET",
    "EMBEDDING_NEIGHBOURS",
    "EMBEDDING_WEIGHT",
    "MAX_ANCHOR_SCAN",
    "MAX_AREA_FRACTION",
    "MAX_CLUSTERED_ENTITIES",
    "MAX_PASSAGE_ENTITIES",
    "MIN_AREA_SIZE",
    "MIN_NEIGHBOUR_STANDOUT",
    "RELATION_WEIGHT",
    "STANDOUT_SPAN",
    "CoMentionPort",
    "GraphTooLarge",
    "SemanticPort",
    "_absorb_small",
    "_adjacency",
    "_co_mention_edges",
    "_greedy_modularity",
    "_naming_anchor",
    "_semantic_edges",
    "_split_oversized",
    "_to_area",
    "project_areas",
    "slugify",
]
