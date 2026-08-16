/** The two numbers the graph canvas needs that depend on how much graph there
 *  is: how close to frame it, and how big to draw a node.
 *
 * Both are arithmetic, so they live here rather than inside the canvas
 * component -- jsdom can judge them, and the component's own tests cannot
 * judge anything the simulation produces. What the browser suite is still
 * needed for is that the canvas *applies* them; see
 * `graph-framing.browser.test.tsx`.
 */

/** The closest a whole-graph fit is allowed to get.
 *
 * `force-graph`'s own `zoomToFit` has no ceiling: it divides the stage by the
 * node bounding box, and a graph of one node has a bounding box of that node's
 * radius. Measured in Chromium at 900x600 with 48px padding, one node framed at
 * **50.4x**. That is not visibly "too close" -- every mark this canvas paints is
 * divided by the zoom, so the dot stays 5px whatever the number says -- but it
 * leaves the view fifty times deeper into a graph than the reader has any reason
 * to be, so the first scroll-wheel notch moves them nowhere and "Reset view"
 * hands back a nonsense frame. The ceiling makes the fitted view of a tiny graph
 * the same reading distance as clicking a node (`FOCUS_ZOOM`), which is the
 * distance the rest of this canvas is designed around.
 */
export const MAX_FIT_ZOOM = 2.5

/** The furthest out a fit will pull, past which the drawing is clipped instead.
 *
 * At 0.05 a 900px stage spans 18,000 graph units. A graph that does not fit in
 * that is one whose nodes are single pixels with no labels (labels stop at 0.7),
 * so pulling back further trades a clipped drawing for a blank one. Clipped is
 * the better failure: something is on screen to pan from.
 */
export const MIN_FIT_ZOOM = 0.05

/** The bounding box of a settled simulation, in graph units. */
export interface Bbox {
  readonly x: readonly [number, number]
  readonly y: readonly [number, number]
}

/** Where to centre and how far to zoom to put `bbox` inside a `width`x`height`
 *  stage with `padding` on every side, subject to the clamps above.
 *
 * `null` for a degenerate box (a stage with no room left after padding, or a
 * non-finite coordinate from a simulation that has not run) -- the caller
 * should leave the view where it is rather than move it somewhere arbitrary.
 */
export const framing = (
  bbox: Bbox,
  width: number,
  height: number,
  padding: number,
): { x: number; y: number; zoom: number } | null => {
  const [x0, x1] = bbox.x
  const [y0, y1] = bbox.y
  if (![x0, x1, y0, y1, width, height].every(Number.isFinite)) return null

  const usableWidth = width - padding * 2
  const usableHeight = height - padding * 2
  if (usableWidth <= 0 || usableHeight <= 0) return null

  // A zero-width or zero-height span is not a guard against bad input, it is
  // the ordinary shape of a graph laid out in a line -- three nodes the
  // simulation happened to settle on one row. Dividing by it gives Infinity,
  // which the clamp below turns into `MAX_FIT_ZOOM`, which is the right answer:
  // there is nothing in that axis to fit, so the other axis decides.
  const fit = Math.min(usableWidth / (x1 - x0), usableHeight / (y1 - y0))

  return {
    x: (x0 + x1) / 2,
    y: (y0 + y1) / 2,
    // `Number.isNaN` rather than letting it through: 0/0 is NaN, not Infinity,
    // and `Math.min`/`Math.max` propagate NaN silently into `zoom()`, where it
    // leaves the canvas blank with nothing to say why.
    zoom: Number.isNaN(fit) ? MAX_FIT_ZOOM : Math.min(MAX_FIT_ZOOM, Math.max(MIN_FIT_ZOOM, fit)),
  }
}

/** How big a node is drawn, in screen pixels, for a graph of `count` nodes.
 *
 * A constant 5px was the whole vocabulary, and it is what makes a small graph
 * look like a rendering failure: one entity on a 900x600 stage is a five-pixel
 * ring adrift in black, which reads as "nothing loaded" rather than as "this
 * project has one entity". Larger marks are affordable exactly when there are
 * few of them, and unaffordable at a thousand -- where 5px rings already pack
 * into a solid disc.
 *
 * Logarithmic rather than linear: the interesting range is 1..100, and a linear
 * ramp to 400 would spend almost all of its travel between 200 and 400 nodes,
 * where nobody can tell the difference.
 */
export const NODE_RADIUS_NEAR = 10
export const NODE_RADIUS_FAR = 5
const RADIUS_FLOOR_AT = 400

export const nodeRadius = (count: number): number => {
  if (count <= 1) return NODE_RADIUS_NEAR
  const t = Math.min(1, Math.log(count) / Math.log(RADIUS_FLOOR_AT))
  return NODE_RADIUS_NEAR - (NODE_RADIUS_NEAR - NODE_RADIUS_FAR) * t
}
