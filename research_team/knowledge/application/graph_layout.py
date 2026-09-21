"""Where each node goes, computed here rather than in a browser.

The console draws its graph with `react-force-graph-2d`, whose d3-force
simulation writes `x`/`y` onto every node while it ticks. An export that
reused those positions would be the cheapest possible layout -- the work is
already done and already on screen -- and it was rejected, because it makes
the export a property of a browser tab: no console open, no export, and
nothing scriptable. So the positions are computed on the server, from the
graph the log already folds to, and what that costs is this module.

**Fruchterman-Reingold, not d3-force.** The two are the same family and
neither is "correct"; what matters is that the result is a settled 2-D
arrangement where an edge is short and two unrelated nodes are far apart. FR
is roughly forty lines of array arithmetic against numpy, which this project
already depends on for the curriculum's cosine pass. The alternatives all
cost a dependency: `networkx` brings a graph library to use one function of
it, `graphviz`/`pygraphviz` bring a system package, and `scipy` brings 30 MB
for a sparse matrix this does not need.

**Deterministic, and that is a product decision rather than tidiness.** The
generator is seeded from a constant, so exporting the same graph twice
produces the same picture. Two people comparing the file they were each sent
are comparing the same drawing; a random seed would make every export a
different graph of the same data, and the first thing anyone would ask is
which one is right.

**Repulsion is blocked rather than computed whole.** Every pair repels every
other pair, so the naive form materialises an `(n, n, 2)` array -- 200 MB of
float32 at the 5,000-node cap `MAX_GRAPH_NODES` allows, per iteration. The
loop below walks rows in blocks of `_BLOCK`, which bounds the working set at
roughly `_BLOCK * n * 2` floats regardless of how big the graph is. It is
slower than one big array on a small graph by the cost of a Python loop over
a handful of blocks, which is not measurable next to the arithmetic.
"""

import math
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

LayoutAlgorithm = Literal["force_directed", "circular", "hierarchical", "radial", "grid"]

#: Rows of the pairwise repulsion matrix computed at once. Chosen so the
#: working array stays a few megabytes at the node cap rather than hundreds:
#: `512 * 5000 * 2` float32 is 20 MB. Not tuned for speed -- measured at 512
#: and 2048 on a 900-node graph and the difference was inside the noise.
_BLOCK = 512

#: The side of the square the drawing is laid out in, in the arbitrary units
#: the exported viewer pans over. Nothing downstream depends on the number --
#: the viewer fits the drawing to its own canvas on load -- but a fixed extent
#: keeps the repulsion constant below meaningful across graphs of different
#: sizes.
_EXTENT = 1000.0

#: A constant seed. See the module docstring: the same graph must export to
#: the same picture twice.
_SEED = 20260822


@dataclass(frozen=True)
class Layout:
    """Settled positions, one row per node, in the input's order.

    A `(n, 2)` array rather than a dict keyed by entity id, because the
    caller already holds the node order it passed in and a dict would invite
    a second source of truth about which row is whose.
    """

    positions: np.ndarray

    def __len__(self) -> int:
        return int(self.positions.shape[0])


def _iterations(node_count: int) -> int:
    """How many passes to run, which shrinks as the graph grows."""
    if node_count <= 200:
        return 400
    if node_count <= 1000:
        return 250
    if node_count <= 2500:
        return 100
    return 60


