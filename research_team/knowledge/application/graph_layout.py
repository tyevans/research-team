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

from dataclasses import dataclass

import numpy as np

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
    """How many passes to run, which shrinks as the graph grows.

    Not a constant, and the reason is that the cost per iteration is
    quadratic while the benefit is not: a 50-node graph is visibly still
    moving at 200 passes and settles by 400, while a 3,000-node graph is a
    hairball whose *shape* is decided in the first hundred and whose
    remaining passes only shuffle nodes inside clusters nobody can see apart.
    Spending four hundred quadratic passes to improve a picture at that size
    is a request held open for minutes with nothing to show for it.
    """
    if node_count <= 200:
        return 400
    if node_count <= 1000:
        return 250
    if node_count <= 2500:
        return 100
    return 60


def compute_layout(node_count: int, edges: list[tuple[int, int]]) -> Layout:
    """Lay `node_count` nodes out in 2-D, pulled together along `edges`.

    `edges` are index pairs into the node order, already resolved by the
    caller -- this module knows nothing about entity ids. Self-edges and
    duplicate edges are harmless: a self-edge contributes a zero-length
    displacement and a duplicate simply pulls twice, which is a reasonable
    reading of two nodes being related two ways.

    An empty graph returns an empty array rather than raising. A graph with
    no edges lays out as a disc rather than a line, because the gravity term
    below is the only force acting and it is radial.
    """
    rng = np.random.default_rng(_SEED)
    if node_count == 0:
        return Layout(np.zeros((0, 2), dtype=np.float32))
    if node_count == 1:
        return Layout(np.zeros((1, 2), dtype=np.float32))

    positions = rng.uniform(-_EXTENT / 2, _EXTENT / 2, size=(node_count, 2)).astype(np.float32)

    # FR's "optimal distance": the edge length the two forces balance at, for
    # `node_count` nodes spread over an `_EXTENT` square.
    k = _EXTENT / np.sqrt(node_count)

    source = np.array([a for a, _ in edges], dtype=np.int64)
    target = np.array([b for _, b in edges], dtype=np.int64)

    passes = _iterations(node_count)
    # The initial step, cooled linearly to nothing. A run that ended while the
    # step was still large would hand back positions caught mid-flight, which
    # is the same defect `GraphCanvas`'s `onEngineStop` comment describes on
    # the client: framing a simulation that has not stopped moving.
    temperature = _EXTENT / 10.0

    for step in range(passes):
        displacement = np.zeros_like(positions)

        # Repulsion, blocked. See the module docstring.
        for start in range(0, node_count, _BLOCK):
            stop = min(start + _BLOCK, node_count)
            delta = positions[start:stop, None, :] - positions[None, :, :]
            distance = np.linalg.norm(delta, axis=-1)
            # A floor rather than a mask on the diagonal: two nodes that
            # random initialisation put in the same place are the same
            # problem as a node against itself, and both are division by
            # zero. Clipping handles the pair nobody thinks to special-case.
            np.maximum(distance, 0.01, out=distance)
            displacement[start:stop] += np.einsum(
                "ijk,ij->ik", delta, (k * k) / (distance * distance)
            )

        # Attraction along edges.
        if source.size:
            delta = positions[source] - positions[target]
            distance = np.maximum(np.linalg.norm(delta, axis=-1), 0.01)
            pull = delta * ((distance / k) / distance)[:, None]
            np.add.at(displacement, source, -pull)
            np.add.at(displacement, target, pull)

        # Gravity toward the origin, which plain FR has no term for. Without
        # it a graph with more than one connected component is a set of
        # clusters repelling each other with nothing pulling back, and they
        # travel outward for as long as the loop runs -- the drawing ends up
        # as a few dense knots at the corners of an empty field. Most real
        # graphs here are disconnected: an extraction run over unrelated
        # documents produces exactly that. Weak (0.01) so it shapes only what
        # nothing else is acting on.
        displacement -= positions * 0.01

        length = np.maximum(np.linalg.norm(displacement, axis=-1), 0.01)
        # Each node moves along its displacement by at most `temperature`.
        # Unbounded steps make the first few passes explode, because the
        # repulsion between two coincident nodes is enormous.
        positions += displacement * (np.minimum(length, temperature) / length)[:, None]
        temperature = (_EXTENT / 10.0) * (1.0 - (step + 1) / passes)

    # Centred and rescaled to `_EXTENT`, which is the only thing that makes
    # that constant true. The loop's own units are decided by the balance
    # between repulsion and the weak gravity above, and measured on
    # 2026-08-22 a 220-node graph settles spanning about 19,000 units against
    # an `_EXTENT` of 1,000 -- so every claim downstream that reads a position
    # as "somewhere in a thousand-unit square" was wrong by a factor of
    # twenty. It cost the exported viewer its labels: its label threshold is a
    # zoom level, and fitting a 19,000-unit drawing to a 1,280px window is a
    # zoom of 0.035, which is below every threshold anybody would write down.
    # Found by opening the file and seeing no labels, not by any check.
    #
    # Normalising also makes two exports comparable: a 40-node graph and a
    # 900-node one now arrive at the same size, so a viewer's fit, its label
    # threshold and its mark size mean the same thing on both.
    positions -= positions.mean(axis=0)
    span = float(max(np.ptp(positions[:, 0]), np.ptp(positions[:, 1])))
    if span > 0:
        positions *= _EXTENT / span

    return Layout(positions.astype(np.float32))
