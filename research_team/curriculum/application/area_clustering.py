"""Community detection and modularity clustering for curriculum area projection.

Applies greedy modularity (Clauset-Newman-Moore) with deterministic tie-breaking,
splits oversized communities, and absorbs undersized communities into their strongest
neighbours.
"""

from __future__ import annotations

import heapq
from collections.abc import Mapping, Sequence

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


__all__ = [
    "MAX_AREA_FRACTION",
    "MIN_AREA_SIZE",
    "_absorb_small",
    "_greedy_modularity",
    "_split_oversized",
]