def fruchterman_reingold_layout(
    node_count: int,
    edges: list[tuple[int, int]],
    *,
    extent: float = _EXTENT,
    seed: int = _SEED,
) -> Layout:
    """Lay `node_count` nodes out using Fruchterman-Reingold force-directed simulation."""
    rng = np.random.default_rng(seed)
    if node_count == 0:
        return Layout(np.zeros((0, 2), dtype=np.float32))
    if node_count == 1:
        return Layout(np.zeros((1, 2), dtype=np.float32))

    positions = rng.uniform(-extent / 2, extent / 2, size=(node_count, 2)).astype(np.float32)

    k = extent / np.sqrt(node_count)
    source = np.array([a for a, _ in edges], dtype=np.int64)
    target = np.array([b for _, b in edges], dtype=np.int64)

    passes = _iterations(node_count)
    temperature = extent / 10.0

    for step in range(passes):
        displacement = np.zeros_like(positions)

        for start in range(0, node_count, _BLOCK):
            stop = min(start + _BLOCK, node_count)
            delta = positions[start:stop, None, :] - positions[None, :, :]
            distance = np.linalg.norm(delta, axis=-1)
            np.maximum(distance, 0.01, out=distance)
            displacement[start:stop] += np.einsum(
                "ijk,ij->ik", delta, (k * k) / (distance * distance)
            )

        if source.size:
            delta = positions[source] - positions[target]
            distance = np.maximum(np.linalg.norm(delta, axis=-1), 0.01)
            pull = delta * ((distance / k) / distance)[:, None]
            np.add.at(displacement, source, -pull)
            np.add.at(displacement, target, pull)

        displacement -= positions * 0.01

        length = np.maximum(np.linalg.norm(displacement, axis=-1), 0.01)
        positions += displacement * (np.minimum(length, temperature) / length)[:, None]
        temperature = (extent / 10.0) * (1.0 - (step + 1) / passes)

    positions -= positions.mean(axis=0)
    span = float(max(np.ptp(positions[:, 0]), np.ptp(positions[:, 1])))
    if span > 0:
        positions *= extent / span

    return Layout(positions.astype(np.float32))


def circular_layout(
    node_count: int,
    edges: list[tuple[int, int]] | None = None,
    *,
    extent: float = _EXTENT,
    order_by_degree: bool = True,
) -> Layout:
    """Lay nodes out in a circle, optionally ordering them by degree."""
    if node_count == 0:
        return Layout(np.zeros((0, 2), dtype=np.float32))
    if node_count == 1:
        return Layout(np.zeros((1, 2), dtype=np.float32))

    order = list(range(node_count))
    if order_by_degree and edges:
        degree = [0] * node_count
        for u, v in edges:
            if 0 <= u < node_count:
                degree[u] += 1
            if 0 <= v < node_count:
                degree[v] += 1
        order.sort(key=lambda idx: degree[idx], reverse=True)

    radius = (extent / 2.0) * 0.9
    positions = np.zeros((node_count, 2), dtype=np.float32)
    step = 2.0 * math.pi / node_count

    for pos, node_idx in enumerate(order):
        angle = pos * step
        positions[node_idx, 0] = round(radius * math.cos(angle), 2)
        positions[node_idx, 1] = round(radius * math.sin(angle), 2)

    return Layout(positions)


def radial_layout(
    node_count: int,
    edges: list[tuple[int, int]],
    *,
    extent: float = _EXTENT,
    center_node: int | None = None,
) -> Layout:
    """Lay nodes out in concentric rings centered on the hub or chosen center."""
    if node_count == 0:
        return Layout(np.zeros((0, 2), dtype=np.float32))
    if node_count == 1:
        return Layout(np.zeros((1, 2), dtype=np.float32))

    adj: dict[int, set[int]] = {i: set() for i in range(node_count)}
    for u, v in edges:
        if 0 <= u < node_count and 0 <= v < node_count:
            adj[u].add(v)
            adj[v].add(u)

    if center_node is None or not (0 <= center_node < node_count):
        center_node = max(range(node_count), key=lambda i: len(adj[i]))

    # BFS levels
    levels: dict[int, int] = {center_node: 0}
    queue = [center_node]
    while queue:
        curr = queue.pop(0)
        curr_lvl = levels[curr]
        for neighbor in sorted(adj[curr]):
            if neighbor not in levels:
                levels[neighbor] = curr_lvl + 1
                queue.append(neighbor)

    # Disconnected nodes placed on the outermost ring
    max_level = max(levels.values()) if levels else 0
    outer_level = max_level + 1
    for i in range(node_count):
        if i not in levels:
            levels[i] = outer_level

    by_level: dict[int, list[int]] = {}
    for node, lvl in levels.items():
        by_level.setdefault(lvl, []).append(node)

    max_r = (extent / 2.0) * 0.9
    num_rings = max(levels.values())
    ring_spacing = max_r / max(num_rings, 1)

    positions = np.zeros((node_count, 2), dtype=np.float32)
    positions[center_node] = [0.0, 0.0]

    for lvl, nodes in by_level.items():
        if lvl == 0:
            continue
        r = lvl * ring_spacing
        step = 2.0 * math.pi / len(nodes)
        for idx, node in enumerate(nodes):
            angle = idx * step
            positions[node, 0] = round(r * math.cos(angle), 2)
            positions[node, 1] = round(r * math.sin(angle), 2)

    return Layout(positions)


