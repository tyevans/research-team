"""Putting areas in an order, and saying why that order.

Clustering answers "what belongs together". This answers "what comes first",
and the two need different readings of the same graph: clustering throws away
edge direction because belonging is symmetric, and ordering is *entirely*
about direction. So the relationships are read again here rather than carried
over from `area_projection`.

**Everything here is derived and nothing is invented.** A model is never asked
what order to teach in. It could produce a plausible one instantly, and a
plausible curriculum order that has no relationship to the corpus is the worst
possible output of this feature -- it would look exactly like a good one and be
unfalsifiable. Every edge this module emits carries the count or the date that
produced it, so a reader can disagree with the evidence rather than with the
verdict.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from research_team.application.area_projection import slugify
from research_team.application.graph_read import GraphRelationship
from research_team.domain.learning_area import LearningArea, LearningPath, PrerequisiteEdge

#: How much one directed relationship between two areas' entities counts.
#:
#: The dominant term by design. A relationship is the only signal here that a
#: model actually read a document and asserted a direction; the other two are
#: inferences over aggregates. Weighting them comparably would let a corpus
#: with a lot of dates outvote a corpus with a lot of stated structure, which
#: is backwards.
REFERENCE_WEIGHT = 1.0

#: How much "A's entities are dated earlier than B's" counts.
#:
#: Small, and smaller than it first looks reasonable to make it, because
#: **chronology is not pedagogy**: the earliest thing in a corpus is very
#: often the hardest to teach first (origins are usually explained after the
#: thing they are origins of). It earns its place as a tie-break in historical
#: corpora, where it is frequently exactly right and where the reference
#: signal is often symmetric.
TEMPORAL_WEIGHT = 0.25

#: How much wider corpus presence counts toward being foundational.
#:
#: An area whose entities are named across many passages is more likely to be
#: the project's shared vocabulary than one confined to a corner of it, and
#: vocabulary precedes the arguments made with it. Weak because the same
#: measurement is also what a *summary* area looks like -- an overview
#: document produces breadth without depth -- and those want opposite
#: placements.
BREADTH_WEIGHT = 0.35

#: Below this, an ordering claim is not made at all.
#:
#: Without a floor every pair of areas gets an edge, because breadth alone is
#: never exactly equal, and the resulting digraph is complete: a total order
#: with no structure in it, presented with the same confidence as a real one.
#: A path that declines to order two areas is telling the truth about them.
MIN_EDGE_WEIGHT = 0.15


@dataclass(frozen=True)
class _Signals:
    references: float
    temporal: float
    breadth: float

    @property
    def total(self) -> float:
        return self.references + self.temporal + self.breadth

    def reason(self) -> str:
        """Why this edge exists, in the order the signals actually contributed.

        Prose rather than a score, because a score is not checkable. "Cited by"
        with a count is something a reader can go and look at; `0.72` is
        something they can only accept or reject.
        """
        parts = []
        if self.references > 0:
            parts.append("its entities are cited by the later area's more than the reverse")
        if self.temporal > 0:
            parts.append("its dated entities come earlier")
        if self.breadth > 0:
            parts.append("its entities appear across more of the corpus")
        return "; ".join(parts) or "no signal"


def _leading_year(temporal: str | None) -> int | None:
    """A sortable year from a rendered extent, or `None`.

    Deliberately crude: it reads the first four-digit run and a leading `BC`
    marker, and gives up on anything else. The alternative is re-parsing
    redstring's extent grammar here, which would be a second implementation of
    something upstream owns and would drift from it silently -- and this signal
    is weighted at a quarter of a reference for exactly the reason that it is
    allowed to be crude.
    """
    if not temporal:
        return None
    digits = ""
    for char in temporal:
        if char.isdigit():
            digits += char
            if len(digits) == 4:
                break
        elif digits:
            break
    if not digits:
        return None
    year = int(digits)
    # `BC` covers `BCE` as a substring, which is what we want: both mean
    # "count backwards". `AD`/`CE` need no branch -- they are the sign this
    # already has.
    return -year if "BC" in temporal.upper() else year


def _median_year(area: LearningArea) -> float | None:
    years = sorted(y for m in area.members if (y := _leading_year(m.temporal)) is not None)
    if not years:
        return None
    middle = len(years) // 2
    return float(years[middle]) if len(years) % 2 else (years[middle - 1] + years[middle]) / 2


def _breadth(area: LearningArea, presence: Mapping[str, int]) -> float:
    """Mean number of passages an area's entities appear in.

    A mean rather than a sum, and the difference is the whole point: a sum
    makes every large area foundational by virtue of being large, so the
    breadth signal would become a second, noisier size signal and the biggest
    cluster would always be first.
    """
    if not area.members:
        return 0.0
    return sum(presence.get(m.entity_id, 0) for m in area.members) / len(area.members)


def _signal_pairs(
    areas: Sequence[LearningArea],
    relationships: Sequence[GraphRelationship],
    passages: Sequence[frozenset[str]],
) -> dict[tuple[str, str], _Signals]:
    home = {m.entity_id: area.slug for area in areas for m in area.members}
    presence: dict[str, int] = {}
    for passage in passages:
        for entity_id in passage:
            presence[entity_id] = presence.get(entity_id, 0) + 1

    crossings: dict[tuple[str, str], int] = {}
    for rel in relationships:
        # Inferred temporal edges are excluded. They are arithmetic over two
        # dates rather than anything a document said, so counting them here
        # would let the temporal signal in a second time at four times its
        # declared weight -- through the term that is supposed to be the one
        # a human can check against a source.
        if rel.inferred:
            continue
        left, right = home.get(rel.source_id), home.get(rel.target_id)
        if left is None or right is None or left == right:
            continue
        crossings[(left, right)] = crossings.get((left, right), 0) + 1

    medians = {area.slug: _median_year(area) for area in areas}
    breadths = {area.slug: _breadth(area, presence) for area in areas}

    signals: dict[tuple[str, str], _Signals] = {}
    for before in areas:
        for after in areas:
            if before.slug >= after.slug:
                continue
            forward = crossings.get((before.slug, after.slug), 0)
            backward = crossings.get((after.slug, before.slug), 0)
            total = forward + backward
            # Normalised by the traffic between this pair, not by the graph:
            # two areas joined by two edges both pointing one way is a strong
            # claim about *those two*, and dividing by a project-wide total
            # would silence it in any large project.
            reference = REFERENCE_WEIGHT * (backward - forward) / total if total else 0.0

            early, late = medians[before.slug], medians[after.slug]
            temporal = 0.0
            if early is not None and late is not None and early != late:
                temporal = TEMPORAL_WEIGHT if early < late else -TEMPORAL_WEIGHT

            wide, narrow = breadths[before.slug], breadths[after.slug]
            widest = max(wide, narrow)
            breadth = BREADTH_WEIGHT * (wide - narrow) / widest if widest else 0.0

            score = _Signals(reference, temporal, breadth)
            # A negative total means the evidence points the other way, so the
            # edge is recorded reversed rather than dropped.
            if score.total >= 0:
                signals[(before.slug, after.slug)] = score
            else:
                signals[(after.slug, before.slug)] = _Signals(-reference, -temporal, -breadth)
    return signals


def _reaches(graph: Mapping[str, set[str]], start: str, target: str) -> bool:
    seen, stack = {start}, [start]
    while stack:
        for nxt in sorted(graph.get(stack.pop(), ())):
            if nxt == target:
                return True
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


def _acyclic_edges(
    signals: Mapping[tuple[str, str], _Signals],
) -> list[PrerequisiteEdge]:
    """Strongest-first edge insertion, skipping any that closes a cycle.

    A feedback-arc-set heuristic, and deterministic because the insertion order
    is `(-weight, before, after)` -- a total order on edges that depends only
    on the graph.

    **A skipped edge is marked `contested` and kept, not dropped.** Two areas
    with a genuine mutual dependency is real information about the subject: it
    says they interleave and that any linear order through them is a
    simplification. A clean topological order with that thrown away would be
    the more confident answer and the less true one, and the reader who most
    needs to know is the one deciding whether to trust the path.
    """
    ordered = sorted(
        (pair for pair, score in signals.items() if score.total >= MIN_EDGE_WEIGHT),
        key=lambda pair: (-signals[pair].total, pair[0], pair[1]),
    )
    adjacency: dict[str, set[str]] = {}
    edges: list[PrerequisiteEdge] = []
    for before, after in ordered:
        score = signals[(before, after)]
        closes = _reaches(adjacency, after, before)
        if not closes:
            adjacency.setdefault(before, set()).add(after)
        edges.append(
            PrerequisiteEdge(
                before=before,
                after=after,
                weight=round(score.total, 4),
                reason=score.reason(),
                contested=closes,
            )
        )
    return edges


def _topological(
    areas: Sequence[LearningArea], edges: Sequence[PrerequisiteEdge]
) -> list[str]:
    """Kahn's algorithm over the uncontested edges, stabilised by area size.

    The ready set is drained largest-area-first, ties on slug. Size rather
    than insertion order because when nothing orders two areas the larger one
    is the better place to start -- it is the one more of the corpus is about
    -- and because "insertion order" here would mean the projection's own
    ordering leaking into a second decision it was never asked to make.
    """
    size = {area.slug: area.size for area in areas}
    successors: dict[str, set[str]] = {area.slug: set() for area in areas}
    indegree = {area.slug: 0 for area in areas}
    for edge in edges:
        if edge.contested or edge.after in successors.get(edge.before, ()):
            continue
        successors[edge.before].add(edge.after)
        indegree[edge.after] += 1

    ready = sorted((s for s, d in indegree.items() if d == 0), key=lambda s: (-size[s], s))
    order: list[str] = []
    while ready:
        slug = ready.pop(0)
        order.append(slug)
        for nxt in sorted(successors[slug]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
        ready.sort(key=lambda s: (-size[s], s))
    # Cycle-broken edges are excluded above, so every area drains. The guard
    # is here anyway because a silent truncation of a curriculum -- a path
    # missing three areas, rendering perfectly -- is precisely the failure
    # this repository keeps meeting, and an assertion is cheaper than finding
    # it in a course.
    assert len(order) == len(areas), "topological order dropped an area"
    return order


def full_path(
    areas: Sequence[LearningArea],
    relationships: Sequence[GraphRelationship],
    passages: Sequence[frozenset[str]],
) -> LearningPath:
    """Every area, in prerequisite order."""
    signals = _signal_pairs(areas, relationships, passages)
    edges = _acyclic_edges(signals)
    order = _topological(areas, edges)
    return LearningPath(
        slug="complete",
        title="The complete path",
        area_slugs=tuple(order),
        edges=tuple(_relevant_edges(order, edges)),
    )


def path_to(
    destination: str,
    areas: Sequence[LearningArea],
    relationships: Sequence[GraphRelationship],
    passages: Sequence[frozenset[str]],
) -> LearningPath | None:
    """What to study in order to reach `destination`, and nothing else.

    The prerequisite *closure* of one area rather than a re-ordering of
    everything, which is why its steps are always a subsequence of the full
    path's -- two paths that disagreed about whether A precedes B would be two
    curricula, and a reader has no way to choose between them.

    `None` when `destination` names no area: a client holding a slug from a
    projection taken before the graph grew is the ordinary case, not a fault.
    """
    if not any(area.slug == destination for area in areas):
        return None
    signals = _signal_pairs(areas, relationships, passages)
    edges = _acyclic_edges(signals)
    order = _topological(areas, edges)

    predecessors: dict[str, set[str]] = {}
    for edge in edges:
        if not edge.contested:
            predecessors.setdefault(edge.after, set()).add(edge.before)

    needed, stack = {destination}, [destination]
    while stack:
        for prior in sorted(predecessors.get(stack.pop(), ())):
            if prior not in needed:
                needed.add(prior)
                stack.append(prior)

    steps = tuple(slug for slug in order if slug in needed)
    return LearningPath(
        slug=slugify(f"to-{destination}", fallback="to-area"),
        title=f"Everything needed for {destination}",
        area_slugs=steps,
        edges=tuple(_relevant_edges(steps, edges)),
        destination=destination,
    )


def _relevant_edges(
    order: Sequence[str], edges: Sequence[PrerequisiteEdge]
) -> list[PrerequisiteEdge]:
    """The edges between consecutive steps, plus every contested edge.

    Not the whole digraph. The question a reader has at step four is "why is
    this fourth", and handing them ninety edges buries the answer in the
    eighty-nine that do not concern them. Contested edges are exempt from that
    filter because they are the ones worth interrupting for wherever they sit.
    """
    positions = {slug: index for index, slug in enumerate(order)}
    kept = []
    for edge in edges:
        if edge.contested:
            if edge.before in positions and edge.after in positions:
                kept.append(edge)
            continue
        before, after = positions.get(edge.before), positions.get(edge.after)
        if before is not None and after is not None and after == before + 1:
            kept.append(edge)
    return kept