def hierarchical_layout(
    node_count: int,
    edges: list[tuple[int, int]],
    *,
    extent: float = _EXTENT,
    orientation: Literal["top_bottom", "left_right"] = "top_bottom",
) -> Layout:
    """Lay nodes out in layered topological tiers for directed DAG/hierarchical view."""
    if node_count == 0:
        return Layout(np.zeros((0, 2), dtype=np.float32))
    if node_count == 1:
        return Layout(np.zeros((1, 2), dtype=np.float32))

    in_degree = [0] * node_count
    forward_adj: dict[int, set[int]] = {i: set() for i in range(node_count)}
    for u, v in edges:
        if 0 <= u < node_count and 0 <= v < node_count:
            forward_adj[u].add(v)
            in_degree[v] += 1

    roots = [i for i, deg in enumerate(in_degree) if deg == 0]
    if not roots:
        roots = [0]

    depths: dict[int, int] = {}
    for root in roots:
        depths[root] = 0
    queue = list(roots)
    while queue:
        curr = queue.pop(0)
        curr_depth = depths[curr]
        if curr_depth >= node_count:
            continue  # cycle guard
        for neighbor in sorted(forward_adj[curr]):
            if neighbor not in depths or depths[neighbor] < curr_depth + 1:
                depths[neighbor] = curr_depth + 1
                queue.append(neighbor)

    for i in range(node_count):
        if i not in depths:
            depths[i] = 0

    by_layer: dict[int, list[int]] = {}
    for node, depth in depths.items():
        by_layer.setdefault(depth, []).append(node)

    num_layers = max(by_layer.keys()) + 1
    y_step = (extent * 0.8) / max(num_layers - 1, 1)

    positions = np.zeros((node_count, 2), dtype=np.float32)
    for layer, nodes in by_layer.items():
        y = (extent * 0.4) - (layer * y_step)
        x_step = (extent * 0.8) / max(len(nodes) + 1, 2)
        start_x = -extent * 0.4
        for idx, node in enumerate(nodes):
            x = start_x + (idx + 1) * x_step
            if orientation == "top_bottom":
                positions[node, 0] = round(x, 2)
                positions[node, 1] = round(y, 2)
            else:
                positions[node, 0] = round(y, 2)
                positions[node, 1] = round(x, 2)

    return Layout(positions)


def grid_layout(
    node_count: int,
    edges: list[tuple[int, int]] | None = None,
    *,
    extent: float = _EXTENT,
) -> Layout:
    """Lay nodes out in a compact 2-D grid."""
    if node_count == 0:
        return Layout(np.zeros((0, 2), dtype=np.float32))
    if node_count == 1:
        return Layout(np.zeros((1, 2), dtype=np.float32))

    cols = math.ceil(math.sqrt(node_count))
    rows = math.ceil(node_count / cols)

    x_step = (extent * 0.8) / max(cols - 1, 1)
    y_step = (extent * 0.8) / max(rows - 1, 1)

    positions = np.zeros((node_count, 2), dtype=np.float32)
    for i in range(node_count):
        c = i % cols
        r = i // cols
        positions[i, 0] = round(-extent * 0.4 + c * x_step, 2)
        positions[i, 1] = round(extent * 0.4 - r * y_step, 2)

    return Layout(positions)


def compute_layout(
    node_count: int,
    edges: list[tuple[int, int]],
    *,
    algorithm: LayoutAlgorithm = "force_directed",
    **kwargs: Any,
) -> Layout:
    """Lay `node_count` nodes out in 2-D using the specified layout algorithm.

    Defaults to Fruchterman-Reingold force-directed layout for full backwards
    compatibility and consistent deterministic rendering.
    """
    match algorithm:
        case "force_directed":
            return fruchterman_reingold_layout(node_count, edges, **kwargs)
        case "circular":
            return circular_layout(node_count, edges, **kwargs)
        case "radial":
            return radial_layout(node_count, edges, **kwargs)
        case "hierarchical":
            return hierarchical_layout(node_count, edges, **kwargs)
        case "grid":
            return grid_layout(node_count, edges, **kwargs)
        case _:
            return fruchterman_reingold_layout(node_count, edges, **kwargs)
